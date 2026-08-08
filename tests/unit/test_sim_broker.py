from datetime import UTC, date, datetime
from decimal import Decimal

from mercurius.backtest.sim_broker import SimBroker
from mercurius.core.enums import Side, SignalKind
from mercurius.core.models import Signal, TradeIntent
from tests.helpers import minute_bars

D = date(2026, 8, 7)
TS = datetime(2026, 8, 7, 14, 0, tzinfo=UTC)


def _intent(side=Side.BUY, qty="10", stop=None):
    sig = Signal("t", "SPY", SignalKind.ENTER_LONG, TS, "test", stop_price=stop)
    return TradeIntent("SPY", side, Decimal(qty), sig, protective_stop=stop)


def test_fill_at_next_open_with_adverse_costs():
    broker = SimBroker(Decimal("2000"), Decimal("1"), Decimal("1"))  # 2 bps total
    broker.submit(_intent())
    bar = minute_bars("SPY", D, [100.0])[0]  # open == 100
    fills = broker.on_bar_open(bar)
    assert len(fills) == 1
    assert fills[0].price == Decimal("100.02")  # 100 * (1 + 2/10000)
    assert broker.positions["SPY"].qty == Decimal("10")
    assert broker.cash == Decimal("2000") - Decimal("10") * Decimal("100.02")


def test_sell_side_costs_move_against_us():
    broker = SimBroker(Decimal("2000"), Decimal("1"), Decimal("1"))
    broker.submit(_intent(side=Side.SELL))
    bar = minute_bars("SPY", D, [100.0])[0]
    fills = broker.on_bar_open(bar)
    assert fills[0].price == Decimal("99.98")


def test_protective_stop_triggers_at_stop_price():
    broker = SimBroker(Decimal("2000"), Decimal("0"), Decimal("0"))
    broker.submit(_intent(stop=Decimal("98")))
    b1, b2 = minute_bars("SPY", D, [100.0, 97.0])
    broker.on_bar_open(b1)
    fills = broker.check_stops(b2)  # b2: open 100, low ~96.99 -> stop touched
    assert len(fills) == 1
    assert fills[0].price == Decimal("98")  # not the (lower) bar low
    assert "SPY" not in broker.positions


def test_stop_gap_through_fills_at_open():
    broker = SimBroker(Decimal("2000"), Decimal("0"), Decimal("0"))
    broker.submit(_intent(stop=Decimal("98")))
    bars = minute_bars("SPY", D, [100.0])
    broker.on_bar_open(bars[0])
    # gap down: next bar opens at 95, well below the 98 stop
    gap_bar = minute_bars("SPY", D, [95.0, 94.0], start_et=(9, 32))[0]
    fills = broker.check_stops(gap_bar)
    assert fills[0].price == Decimal("95.00")  # open, worse than stop


def test_no_lookahead_order_never_fills_same_bar():
    broker = SimBroker(Decimal("2000"))
    bar = minute_bars("SPY", D, [100.0])[0]
    broker.on_bar_open(bar)  # nothing pending yet
    broker.submit(_intent())
    assert broker.positions.get("SPY") is None  # still unfilled until next bar


def test_equity_marks():
    broker = SimBroker(Decimal("2000"), Decimal("0"), Decimal("0"))
    broker.submit(_intent())
    bar = minute_bars("SPY", D, [100.0])[0]
    broker.on_bar_open(bar)
    eq = broker.equity({"SPY": Decimal("101")})
    assert eq == Decimal("2000") + Decimal("10")  # +$1 x 10 shares
