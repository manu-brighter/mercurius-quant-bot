from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from mercurius.config import load_config
from mercurius.journal import db as evk
from mercurius.journal.db import Journal
from mercurius.journal.report import (
    bootstrap_p5_mean,
    realized_slippage_ratio,
    render_report,
    render_scorecard,
    session_counts,
)
from mercurius.journal.writer import JournalWriter

ROOT = Path(__file__).resolve().parents[2]
TS = datetime.now(tz=UTC) - timedelta(hours=2)


def _cfg():
    return load_config(ROOT / "config" / "default.yaml")


def _journal_with_trades(pnls):
    j = Journal(":memory:")
    w = JournalWriter(j)
    for i, pnl in enumerate(pnls):
        w.trade_closed(
            TS + timedelta(minutes=i),
            "SPY",
            "orb",
            Decimal("5"),
            Decimal("100"),
            Decimal("101"),
            Decimal(str(pnl)),
        )
    return j


def test_daily_report_renders():
    j = _journal_with_trades([10, -5, 3])
    out = render_report(_cfg(), j, "daily")
    assert "trades          : 3" in out
    assert "net pnl         : +8.00" in out


def test_scorecard_fails_with_few_trades():
    j = _journal_with_trades([10, -5])
    out = render_scorecard(_cfg(), j)
    assert "[FAIL] trades >= 150" in out
    assert "MANUAL" in out  # benchmark rows never silently pass


def test_scorecard_session_criterion():
    j = _journal_with_trades([1])
    w = JournalWriter(j)
    w.session(TS, evk.SESSION_START, "2026-08-07")
    w.session(TS + timedelta(hours=6), evk.SESSION_END, "2026-08-07")
    w.session(TS + timedelta(days=1), evk.SESSION_START, "2026-08-08")  # never ended
    started, ended = session_counts(j)
    assert (started, ended) == (2, 1)
    out = render_scorecard(_cfg(), j)
    assert "[FAIL] all sessions ended cleanly" in out


def test_bootstrap_p5():
    assert bootstrap_p5_mean([1.0] * 20, 200) == 1.0  # constant pnl: p5 == mean
    losing = bootstrap_p5_mean([-1.0, 1.0, -1.0, -1.0, 1.0] * 4, 500)
    assert losing is not None and losing < 0


def test_slippage_ratio():
    j = Journal(":memory:")
    w = JournalWriter(j)
    from mercurius.core.enums import Side, SignalKind
    from mercurius.core.models import Fill, Signal, TradeIntent

    sig = Signal("s", "SPY", SignalKind.ENTER_LONG, TS, "t")
    intent = TradeIntent("SPY", Side.BUY, Decimal("5"), sig, limit_price=Decimal("100.00"))
    w.intent(TS, intent)
    w.fill(Fill(intent.client_order_id, "SPY", Side.BUY, Decimal("5"), Decimal("100.03"), TS))
    # 3 bps realized vs 1.5 bps modeled -> ratio 2.0
    ratio = realized_slippage_ratio(j, Decimal("1.5"))
    assert ratio is not None and abs(ratio - 2.0) < 0.01
