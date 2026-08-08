from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from mercurius.config.schema import AppConfig, Secrets


class _EnvSecrets(BaseSettings):
    """Secrets come exclusively from the environment / .env — never YAML."""

    model_config = SettingsConfigDict(
        env_prefix="MERCURIUS_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_paper: bool = True
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(*yaml_paths: str | Path) -> AppConfig:
    """Merge YAML files left-to-right (later wins), then attach env secrets."""
    merged: dict[str, Any] = {}
    for p in yaml_paths:
        with open(p) as f:
            doc = yaml.safe_load(f) or {}
        merged = _deep_merge(merged, doc)

    env = _EnvSecrets()
    cfg = AppConfig.model_validate(merged)
    cfg.secrets = Secrets(
        alpaca_api_key=env.alpaca_api_key,
        alpaca_secret_key=env.alpaca_secret_key,
        alpaca_paper=env.alpaca_paper,
        telegram_bot_token=env.telegram_bot_token,
        telegram_chat_id=env.telegram_chat_id,
    )
    return cfg
