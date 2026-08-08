"""Table-driven RiskEngine tests: each limit breached in isolation."""

from datetime import UTC, datetime
from decimal import Decimal

from mercurius.config.schema import RiskConfig
from mercurius.core.enums import AccountMode, SignalKind
from mercurius.core.models import Position, Signal, TradeIntent
from mercurius.risk.engine import Approved, Rejected, RiskEngine

TS = datetime(2026, 8, 7, 14, 0, tzinfo=UTC)  # 10:00 ET


def _intent(kind=SignalKind.ENTER_LONG, qty="5", limit="100", instrument="SPY"):
    from mercurius.core.enums import Side

    sig = Signal("s", instrument, kind, TS, "t", stop_price=Decimal("99"))
    side = Side.SELL if kind == SignalKind.ENTER_SHORT else Side.BUY
    return TradeIntent(instrument, side, Decimal(qty), sig, limit_price=Decimal(limit))


def _engine(mode=AccountMode.MARGIN, **overrides):
    cfg = RiskConfig(**overrides)
    eng = RiskEngine(cfg, mode)
    eng.on_session_start(TS, Decimal("2000"))
    return eng


def test_happy_path_approved():
    assert isinstance(_engine().check(_intent(), Decimal("2000")), Approved)


def test_exit_always_allowed_even_when_halted():
    eng = _engine()
    eng.state.halted = True
    verdict = eng.check(_intent(kind=SignalKind.EXIT), Decimal("2000"))
    assert isinstance(verdict, Approved)


def test_halted_blocks_entries():
    eng = _engine()
    eng.state.halted = True
    v = eng.check(_intent(), Decimal("2000"))
    assert isinstance(v, Rejected) and "halted" in v.reason


def test_max_trades_per_day():
    eng = _engine(max_trades_per_day=1)
    eng.state.trades_today = 1
    assert isinstance(eng.check(_intent(), Decimal("2000")), Rejected)


def test_max_concurrent_positions():
    eng = _engine(max_concurrent_positions=1)
    eng.state.positions["QQQ"] = Position("QQQ", Decimal("1"), Decimal("400"), TS)
    assert isinstance(eng.check(_intent(), Decimal("2000")), Rejected)


def test_no_doubling_same_instrument():
    eng = _engine()
    eng.state.positions["SPY"] = Position("SPY", Decimal("1"), Decimal("100"), TS)
    v = eng.check(_intent(), Decimal("2000"))
    assert isinstance(v, Rejected) and "already open" in v.reason


def test_short_requires_margin_mode():
    eng = _engine(mode=AccountMode.CASH)
    v = eng.check(_intent(kind=SignalKind.ENTER_SHORT), Decimal("2000"))
    assert isinstance(v, Rejected) and "margin" in v.reason
    eng2 = _engine(mode=AccountMode.MARGIN)
    assert isinstance(eng2.check(_intent(kind=SignalKind.ENTER_SHORT), Decimal("2000")), Approved)


def test_notional_cap():
    eng = _engine(max_position_notional_usd=Decimal("300"))
    v = eng.check(_intent(qty="5", limit="100"), Decimal("2000"))  # 500 notional
    assert isinstance(v, Rejected) and "notional" in v.reason


def test_daily_loss_halt_and_latch():
    eng = _engine(max_daily_loss_usd=Decimal("40"), max_daily_loss_pct=Decimal("0.02"))
    assert eng.on_equity(TS, Decimal("1990")) is None  # -10: fine
    reason = eng.on_equity(TS, Decimal("1959"))  # -41 >= min(40, 2% of 2000=40)
    assert reason is not None and eng.state.halted
    # latch survives further equity recovery
    assert eng.on_equity(TS, Decimal("2005")) is None
    assert eng.state.halted


def test_mid_session_restart_keeps_state():
    eng = _engine()
    eng.state.trades_today = 2
    eng.state.halted = True
    eng.on_session_start(TS, Decimal("2000"))  # same date: no reset
    assert eng.state.trades_today == 2 and eng.state.halted


def test_new_session_resets():
    eng = _engine()
    eng.state.trades_today = 2
    eng.state.halted = True
    next_day = datetime(2026, 8, 10, 14, 0, tzinfo=UTC)
    eng.on_session_start(next_day, Decimal("2000"))
    assert eng.state.trades_today == 0 and not eng.state.halted


def test_restore_halt():
    eng = _engine()
    eng.restore_halt("restored from journal")
    assert eng.state.halted
    assert isinstance(eng.check(_intent(), Decimal("2000")), Rejected)
