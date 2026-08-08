"""Historical 1-minute bars from Alpaca, with a local parquet cache.

Guarantees every `Bar` leaving this module satisfies:

- **`ts_utc` is the bar CLOSE time.** Alpaca stamps a bar with the START of its
  aggregation window; one timeframe is added on ingest. The no-lookahead
  property of the backtest rests on this — a strategy must never see a bar
  before the minute it summarizes is over.
- **Regular trading hours only** (first close 09:31 ET, last close 16:00 ET, or
  13:00 ET on early-close days). Extended-hours bars would silently corrupt the
  ORB opening range and the session-open logic. The filter runs on *load*, so
  the cache keeps whatever the API returned and never needs re-downloading.
- **Prices are Decimal**, round-tripped through parquet as strings. No float
  ever touches a price.

Cache layout: ``<cache_dir>/<feed>/<SYMBOL>/<YYYY-MM>.parquet``, one file per
month. Bars at/after ``backtest.holdout_start`` are written under
``data.holdout_dir`` instead, so what is off-limits for fitting is visible on
disk rather than only in someone's head.

`load_cached_bars` still reads both trees: **the requested date range is the
holdout mechanism.** It has to be, because live trading and warmup run on
today's bars, which are themselves inside the holdout period. Fitting on the
holdout is prevented where it belongs — `sweep._assert_no_holdout` rejects any
bar list that reaches into it.
"""

from __future__ import annotations

import logging
import time as _time
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from mercurius.config.schema import AppConfig
from mercurius.core.clock import ET, close_time_et, is_trading_day
from mercurius.core.models import Bar

log = logging.getLogger(__name__)

BAR_MINUTES = 1
FIRST_RTH_CLOSE = time(9, 31)

# Alpaca allows 200 requests/min on the free plan; stay comfortably under it.
_MIN_REQUEST_INTERVAL_S = 0.35
_last_request_at = 0.0

_COLUMNS = ["ts_utc", "open", "high", "low", "close", "volume", "vwap"]


# -- clients ---------------------------------------------------------------
def _hist_client(cfg: AppConfig):
    from alpaca.data.historical.stock import StockHistoricalDataClient

    return StockHistoricalDataClient(
        api_key=cfg.secrets.alpaca_api_key.get_secret_value(),
        secret_key=cfg.secrets.alpaca_secret_key.get_secret_value(),
    )


def _throttle() -> None:
    global _last_request_at
    wait = _MIN_REQUEST_INTERVAL_S - (_time.monotonic() - _last_request_at)
    if wait > 0:
        _time.sleep(wait)
    _last_request_at = _time.monotonic()


# -- conversion ------------------------------------------------------------
def to_bar(symbol: str, raw) -> Bar:
    """Alpaca bar (start-stamped) -> our Bar (close-stamped, Decimal prices)."""
    ts = raw.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return Bar(
        symbol=symbol,
        ts_utc=ts.astimezone(UTC) + timedelta(minutes=BAR_MINUTES),
        open=Decimal(str(raw.open)),
        high=Decimal(str(raw.high)),
        low=Decimal(str(raw.low)),
        close=Decimal(str(raw.close)),
        volume=int(raw.volume or 0),
        vwap=Decimal(str(raw.vwap)) if getattr(raw, "vwap", None) is not None else None,
    )


def in_regular_hours(ts_utc: datetime) -> bool:
    """True if a close-stamped bar belongs to the regular session."""
    et = ts_utc.astimezone(ET)
    d = et.date()
    if not is_trading_day(d):
        return False
    return FIRST_RTH_CLOSE <= et.time() <= close_time_et(d)


# -- cache paths -----------------------------------------------------------
def _feed(cfg: AppConfig, feed: str | None = None) -> str:
    return (feed or cfg.data.feed).lower()


def _holdout_cutoff(cfg: AppConfig) -> datetime:
    return datetime.fromisoformat(cfg.backtest.holdout_start).replace(tzinfo=UTC)


def _month_path(cfg: AppConfig, symbol: str, ym: str, feed: str, holdout: bool) -> Path:
    root = cfg.data.holdout_dir if holdout else cfg.data.cache_dir
    return Path(root) / feed / symbol.upper() / f"{ym}.parquet"


def _months(start: date, end: date) -> list[str]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _parse_day(value: str) -> date:
    return date.fromisoformat(value[:10])


