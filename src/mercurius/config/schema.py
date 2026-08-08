from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr


class SessionConfig(BaseModel):
    warmup_minutes_before_open: int = 20
    no_new_entries_after: str = "15:30"  # ET, "HH:MM"
    flatten_before_close_minutes: int = 10


class NoiseBandsConfig(BaseModel):
    enabled: bool = True
    symbol: str = "SPY"
    lookback_days: int = 14  # frozen per SSRN 4824172; not a tuning knob
    decision_minutes: list[int] = Field(default_factory=lambda: [0, 30])
    trail_stop_pct: Decimal = Decimal("0.005")


class OrbConfig(BaseModel):
    enabled: bool = True
    symbol: str = "QQQ"
    range_minutes: int = 5
    entry_cutoff: str = "10:30"  # ET
    target_r_multiple: Decimal = Decimal("2")
    min_range_atr_frac: Decimal = Decimal("0.15")
    max_range_atr_frac: Decimal = Decimal("0.60")
    volume_mult: Decimal = Decimal("1.5")
    ema_filter_period: int = 50


class StrategiesConfig(BaseModel):
    noise_bands: NoiseBandsConfig = NoiseBandsConfig()
    orb: OrbConfig = OrbConfig()


class RiskConfig(BaseModel):
    max_daily_loss_usd: Decimal = Decimal("40")
    max_daily_loss_pct: Decimal = Decimal("0.02")
    max_position_notional_usd: Decimal = Decimal("1000")
    risk_per_trade_pct: Decimal = Decimal("0.01")
    max_concurrent_positions: int = 2
    max_trades_per_day: int = 3
    equity_poll_seconds: int = 20
    kill_switch_file: Path = Path("data/KILL")
    heartbeat_file: Path = Path("data/heartbeat")
    heartbeat_stale_minutes: int = 3
    on_unknown_position: str = "flatten"  # adopt | flatten


class KillCriteria(BaseModel):
    """Pre-registered before go-live. Not renegotiable after results exist."""

    max_drawdown_from_peak_pct: Decimal = Decimal("0.15")
    slippage_vs_model_max_ratio: Decimal = Decimal("2.0")
    slippage_breach_consecutive_trades: int = 10
    min_trades_before_judgement: int = 150


class JournalConfig(BaseModel):
    db_path: Path = Path("data/journal.sqlite")


class DataConfig(BaseModel):
    cache_dir: Path = Path("data/cache")
    feed: str = "iex"  # pinned: backtest the same tape the free live feed trades
    adjustment: str = "all"
    chain_snapshot_dir: Path = Path("data/chains")
    holdout_dir: Path = Path("data/holdout")


class BacktestConfig(BaseModel):
    start: str = "2023-01-01"
    end: str = "2025-12-31"
    slippage_bps: Decimal = Decimal("1.5")
    spread_haircut_bps: Decimal = Decimal("1.0")
    fill_at: str = "next_open"
    # Data at/after this date is locked holdout: the sweep refuses to touch it.
    holdout_start: str = "2026-01-01"
    trial_log: Path = Path("data/trials.jsonl")


class NotifyConfig(BaseModel):
    telegram_enabled: bool = False


class Secrets(BaseModel):
    alpaca_api_key: SecretStr = SecretStr("")
    alpaca_secret_key: SecretStr = SecretStr("")
    alpaca_paper: bool = True
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_chat_id: str = ""


class AppConfig(BaseModel):
    capital_usd: Decimal = Decimal("2000")
    symbols: list[str] = Field(default_factory=lambda: ["SPY", "QQQ"])
    session: SessionConfig = SessionConfig()
    strategies: StrategiesConfig = StrategiesConfig()
    risk: RiskConfig = RiskConfig()
    kill_criteria: KillCriteria = KillCriteria()
    journal: JournalConfig = JournalConfig()
    data: DataConfig = DataConfig()
    backtest: BacktestConfig = BacktestConfig()
    notify: NotifyConfig = NotifyConfig()
    secrets: Secrets = Secrets()
