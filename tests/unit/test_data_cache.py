"""Bar cache invariants: close-stamping, session filtering, holdout separation.

These are the properties the whole no-lookahead design rests on, so they are
tested against the pure functions — no network, no Alpaca.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from mercurius.config.schema import AppConfig
from mercurius.core.models import Bar
from mercurius.data.alpaca_hist import (
    _store,
    in_regular_hours,
    load_cached_bars,
    to_bar,
)

ET_OFFSET_WINTER = timedelta(hours=-5)


def _cfg(tmp_path) -> AppConfig:
    cfg = AppConfig()
    cfg.data.cache_dir = tmp_path / "cache"
    cfg.data.holdout_dir = tmp_path / "holdout"
    return cfg


def _et(y, m, d, hh, mm) -> datetime:
    """A UTC instant expressed from an ET wall-clock time (winter, UTC-5)."""
    return datetime(y, m, d, hh, mm, tzinfo=UTC) - ET_OFFSET_WINTER


def _bar(ts: datetime, symbol: str = "SPY", close: str = "500.12") -> Bar:
    return Bar(
        symbol=symbol,
        ts_utc=ts,
        open=Decimal("500.01"),
        high=Decimal("500.99"),
        low=Decimal("499.55"),
        close=Decimal(close),
        volume=1234,
        vwap=Decimal("500.40"),
    )


# -- close stamping --------------------------------------------------------
def test_to_bar_shifts_start_stamp_to_close():
    """Alpaca stamps the bar START; a strategy may only see completed bars."""
    raw = SimpleNamespace(
        timestamp=datetime(2025, 3, 4, 14, 30, tzinfo=UTC),
        open=500.1,
        high=500.9,
        low=499.9,
        close=500.5,
        volume=1000,
        vwap=500.4,
    )
    bar = to_bar("SPY", raw)
    assert bar.ts_utc == datetime(2025, 3, 4, 14, 31, tzinfo=UTC)
    assert bar.close == Decimal("500.5")
    assert isinstance(bar.close, Decimal)


def test_to_bar_assumes_utc_for_naive_stamps():
    raw = SimpleNamespace(
        timestamp=datetime(2025, 3, 4, 14, 30),
        open=1,
        high=1,
        low=1,
        close=1,
        volume=0,
        vwap=None,
    )
    assert to_bar("SPY", raw).ts_utc == datetime(2025, 3, 4, 14, 31, tzinfo=UTC)


# -- session filtering -----------------------------------------------------
@pytest.mark.parametrize(
    ("hh", "mm", "expected"),
    [
        (9, 30, False),  # closes the 09:29 pre-market minute
        (9, 31, True),  # first regular-hours bar
        (12, 0, True),
        (16, 0, True),  # last regular-hours bar
        (16, 1, False),  # after-hours
        (4, 0, False),  # pre-market
    ],
)
def test_regular_hours_boundaries(hh, mm, expected):
    assert in_regular_hours(_et(2025, 3, 4, hh, mm)) is expected


def test_regular_hours_excludes_weekends_and_holidays():
    assert in_regular_hours(_et(2025, 3, 8, 12, 0)) is False  # Saturday
    assert in_regular_hours(_et(2025, 7, 4, 12, 0)) is False  # Independence Day


def test_regular_hours_respects_early_close():
    """2025-11-28 is a 13:00 ET early close."""
    assert in_regular_hours(_et(2025, 11, 28, 13, 0)) is True
    assert in_regular_hours(_et(2025, 11, 28, 13, 1)) is False


# -- cache round-trip ------------------------------------------------------
def test_cache_round_trip_preserves_decimals(tmp_path):
    cfg = _cfg(tmp_path)
    bars = [_bar(_et(2025, 3, 4, 9, 31) + timedelta(minutes=i)) for i in range(5)]
    _store(cfg, "SPY", bars, "iex")

    loaded = load_cached_bars(cfg, "SPY", "2025-03-04", "2025-03-04")
    assert [b.ts_utc for b in loaded] == [b.ts_utc for b in bars]
    assert loaded[0].close == Decimal("500.12")
    assert loaded[0].vwap == Decimal("500.40")
    assert loaded[0].volume == 1234


def test_load_drops_extended_hours_bars(tmp_path):
    cfg = _cfg(tmp_path)
    _store(
        cfg,
        "SPY",
        [
            _bar(_et(2025, 3, 4, 8, 0)),  # pre-market
            _bar(_et(2025, 3, 4, 10, 0)),  # regular
            _bar(_et(2025, 3, 4, 18, 0)),  # after-hours
        ],
        "iex",
    )
    loaded = load_cached_bars(cfg, "SPY", "2025-03-04", "2025-03-04")
    assert [b.ts_utc for b in loaded] == [_et(2025, 3, 4, 10, 0)]


def test_store_is_idempotent(tmp_path):
    cfg = _cfg(tmp_path)
    bars = [_bar(_et(2025, 3, 4, 9, 31) + timedelta(minutes=i)) for i in range(3)]
    _store(cfg, "SPY", bars, "iex")
    _store(cfg, "SPY", bars, "iex")
    assert len(load_cached_bars(cfg, "SPY", "2025-03-04", "2025-03-04")) == 3


# -- holdout separation ----------------------------------------------------
def test_holdout_bars_are_stored_in_their_own_tree(tmp_path):
    """Holdout data is separated on disk so it is visible and lockable."""
    cfg = _cfg(tmp_path)
    pre = _bar(_et(2025, 12, 31, 12, 0))
    post = _bar(_et(2026, 1, 5, 12, 0))
    _store(cfg, "SPY", [pre, post], "iex")

    assert (cfg.data.cache_dir / "iex" / "SPY" / "2025-12.parquet").exists()
    assert (cfg.data.holdout_dir / "iex" / "SPY" / "2026-01.parquet").exists()
    assert not (cfg.data.cache_dir / "iex" / "SPY" / "2026-01.parquet").exists()


def test_requested_range_is_the_holdout_mechanism(tmp_path):
    """Live/warmup must get today's bars; a pre-2026 range must get none."""
    cfg = _cfg(tmp_path)
    pre = _bar(_et(2025, 12, 31, 12, 0))
    post = _bar(_et(2026, 1, 5, 12, 0))
    _store(cfg, "SPY", [pre, post], "iex")

    fit_range = load_cached_bars(cfg, "SPY", "2025-01-01", "2025-12-31")
    assert [b.ts_utc for b in fit_range] == [pre.ts_utc]

    spanning = load_cached_bars(cfg, "SPY", "2025-12-01", "2026-01-31")
    assert [b.ts_utc for b in spanning] == [pre.ts_utc, post.ts_utc]


