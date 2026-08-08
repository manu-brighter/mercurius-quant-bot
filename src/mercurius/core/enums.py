from enum import StrEnum


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class SignalKind(StrEnum):
    ENTER_LONG = "enter_long"
    ENTER_SHORT = "enter_short"
    EXIT = "exit"


class OrderStatus(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"

    @property
    def is_terminal(self) -> bool:
        return self in (
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        )


class AccountMode(StrEnum):
    # >= $2k margin account: shorting allowed, normal settlement.
    MARGIN = "margin"
    # Below $2k or cash account: long-only, settled-cash ledger enforced.
    CASH = "cash"
