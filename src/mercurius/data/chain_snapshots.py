"""Daily option-chain snapshots — data collection only, no trading.

Options are v2 and blocked on paid OPRA data. The point of running this from
day one is that the *decision* about v2 needs months of history that cannot be
bought retroactively: how wide the spreads really are at the strikes and
expiries the strategies would touch, and how fast quotes decay.

The free plan serves the **indicative** feed, which is delayed/derived and must
never be treated as tradable. Snapshots record which feed produced them so a
later analysis cannot silently mix the two.

Scope is bounded on purpose (near-dated expiries, strikes near spot): SPY's
full chain is thousands of contracts per day and none of the far wings inform
the v2 question.

Layout: ``<chain_snapshot_dir>/<SYMBOL>/<YYYY-MM-DD>.parquet``.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from mercurius.config.schema import AppConfig

log = logging.getLogger(__name__)

MAX_DAYS_TO_EXPIRY = 60
STRIKE_WINDOW_PCT = Decimal("0.15")

# The free plan serves "indicative" quotes only. This is requested explicitly,
# and stamped into every row, so a future OPRA subscription produces visibly
# different data rather than silently better data mixed into the same history.
# Change to "opra" only together with the Algo Trader Plus subscription.
SNAPSHOT_FEED = "indicative"


def _option_client(cfg: AppConfig):
    from alpaca.data.historical.option import OptionHistoricalDataClient

    return OptionHistoricalDataClient(
        api_key=cfg.secrets.alpaca_api_key.get_secret_value(),
        secret_key=cfg.secrets.alpaca_secret_key.get_secret_value(),
    )


def _spot(cfg: AppConfig, symbol: str) -> Decimal:
    from alpaca.data.requests import StockLatestTradeRequest

    from mercurius.data.alpaca_hist import _hist_client

    client = _hist_client(cfg)
    req = StockLatestTradeRequest(symbol_or_symbols=symbol, feed=cfg.data.feed.lower())
    trade = client.get_stock_latest_trade(req)
    return Decimal(str(trade[symbol].price))


def _num(value) -> str | None:
    return None if value is None else str(value)


def snapshot_chain(cfg: AppConfig, symbol: str, on: date | None = None) -> int:
    """Record one day's bounded option chain for `symbol`; returns row count."""
    from alpaca.data.requests import OptionChainRequest

    symbol = symbol.upper()
    on = on or datetime.now(tz=UTC).date()
    spot = _spot(cfg, symbol)
    lo = spot * (Decimal("1") - STRIKE_WINDOW_PCT)
    hi = spot * (Decimal("1") + STRIKE_WINDOW_PCT)

    from alpaca.data.enums import OptionsFeed

    feed = OptionsFeed(SNAPSHOT_FEED)
    req = OptionChainRequest(
        underlying_symbol=symbol,
        strike_price_gte=float(lo),
        strike_price_lte=float(hi),
        expiration_date_lte=on + timedelta(days=MAX_DAYS_TO_EXPIRY),
        feed=feed,
    )
    client = _option_client(cfg)
    chain = client.get_option_chain(req)
    rows = []
    for contract, snap in chain.items():
        quote = getattr(snap, "latest_quote", None)
        trade = getattr(snap, "latest_trade", None)
        greeks = getattr(snap, "greeks", None)
        rows.append(
            {
                "snapshot_date": on.isoformat(),
                "captured_at": datetime.now(tz=UTC).isoformat(),
                "underlying": symbol,
                "underlying_price": str(spot),
                "contract": contract,
                "feed": feed.value,
                "bid": _num(getattr(quote, "bid_price", None)),
                "ask": _num(getattr(quote, "ask_price", None)),
                "bid_size": _num(getattr(quote, "bid_size", None)),
                "ask_size": _num(getattr(quote, "ask_size", None)),
                "quote_ts": (
                    getattr(quote, "timestamp", None).isoformat()
                    if getattr(quote, "timestamp", None)
                    else None
                ),
                "last": _num(getattr(trade, "price", None)),
                "iv": _num(getattr(snap, "implied_volatility", None)),
                "delta": _num(getattr(greeks, "delta", None)),
                "gamma": _num(getattr(greeks, "gamma", None)),
                "theta": _num(getattr(greeks, "theta", None)),
                "vega": _num(getattr(greeks, "vega", None)),
            }
        )

    if not rows:
        log.warning("%s: option chain returned no contracts near %s", symbol, spot)
        return 0

    import pandas as pd

    path = Path(cfg.data.chain_snapshot_dir) / symbol / f"{on.isoformat()}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    log.info("%s: snapshotted %d contracts near spot %s -> %s", symbol, len(rows), spot, path)
    return len(rows)


def snapshot_cli(cfg: AppConfig) -> int:
    total = 0
    for symbol in cfg.symbols:
        try:
            n = snapshot_chain(cfg, symbol)
        except Exception:
            log.exception("chain snapshot failed for %s", symbol)
            continue
        total += n
        print(f"{symbol}: {n} contracts snapshotted")
    return 0 if total else 1