# -- parquet i/o -----------------------------------------------------------
def _write_month(path: Path, bars: list[Bar]) -> None:
    """Merge `bars` into the month file, de-duplicating on timestamp."""
    import pandas as pd

    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "ts_utc": [b.ts_utc.isoformat() for b in bars],
            "open": [str(b.open) for b in bars],
            "high": [str(b.high) for b in bars],
            "low": [str(b.low) for b in bars],
            "close": [str(b.close) for b in bars],
            "volume": [b.volume for b in bars],
            "vwap": [None if b.vwap is None else str(b.vwap) for b in bars],
        },
        columns=_COLUMNS,
    )
    if path.exists():
        frame = pd.concat([pd.read_parquet(path), frame], ignore_index=True)
    frame = frame.drop_duplicates(subset="ts_utc", keep="last").sort_values("ts_utc")
    frame.to_parquet(path, index=False)


def _read_month(path: Path, symbol: str) -> list[Bar]:
    import pandas as pd

    if not path.exists():
        return []
    frame = pd.read_parquet(path)
    out: list[Bar] = []
    for row in frame.itertuples(index=False):
        vwap = getattr(row, "vwap", None)
        out.append(
            Bar(
                symbol=symbol,
                ts_utc=datetime.fromisoformat(row.ts_utc),
                open=Decimal(row.open),
                high=Decimal(row.high),
                low=Decimal(row.low),
                close=Decimal(row.close),
                volume=int(row.volume),
                vwap=None if vwap is None or pd.isna(vwap) else Decimal(str(vwap)),
            )
        )
    return out


def _store(cfg: AppConfig, symbol: str, bars: list[Bar], feed: str) -> None:
    """Write bars into monthly files, routing the holdout to its own tree."""
    cutoff = _holdout_cutoff(cfg)
    buckets: dict[tuple[str, bool], list[Bar]] = {}
    for b in bars:
        key = (b.ts_utc.strftime("%Y-%m"), b.ts_utc >= cutoff)
        buckets.setdefault(key, []).append(b)
    for (ym, holdout), group in buckets.items():
        _write_month(_month_path(cfg, symbol, ym, feed, holdout), group)
        if holdout:
            log.info("%s %s: %d bars routed to the locked holdout", symbol, ym, len(group))


# -- fetching --------------------------------------------------------------
def fetch_bars(cfg: AppConfig, symbol: str, start: date, end: date, feed: str) -> list[Bar]:
    """One API call per month; returns raw (unfiltered) close-stamped bars."""
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = _hist_client(cfg)
    out: list[Bar] = []
    for ym in _months(start, end):
        y, m = (int(x) for x in ym.split("-"))
        m_start = max(start, date(y, m, 1))
        m_end = min(end, date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1))
        _throttle()
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=datetime.combine(m_start, time.min, tzinfo=UTC),
            end=datetime.combine(m_end, time.max, tzinfo=UTC),
            feed=DataFeed(feed),
            adjustment=Adjustment(cfg.data.adjustment),
        )
        bars = client.get_stock_bars(req)
        raws = bars.data.get(symbol, []) if hasattr(bars, "data") else bars.get(symbol, [])
        out.extend(to_bar(symbol, r) for r in raws)
        log.info("%s %s: fetched %d bars (%s)", symbol, ym, len(raws), feed)
    return out


def download_bars(
    cfg: AppConfig, symbol: str, start: str, end: str, feed: str | None = None
) -> int:
    """Download and cache bars for [start, end]; returns the number cached."""
    f = _feed(cfg, feed)
    bars = fetch_bars(cfg, symbol, _parse_day(start), _parse_day(end), f)
    _store(cfg, symbol, bars, f)
    return len(bars)


