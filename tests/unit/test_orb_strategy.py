"""Golden-file style tests: synthetic sessions with known expected signals."""

from datetime import date, timedelta
from decimal import Decimal

from mercurius.core.enums import SignalKind
from mercurius.strategies.base import StrategyContext
from mercurius.strategies.orb import OrbStrategy
from tests.helpers import minute_bars

D0 = date(2026, 8, 3)  # Monday


def _run_session(strat, trading_date, prices, volumes=None, position=None):
    ctx = StrategyContext(strat.symbol)
    ctx._set_position(position)
    strat.on_session_start(ctx)
    out = []
    for bar in minute_bars(strat.symbol, trading_date, prices, volumes=volumes):
        ctx._push_bar(bar)
        out.extend((bar, s) for s in strat.on_bar(ctx, bar))
    strat.on_session_end(ctx)
    return out


def _strat(**kw):
    defaults = dict(symbol="QQQ", ema_filter_period=5)
    defaults.update(kw)
    return OrbStrategy(**defaults)


def _warm(strat):
    """Feed one prior quiet session so the 20-bar volume median has history.

    (In production the median carries across sessions; only the very first
    20 bars of a fresh backtest lack it, by design.)
    """
    _run_session(strat, D0 - timedelta(days=3), [100.0 + 0.01 * (i % 3) for i in range(25)])


def test_breakout_long_fires_on_close_beyond_range():
    strat = _strat()
    _warm(strat)
    # OR bars (5): drift up 100 -> 101 (clear body, no doji). Then breakout at bar 8.
    prices = [100.0, 100.3, 100.6, 100.8, 101.0, 100.9, 100.95, 101.5, 101.6, 101.7]
    volumes = [10_000] * 7 + [30_000, 10_000, 10_000]  # breakout bar has volume
    # ATR warmup not satisfied (needs 14 sessions) -> ATR filter inactive; fine.
    events = _run_session(strat, D0, prices, volumes)
    entries = [(b, s) for b, s in events if s.kind == SignalKind.ENTER_LONG]
    assert len(entries) == 1
    bar, sig = entries[0]
    assert bar.close == Decimal("101.5")  # the first close beyond OR high (~101.01)
    assert sig.stop_price == strat._or_low
    assert sig.target_price is not None


def test_doji_opening_range_blocks_day():
    strat = _strat()
    # OR: open 100.0, close back at 100.02 with range ~1 -> body < 10% of range
    prices = [100.0, 100.9, 100.1, 100.5, 100.02, 101.5, 102.0, 102.5]
    volumes = [10_000] * 5 + [50_000] * 3
    events = _run_session(strat, D0, prices, volumes)
    assert not events  # doji day: no signals despite a clean breakout


def test_low_volume_breakout_is_ignored():
    strat = _strat()
    prices = [100.0, 100.3, 100.6, 100.8, 101.0, 101.5, 101.6, 101.7]
    volumes = [10_000] * 8  # breakout bar volume == median, not > 1.5x
    events = _run_session(strat, D0, prices, volumes)
    assert not [e for _, e in events if e.kind == SignalKind.ENTER_LONG]


def test_one_trade_per_day():
    strat = _strat()
    _warm(strat)
    prices = [100.0, 100.3, 100.6, 100.8, 101.0] + [101.5, 100.5, 101.6, 100.4, 101.8]
    volumes = [10_000] * 5 + [30_000] * 5
    events = _run_session(strat, D0, prices, volumes)
    entries = [e for _, e in events if e.kind == SignalKind.ENTER_LONG]
    assert len(entries) == 1


def test_entry_cutoff_blocks_late_breakouts():
    strat = _strat(entry_cutoff="09:40")
    # breakout at minute 12 (09:42) — after cutoff
    prices = [100.0, 100.3, 100.6, 100.8, 101.0] + [100.9] * 6 + [101.5]
    volumes = [10_000] * 11 + [40_000]
    events = _run_session(strat, D0, prices, volumes)
    assert not [e for _, e in events if e.kind == SignalKind.ENTER_LONG]


def test_short_breakout_with_ema_gate():
    strat = _strat()
    _warm(strat)
    prices = [100.0, 99.8, 99.6, 99.4, 99.2, 98.5, 98.4]
    volumes = [10_000] * 5 + [30_000, 10_000]
    events = _run_session(strat, D0, prices, volumes)
    shorts = [e for _, e in events if e.kind == SignalKind.ENTER_SHORT]
    assert len(shorts) == 1
    assert shorts[0].stop_price == strat._or_high


def test_atr_filter_blocks_oversized_range():
    strat = _strat()
    # 15 quiet sessions: the prior session's OHLC is pushed into the ATR on the
    # NEXT session's start, so 15 sessions yield the 14 pushes ATR(14) needs.
    for _ in range(15):
        _run_session(strat, D0, [100.0, 100.4, 100.6, 100.8, 100.2, 100.5])
    assert strat._atr.value is not None
    # now a session whose 5-min range (~3.0) is > 0.60 x ATR
    prices = [100.0, 101.5, 99.5, 102.0, 102.5, 103.5, 104.0]
    volumes = [10_000] * 5 + [40_000] * 2
    events = _run_session(strat, D0, prices, volumes)
    assert not events  # range too wide vs ATR -> no-trade day
