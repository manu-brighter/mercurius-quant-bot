"""Performance metrics from an equity curve + trade list."""

from __future__ import annotations

import math
from collections import defaultdict
from decimal import Decimal

from mercurius.backtest.engine import BacktestResult


def daily_returns(equity_curve: list) -> list[float]:
    """Collapse a per-bar equity curve to end-of-day returns."""
    by_day: dict = {}
    for ts, eq in equity_curve:
        by_day[ts.date()] = eq  # last write per day wins
    days = sorted(by_day)
    rets = []
    for prev, cur in zip(days, days[1:], strict=False):
        p, c = float(by_day[prev]), float(by_day[cur])
        if p > 0:
            rets.append(c / p - 1.0)
    return rets


def sharpe(rets: list[float], periods_per_year: int = 252) -> float | None:
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return None
    return mean / sd * math.sqrt(periods_per_year)


def max_drawdown(equity_curve: list) -> float:
    peak, mdd = None, 0.0
    for _, eq in equity_curve:
        e = float(eq)
        peak = e if peak is None else max(peak, e)
        if peak > 0:
            mdd = max(mdd, (peak - e) / peak)
    return mdd


def trade_stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0}
    pnls = [float(t["pnl"]) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    return {
        "n": len(trades),
        "win_rate": len(wins) / len(pnls),
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "avg_win": (gross_win / len(wins)) if wins else 0.0,
        "avg_loss": (-gross_loss / len(losses)) if losses else 0.0,
        "net_pnl": sum(pnls),
        "expectancy_after_top5pct": _expectancy_trimmed(pnls),
    }


def _expectancy_trimmed(pnls: list[float]) -> float:
    """Mean trade PnL after deleting the best 5% of trades — a cheap check
    that the result isn't carried by a couple of lucky outliers."""
    if not pnls:
        return 0.0
    n_drop = max(1, int(len(pnls) * 0.05)) if len(pnls) >= 20 else 0
    trimmed = sorted(pnls)[: len(pnls) - n_drop] if n_drop else pnls
    return sum(trimmed) / len(trimmed) if trimmed else 0.0


def per_strategy(trades: list[dict]) -> dict[str, dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        groups[t.get("strategy_id") or "?"].append(t)
    return {k: trade_stats(v) for k, v in groups.items()}


def summarize(result: BacktestResult, initial_capital: Decimal) -> str:
    rets = daily_returns(result.equity_curve)
    s = sharpe(rets)
    mdd = max_drawdown(result.equity_curve)
    stats = trade_stats(result.trades)
    lines = [
        "== Backtest summary ==",
        f"initial capital : {initial_capital}",
        f"final equity    : {result.final_equity}",
        f"trading days    : {len(rets) + 1 if rets else 0}",
        f"sharpe (daily)  : {s:.2f}" if s is not None else "sharpe (daily)  : n/a",
        f"max drawdown    : {mdd:.1%}",
        f"trades          : {stats.get('n', 0)}",
    ]
    if stats.get("n"):
        lines += [
            f"win rate        : {stats['win_rate']:.1%}",
            f"profit factor   : {stats['profit_factor']:.2f}",
            f"net pnl         : {stats['net_pnl']:.2f}",
            f"expectancy w/o top 5% : {stats['expectancy_after_top5pct']:.2f}",
        ]
        for sid, st in per_strategy(result.trades).items():
            lines.append(
                f"  [{sid}] n={st['n']} win={st['win_rate']:.1%} pf={st['profit_factor']:.2f} "
                f"pnl={st['net_pnl']:.2f}"
            )
    if result.rejections:
        lines.append(f"risk rejections : {result.rejections}")
    if result.conflicts:
        lines.append(
            f"symbol conflicts: {result.conflicts} entries refused (symbol already held "
            "by another strategy) — this run is not a clean per-strategy measurement"
        )
    return "\n".join(lines)
