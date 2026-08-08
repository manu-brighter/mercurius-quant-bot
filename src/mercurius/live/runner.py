"""Live paper-trading loop.

Session flow:
  startup -> account sanity -> reconcile -> warmup replay (recent history fed
  to strategies without trading) -> stream loop until close-minus-N minutes ->
  flatten -> session summary.

Fail-closed behaviors: kill-switch file halts and flattens; risk halt flattens
and blocks entries for the day (persisted); stale data blocks entries; every
loop iteration writes the heartbeat the dead-man's watchdog checks.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from mercurius.config.schema import AppConfig
from mercurius.core.clock import ET, WallClock, next_session, session_for
from mercurius.core.enums import SignalKind
from mercurius.core.models import Bar, Signal, TradeIntent, round_to_tick
from mercurius.data.alpaca_stream import AlpacaStream
from mercurius.execution.executor import Executor
from mercurius.execution.reconcile import reconcile
from mercurius.journal import db as evk
from mercurius.journal.db import Journal
from mercurius.journal.writer import JournalWriter
from mercurius.notify.telegram import build_notifier
from mercurius.risk.engine import Approved, RiskEngine
from mercurius.risk.sizing import size_position
from mercurius.strategies.base import StrategyContext
from mercurius.strategies.registry import build_strategies

log = logging.getLogger(__name__)

STALE_ENTRY_BLOCK_S = 120  # no new entries if no bar for 2 minutes
WARMUP_DAYS = 25  # sessions of history replayed into strategies at startup


class LiveRunner:
    def __init__(self, cfg: AppConfig, broker=None) -> None:
        from mercurius.execution.alpaca_broker import AlpacaBroker

        self.cfg = cfg
        self.clock = WallClock()
        self.broker = broker or AlpacaBroker(cfg)
        self.journal = Journal(cfg.journal.db_path)
        self.writer = JournalWriter(self.journal)
        self.notifier = build_notifier(cfg)
        self.risk = RiskEngine(cfg.risk, self.broker.account_mode())
        self.executor = Executor(self.broker, self.writer, self.clock)
        self.strategies = build_strategies(cfg)
        self.contexts = {s.strategy_id: StrategyContext(s.symbol) for s in self.strategies}
        self.stream: AlpacaStream | None = None
        self._equity_cache = Decimal("0")

    # -- startup checks ----------------------------------------------------
    def _sanity_checks(self) -> None:
        eq = self.broker.equity()
        self._equity_cache = eq
        cap = self.cfg.capital_usd
        if eq > cap * 2 or eq < cap / 2:
            raise SystemExit(
                f"broker equity {eq} is far from configured capital {cap}. For paper: "
                "reset the paper account to ~$2,000 in the Alpaca dashboard so sizing "
                "and results are meaningful. Refusing to start."
            )
        skew = abs((datetime.now(tz=UTC) - self.clock.now_utc()).total_seconds())
        if skew > 1.0:  # pragma: no cover - same clock here; guards future clock swaps
            raise SystemExit(f"clock skew {skew}s — fix NTP before trading")
        log.info(
            "sanity ok: equity=%s mode=%s strategies=%s",
            eq,
            self.risk.account_mode,
            [s.strategy_id for s in self.strategies],
        )

    def _heartbeat(self) -> None:
        hb = self.cfg.risk.heartbeat_file
        hb.parent.mkdir(parents=True, exist_ok=True)
        hb.touch()

    def _kill_switch_raised(self) -> bool:
        return self.cfg.risk.kill_switch_file.exists()

    # -- warmup ------------------------------------------------------------
    def _warmup(self) -> None:
        """Replay recent cached/downloaded history through strategies so
        session-based indicators (14-day bands, ATR) are warm at the open."""
        from mercurius.data.alpaca_hist import download_bars, load_cached_bars

        start = (datetime.now(tz=UTC) - timedelta(days=WARMUP_DAYS + 10)).strftime("%Y-%m-%d")
        end = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        symbols = sorted({s.symbol for s in self.strategies})
        bars: list[Bar] = []
        for sym in symbols:
            try:
                download_bars(self.cfg, sym, start, end)
            except Exception:
                log.exception("warmup download failed for %s; using cache only", sym)
            bars.extend(load_cached_bars(self.cfg, sym, start, end))
        bars.sort(key=lambda b: b.ts_utc)
        current_date = None
        for bar in bars:
            d = bar.ts_utc.astimezone(ET).date()
            if d != current_date:
                current_date = d
                for s in self.strategies:
                    if s.symbol == bar.symbol:
                        s.on_session_start(self.contexts[s.strategy_id])
            for s in self.strategies:
                if s.symbol == bar.symbol:
                    ctx = self.contexts[s.strategy_id]
                    ctx._push_bar(bar)
                    s.on_bar(ctx, bar)  # signals during warmup are discarded
        log.info("warmup replay complete: %d bars across %s", len(bars), symbols)

    # -- signal handling ---------------------------------------------------
    def _handle_signals(self, signals: list[Signal], bar: Bar) -> None:
        for sig in signals:
            self.writer.signal(sig)
            if sig.kind == SignalKind.EXIT:
                self.executor.close_position(sig.symbol, sig, limit_price=None)
                self.risk.record_exit(sig.symbol)
                continue

            if (
                self.stream is not None
                and (self.stream.staleness_seconds() or 0) > STALE_ENTRY_BLOCK_S
            ):
                log.warning("stale data: blocking entry signal %s", sig.reason)
                continue

            from mercurius.core.enums import Side

            side = Side.BUY if sig.kind == SignalKind.ENTER_LONG else Side.SELL
            qty = size_position(self._equity_cache, bar.close, sig.stop_price, self.cfg.risk)
            if qty <= 0:
                continue
            intent = TradeIntent(
                instrument=sig.symbol,
                side=side,
                qty=qty,
                signal=sig,
                limit_price=round_to_tick(bar.close),
                protective_stop=sig.stop_price,
            )
            verdict = self.risk.check(intent, self._equity_cache)
            if not isinstance(verdict, Approved):
                self.writer.intent_rejected(self.clock.now_utc(), intent, verdict.reason)
                log.info("risk rejected %s: %s", sig.reason, verdict.reason)
                continue
            self.executor.execute(intent)
            pos = self.broker.get_positions().get(sig.symbol)
            if pos is not None:
                self.risk.record_entry(pos)
            else:
                self.risk.state.trades_today += 1  # count submitted entries regardless

    # -- background tasks --------------------------------------------------
    async def _equity_poller(self) -> None:
        while True:
            await asyncio.sleep(self.cfg.risk.equity_poll_seconds)
            try:
                eq = await asyncio.to_thread(self.broker.equity)
                self._equity_cache = eq
                now = self.clock.now_utc()
                self.writer.equity(now, eq, Decimal("0"))
                halt = self.risk.on_equity(now, eq)
                if halt:
                    self.writer.risk_halt(now, halt)
                    self.notifier.send(f"🛑 RISK HALT: {halt} — flattening all positions.")
                    await asyncio.to_thread(self.broker.flatten_all)
            except Exception:
                log.exception("equity poll failed")

    async def _fill_poller(self) -> None:
        """Reconciliation-grade fill tracking via REST polling.

        (The trade_updates websocket is the lower-latency path; polling every
        few seconds is the dependable fallback and is sufficient for a
        strategy that decides at most once a minute.)
        """
        from mercurius.core.models import Fill

        seen: dict[str, Decimal] = {}
        while True:
            await asyncio.sleep(3)
            try:
                for order in await asyncio.to_thread(self._tracked_open_orders):
                    prev = seen.get(order.client_order_id, Decimal("0"))
                    if order.filled_qty > prev:
                        fill = Fill(
                            client_order_id=order.client_order_id,
                            instrument=order.instrument,
                            side=order.side,
                            qty=order.filled_qty - prev,
                            price=order.avg_fill_price or Decimal("0"),
                            ts_utc=self.clock.now_utc(),
                        )
                        seen[order.client_order_id] = order.filled_qty
                        self.executor.on_fill(fill)
                self.executor.cancel_stale()
            except Exception:
                log.exception("fill poll failed")

    def _tracked_open_orders(self):
        out = []
        for coid in list(self.executor._tracked):
            o = self.broker.get_order(coid)
            if o is not None:
                self.executor._tracked[coid] = o
                out.append(o)
        return out

    # -- main --------------------------------------------------------------
    async def run_session(self) -> None:
        now = self.clock.now_utc()
        today = session_for(now.astimezone(ET).date())
        if today is None or now >= today.close_utc:
            nxt = next_session(now)
            wait = (nxt.open_utc - now).total_seconds()
            log.info("market closed; next session %s in %.0f min", nxt.trading_date, wait / 60)
            await asyncio.sleep(max(0, wait - self.cfg.session.warmup_minutes_before_open * 60))
            today = nxt
            now = self.clock.now_utc()

        self._sanity_checks()
        reconcile(self.cfg, self.broker, self.journal, self.risk, now)
        self._warmup()

        if now < today.open_utc:
            wait = (today.open_utc - now).total_seconds()
            log.info("waiting %.0fs for the open", wait)
            await asyncio.sleep(wait)

        eq = self.broker.equity()
        self._equity_cache = eq
        self.risk.on_session_start(self.clock.now_utc(), eq)
        self.writer.session(self.clock.now_utc(), evk.SESSION_START, str(today.trading_date))
        for s in self.strategies:
            s.on_session_start(self.contexts[s.strategy_id])
        self.notifier.send(f"🟢 session {today.trading_date} started, equity {eq}")

        symbols = sorted({s.symbol for s in self.strategies})
        self.stream = AlpacaStream(self.cfg, symbols)
        stream_task = asyncio.create_task(self.stream.run())
        poll_tasks = [
            asyncio.create_task(self._equity_poller()),
            asyncio.create_task(self._fill_poller()),
        ]
        flatten_at = today.close_utc - timedelta(
            minutes=self.cfg.session.flatten_before_close_minutes
        )
        flattened = False
        try:
            while self.clock.now_utc() < today.close_utc:
                self._heartbeat()
                if self._kill_switch_raised():
                    log.error("kill switch file present — flattening and stopping")
                    self.notifier.send("🔴 kill switch raised — flattening and stopping.")
                    await asyncio.to_thread(self.broker.flatten_all)
                    break
                if not flattened and self.clock.now_utc() >= flatten_at:
                    log.info("flatten window reached (%s)", flatten_at)
                    await asyncio.to_thread(self.broker.flatten_all)
                    flattened = True
                try:
                    bar = await asyncio.wait_for(self.stream.queue.get(), timeout=15)
                except TimeoutError:
                    continue
                if flattened or self.risk.state.halted:
                    continue  # drain bars, no new decisions
                for strat in self.strategies:
                    if strat.symbol != bar.symbol:
                        continue
                    ctx = self.contexts[strat.strategy_id]
                    ctx._push_bar(bar)
                    ctx._set_position(self.broker.get_positions().get(strat.symbol))
                    signals = strat.on_bar(ctx, bar)
                    if signals:
                        self._handle_signals(signals, bar)
        finally:
            self.stream.stop()
            stream_task.cancel()
            for t in poll_tasks:
                t.cancel()
            if not flattened:
                try:
                    await asyncio.to_thread(self.broker.flatten_all)
                except Exception:
                    log.exception("final flatten failed — CHECK POSITIONS MANUALLY")
                    self.notifier.send("🔴 final flatten FAILED — check positions manually!")
            final_eq = self.broker.equity()
            self.writer.session(self.clock.now_utc(), evk.SESSION_END, str(today.trading_date))
            day_pnl = final_eq - eq
            self.notifier.send(
                f"⚪ session {today.trading_date} ended. equity {final_eq} ({day_pnl:+})"
            )
            log.info("session end: equity=%s day_pnl=%s", final_eq, day_pnl)


def run_live(cfg: AppConfig) -> int:
    runner = LiveRunner(cfg)
    log.info("Mercurius live runner starting (paper=%s)", cfg.secrets.alpaca_paper)
    if not cfg.secrets.alpaca_paper:
        log.warning("LIVE TRADING MODE — real money. Ctrl-C now if unintended.")
    try:
        while True:
            asyncio.run(runner.run_session())
    except KeyboardInterrupt:
        log.info("stopped by user")
        return 0
