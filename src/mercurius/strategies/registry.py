"""Strategy registry: config -> instantiated strategies (one per symbol).

Instance ids are suffixed with the symbol (noise_bands_SPY, orb_QQQ, ...) so
journal attribution and the one-position-per-instrument risk rule stay exact.
"""

from __future__ import annotations

from mercurius.config.schema import AppConfig
from mercurius.strategies.base import Strategy
from mercurius.strategies.ibs_reversion import IbsReversionStrategy
from mercurius.strategies.noise_bands import NoiseBandsStrategy
from mercurius.strategies.orb import OrbStrategy
from mercurius.strategies.rsi2_reversion import Rsi2ReversionStrategy


def build_strategies(cfg: AppConfig, only: str | None = None) -> list[Strategy]:
    out: list[Strategy] = []
    nb = cfg.strategies.noise_bands
    if nb.enabled:
        for symbol in nb.symbols:
            out.append(
                NoiseBandsStrategy(
                    symbol=symbol,
                    lookback_days=nb.lookback_days,
                    decision_minutes=tuple(nb.decision_minutes),
                    strategy_id=f"noise_bands_{symbol}",
                )
            )
    orb = cfg.strategies.orb
    if orb.enabled:
        for symbol in orb.symbols:
            out.append(
                OrbStrategy(
                    symbol=symbol,
                    range_minutes=orb.range_minutes,
                    entry_cutoff=orb.entry_cutoff,
                    target_r_multiple=orb.target_r_multiple,
                    min_range_atr_frac=orb.min_range_atr_frac,
                    max_range_atr_frac=orb.max_range_atr_frac,
                    volume_mult=orb.volume_mult,
                    ema_filter_period=orb.ema_filter_period,
                    strategy_id=f"orb_{symbol}",
                )
            )
    rsi2 = cfg.strategies.rsi2
    if rsi2.enabled:
        for symbol in rsi2.symbols:
            out.append(
                Rsi2ReversionStrategy(
                    symbol=symbol,
                    rsi_period=rsi2.rsi_period,
                    entry_rsi=rsi2.entry_rsi,
                    exit_rsi=rsi2.exit_rsi,
                    trend_sma=rsi2.trend_sma,
                    exit_sma=rsi2.exit_sma,
                    disaster_stop_pct=rsi2.disaster_stop_pct,
                    strategy_id=f"rsi2_{symbol}",
                )
            )
    ibs = cfg.strategies.ibs
    if ibs.enabled:
        for symbol in ibs.symbols:
            out.append(
                IbsReversionStrategy(
                    symbol=symbol,
                    entry_ibs=ibs.entry_ibs,
                    exit_ibs=ibs.exit_ibs,
                    trend_sma=ibs.trend_sma,
                    disaster_stop_pct=ibs.disaster_stop_pct,
                    strategy_id=f"ibs_{symbol}",
                )
            )

    if only is not None:
        # accept either a family name ("orb") or a full instance id ("orb_QQQ")
        out = [s for s in out if s.strategy_id == only or s.strategy_id.rsplit("_", 1)[0] == only]
    return out
