"""Notifications. NullNotifier by default; Telegram via plain HTTPS when
configured (no extra dependency). Failures never propagate into trading."""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Protocol

from mercurius.config.schema import AppConfig

log = logging.getLogger(__name__)


class Notifier(Protocol):
    def send(self, text: str) -> None: ...


class NullNotifier:
    def send(self, text: str) -> None:  # pragma: no cover - trivial
        pass


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id

    def send(self, text: str) -> None:
        try:
            payload = json.dumps({"chat_id": self._chat_id, "text": text[:4000]}).encode()
            req = urllib.request.Request(
                self._url, data=payload, headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=10)  # noqa: S310
        except Exception:
            log.exception("telegram send failed (trading unaffected)")


def build_notifier(cfg: AppConfig) -> Notifier:
    token = cfg.secrets.telegram_bot_token.get_secret_value()
    if cfg.notify.telegram_enabled and token and cfg.secrets.telegram_chat_id:
        return TelegramNotifier(token, cfg.secrets.telegram_chat_id)
    return NullNotifier()