def test_same_minute_in_both_trees_is_returned_once(tmp_path):
    """Moving holdout_start forward strands old files; a replayed duplicate
    minute would corrupt the backtest silently."""
    cfg = _cfg(tmp_path)
    bar = _bar(_et(2026, 1, 5, 12, 0))
    _store(cfg, "SPY", [bar], "iex")  # -> holdout tree

    cfg.backtest.holdout_start = "2027-01-01"
    _store(cfg, "SPY", [bar], "iex")  # -> cache tree, same minute

    assert (cfg.data.holdout_dir / "iex" / "SPY" / "2026-01.parquet").exists()
    assert (cfg.data.cache_dir / "iex" / "SPY" / "2026-01.parquet").exists()
    assert [b.ts_utc for b in load_cached_bars(cfg, "SPY", "2026-01-01", "2026-01-31")] == [
        bar.ts_utc
    ]


def test_sweep_rejects_bars_loaded_across_the_holdout(tmp_path):
    """The enforcement point: loading holdout bars is fine, fitting on them is not."""
    from mercurius.backtest.sweep import HoldoutViolation, _assert_no_holdout

    cfg = _cfg(tmp_path)
    _store(cfg, "SPY", [_bar(_et(2025, 12, 31, 12, 0)), _bar(_et(2026, 1, 5, 12, 0))], "iex")
    bars = load_cached_bars(cfg, "SPY", "2025-12-01", "2026-01-31")

    with pytest.raises(HoldoutViolation):
        _assert_no_holdout(cfg, bars)


def test_symbols_do_not_bleed_between_caches(tmp_path):
    cfg = _cfg(tmp_path)
    _store(cfg, "SPY", [_bar(_et(2025, 3, 4, 10, 0), "SPY")], "iex")
    _store(cfg, "QQQ", [_bar(_et(2025, 3, 4, 10, 0), "QQQ")], "iex")
    loaded = load_cached_bars(cfg, "QQQ", "2025-03-04", "2025-03-04")
    assert [b.symbol for b in loaded] == ["QQQ"]
