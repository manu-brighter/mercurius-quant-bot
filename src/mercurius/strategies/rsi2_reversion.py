"""Connors-style RSI(2) pullback mean reversion on daily bars.

Rules as published (Connors & Alvarez, *Short Term Trading Strategies That
Work*, 2008 — the most-replicated retail formulation):
- Trend filter: only trade long while close > 200-day SMA.
- Entry: RSI(2) closes below `entry_rsi` (10 in the standard variant).
- Exit: RSI(2) closes above `exit_rsi` (65), OR close > 5-day SMA.
- Typical hold 2-7 days; ~15-30 trades/year/instrument.

Honest health warning, recorded here because it decides how to read results:
this is the most-published, most-arbitraged pattern in retail quant. Long-sample
backtests report 65-79% win rates, but out-of-sample tests covering 2024-2026
report win rates collapsing toward ~30%, and it fails hardest in sustained bear
markets where "buy the dip" stops working. The reason it is still worth testing
here is cost, not novelty: at ~0.5-0.8% average trade P&L, a 2.5bps round trip
is ~3% of the edge instead of the ~400% it was intraday. If it fails the gate,
it fails on edge decay, and that is a real answer.

Deviations from the published rule, on purpose:
- Long-only. The short mirror trades against the 200-day trend and is far less
  robustly documented; excluded from v1.
- A wide disaster stop (`disaster_stop_pct`, default 5%) is attached. The
  published rule has NO stop — it exits on the indicator alone. We need a stop
  because position sizing is risk-based (`risk/sizing.py` refuses to size
  without one) and because an unstopped overnight position is not something
  this project is willing to hold. It sits far enough away to rarely bind.
"""

from __future__ import annotations

from decimal import Decimal

from mercurius.core.enums import SignalKind
from mercurius.core.models import Bar, Signal
from mercurius.strategies.base import StrategyContext
from mercurius.strategies.indicators import IncrementalRSI, IncrementalSMA


class Rsi2ReversionStrategy:
    def __init__(
        self,
        symbol: str = "SPY",
        rsi_period: int = 2,
        entry_rsi: Decimal = Decimal("10"),
        exit_rsi: Decimal = Decimal("65"),
        trend_sma: int = 200,
        exit_sma: int = 5,
        disaster_stop_pct: Decimal = Decimal("0.05"),
        strategy_id: str = "rsi2",
    ) -> None:
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.entry_rsi = entry_rsi
        self.exit_rsi = exit_rsi
        self.disaster_stop_pct = disaster_stop_pct
        self.intraday = False  # multi-day holds: no forced flatten at the close
        self.warmup_bars = trend_sma + 5

        self._rsi = IncrementalRSI(rsi_period)
        self._trend = IncrementalSMA(trend_sma)
        self._exit_sma = IncrementalSMA(exit_sma)

    # Daily strategies have no intraday session state to reset.
    def on_session_start(self, ctx: StrategyContext) -> None:
        pass

    def on_session_end(self, ctx: StrategyContext) -> None:
        pass

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> list[Signal]:
        rsi = self._rsi.update(bar.close)
        trend = self._trend.update(bar.close)
        exit_sma = self._exit_sma.update(bar.close)
        if rsi is None or trend is None or exit_sma is None:
            return []

        pos = ctx.position
        holding = pos is not None and pos.qty != 0

        if holding:
            if rsi > self.exit_rsi:
                return [self._sig(bar, SignalKind.EXIT, f"RSI(2) {rsi:.1f} > {self.exit_rsi}")]
            if bar.close > exit_sma:
                return [
                    self._sig(bar, SignalKind.EXIT, f"close {bar.close} > 5d SMA {exit_sma:.2f}")
                ]
            return []

        if bar.close > trend and rsi < self.entry_rsi:
            stop = bar.close * (1 - self.disaster_stop_pct)
            return [
                self._sig(
                    bar,
                    SignalKind.ENTER_LONG,
                    f"RSI(2) {rsi:.1f} < {self.entry_rsi} above 200d SMA {trend:.2f}",
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
