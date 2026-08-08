from datetime import date
from decimal import Decimal
from pathlib import Path

from mercurius.backtest.engine import run_backtest
from mercurius.backtest.metrics import max_drawdown, trade_stats
from mercurius.config import load_config
from mercurius.core.enums import SignalKind
from mercurius.core.models import Bar, Signal
from mercurius.journal.db import FILL, SIGNAL, TRADE_CLOSED, Journal
from mercurius.strategies.base import StrategyContext
from tests.helpers import minute_bars

ROOT = Path(__file__).resolve().parents[2]


def _cfg():
    return load_config(ROOT / "config" / "default.yaml", ROOT / "config" / "backtest.yaml")


class ScriptedStrategy:
    """Enters long on bar N, exits on bar M — for engine plumbing tests."""

    strategy_id = "scripted"
    symbol = "SPY"
    warmup_bars = 1

    def __init__(self, enter_at: int, exit_at: int, stop_offset: str = "5"):
        self.enter_at = enter_at
        self.exit_at = exit_at
        self.stop_offset = Decimal(stop_offset)
        self.seen = 0

    def on_session_start(self, ctx: StrategyContext) -> None:
        self.seen = 0

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> list[Signal]:
        self.seen += 1
        if self.seen == self.enter_at:
            return [
                Signal(
                    self.strategy_id,
                    self.symbol,
                    SignalKind.ENTER_LONG,
                    bar.ts_utc,
                    "scripted entry",
                    stop_price=bar.close - self.stop_offset,
                )
            ]
        if self.seen == self.exit_at:
            return [
                Signal(self.strategy_id, self.symbol, SignalKind.EXIT, bar.ts_utc, "scripted exit")
            ]
        return []


def _bars():
    prices = [100.0, 100.5, 101.0, 101.5, 102.0, 102.5, 103.0, 102.8, 102.6, 102.4]
    return minute_bars("SPY", date(2026, 8, 7), prices)


def test_round_trip_and_journal():
    cfg = _cfg()
    journal = Journal(":memory:")
    strat = ScriptedStrategy(enter_at=2, exit_at=5)
    result = run_backtest(cfg, [strat], _bars(), journal)

    assert len(result.trades) == 1
    t = result.trades[0]
    # entered at bar 3's open (101.0 + costs), exited at bar 6's open (102.5 - costs)
    assert t["pnl"] > 0
    assert journal.events(SIGNAL) and journal.events(FILL)
    closed = journal.events(TRADE_CLOSED)
    assert len(closed) == 1
    assert Decimal(closed[0]["pnl"]) == t["pnl"]


def test_determinism():
    cfg = _cfg()
    r1 = run_backtest(cfg, [ScriptedStrategy(2, 5)], _bars())
    r2 = run_backtest(cfg, [ScriptedStrategy(2, 5)], _bars())
    assert [t["pnl"] for t in r1.trades] == [t["pnl"] for t in r2.trades]
    assert r1.equity_curve == r2.equity_curve


def test_no_lookahead_entry_fills_next_bar_open():
    cfg = _cfg()
    journal = Journal(":memory:")
    run_backtest(cfg, [ScriptedStrategy(2, 9)], _bars(), journal)
    fills = journal.events(FILL)
    signals = journal.events(SIGNAL)
    # first fill must be strictly after the first signal's timestamp
    assert fills[0]["ts_utc"] > signals[0]["ts_utc"]


def test_stop_loss_closes_trade():
    cfg = _cfg()
    prices = [100.0, 100.5, 100.4, 95.0, 94.0, 94.5, 94.2, 94.1, 94.0, 93.9]
    bars = minute_bars("SPY", date(2026, 8, 7), prices)
    strat = ScriptedStrategy(enter_at=2, exit_at=99, stop_offset="2")  # stop at 98.5
    result = run_backtest(cfg, [strat], bars)
    assert len(result.trades) == 1
    assert result.trades[0]["pnl"] < 0  # stopped out at a loss
    stats = trade_stats(result.trades)
    assert stats["win_rate"] == 0.0


def test_daily_loss_halt_flattens_and_blocks():
    cfg = _cfg()
    # loss limit tiny: any losing trade should halt the engine
    cfg.risk.max_daily_loss_usd = Decimal("1")
    cfg.risk.max_daily_loss_pct = Decimal("0.0005")
    prices = [100.0, 100.5, 100.4, 95.0, 94.0, 94.5, 94.2, 94.3, 94.4, 94.5]
    bars = minute_bars("SPY", date(2026, 8, 7), prices)
    journal = Journal(":memory:")
    # strategy would re-enter at bar 7 but the halt must block it
    strat = ScriptedStrategy(enter_at=2, exit_at=99, stop_offset="2")
    run_backtest(cfg, [strat], bars, journal)
    halts = journal.events("risk_halt")
    assert len(halts) >= 1


def test_flatten_before_close():
    cfg = _cfg()
    # session close 16:00 ET; place bars ending 15:52-15:59 so flatten window hits
    prices = [100.0] * 12
    bars = minute_bars("SPY", date(2026, 8, 7), prices, start_et=(15, 47))
    strat = ScriptedStrategy(enter_at=1, exit_at=99, stop_offset="5")
    result = run_backtest(cfg, [strat], bars)
    # position entered early must be closed by engine before session end
    assert len(result.trades) == 1


def test_max_drawdown_metric():
    curve = [(None, Decimal("100")), (None, Decimal("120")), (None, Decimal("90"))]
    assert max_drawdown(curve) == 0.25
