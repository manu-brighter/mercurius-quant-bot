"""Internal Bar Strength (IBS) mean reversion on daily bars.

IBS = (close - low) / (high - low), in [0, 1]: where in the day's range the
close landed. Low IBS = closed near the low = short-term oversold.

Rules:
- Trend filter: long only while close > 200-day SMA (same discipline as the
  RSI(2) strategy; the bare IBS rule has no filter, we keep one for symmetry
  and because it is the better-documented long-only form).
- Entry: IBS < `entry_ibs` (0.2).
- Exit: IBS > `exit_ibs` (0.8).
- ~5-6 day average hold, ~19-25 trades/year/instrument.

Why this alongside RSI(2): it is a different, less-crowded read on the same
short-reversal effect (published support incl. Pandey & Joshi 2023 across
country ETFs), and running both roughly doubles the trade count, which is what
makes a statistical gate reachable this decade. Treat them as correlated, not
independent — if both fail, that is one verdict on short-term reversal, not two.

Same deliberate deviations as the RSI(2) module: long-only, and a wide
disaster stop we added for risk-based sizing (the published rule has none).
"""

from __future__ import annotations

from decimal import Decimal

from mercurius.core.enums import SignalKind
from mercurius.core.models import Bar, Signal
from mercurius.strategies.base import StrategyContext
from mercurius.strategies.indicators import IncrementalSMA


def internal_bar_strength(bar: Bar) -> Decimal | None:
    """None when the bar has no range (halt / limit day)."""
    rng = bar.high - bar.low
    if rng <= 0:
        return None
    return (bar.close - bar.low) / rng


class IbsReversionStrategy:
    def __init__(
        self,
        symbol: str = "SPY",
        entry_ibs: Decimal = Decimal("0.2"),
        exit_ibs: Decimal = Decimal("0.8"),
        trend_sma: int = 200,
        disaster_stop_pct: Decimal = Decimal("0.05"),
        strategy_id: str = "ibs",
    ) -> None:
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.entry_ibs = entry_ibs
        self.exit_ibs = exit_ibs
        self.disaster_stop_pct = disaster_stop_pct
        self.intraday = False
        self.warmup_bars = trend_sma + 5

        self._trend = IncrementalSMA(trend_sma)

    def on_session_start(self, ctx: StrategyContext) -> None:
        pass

    def on_session_end(self, ctx: StrategyContext) -> None:
        pass

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> list[Signal]:
        trend = self._trend.update(bar.close)
        ibs = internal_bar_strength(bar)
        if trend is None or ibs is None:
            return []

        pos = ctx.position
        if pos is not None and pos.qty != 0:
            if ibs > self.exit_ibs:
                return [self._sig(bar, SignalKind.EXIT, f"IBS {ibs:.2f} > {self.exit_ibs}")]
            return []

        if bar.close > trend and ibs < self.entry_ibs:
            stop = bar.close * (1 - self.disaster_stop_pct)
            return [
                self._sig(
                    bar,
                    SignalKind.ENTER_LONG,
                    f"IBS {ibs:.2f} < {self.entry_ibs} above 200d SMA {trend:.2f}",
                    stop=stop,
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
