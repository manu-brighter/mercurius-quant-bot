"""Daily/weekly reports and the go/no-go scorecard, computed from the journal.

The scorecard is a RELIABILITY + CALIBRATION gate, honestly framed: three
months of paper trading cannot prove profitability. Passing means "allowed to
discuss going live with $2,000" — nothing more. Criteria that need external
data (buy-and-hold benchmark, random-entry control) are marked MANUAL and run
via the backtest tooling, not silently skipped.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from mercurius.config.schema import AppConfig
from mercurius.journal import db as evk
from mercurius.journal.db import Journal


def _trades(journal: Journal, since: datetime | None = None) -> list[dict]:
    return journal.events(evk.TRADE_CLOSED, since=since)


def _pnls(trades: list[dict]) -> list[float]:
    return [float(t["pnl"]) for t in trades]


def bootstrap_p5_mean(pnls: list[float], n_samples: int, seed: int = 17) -> float | None:
    """5th percentile of the bootstrapped mean trade PnL."""
    if len(pnls) < 10:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(pnls, k=len(pnls))) / len(pnls) for _ in range(n_samples))
    return means[int(0.05 * n_samples)]


def session_counts(journal: Journal) -> tuple[int, int]:
    """(started, cleanly_ended) session counts."""
    starts = journal.events(evk.SESSION_START)
    ends = journal.events(evk.SESSION_END)
    return len({e["trading_date"] for e in starts}), len({e["trading_date"] for e in ends})


def max_drawdown_from_equity(journal: Journal) -> float:
    peak, mdd = None, 0.0
    for ev in journal.events(evk.EQUITY):
        eq = float(ev["equity"])
        peak = eq if peak is None else max(peak, eq)
        if peak and peak > 0:
            mdd = max(mdd, (peak - eq) / peak)
    return mdd


def realized_slippage_ratio(journal: Journal, modeled_bps: Decimal) -> float | None:
    """Avg |fill - intended limit| in bps vs the modeled slippage assumption."""
    intents = {e["client_order_id"]: e for e in journal.events(evk.INTENT)}
    diffs = []
    for f in journal.events(evk.FILL):
        it = intents.get(f["client_order_id"])
        if not it or not it.get("limit_price"):
            continue
        limit = float(it["limit_price"])
        fill = float(f["price"])
        if limit > 0:
            diffs.append(abs(fill - limit) / limit * 10_000)
    if not diffs:
        return None
    avg_bps = sum(diffs) / len(diffs)
    return avg_bps / float(modeled_bps) if modeled_bps else None


def render_report(cfg: AppConfig, journal: Journal, period: str = "daily") -> str:
    now = datetime.now(tz=UTC)
    since = now - timedelta(days=1 if period == "daily" else 7)
    trades = _trades(journal, since=since)
    pnls = _pnls(trades)
    wins = [p for p in pnls if p > 0]
    gross_win, gross_loss = sum(wins), -sum(p for p in pnls if p <= 0)
    lines = [
        f"== Mercurius {period} report — {now:%Y-%m-%d %H:%M} UTC ==",
        f"trades          : {len(trades)}",
    ]
    if trades:
        lines += [
            f"net pnl         : {sum(pnls):+.2f}",
            f"win rate        : {len(wins) / len(pnls):.1%}",
            f"profit factor   : {(gross_win / gross_loss) if gross_loss else float('inf'):.2f}",
        ]
    halts = journal.events(evk.RISK_HALT, since=since)
    if halts:
        lines.append(f"RISK HALTS      : {len(halts)} — {[h['halt_reason'] for h in halts]}")
    rejections = journal.events(evk.INTENT_REJECTED, since=since)
    if rejections:
        lines.append(f"risk rejections : {len(rejections)}")
    if period == "weekly":
        lines += ["", render_scorecard(cfg, journal)]
    return "\n".join(lines)


def render_scorecard(cfg: AppConfig, journal: Journal) -> str:
    sc = cfg.scorecard
    trades = _trades(journal)
    pnls = _pnls(trades)
    wins = [p for p in pnls if p > 0]
    gross_win, gross_loss = sum(wins), -sum(p for p in pnls if p <= 0)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    started, ended = session_counts(journal)
    mdd = max_drawdown_from_equity(journal)
    p5 = bootstrap_p5_mean(pnls, sc.bootstrap_samples)
    slip = realized_slippage_ratio(journal, cfg.backtest.slippage_bps)

    n_drop = max(1, int(len(pnls) * 0.05)) if len(pnls) >= 20 else 0
    trimmed = sorted(pnls)[: len(pnls) - n_drop] if n_drop else pnls
    trimmed_exp = (sum(trimmed) / len(trimmed)) if trimmed else 0.0

    def row(name: str, ok: bool | None, detail: str) -> str:
        mark = "PASS" if ok else ("FAIL" if ok is False else "n/a ")
        return f"  [{mark}] {name:<28} {detail}"

    lines = [
        "== Go/no-go scorecard (pre-registered; reliability gate, not a profit proof) ==",
        row(f"trades >= {sc.min_trades}", len(pnls) >= sc.min_trades, f"{len(pnls)}"),
        row(f"sessions >= {sc.min_sessions}", started >= sc.min_sessions, f"{started}"),
        row("net pnl > 0", sum(pnls) > 0 if pnls else None, f"{sum(pnls):+.2f}"),
        row(
            f"profit factor >= {sc.min_profit_factor}",
            pf >= float(sc.min_profit_factor) if pnls else None,
            f"{pf:.2f}" if pnls else "-",
        ),
        row("expectancy w/o top 5% > 0", trimmed_exp > 0 if pnls else None, f"{trimmed_exp:+.2f}"),
        row(
            "bootstrap p5 mean > 0",
            (p5 > 0) if p5 is not None else None,
            f"{p5:+.2f}" if p5 is not None else "needs >= 10 trades",
        ),
        row(
            f"max drawdown < {float(sc.max_drawdown_pct):.0%}",
            mdd < float(sc.max_drawdown_pct),
            f"{mdd:.1%}",
        ),
        row(
            f"slippage ratio <= {sc.max_slippage_ratio}",
            (slip <= float(sc.max_slippage_ratio)) if slip is not None else None,
            f"{slip:.2f}x" if slip is not None else "no limit-price fills yet",
        ),
        row(
            "all sessions ended cleanly",
            ended >= started if started else None,
            f"{ended}/{started} ended (unended = possible unmanaged position)",
        ),
        row("beats buy-and-hold SPY", None, "MANUAL: compare vs SPY over same window"),
        row("beats random-entry control", None, "MANUAL: run control backtest, same sizing/exits"),
        "",
        "Passing = permission to DISCUSS live trading with $2,000. Nothing more.",
    ]
    return "\n".join(lines)


def report_cli(cfg: AppConfig, period: str) -> int:
    journal = Journal(cfg.journal.db_path)
    print(render_report(cfg, journal, period))
    return 0
