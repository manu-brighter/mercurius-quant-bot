"""SPY intraday momentum via "noise bands" (Zarattini/Aziz/Barbon, SSRN 4824172).

Mechanic:
- For each minute-of-session, track |close/session_open - 1| per session; the
  band width at that minute is the average over the trailing `lookback_days`
  completed sessions (14, frozen per the paper — not a tuning knob).
- Bands are anchored gap-aware: upper on max(today_open, prev_close), lower on
  min(today_open, prev_close).
- Decisions ONLY at :00/:30 ET marks (~13/day): price above upper band -> long,
  below lower band -> short, inside the noise -> flat.
- Protective stop: trail_stop_pct from entry (broker-side); the band exit at
  the next decision mark is the primary exit. Engine force-flattens at close.
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal

from mercurius.core.clock import et_minute
from mercurius.core.enums import SignalKind
from mercurius.core.models import Bar, Signal
from mercurius.strategies.base import StrategyContext


class NoiseBandsStrategy:
    def __init__(
        self,
        symbol: str = "SPY",
        lookback_days: int = 14,
        decision_minutes: tuple[int, ...] = (0, 30),
        trail_stop_pct: Decimal = Decimal("0.005"),
        strategy_id: str = "noise_bands",
    ) -> None:
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.lookback_days = lookback_days
        self.decision_minutes = tuple(decision_minutes)
        self.trail_stop_pct = trail_stop_pct
        self.warmup_bars = 1  # warmup is session-based, handled internally

        # trailing per-minute |move from open|, one dict per completed session
        self._session_moves: deque[dict[int, Decimal]] = deque(maxlen=lookback_days)
        self._today_moves: dict[int, Decimal] = {}
        self._today_open: Decimal | None = None
        self._prev_close: Decimal | None = None
        self._last_close: Decimal | None = None

    # -- session lifecycle -------------------------------------------------
    def on_session_start(self, ctx: StrategyContext) -> None:
        if self._today_moves:
            self._session_moves.append(self._today_moves)
        self._prev_close = self._last_close
        self._today_moves = {}
        self._today_open = None

    def on_session_end(self, ctx: StrategyContext) -> None:
        pass

    # -- helpers -----------------------------------------------------------
    def _minute_index(self, bar: Bar) -> int:
        h, m = et_minute(bar.ts_utc)
        return (h - 9) * 60 + (m - 30)

    def _band_width(self, minute_idx: int) -> Decimal | None:
        if len(self._session_moves) < self.lookback_days:
            return None
        vals = [s[minute_idx] for s in self._session_moves if minute_idx in s]
        if len(vals) < self.lookback_days // 2:
            return None
        return sum(vals) / Decimal(len(vals))

    def _is_decision_bar(self, bar: Bar) -> bool:
        _, m = et_minute(bar.ts_utc)
        return m in self.decision_minutes

    # -- main --------------------------------------------------------------
    def on_bar(self, ctx: StrategyContext, bar: Bar) -> list[Signal]:
        if self._today_open is None:
            self._today_open = bar.open
        self._last_close = bar.close

        idx = self._minute_index(bar)
        if idx >= 0:
            self._today_moves[idx] = abs(bar.close / self._today_open - 1)

        if not self._is_decision_bar(bar):
            return []
        width = self._band_width(idx)
        if width is None or self._today_open is None:
            return []

        upper_anchor = (
            max(self._today_open, self._prev_close) if self._prev_close else self._today_open
        )
        lower_anchor = (
            min(self._today_open, self._prev_close) if self._prev_close else self._today_open
        )
        upper = upper_anchor * (1 + width)
        lower = lower_anchor * (1 - width)

        pos = ctx.position
        price = bar.close
        signals: list[Signal] = []

        if pos is not None and pos.qty != 0:
            if pos.is_long and price <= upper or not pos.is_long and price >= lower:
                signals.append(self._sig(bar, SignalKind.EXIT, f"price {price} back inside noise"))
            return signals

        if price > upper:
            stop = price * (1 - self.trail_stop_pct)
            signals.append(
                self._sig(bar, SignalKind.ENTER_LONG, f"price {price} > upper band {upper}", stop)
            )
        elif price < lower:
            stop = price * (1 + self.trail_stop_pct)
            signals.append(
                self._sig(bar, SignalKind.ENTER_SHORT, f"price {price} < lower band {lower}", stop)
            )
        return signals

    def _sig(self, bar: Bar, kind: SignalKind, reason: str, stop: Decimal | None = None) -> Signal:
        return Signal(
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            kind=kind,
            bar_ts=bar.ts_utc,
            reason=reason,
            stop_price=stop,
        )
