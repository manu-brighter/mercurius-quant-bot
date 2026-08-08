from datetime import UTC, datetime
from decimal import Decimal

import pytest

from mercurius.core.enums import Side, SignalKind
from mercurius.core.models import Bar, Position, Signal, TradeIntent, round_to_tick

TS = datetime(2026, 8, 7, 14, 0, tzinfo=UTC)


def _signal(**kw) -> Signal:
    defaults = dict(
        strategy_id="orb", symbol="QQQ", kind=SignalKind.ENTER_LONG, bar_ts=TS, reason="test"
    )
    defaults.update(kw)
    return Signal(**defaults)


def test_bar_requires_tz():
    with pytest.raises(ValueError):
        Bar("SPY", datetime(2026, 8, 7, 14, 0), *(Decimal("1"),) * 4, 100)


def test_round_to_tick():
    assert round_to_tick(Decimal("12.3449")) == Decimal("12.34")
    assert round_to_tick(Decimal("12.345")) == Decimal("12.35")  # half-up
    assert round_to_tick(Decimal("12.30")) == Decimal("12.30")


def test_client_order_id_deterministic_and_distinct():
    a = TradeIntent("QQQ", Side.BUY, Decimal("1.5"), _signal())
    b = TradeIntent("QQQ", Side.BUY, Decimal("2.0"), _signal())  # qty differs only
    c = TradeIntent("QQQ", Side.SELL, Decimal("1.5"), _signal(kind=SignalKind.EXIT))
    assert a.client_order_id == b.client_order_id  # same signal => same id (idempotency)
    assert a.client_order_id != c.client_order_id
    assert a.client_order_id.startswith("mrc-")


def test_position_pnl_signs():
    long_pos = Position("SPY", Decimal("2"), Decimal("100"), TS)
    short_pos = Position("SPY", Decimal("-2"), Decimal("100"), TS)
    assert long_pos.unrealized_pnl(Decimal("101")) == Decimal("2")
    assert short_pos.unrealized_pnl(Decimal("101")) == Decimal("-2")
    assert not short_pos.is_long
