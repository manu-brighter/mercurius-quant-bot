from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from mercurius.config import load_config
from mercurius.core.enums import Side
from mercurius.core.models import Fill
from mercurius.execution.reconcile import journal_open_positions, reconcile
from mercurius.journal.db import Journal
from mercurius.journal.writer import JournalWriter
from mercurius.risk.engine import RiskEngine
from tests.fakes import FakeBroker

ROOT = Path(__file__).resolve().parents[2]
TS = datetime(2026, 8, 7, 14, 0, tzinfo=UTC)


def _cfg(policy="flatten"):
    cfg = load_config(ROOT / "config" / "default.yaml")
    cfg.risk.on_unknown_position = policy
    return cfg


def _fill(journal, instrument, side, qty):
    JournalWriter(journal).fill(
        Fill(
            client_order_id="x",
            instrument=instrument,
            side=side,
            qty=Decimal(qty),
            price=Decimal("100"),
            ts_utc=TS,
        )
    )


def test_journal_open_positions_nets_signed_qty():
    j = Journal(":memory:")
    _fill(j, "SPY", Side.BUY, "10")
    _fill(j, "SPY", Side.SELL, "10")  # closed
    _fill(j, "QQQ", Side.BUY, "4")  # open
    _fill(j, "IWM", Side.SELL, "3")  # open short
    assert journal_open_positions(j) == {"QQQ", "IWM"}


def test_unknown_broker_position_flatten_policy():
    cfg = _cfg("flatten")
    broker = FakeBroker()
    broker.set_position("SPY", "5")
    j = Journal(":memory:")
    risk = RiskEngine(cfg.risk)
    report = reconcile(cfg, broker, j, risk, TS)
    assert report["flattened"] == ["SPY"]
    assert broker.flatten_calls == 1


def test_unknown_broker_position_adopt_policy():
    cfg = _cfg("adopt")
    broker = FakeBroker()
    broker.set_position("SPY", "5")
    j = Journal(":memory:")
    risk = RiskEngine(cfg.risk)
    report = reconcile(cfg, broker, j, risk, TS)
    assert report["adopted"] == ["SPY"]
    assert broker.flatten_calls == 0
    assert "SPY" in risk.state.positions


def test_stale_journal_position_reported():
    cfg = _cfg()
    broker = FakeBroker()  # flat at broker
    j = Journal(":memory:")
    _fill(j, "QQQ", Side.BUY, "4")
    report = reconcile(cfg, broker, j, Journal and RiskEngine(cfg.risk), TS)
    assert report["stale_journal"] == ["QQQ"]


def test_orphan_stop_cancelled():
    cfg = _cfg()
    broker = FakeBroker()
    broker.submit_stop("SPY", Decimal("5"), Decimal("98"), "mrc-abc-stp")
    j = Journal(":memory:")
    report = reconcile(cfg, broker, j, RiskEngine(cfg.risk), TS)
    assert report["cancelled_stops"] == ["mrc-abc-stp"]
    assert "mrc-abc-stp" in broker.cancelled


def test_same_day_halt_restored():
    cfg = _cfg()
    broker = FakeBroker()
    j = Journal(":memory:")
    JournalWriter(j).risk_halt(TS, "daily loss 41 >= limit 40")
    risk = RiskEngine(cfg.risk)
    report = reconcile(cfg, broker, j, risk, TS)
    assert report.get("halt_restored") is True
    assert risk.state.halted


def test_prior_day_halt_not_restored():
    cfg = _cfg()
    broker = FakeBroker()
    j = Journal(":memory:")
    JournalWriter(j).risk_halt(datetime(2026, 8, 6, 14, 0, tzinfo=UTC), "old halt")
    risk = RiskEngine(cfg.risk)
    reconcile(cfg, broker, j, risk, TS)
    assert not risk.state.halted
