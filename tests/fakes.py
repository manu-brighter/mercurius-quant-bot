"""FakeBroker: in-memory Broker implementation for executor/reconcile tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from mercurius.core.enums import AccountMode, OrderStatus, Side
from mercurius.core.models import Order, Position, TradeIntent


class FakeBroker:
    def __init__(self, equity: Decimal = Decimal("2000"), mode=AccountMode.MARGIN) -> None:
        self._equity = equity
        self._mode = mode
        self.orders: dict[str, Order] = {}
        self.positions: dict[str, Position] = {}
        self.submitted: list[TradeIntent] = []
        self.cancelled: list[str] = []
        self.flatten_calls = 0
        self.reject_next = False

    # -- Broker protocol ---------------------------------------------------
    def submit(self, intent: TradeIntent) -> Order:
        if intent.client_order_id in self.orders:
            raise AssertionError(f"duplicate submit for {intent.client_order_id}")
        status = OrderStatus.REJECTED if self.reject_next else OrderStatus.SUBMITTED
        self.reject_next = False
        order = Order(
            client_order_id=intent.client_order_id,
            instrument=intent.instrument,
            side=intent.side,
            qty=intent.qty,
            status=status,
            broker_order_id=f"b-{len(self.orders)}",
            limit_price=intent.limit_price,
            submitted_at=datetime.now(tz=UTC),
        )
        self.orders[intent.client_order_id] = order
        self.submitted.append(intent)
        return order

    def submit_stop(
        self,
        instrument: str,
        qty: Decimal,
        stop_price: Decimal,
        client_order_id: str,
        gtc: bool = False,
    ) -> Order:
        self.stop_tifs = getattr(self, "stop_tifs", {})
        self.stop_tifs[client_order_id] = "gtc" if gtc else "day"
        order = Order(
            client_order_id=client_order_id,
            instrument=instrument,
            side=Side.SELL,
            qty=qty,
            status=OrderStatus.SUBMITTED,
            broker_order_id=f"b-{len(self.orders)}",
            submitted_at=datetime.now(tz=UTC),
        )
        self.orders[client_order_id] = order
        return order

    def cancel(self, client_order_id: str) -> None:
        self.cancelled.append(client_order_id)
        if client_order_id in self.orders:
            self.orders[client_order_id].status = OrderStatus.CANCELED

    def get_order(self, client_order_id: str) -> Order | None:
        return self.orders.get(client_order_id)

    def get_open_orders(self) -> list[Order]:
        return [o for o in self.orders.values() if not o.status.is_terminal]

    def get_positions(self) -> dict[str, Position]:
        return dict(self.positions)

    def flatten_all(self) -> None:
        self.flatten_calls += 1
        self.positions.clear()
        for o in self.get_open_orders():
            o.status = OrderStatus.CANCELED

    def equity(self) -> Decimal:
        return self._equity

    def account_mode(self) -> AccountMode:
        return self._mode

    # -- test helpers ------------------------------------------------------
    def set_position(self, instrument: str, qty: str, entry: str = "100") -> None:
        self.positions[instrument] = Position(
            instrument=instrument,
            qty=Decimal(qty),
            avg_entry=Decimal(entry),
            opened_at=datetime.now(tz=UTC),
        )
