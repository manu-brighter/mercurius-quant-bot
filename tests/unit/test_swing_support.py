"""Overnight-hold (swing) support: flatten exemption + GTC protective stops."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from mercurius.backtest.engine import run_backtest
from mercurius.config import load_config
from mercurius.core.clock import SimClock
from mercurius.core.enums import Side, SignalKind
from mercurius.core.models import Fill, Signal, TradeIntent
from mercurius.execution.executor import STOP_SUFFIX, Executor
from mercurius.journal.db import Journal
from mercurius.journal.writer import JournalWriter
from tests.fakes import FakeBroker
from tests.helpers import minute_bars
from tests.integration.test_backtest_engine import ScriptedStrategy

ROOT = Path(__file__).resolve().parents[2]
TS = datetime(2026, 8, 7, 14, 0, tzinfo=UTC)


def _cfg():
    return load_config(ROOT / "config" / "default.yaml", ROOT / "config" / "backtest.yaml")


class SwingScripted(ScriptedStrategy):
    """Scripted strategy marked as swing (no forced flatten at the close).

    Unlike the intraday scripted strategy, the bar counter does NOT reset per
    session — swing scripts count bars across days.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.intraday = False

    def on_session_start(self, ctx):
        pass  # keep the cross-session bar counter


def test_intraday_position_flattened_at_close_swing_position_survives():
    cfg = _cfg()
    prices = [100.0] * 12
    # bars run 15:47-15:59 ET: inside the flatten-before-close window
    bars_day = minute_bars("SPY", date(2026, 8, 7), prices, start_et=(15, 47))

    intraday = ScriptedStrategy(enter_at=1, exit_at=99, stop_offset="5")
    r1 = run_backtest(cfg, [intraday], bars_day)
    assert len(r1.trades) == 1  # forced flat before close

    swing = SwingScripted(enter_at=1, exit_at=99, stop_offset="5")
    r2 = run_backtest(cfg, [swing], bars_day)
    assert len(r2.trades) == 0  # held through the close window


def test_swing_position_survives_into_next_session():
    cfg = _cfg()
    d1 = minute_bars("SPY", date(2026, 8, 6), [100.0] * 8, start_et=(15, 45))
    d2 = minute_bars("SPY", date(2026, 8, 7), [101.0] * 5, start_et=(9, 30))
    swing = SwingScripted(enter_at=1, exit_at=10, stop_offset="5")
    r = run_backtest(cfg, [swing], d1 + d2)
    # entered on day 1, exited on day 2 -> exactly one multi-session round trip
    assert len(r.trades) == 1
    t = r.trades[0]
    assert t["opened_at"].date() != t["closed_at"].date()


def test_risk_halt_flattens_swing_positions_too():
    cfg = _cfg()
    cfg.risk.max_daily_loss_usd = Decimal("1")
    cfg.risk.max_daily_loss_pct = Decimal("0.0005")
    prices = [100.0, 100.5, 100.4, 95.0, 94.0, 94.5]
    bars = minute_bars("SPY", date(2026, 8, 7), prices)
    swing = SwingScripted(enter_at=1, exit_at=99, stop_offset="20")  # wide stop, no stop-out
    journal = Journal(":memory:")
    r = run_backtest(cfg, [swing], bars, journal)
    assert journal.events("risk_halt")
    assert len(r.trades) == 1  # halt flatten closed the swing position (fail closed)


def test_swing_intent_gets_gtc_stop():
    broker = FakeBroker()
    ex = Executor(broker, JournalWriter(Journal(":memory:")), SimClock(TS))
    sig = Signal("swing_s", "SPY", SignalKind.ENTER_LONG, TS, "t", stop_price=Decimal("95"))
    intent = TradeIntent(
        "SPY", Side.BUY, Decimal("5"), sig, protective_stop=Decimal("95"), stop_gtc=True
    )
    ex.execute(intent)
    ex.on_fill(Fill(intent.client_order_id, "SPY", Side.BUY, Decimal("5"), Decimal("100"), TS))
    stop_id = intent.client_order_id + STOP_SUFFIX
    assert broker.stop_tifs[stop_id] == "gtc"


def test_intraday_intent_gets_day_stop():
    broker = FakeBroker()
    ex = Executor(broker, JournalWriter(Journal(":memory:")), SimClock(TS))
    sig = Signal("orb_SPY", "SPY", SignalKind.ENTER_LONG, TS, "t", stop_price=Decimal("95"))
    intent = TradeIntent("SPY", Side.BUY, Decimal("5"), sig, protective_stop=Decimal("95"))
    ex.execute(intent)
    ex.on_fill(Fill(intent.client_order_id, "SPY", Side.BUY, Decimal("5"), Decimal("100"), TS))
    assert broker.stop_tifs[intent.client_order_id + STOP_SUFFIX] == "day"
