"""Broker protocol — the only seam between strategy-land and any real broker.

Implementations: SimBroker (backtest), AlpacaBroker (live/paper), FakeBroker
(tests). Porting to IBKR later means implementing exactly this surface.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from mercurius.core.enums import AccountMode
from mercurius.core.models import Order, Position, TradeIntent


class Broker(Protocol):
    def submit(self, intent: TradeIntent) -> Order: ...

    def submit_stop(
        self,
        instrument: str,
        qty: Decimal,
        stop_price: Decimal,
        client_order_id: str,
        gtc: bool = False,
    ) -> Order: ...

    def cancel(self, client_order_id: str) -> None: ...

    def get_order(self, client_order_id: str) -> Order | None: ...

    def get_open_orders(self) -> list[Order]: ...

    def get_positions(self) -> dict[str, Position]: ...

    def flatten_all(self) -> None: ...

    def equity(self) -> Decimal: ...

    def account_mode(self) -> AccountMode: ...
