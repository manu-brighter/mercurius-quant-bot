"""Strategy registry: config -> instantiated strategies."""

from __future__ import annotations

from mercurius.config.schema import AppConfig
from mercurius.strategies.base import Strategy
from mercurius.strategies.noise_bands import NoiseBandsStrategy
from mercurius.strategies.orb import OrbStrategy


def build_strategies(cfg: AppConfig, only: str | None = None) -> list[Strategy]:
    out: list[Strategy] = []
    nb = cfg.strategies.noise_bands
    if nb.enabled:
        out.append(
            NoiseBandsStrategy(
                symbol=nb.symbol,
                lookback_days=nb.lookback_days,
                decision_minutes=tuple(nb.decision_minutes),
                trail_stop_pct=nb.trail_stop_pct,
            )
        )
    orb = cfg.strategies.orb
    if orb.enabled:
        out.append(
            OrbStrategy(
                symbol=orb.symbol,
                range_minutes=orb.range_minutes,
                entry_cutoff=orb.entry_cutoff,
                target_r_multiple=orb.target_r_multiple,
                min_range_atr_frac=orb.min_range_atr_frac,
                max_range_atr_frac=orb.max_range_atr_frac,
                volume_mult=orb.volume_mult,
                ema_filter_period=orb.ema_filter_period,
            )
        )
    if only is not None:
        out = [s for s in out if s.strategy_id == only]
    return out
