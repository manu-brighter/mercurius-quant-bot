"""Position sizing: fixed fractional risk between entry and stop."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from mercurius.config.schema import RiskConfig

QTY_STEP = Decimal("0.001")  # Alpaca fractional granularity


def size_position(
    equity: Decimal,
    entry: Decimal,
    stop: Decimal | None,
    risk_cfg: RiskConfig,
) -> Decimal:
    """Return share qty (>= 0). Zero means: do not trade.

    Risk budget = equity * risk_per_trade_pct, spread over the entry-to-stop
    distance. Without a stop we refuse to size (no unbounded risk trades).
    Caps: max position notional, and never more than equity itself (1x).
    """
    if stop is None or entry <= 0:
        return Decimal("0")
    per_share_risk = abs(entry - stop)
    if per_share_risk == 0:
        return Decimal("0")
    budget = equity * risk_cfg.risk_per_trade_pct
    qty = budget / per_share_risk
    max_notional = min(risk_cfg.max_position_notional_usd, equity)
    qty = min(qty, max_notional / entry)
    return qty.quantize(QTY_STEP, rounding=ROUND_DOWN)
