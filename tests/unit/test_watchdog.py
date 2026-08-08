import time
from datetime import UTC, datetime
from pathlib import Path

from mercurius.config import load_config
from mercurius.core.clock import SimClock
from mercurius.watchdog.deadman import check_once
from tests.fakes import FakeBroker

ROOT = Path(__file__).resolve().parents[2]

OPEN_TS = datetime(2026, 8, 7, 15, 0, tzinfo=UTC)  # 11:00 ET, market open
CLOSED_TS = datetime(2026, 8, 8, 15, 0, tzinfo=UTC)  # Saturday


def _cfg(tmp_path, stale_minutes=3):
    cfg = load_config(ROOT / "config" / "default.yaml")
    cfg.risk.heartbeat_file = tmp_path / "heartbeat"
    cfg.risk.kill_switch_file = tmp_path / "KILL"
    cfg.risk.heartbeat_stale_minutes = stale_minutes
    return cfg


def test_fresh_heartbeat_no_fire(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.risk.heartbeat_file.touch()
    broker = FakeBroker()
    broker.set_position("SPY", "5")
    assert check_once(cfg, broker, SimClock(OPEN_TS)) is False
    assert broker.flatten_calls == 0


def test_stale_heartbeat_fires_and_raises_kill(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.risk.heartbeat_file.touch()
    old = time.time() - 600  # 10 minutes ago
    import os

    os.utime(cfg.risk.heartbeat_file, (old, old))
    broker = FakeBroker()
    broker.set_position("SPY", "5")
    assert check_once(cfg, broker, SimClock(OPEN_TS)) is True
    assert broker.flatten_calls == 1
    assert cfg.risk.kill_switch_file.exists()


def test_market_closed_never_fires(tmp_path):
    cfg = _cfg(tmp_path)  # no heartbeat file at all
    broker = FakeBroker()
    broker.set_position("SPY", "5")
    assert check_once(cfg, broker, SimClock(CLOSED_TS)) is False


def test_no_heartbeat_no_positions_no_fire(tmp_path):
    cfg = _cfg(tmp_path)
    broker = FakeBroker()  # flat
    assert check_once(cfg, broker, SimClock(OPEN_TS)) is False


def test_no_heartbeat_with_positions_fires(tmp_path):
    cfg = _cfg(tmp_path)
    broker = FakeBroker()
    broker.set_position("SPY", "5")
    assert check_once(cfg, broker, SimClock(OPEN_TS)) is True