def load_cached_bars(
    cfg: AppConfig, symbol: str, start: str, end: str, feed: str | None = None
) -> list[Bar]:
    """Regular-hours bars from the cache for [start, end], sorted by close time.

    Reads both trees: **the requested date range is the holdout mechanism.**
    Ask for pre-2026 dates and you get no holdout data; ask for 2026 and you do
    — which is required, because live trading and warmup run on today's bars.

    What must never happen is *fitting* on the holdout, and that is enforced
    where it belongs: `sweep._assert_no_holdout` rejects any bar list reaching
    into the holdout, so a sweep handed these bars fails closed.
    """
    f = _feed(cfg, feed)
    d_start, d_end = _parse_day(start), _parse_day(end)
    symbol = symbol.upper()

    out: list[Bar] = []
    for ym in _months(d_start, d_end):
        out.extend(_read_month(_month_path(cfg, symbol, ym, f, holdout=False), symbol))
        out.extend(_read_month(_month_path(cfg, symbol, ym, f, holdout=True), symbol))

    # De-duplicate across the two trees: moving `holdout_start` forward leaves
    # the old holdout files in place while fresh downloads land in the cache,
    # and a duplicated minute would be replayed twice by the backtest.
    kept: dict[datetime, Bar] = {}
    for b in out:
        if d_start <= b.ts_utc.astimezone(ET).date() <= d_end and in_regular_hours(b.ts_utc):
            kept[b.ts_utc] = b
    return [kept[ts] for ts in sorted(kept)]


# -- CLI entrypoints -------------------------------------------------------
def download_cli(cfg: AppConfig, symbols: list[str], start: str | None, end: str | None) -> int:
    start = start or cfg.backtest.start
    end = end or cfg.backtest.end
    for symbol in symbols:
        symbol = symbol.strip().upper()
        n = download_bars(cfg, symbol, start, end)
        usable = len(load_cached_bars(cfg, symbol, start, end))
        print(f"{symbol}: {n} bars cached, {usable} regular-hours bars usable ({start}..{end})")
    return 0


def feed_diagnostic_cli(cfg: AppConfig, symbol: str, start: str, end: str) -> int:
    """Quantify what the free IEX tape misses versus consolidated SIP.

    IEX is one venue (~2-3% of consolidated volume); the bot trades it because
    it is the feed the free plan streams live. This measures the gap so the
    backtest's optimism is a known number rather than an assumption.
    """
    from alpaca.common.exceptions import APIError

    symbol = symbol.upper()
    d_start, d_end = _parse_day(start), _parse_day(end)

    iex = [b for b in fetch_bars(cfg, symbol, d_start, d_end, "iex") if in_regular_hours(b.ts_utc)]
    try:
        sip = [
            b for b in fetch_bars(cfg, symbol, d_start, d_end, "sip") if in_regular_hours(b.ts_utc)
        ]
    except APIError as e:
        print(f"\n=== feed diagnostic {symbol} {start}..{end} ===")
        print(f"IEX regular-hours bars: {len(iex)}")
        print(f"SIP unavailable on this plan ({e}).")
        print("Record this as the diagnostic result: IEX-only, divergence unmeasured.")
        return 0

    by_ts_iex = {b.ts_utc: b for b in iex}
    by_ts_sip = {b.ts_utc: b for b in sip}
    missing = sorted(set(by_ts_sip) - set(by_ts_iex))
    common = sorted(set(by_ts_sip) & set(by_ts_iex))

    diffs_bps = [
        abs(by_ts_iex[ts].close - by_ts_sip[ts].close) / by_ts_sip[ts].close * Decimal("10000")
        for ts in common
        if by_ts_sip[ts].close
    ]
    diffs_bps.sort()
    iex_vol = sum(by_ts_iex[ts].volume for ts in common)
    sip_vol = sum(by_ts_sip[ts].volume for ts in common)

    def _pct(values: list[Decimal], q: float) -> Decimal:
        return values[min(len(values) - 1, int(q * len(values)))] if values else Decimal("0")

    print(f"\n=== feed diagnostic {symbol} {start}..{end} ===")
    print(f"SIP regular-hours bars     : {len(sip)}")
    print(f"IEX regular-hours bars     : {len(iex)}")
    print(
        f"minutes missing from IEX   : {len(missing)} "
        f"({len(missing) / max(1, len(sip)) * 100:.2f}% of SIP minutes)"
    )
    if diffs_bps:
        print(f"close divergence  median   : {_pct(diffs_bps, 0.50):.2f} bps")
        print(f"close divergence  p95      : {_pct(diffs_bps, 0.95):.2f} bps")
        print(f"close divergence  max      : {diffs_bps[-1]:.2f} bps")
    print(
        f"IEX volume share           : {iex_vol / sip_vol * 100:.2f}%"
        if sip_vol
        else "IEX volume share           : n/a"
    )
    print(
        "\nInterpretation: missing minutes are minutes the bot is blind during; "
        "divergence is the error in every backtest fill price."
    )
    return 0
