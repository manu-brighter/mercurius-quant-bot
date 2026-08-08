"""Dead-man's switch: an INDEPENDENT process that flattens if the bot dies.

Run alongside the bot (separate systemd unit / terminal):
    python -m mercurius watchdog

Logic: during market hours, if the bot's heartbeat file is older than
`heartbeat_stale_minutes`, assume the bot is dead with unknown positions:
cancel everything, close everything, raise the kill switch, alert, and keep
checking. Uses its own broker client — shares nothing with the bot process.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from mercurius.config.schema import AppConfig
from mercurius.core.clock import WallClock, is_market_open
from mercurius.notify.telegram import build_notifier

log = logging.getLogger(__name__)

CHECK_INTERVAL_S = 30


def heartbeat_age_seconds(cfg: AppConfig) -> float | None:
    try:
        mtime = cfg.risk.heartbeat_file.stat().st_mtime
    except FileNotFoundError:
        return None
    return time.time() - mtime


def check_once(cfg: AppConfig, broker, clock=None) -> bool:
    """Returns True if the switch fired."""
    clock = clock or WallClock()
    if not is_market_open(clock):
        return False
    age = heartbeat_age_seconds(cfg)
    if age is None:
        # no heartbeat file at all during market hours: bot never started
        # today or file was removed — treat as stale only if positions exist
        age = float("inf") if broker.get_positions() else None
    if age is None or age < cfg.risk.heartbeat_stale_minutes * 60:
        return False
    log.error("DEAD-MAN'S SWITCH: heartbeat stale (%.0fs) during market hours", age)
    broker.flatten_all()
    cfg.risk.kill_switch_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.risk.kill_switch_file.touch()
    return True


def watchdog_cli(cfg: AppConfig) -> int:
    from mercurius.execution.alpaca_broker import AlpacaBroker

    notifier = build_notifier(cfg)
    broker = AlpacaBroker(cfg)
    log.info(
        "watchdog running: heartbeat=%s stale_after=%dmin",
        cfg.risk.heartbeat_file,
        cfg.risk.heartbeat_stale_minutes,
    )
    while True:
        try:
            if check_once(cfg, broker):
                notifier.send(
                    f"🔴 DEAD-MAN'S SWITCH fired at {datetime.now(tz=UTC):%H:%M:%S} UTC: "
                    "bot heartbeat stale during market hours. All positions flattened, "
                    "kill switch raised."
                )
        except Exception:
            log.exception("watchdog check failed; retrying")
        time.sleep(CHECK_INTERVAL_S)
