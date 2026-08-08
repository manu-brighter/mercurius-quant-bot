"""Incremental indicators — O(1) per bar, no lookahead, Decimal-native.

Each is a small state machine fed completed bars; values are None until the
indicator has seen enough data. Correctness is tested against pandas
reference implementations in tests/unit/test_indicators.py.
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal


class IncrementalEMA:
    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self._alpha = Decimal(2) / Decimal(period + 1)
        self._seed: list[Decimal] = []
        self.value: Decimal | None = None

    def update(self, x: Decimal) -> Decimal | None:
        if self.value is None:
            self._seed.append(x)
            if len(self._seed) == self.period:
                self.value = sum(self._seed) / Decimal(self.period)  # SMA seed
            return self.value
        self.value = self._alpha * x + (1 - self._alpha) * self.value
        return self.value


class RollingMedian:
    """Median over a fixed window (used for volume baselines)."""

    def __init__(self, window: int) -> None:
        self.window = window
        self._buf: deque[Decimal] = deque(maxlen=window)

    def update(self, x: Decimal) -> Decimal | None:
        self._buf.append(x)
        if len(self._buf) < self.window:
            return None
        s = sorted(self._buf)
        mid = len(s) // 2
        if len(s) % 2:
            return s[mid]
        return (s[mid - 1] + s[mid]) / 2

    @property
    def value(self) -> Decimal | None:
        if len(self._buf) < self.window:
            return None
        s = sorted(self._buf)
        mid = len(s) // 2
        return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


class SessionATR:
    """ATR over completed *sessions* (daily true range from intraday data).

    Feed it one (high, low, close) per completed session via `push_session`;
    `value` is the simple average of the last `period` true ranges.
    """

    def __init__(self, period: int = 14) -> None:
        self.period = period
        self._trs: deque[Decimal] = deque(maxlen=period)
        self._prev_close: Decimal | None = None

    def push_session(self, high: Decimal, low: Decimal, close: Decimal) -> None:
        if self._prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._trs.append(tr)
        self._prev_close = close

    @property
    def value(self) -> Decimal | None:
        if len(self._trs) < self.period:
            return None
        return sum(self._trs) / Decimal(len(self._trs))

    @property
    def n_sessions(self) -> int:
        return len(self._trs)


class IncrementalSMA:
    def __init__(self, period: int) -> None:
        self.period = period
        self._buf: deque[Decimal] = deque(maxlen=period)

    def update(self, x: Decimal) -> Decimal | None:
        self._buf.append(x)
        return self.value

    @property
    def value(self) -> Decimal | None:
        if len(self._buf) < self.period:
            return None
        return sum(self._buf) / Decimal(self.period)


class IncrementalRSI:
    """Wilder-smoothed RSI. Seeded with a simple average of the first `period`
    gains/losses, then Wilder's recursive smoothing — matches the standard
    published formulation (and pandas-ta/TA-Lib) after warmup."""

    def __init__(self, period: int = 2) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self._prev: Decimal | None = None
        self._avg_gain: Decimal | None = None
        self._avg_loss: Decimal | None = None
        self._seed_gains: list[Decimal] = []
        self._seed_losses: list[Decimal] = []
        self.value: Decimal | None = None

    def update(self, x: Decimal) -> Decimal | None:
        if self._prev is None:
            self._prev = x
            return None
        change = x - self._prev
        self._prev = x
        gain = max(change, Decimal("0"))
        loss = max(-change, Decimal("0"))
        if self._avg_gain is None:
            self._seed_gains.append(gain)
            self._seed_losses.append(loss)
            if len(self._seed_gains) < self.period:
                return None
            self._avg_gain = sum(self._seed_gains) / Decimal(self.period)
            self._avg_loss = sum(self._seed_losses) / Decimal(self.period)
        else:
            p = Decimal(self.period)
            self._avg_gain = (self._avg_gain * (p - 1) + gain) / p
            self._avg_loss = (self._avg_loss * (p - 1) + loss) / p
        if self._avg_loss == 0:
            self.value = Decimal("100") if self._avg_gain > 0 else Decimal("50")
        else:
            rs = self._avg_gain / self._avg_loss
            self.value = Decimal("100") - Decimal("100") / (1 + rs)
        return self.value
