from datetime import UTC, datetime, timedelta
from decimal import Decimal

from mercurius.core.clock import SimClock
from mercurius.core.enums import OrderStatus, Side, SignalKind
from mercurius.core.models import Fill, Signal, TradeIntent
from mercurius.execution.executor import STOP_SUFFIX, Executor
from mercurius.journal.db import FILL, Journal
from mercurius.journal.writer import JournalWriter
from tests.fakes import FakeBroker

TS = datetime(2026, 8, 7, 14, 0, tzinfo=UTC)


def _setup():
    broker = FakeBroker()
    journal = Journal(":memory:")
    clock = SimClock(TS)
    ex = Executor(broker, JournalWriter(journal), clock, order_timeout_s=90)
    return broker, journal, clock, ex


def _intent(stop=None, qty="5"):
    sig = Signal("s", "SPY", SignalKind.ENTER_LONG, TS, "t", stop_price=stop)
    return TradeIntent("SPY", Side.BUY, Decimal(qty), sig, protective_stop=stop)


def _fill(intent, qty, price="100"):
    return Fill(
        client_order_id=intent.client_order_id,
        instrument=intent.instrument,
        side=intent.side,
        qty=Decimal(qty),
        price=Decimal(price),
        ts_utc=TS,
    )


def test_idempotent_execute_never_double_submits():
    broker, _, _, ex = _setup()
    intent = _intent()
    ex.execute(intent)
    ex.execute(intent)  # second call adopts, FakeBroker would raise on dup submit
    assert len(broker.submitted) == 1


def test_partial_fills_accumulate():
    broker, journal, _, ex = _setup()
    intent = _intent(qty="10")
    order = ex.execute(intent)
    ex.on_fill(_fill(intent, "4", "100"))
    assert order.status == OrderStatus.PARTIALLY_FILLED
    assert order.filled_qty == Decimal("4")
    ex.on_fill(_fill(intent, "6", "101"))
    assert order.status == OrderStatus.FILLED
    assert order.filled_qty == Decimal("10")
    # avg price: (4*100 + 6*101)/10
    assert order.avg_fill_price == Decimal("100.6")
    assert len(journal.events(FILL)) == 2


def test_protective_stop_submitted_after_full_fill():
    broker, _, _, ex = _setup()
    intent = _intent(stop=Decimal("98"), qty="10")
    ex.execute(intent)
    ex.on_fill(_fill(intent, "10"))
    stop_id = intent.client_order_id + STOP_SUFFIX
    assert stop_id in broker.orders
    assert broker.orders[stop_id].qty == Decimal("10")


def test_no_stop_before_full_fill():
    broker, _, _, ex = _setup()
    intent = _intent(stop=Decimal("98"), qty="10")
    ex.execute(intent)
    ex.on_fill(_fill(intent, "4"))
    assert intent.client_order_id + STOP_SUFFIX not in broker.orders


def test_close_position_cancels_stop_and_uses_broker_qty():
    broker, _, _, ex = _setup()
    intent = _intent(stop=Decimal("98"), qty="10")
    ex.execute(intent)
    ex.on_fill(_fill(intent, "10"))
    # broker reports only 7 shares (e.g. partial manual close elsewhere)
    broker.set_position("SPY", "7")
    exit_sig = Signal("s", "SPY", SignalKind.EXIT, TS, "exit")
    ex.close_position("SPY", exit_sig)
    stop_id = intent.client_order_id + STOP_SUFFIX
    assert stop_id in broker.cancelled
    closing = broker.submitted[-1]
    assert closing.side == Side.SELL
    assert closing.qty == Decimal("7")  # broker truth, not the intended 10


def test_cancel_stale_orders_after_timeout():
    broker, _, clock, ex = _setup()
    intent = _intent()
    order = ex.execute(intent)
    order.submitted_at = TS
    clock.advance_to(TS + timedelta(seconds=120))
    cancelled = ex.cancel_stale()
    assert intent.client_order_id in cancelled
    assert intent.client_order_id in broker.cancelled


def test_stops_are_not_timeout_cancelled():
    broker, _, clock, ex = _setup()
    intent = _intent(stop=Decimal("98"), qty="10")
    ex.execute(intent)
    ex.on_fill(_fill(intent, "10"))
    stop_id = intent.client_order_id + STOP_SUFFIX
    ex._tracked[stop_id] = broker.orders[stop_id]
    broker.orders[stop_id].submitted_at = TS
    clock.advance_to(TS + timedelta(seconds=600))
    cancelled = ex.cancel_stale()
    assert stop_id not in cancelled
