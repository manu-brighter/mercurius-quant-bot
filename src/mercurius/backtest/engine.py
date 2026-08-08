"""Backtest engine: replays bars through the SAME strategy/risk/journal path
the live loop uses; only the broker is simulated.

Per-bar ordering (no lookahead by construction):
  1. fill orders queued on the previous bar at this bar's open
  2. protective-stop checks inside this bar's range
  3. strategy sees the completed bar -> signals
  4. risk check + sizing -> orders queued for the NEXT bar
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from mercurius.config.schema import AppConfig
from mercurius.core.clock import ET, SimClock, session_for
from mercurius.core.enums import SignalKind
from mercurius.core.models import Bar, Fill, Signal, TradeIntent, round_to_tick
from mercurius.journal import db as evk
from mercurius.journal.db import Journal
from mercurius.journal.writer import JournalWriter
from mercurius.risk.engine import Approved, RiskEngine
from mercurius.risk.sizing import size_position
from mercurius.strategies.base import Strategy, StrategyContext

from .sim_broker import SimBroker

log = logging.getLogger(__name__)


class BacktestResult:
    def __init__(self) -> None:
        self.equity_curve: list[tuple[datetime, Decimal]] = []
        self.trades: list[dict] = []
        self.rejections: int = 0

    @property
    def final_equity(self) -> Decimal:
        return self.equity_curve[-1][1] if self.equity_curve else Decimal("0")


def run_backtest(
    cfg: AppConfig,
    strategies: list[Strategy],
    bars: list[Bar],
    journal: Journal | None = None,
) -> BacktestResult:
    """`bars` must be sorted by ts_utc (mixed symbols allowed)."""
    journal = journal or Journal(":memory:")
    writer = JournalWriter(journal)
    broker = SimBroker(
        cash=cfg.capital_usd,
        slippage_bps=cfg.backtest.slippage_bps,
        spread_haircut_bps=cfg.backtest.spread_haircut_bps,
    )
    risk = RiskEngine(cfg.risk)
    result = BacktestResult()

    contexts = {s.strategy_id: StrategyContext(s.symbol) for s in strategies}
    strategies_by_symbol: dict[str, list[Strategy]] = {}
    for s in strategies:
        strategies_by_symbol.setdefault(s.symbol, []).append(s)
    swing_ids = {s.strategy_id for s in strategies if not getattr(s, "intraday", True)}

    # entry bookkeeping for round-trip trade records
    open_trades: dict[str, dict] = {}
    marks: dict[str, Decimal] = {}
    clock: SimClock | None = None
    current_session = None

    for bar in bars:
        if clock is None:
            clock = SimClock(bar.ts_utc)
        else:
            clock.advance_to(bar.ts_utc)
        marks[bar.symbol] = bar.close

        bar_date = bar.ts_utc.astimezone(ET).date()
        if current_session != bar_date:
            current_session = bar_date
            eq = broker.equity(marks)
            risk.on_session_start(bar.ts_utc, eq)
            writer.session(bar.ts_utc, evk.SESSION_START, str(bar_date))
            for s in strategies:
                s.on_session_start(contexts[s.strategy_id])

        # 1+2: fills from queued orders and stops
        fills = broker.on_bar_open(bar) + broker.check_stops(bar)
        for f in fills:
            writer.fill(f)
            _track_trade(f, broker, open_trades, writer, result, risk)

        # 3: strategies see the completed bar
        session = session_for(bar_date)
        for strat in strategies_by_symbol.get(bar.symbol, []):
            ctx = contexts[strat.strategy_id]
            ctx._push_bar(bar)
            ctx._set_position(broker.positions.get(strat.symbol))
            if len(ctx.bars) < strat.warmup_bars:
                continue
            signals = strat.on_bar(ctx, bar)
            for sig in signals:
                writer.signal(sig)
                _handle_signal(sig, bar, broker, risk, writer, result, cfg, marks)

        # 4: forced flatten near close (engine-level guard, mirrors live)
        if session is not None:
            mins_left = (session.close_utc - bar.ts_utc).total_seconds() / 60
            if mins_left <= cfg.session.flatten_before_close_minutes:
                _flatten_all(bar, broker, writer, skip_strategy_ids=swing_ids)

        eq = broker.equity(marks)
        result.equity_curve.append((bar.ts_utc, eq))
        halt = risk.on_equity(bar.ts_utc, eq)
        if halt:
            writer.risk_halt(bar.ts_utc, halt)
            _flatten_all(bar, broker, writer)

    return result


def _handle_signal(
    sig: Signal,
    bar: Bar,
    broker: SimBroker,
    risk: RiskEngine,
    writer: JournalWriter,
    result: BacktestResult,
    cfg: AppConfig,
    marks: dict[str, Decimal],
) -> None:
    from mercurius.core.enums import Side

    pos = broker.positions.get(sig.symbol)
    if sig.kind == SignalKind.EXIT:
        if pos is None or pos.qty == 0:
            return
        intent = TradeIntent(
            instrument=sig.symbol,
            side=Side.SELL if pos.is_long else Side.BUY,
            qty=abs(pos.qty),
            signal=sig,
        )
        broker.submit(intent)
        writer.intent(bar.ts_utc, intent)
        return

    equity = broker.equity(marks)
    side = Side.BUY if sig.kind == SignalKind.ENTER_LONG else Side.SELL
    qty = size_position(equity, bar.close, sig.stop_price, cfg.risk)
    if qty <= 0:
        return
    intent = TradeIntent(
        instrument=sig.symbol,
        side=side,
        qty=qty,
        signal=sig,
        limit_price=round_to_tick(bar.close),
        protective_stop=sig.stop_price,
    )
    verdict = risk.check(intent, equity)
    if not isinstance(verdict, Approved):
        writer.intent_rejected(bar.ts_utc, intent, verdict.reason)
        result.rejections += 1
        return
    broker.submit(intent)
    writer.intent(bar.ts_utc, intent)


def _track_trade(
    fill: Fill,
    broker: SimBroker,
    open_trades: dict[str, dict],
    writer: JournalWriter,
    result: BacktestResult,
    risk: RiskEngine,
) -> None:
    from mercurius.core.enums import Side

    pos = broker.positions.get(fill.instrument)
    if fill.instrument not in open_trades:
        # opening fill
        open_trades[fill.instrument] = {
            "entry_price": fill.price,
            "qty": fill.qty if fill.side == Side.BUY else -fill.qty,
            "strategy_id": pos.strategy_id if pos else None,
            "opened_at": fill.ts_utc,
        }
        if pos is not None:
            risk.record_entry(pos)
        return
    if pos is None or pos.qty == 0:
        # closing fill -> record round trip
        t = open_trades.pop(fill.instrument)
        signed_qty = t["qty"]
        pnl = (fill.price - t["entry_price"]) * signed_qty
        writer.trade_closed(
            fill.ts_utc,
            fill.instrument,
            t["strategy_id"],
            signed_qty,
            t["entry_price"],
            fill.price,
            pnl,
        )
        result.trades.append(
            {
                "instrument": fill.instrument,
                "strategy_id": t["strategy_id"],
                "qty": signed_qty,
                "entry_price": t["entry_price"],
                "exit_price": fill.price,
                "pnl": pnl,
                "opened_at": t["opened_at"],
                "closed_at": fill.ts_utc,
            }
        )
        risk.record_exit(fill.instrument)


def _flatten_all(
    bar: Bar,
    broker: SimBroker,
    writer: JournalWriter,
    skip_strategy_ids: set[str] | None = None,
) -> None:
    from mercurius.core.enums import Side

    pos = broker.positions.get(bar.symbol)
    if pos is None or pos.qty == 0:
        return
    # Swing positions survive the close; risk-halt flattens (no skip set) do not.
    if skip_strategy_ids and pos.strategy_id in skip_strategy_ids:
        return
    sig = Signal(
        strategy_id=pos.strategy_id or "engine",
        symbol=bar.symbol,
        kind=SignalKind.EXIT,
        bar_ts=bar.ts_utc,
        reason="flatten_before_close",
    )
    intent = TradeIntent(
        instrument=bar.symbol,
        side=Side.SELL if pos.is_long else Side.BUY,
        qty=abs(pos.qty),
        signal=sig,
    )
    broker.submit(intent)
    writer.intent(bar.ts_utc, intent)


def run_backtest_cli(cfg: AppConfig, strategy: str | None = None) -> int:
    from mercurius.backtest.metrics import summarize
    from mercurius.data.alpaca_hist import load_cached_bars
    from mercurius.strategies.registry import build_strategies

    strategies = build_strategies(cfg, only=strategy)
    if not strategies:
        log.error("no enabled strategies%s", f" matching {strategy!r}" if strategy else "")
        return 1
    symbols = sorted({s.symbol for s in strategies})
    bars: list[Bar] = []
    for sym in symbols:
        cached = load_cached_bars(cfg, sym, cfg.backtest.start, cfg.backtest.end)
        if not cached:
            log.error(
                "no cached bars for %s %s..%s — run `mercurius download-data` first",
                sym,
                cfg.backtest.start,
                cfg.backtest.end,
            )
            return 1
        bars.extend(cached)
    bars.sort(key=lambda b: b.ts_utc)

    result = run_backtest(cfg, strategies, bars)
    print(summarize(result, cfg.capital_usd))
    return 0
