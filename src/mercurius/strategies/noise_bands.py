"""SPY intraday momentum via "noise bands" — Zarattini/Barbon/Aziz, SSRN 4824172.

FIDELITY-AUDITED version (2026-08-08). Deviations from the paper's spec were
identified and corrected after the first M2 gate failure; every remaining
deviation is listed here on purpose:

Faithful to the paper (per the paper's text as reconstructed from multiple
independent secondary sources — the PDF itself is egress-blocked here):
- Bands: day_open-anchored ± sigma_t, where sigma_t = trailing 14-session
  average of |close/day_open - 1| at minute-of-day t. Lookback frozen at 14.
- Entries: level checks ONLY at HH:00/HH:30 — long above the upper band,
  short below the lower band.
- Exits: CONTINUOUS (every bar) trailing check — a long exits the moment
  price falls below max(upper band, session VWAP); a short exits when price
  rises above min(lower band, session VWAP). Otherwise positions are held
  toward the 16:00 close (the engine's flatten-before-close is the backstop).
- No fixed-percentage stop (the earlier 0.5% trail was NOT in the paper and
  was removed in this audit).

Known deviations (documented, deliberate):
- Gap adjustment: the paper describes shifting bounds by prior overnight gaps;
  exact arithmetic unverified. We anchor the upper band at max(open, prev
  close) and the lower at min(open, prev close) — same direction, possibly
  not identical magnitude.
- Sizing: paper vol-targets 2%/day with up to 4x leverage; we size by %-risk
  with no leverage (account constraint). Affects return scale, not the sign
  of per-trade edge.
- Protective stop for the broker/sizing anchor: the band level at entry
  (the paper's initial trailing level), enforced intra-bar by the broker sim.
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
        strategy_id: str = "noise_bands",
    ) -> None:
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.lookback_days = lookback_days
        self.decision_minutes = tuple(decision_minutes)
        self.warmup_bars = 1  # warmup is session-based, handled internally
        self.intraday = True

        # trailing per-minute |move from open|, one dict per completed session
        self._session_moves: deque[dict[int, Decimal]] = deque(maxlen=lookback_days)
        self._today_moves: dict[int, Decimal] = {}
        self._today_open: Decimal | None = None
        self._prev_close: Decimal | None = None
        self._last_close: Decimal | None = None
        # session VWAP accumulators
        self._pv_sum = Decimal("0")
        self._vol_sum = Decimal("0")

    # -- session lifecycle -------------------------------------------------
    def on_session_start(self, ctx: StrategyContext) -> None:
        if self._today_moves:
            self._session_moves.append(self._today_moves)
        self._prev_close = self._last_close
        self._today_moves = {}
        self._today_open = None
        self._pv_sum = Decimal("0")
        self._vol_sum = Decimal("0")

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

    def _bands(self, minute_idx: int) -> tuple[Decimal, Decimal] | None:
        width = self._band_width(minute_idx)
        if width is None or self._today_open is None:
            return None
        upper_anchor = (
            max(self._today_open, self._prev_close) if self._prev_close else self._today_open
        )
        lower_anchor = (
            min(self._today_open, self._prev_close) if self._prev_close else self._today_open
        )
        return upper_anchor * (1 + width), lower_anchor * (1 - width)

    def _session_vwap(self) -> Decimal | None:
        if self._vol_sum == 0:
            return None
        return self._pv_sum / self._vol_sum

    def _is_decision_bar(self, bar: Bar) -> bool:
        _, m = et_minute(bar.ts_utc)
        return m in self.decision_minutes

    # -- main --------------------------------------------------------------
    def on_bar(self, ctx: StrategyContext, bar: Bar) -> list[Signal]:
        if self._today_open is None:
            self._today_open = bar.open
        self._last_close = bar.close

        # session VWAP: per-bar vwap when present, else typical price
        px = bar.vwap if bar.vwap is not None else (bar.high + bar.low + bar.close) / 3
        vol = Decimal(bar.volume)
        self._pv_sum += px * vol
        self._vol_sum += vol

        idx = self._minute_index(bar)
        if idx >= 0:
            self._today_moves[idx] = abs(bar.close / self._today_open - 1)

        bands = self._bands(idx)
        if bands is None:
            return []
        upper, lower = bands
        price = bar.close
        pos = ctx.position

        # EXIT: continuous trailing check on every bar (paper: "immediately")
        if pos is not None and pos.qty != 0:
            vwap = self._session_vwap()
            if pos.is_long:
                trail = max(upper, vwap) if vwap is not None else upper
                if price < trail:
                    return [self._sig(bar, SignalKind.EXIT, f"price {price} < trail {trail}")]
            else:
                trail = min(lower, vwap) if vwap is not None else lower
                if price > trail:
                    return [self._sig(bar, SignalKind.EXIT, f"price {price} > trail {trail}")]
            return []

        # ENTRY: level checks only at the half-hour grid
        if not self._is_decision_bar(bar):
            return []
        if price > upper:
            return [
                self._sig(
                    bar,
                    SignalKind.ENTER_LONG,
                    f"price {price} > upper band {upper}",
                    stop=upper,  # initial trailing level = the band itself
                )
            ]
        if price < lower:
            return [
                self._sig(
                    bar,
                    SignalKind.ENTER_SHORT,
                    f"price {price} < lower band {lower}",
                    stop=lower,
                )
            ]
        return []

    def _sig(self, bar: Bar, kind: SignalKind, reason: str, stop: Decimal | None = None) -> Signal:
        return Signal(
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            kind=kind,
            bar_ts=bar.ts_utc,
            reason=reason,
            stop_price=stop,
        )
