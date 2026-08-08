"""5-minute Opening Range Breakout with non-fitted filters.

Rules (parameters from published research, deliberately NOT swept):
- Opening range = high/low of the first `range_minutes` (09:30-09:35 ET).
- Entry: first 1-min CLOSE beyond the range (close, not touch), only until
  `entry_cutoff` ET. One trade per day maximum.
- Stop: opposite side of the range (1R). Target: `target_r_multiple` x R.
- Filters, all cheap and mechanistic:
    * doji opening range (|range candle body| < 10% of range) -> no trade day
    * range width outside [min,max] x ATR(14 sessions) -> no trade day
    * breakout bar volume must exceed volume_mult x rolling 20-bar median
    * EMA(50) directional gate: longs only above, shorts only below
- Time stop: exit any open position at 15:45 ET (engine also force-flattens
  before the close as a backstop).
Day-of-week filters are deliberately absent (overfitting signature).
"""

from __future__ import annotations

from decimal import Decimal

from mercurius.core.clock import et_minute
from mercurius.core.enums import SignalKind
from mercurius.core.models import Bar, Signal
from mercurius.strategies.base import StrategyContext
from mercurius.strategies.indicators import IncrementalEMA, RollingMedian, SessionATR


class OrbStrategy:
    def __init__(
        self,
        symbol: str = "QQQ",
        range_minutes: int = 5,
        entry_cutoff: str = "10:30",
        target_r_multiple: Decimal = Decimal("2"),
        min_range_atr_frac: Decimal = Decimal("0.15"),
        max_range_atr_frac: Decimal = Decimal("0.60"),
        volume_mult: Decimal = Decimal("1.5"),
        ema_filter_period: int = 50,
        strategy_id: str = "orb",
    ) -> None:
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.range_minutes = range_minutes
        h, m = entry_cutoff.split(":")
        self.entry_cutoff = (int(h), int(m))
        self.target_r = target_r_multiple
        self.min_range_atr_frac = min_range_atr_frac
        self.max_range_atr_frac = max_range_atr_frac
        self.volume_mult = volume_mult
        self.warmup_bars = 1
        self.intraday = True

        self._atr = SessionATR(14)
        self._ema = IncrementalEMA(ema_filter_period)
        self._vol_median = RollingMedian(20)

        self._reset_day()
        self._sess_high: Decimal | None = None
        self._sess_low: Decimal | None = None
        self._sess_close: Decimal | None = None

    def _reset_day(self) -> None:
        self._or_high: Decimal | None = None
        self._or_low: Decimal | None = None
        self._or_open: Decimal | None = None
        self._or_close: Decimal | None = None
        self._or_done = False
        self._no_trade_day = False
        self._traded_today = False
        self._entry_price: Decimal | None = None
        self._stop: Decimal | None = None
        self._target: Decimal | None = None

    # -- session lifecycle -------------------------------------------------
    def on_session_start(self, ctx: StrategyContext) -> None:
        if self._sess_high is not None and self._sess_low is not None:
            self._atr.push_session(self._sess_high, self._sess_low, self._sess_close)
        self._sess_high = self._sess_low = self._sess_close = None
        self._reset_day()

    def on_session_end(self, ctx: StrategyContext) -> None:
        pass

    # -- main --------------------------------------------------------------
    def on_bar(self, ctx: StrategyContext, bar: Bar) -> list[Signal]:
        h, m = et_minute(bar.ts_utc)
        minutes_in = (h - 9) * 60 + (m - 30)  # bar CLOSE time: first bar -> 1

        # session OHLC tracking for the ATR
        self._sess_high = bar.high if self._sess_high is None else max(self._sess_high, bar.high)
        self._sess_low = bar.low if self._sess_low is None else min(self._sess_low, bar.low)
        self._sess_close = bar.close
        self._ema.update(bar.close)
        vol_median = self._vol_median.value
        self._vol_median.update(Decimal(bar.volume))

        # opening range accumulation
        if minutes_in <= 0:
            return []
        if not self._or_done:
            if self._or_open is None:
                self._or_open = bar.open
            self._or_high = bar.high if self._or_high is None else max(self._or_high, bar.high)
            self._or_low = bar.low if self._or_low is None else min(self._or_low, bar.low)
            self._or_close = bar.close
            if minutes_in >= self.range_minutes:
                self._or_done = True
                self._apply_day_filters()
            return []

        pos = ctx.position
        holding = pos is not None and pos.qty != 0

        # time stop at 15:45 ET
        if holding and (h, m) >= (15, 45):
            return [self._sig(bar, SignalKind.EXIT, "time stop 15:45 ET")]

        # target management (stop is broker-side)
        if holding and self._target is not None:
            if pos.is_long and bar.close >= self._target:
                return [self._sig(bar, SignalKind.EXIT, f"target {self._target} reached")]
            if not pos.is_long and bar.close <= self._target:
                return [self._sig(bar, SignalKind.EXIT, f"target {self._target} reached")]
            return []

        # entry logic
        if self._no_trade_day or self._traded_today or holding:
            return []
        if (h, m) > self.entry_cutoff:
            return []
        assert self._or_high is not None and self._or_low is not None
        r = self._or_high - self._or_low
        if r <= 0:
            return []

        vol_ok = vol_median is not None and Decimal(bar.volume) > self.volume_mult * vol_median
        ema = self._ema.value

        if bar.close > self._or_high and vol_ok and (ema is None or bar.close > ema):
            self._traded_today = True
            self._stop = self._or_low
            self._target = bar.close + self.target_r * r
            return [
                self._sig(
                    bar,
                    SignalKind.ENTER_LONG,
                    f"close {bar.close} > OR high {self._or_high}",
                    stop=self._stop,
                    target=self._target,
                )
            ]
        if bar.close < self._or_low and vol_ok and (ema is None or bar.close < ema):
            self._traded_today = True
            self._stop = self._or_high
            self._target = bar.close - self.target_r * r
            return [
                self._sig(
                    bar,
                    SignalKind.ENTER_SHORT,
                    f"close {bar.close} < OR low {self._or_low}",
                    stop=self._stop,
                    target=self._target,
                )
            ]
        return []

    # -- filters -----------------------------------------------------------
    def _apply_day_filters(self) -> None:
        assert self._or_high is not None and self._or_low is not None
        rng = self._or_high - self._or_low
        if rng <= 0:
            self._no_trade_day = True
            return
        # doji: opening-range body < 10% of its range
        if self._or_open is not None and self._or_close is not None:
            body = abs(self._or_close - self._or_open)
            if body < rng * Decimal("0.10"):
                self._no_trade_day = True
                return
        atr = self._atr.value
        if atr is not None and atr > 0:
            frac = rng / atr
            if frac < self.min_range_atr_frac or frac > self.max_range_atr_frac:
                self._no_trade_day = True

    def _sig(
        self,
        bar: Bar,
        kind: SignalKind,
        reason: str,
        stop: Decimal | None = None,
        target: Decimal | None = None,
    ) -> Signal:
        return Signal(
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            kind=kind,
            bar_ts=bar.ts_utc,
            reason=reason,
            stop_price=stop,
            target_price=target,
        )
