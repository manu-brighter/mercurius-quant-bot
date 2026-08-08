"""Daily bars for swing strategies.

Same guarantees as the minute-bar module (close-stamped, Decimal, holdout
routing) with daily granularity: a daily bar's `ts_utc` is the session CLOSE
(16:00 ET, or 13:00 on early closes), so a swing strategy deciding on a daily
bar can never see it before the session it summarizes is over.

Feed note: daily bars default to the SIP-derived consolidated aggregates (free
tier serves them delayed, which is irrelevant for after-close decisions) —
unlike intraday, where the free live stream is IEX-only and backtests are
pinned to IEX to match. For end-of-day closes the consolidated figure IS the
number every published daily-bar strategy was built on.

Cache layout: ``<cache_dir>/daily/<feed>/<SYMBOL>/<YYYY-MM>.parquet``; bars
at/after ``backtest.holdout_start`` route to ``<holdout_dir>/daily/...``.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from mercurius.config.schema import AppConfig
from mercurius.core.clock import ET, close_time_et, is_trading_day
from mercurius.core.models import Bar
from mercurius.data.alpaca_hist import (
    _hist_client,
    _holdout_cutoff,
    _months,
    _parse_day,
    _read_month,
    _throttle,
    _write_month,
)

log = logging.getLogger(__name__)

DAILY_FEED = "sip"  # consolidated aggregates; delayed on free tier, fine for EOD


def _tree(cfg: AppConfig, holdout: bool) -> Path:
    root = cfg.data.holdout_dir if holdout else cfg.data.cache_dir
    return Path(root) / "daily" / DAILY_FEED


def _month_path(cfg: AppConfig, symbol: str, ym: str, holdout: bool) -> Path:
    return _tree(cfg, holdout) / symbol.upper() / f"{ym}.parquet"


def _close_stamp(trading_day: date) -> datetime:
    return datetime.combine(trading_day, close_time_et(trading_day), tzinfo=ET).astimezone(UTC)


def fetch_daily_bars(cfg: AppConfig, symbol: str, start: date, end: date) -> list[Bar]:
    """Fetch daily bars over REST; close-stamped, trading days only."""
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = _hist_client(cfg)
    _throttle()
    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
        end=datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
        adjustment=Adjustment(cfg.data.adjustment),
        feed=DataFeed(DAILY_FEED),
    )
    barset = client.get_stock_bars(req)
    raws = barset.data.get(symbol, []) if hasattr(barset, "data") else []
    out: list[Bar] = []
    for raw in raws:
        d = raw.timestamp.astimezone(ET).date() if raw.timestamp.tzinfo else raw.timestamp.date()
        if not is_trading_day(d):
            continue
        out.append(
            Bar(
                symbol=symbol,
                ts_utc=_close_stamp(d),
                open=Decimal(str(raw.open)),
                high=Decimal(str(raw.high)),
                low=Decimal(str(raw.low)),
                close=Decimal(str(raw.close)),
                volume=int(raw.volume or 0),
                vwap=Decimal(str(raw.vwap)) if getattr(raw, "vwap", None) is not None else None,
            )
        )
    out.sort(key=lambda b: b.ts_utc)
    return out


def download_daily_bars(cfg: AppConfig, symbol: str, start: str, end: str) -> int:
    bars = fetch_daily_bars(cfg, symbol, _parse_day(start), _parse_day(end))
    if not bars:
        log.warning("no daily bars for %s %s..%s", symbol, start, end)
        return 0
    cutoff = _holdout_cutoff(cfg)
    buckets: dict[tuple[str, bool], list[Bar]] = {}
    for b in bars:
        key = (b.ts_utc.strftime("%Y-%m"), b.ts_utc >= cutoff)
        buckets.setdefault(key, []).append(b)
    for (ym, holdout), group in buckets.items():
        _write_month(_month_path(cfg, symbol, ym, holdout), group)
    log.info("cached %d daily bars for %s", len(bars), symbol)
    return len(bars)


def load_cached_daily_bars(cfg: AppConfig, symbol: str, start: str, end: str) -> list[Bar]:
    lo, hi = _parse_day(start), _parse_day(end)
    out: list[Bar] = []
    for ym in _months(lo, hi):
        for holdout in (False, True):
            out.extend(_read_month(_month_path(cfg, symbol, ym, holdout), symbol))
    lo_dt = datetime.combine(lo, datetime.min.time(), tzinfo=UTC)
    hi_dt = datetime.combine(hi + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    out = [b for b in out if lo_dt <= b.ts_utc < hi_dt]
    out.sort(key=lambda b: b.ts_utc)
    return out


def download_daily_cli(
    cfg: AppConfig, symbols: list[str], start: str | None, end: str | None
) -> int:
    """`mercurius download-data --timeframe daily`.

    Swing strategies need 200 sessions of warmup before their first signal, so
    the default start reaches well back beyond the backtest window.
    """
    start = start or "2015-01-01"
    end = end or cfg.backtest.end
    total = 0
    for symbol in symbols:
        total += download_daily_bars(cfg, symbol.strip().upper(), start, end)
    print(f"cached {total} daily bars across {len(symbols)} symbols")
    return 0 if total else 1
