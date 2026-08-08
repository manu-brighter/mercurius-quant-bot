"""Synthetic bar generation for tests: deterministic, tz-correct, ET-session-aware."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from mercurius.core.clock import ET, UTC
from mercurius.core.models import Bar


def minute_bars(
    symbol: str,
    trading_date: date,
    prices: list[float],
    start_et: tuple[int, int] = (9, 30),
    volume: int = 10_000,
    volumes: list[int] | None = None,
) -> list[Bar]:
    """One bar per price; bar N closes at start_et + N+1 minutes.

    open of bar N = close of bar N-1 (first open = first price); high/low
    padded a cent beyond open/close.
    """
    bars: list[Bar] = []
    t0 = datetime.combine(trading_date, datetime.min.time(), tzinfo=ET).replace(
        hour=start_et[0], minute=start_et[1]
    )
    prev_close = Decimal(str(prices[0]))
    for i, p in enumerate(prices):
        close = Decimal(str(p))
        open_ = prev_close
        hi = max(open_, close) + Decimal("0.01")
        lo = min(open_, close) - Decimal("0.01")
        ts_close = (t0 + timedelta(minutes=i + 1)).astimezone(UTC)
        bars.append(
            Bar(
                symbol=symbol,
                ts_utc=ts_close,
                open=open_,
                high=hi,
                low=lo,
                close=close,
                volume=volumes[i] if volumes else volume,
            )
        )
        prev_close = close
    return bars
