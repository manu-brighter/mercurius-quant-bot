"""Shared value objects. Every module speaks these types; prices are Decimal.

`Bar.ts_utc` is the bar CLOSE time. A strategy receiving a bar therefore only
ever sees fully completed bars — the no-lookahead property rests on this.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from mercurius.core.enums import OrderStatus, Side, SignalKind

PENNY = Decimal("0.01")


def round_to_tick(price: Decimal, tick: Decimal = PENNY) -> Decimal:
    """Round a price to the instrument tick (default: one cent)."""
    return (price / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: str
    ts_utc: datetime  # bar close time, tz-aware UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    vwap: Decimal | None = None

    def __post_init__(self) -> None:
        if self.ts_utc.tzinfo is None:
            raise ValueError("Bar.ts_utc must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Signal:
    """Pure strategy intent on the underlying. No sizes, no order details."""

    strategy_id: str
    symbol: str
    kind: SignalKind
    bar_ts: datetime
    reason: str
    stop_price: Decimal | None = None
    target_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class TradeIntent:
    """Risk-approved, sized plan ready for the executor."""

    instrument: str
    side: Side
    qty: Decimal  # fractional shares allowed
    signal: Signal
    limit_price: Decimal | None = None
    protective_stop: Decimal | None = None

    @property
    def client_order_id(self) -> str:
        """Deterministic id: the same signal never produces two live orders."""
        raw = (
            f"{self.signal.strategy_id}|{self.instrument}|"
            f"{self.signal.bar_ts.isoformat()}|{self.signal.kind}|{self.side}"
        )
        return "mrc-" + hashlib.sha256(raw.encode()).hexdigest()[:24]


@dataclass(slots=True)
class Order:
    client_order_id: str
    instrument: str
    side: Side
    qty: Decimal
    status: OrderStatus = OrderStatus.PENDING
    broker_order_id: str | None = None
    limit_price: Decimal | None = None
    filled_qty: Decimal = Decimal("0")
    avg_fill_price: Decimal | None = None
    submitted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Fill:
    client_order_id: str
    instrument: str
    side: Side
    qty: Decimal
    price: Decimal
    ts_utc: datetime
    fee: Decimal = Decimal("0")


@dataclass(slots=True)
class Position:
    instrument: str
    qty: Decimal  # signed: negative = short
    avg_entry: Decimal
    opened_at: datetime
    strategy_id: str | None = None
    protective_stop_order_id: str | None = None

    @property
    def is_long(self) -> bool:
        return self.qty > 0

    def unrealized_pnl(self, mark: Decimal) -> Decimal:
        return (mark - self.avg_entry) * self.qty


@dataclass(slots=True)
class EquitySnapshot:
    ts_utc: datetime
    equity: Decimal
    cash: Decimal = field(default=Decimal("0"))
