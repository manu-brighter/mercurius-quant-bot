from datetime import date, timedelta
from decimal import Decimal

from mercurius.core.enums import SignalKind
from mercurius.strategies.base import StrategyContext
from mercurius.strategies.noise_bands import NoiseBandsStrategy
from tests.helpers import minute_bars


def _feed_session(strat, ctx, trading_date, prices, position=None):
    ctx._set_position(position)
    strat.on_session_start(ctx)
    out = []
    for bar in minute_bars(strat.symbol, trading_date, prices):
        ctx._push_bar(bar)
        out.extend((bar, s) for s in strat.on_bar(ctx, bar))
    strat.on_session_end(ctx)
    return out


def _quiet_session_prices(n=65):
    # ±0.05% wiggle around 100 -> tiny noise bands
    return [100.0 + 0.05 * ((-1) ** i) for i in range(n)]


def test_warmup_silence_before_lookback_sessions():
    strat = NoiseBandsStrategy(lookback_days=5)
    ctx = StrategyContext("SPY")
    d = date(2026, 8, 3)
    for i in range(4):  # fewer than lookback sessions
        events = _feed_session(strat, ctx, d + timedelta(days=i), _quiet_session_prices())
        assert events == [], "no signals allowed during warmup"


def test_long_signal_beyond_upper_band():
    strat = NoiseBandsStrategy(lookback_days=5, decision_minutes=(0, 30))
    ctx = StrategyContext("SPY")
    d = date(2026, 8, 3)
    for i in range(5):
        _feed_session(strat, ctx, d + timedelta(days=i), _quiet_session_prices())
    # day 6: strong rally: by 10:00 price is 1% above open — way beyond tiny bands
    prices = [100.0 + 0.04 * i for i in range(35)]
    events = _feed_session(strat, ctx, d + timedelta(days=7), prices)
    longs = [(b, s) for b, s in events if s.kind == SignalKind.ENTER_LONG]
    assert longs, "expected a long entry beyond the upper noise band"
    bar, sig = longs[0]
    # decision bars only: entry must be at :00 or :30 ET
    assert bar.ts_utc.minute in (0, 30)
    assert sig.stop_price is not None and sig.stop_price < bar.close


def test_short_signal_beyond_lower_band():
    strat = NoiseBandsStrategy(lookback_days=5)
    ctx = StrategyContext("SPY")
    d = date(2026, 8, 3)
    for i in range(5):
        _feed_session(strat, ctx, d + timedelta(days=i), _quiet_session_prices())
    prices = [100.0 - 0.04 * i for i in range(35)]
    events = _feed_session(strat, ctx, d + timedelta(days=7), prices)
    shorts = [(b, s) for b, s in events if s.kind == SignalKind.ENTER_SHORT]
    assert shorts
    bar, sig = shorts[0]
    assert sig.stop_price is not None and sig.stop_price > bar.close  # stop above short entry


def test_no_signal_inside_noise():
    strat = NoiseBandsStrategy(lookback_days=5)
    ctx = StrategyContext("SPY")
    d = date(2026, 8, 3)
    # noisy warmup sessions: ±1% swings -> wide bands
    wave = [100.0 + (1.0 if (i // 5) % 2 == 0 else -1.0) for i in range(65)]
    for i in range(5):
        _feed_session(strat, ctx, d + timedelta(days=i), wave)
    # a mild day well inside those wide bands
    prices = [100.0 + 0.002 * i for i in range(35)]
    events = _feed_session(strat, ctx, d + timedelta(days=7), prices)
    assert not [s for _, s in events if s.kind != SignalKind.EXIT]


def test_exit_when_price_returns_inside_band():
    from datetime import UTC, datetime

    from mercurius.core.models import Position

    strat = NoiseBandsStrategy(lookback_days=5)
    ctx = StrategyContext("SPY")
    d = date(2026, 8, 3)
    for i in range(5):
        _feed_session(strat, ctx, d + timedelta(days=i), _quiet_session_prices())
    pos = Position("SPY", Decimal("1"), Decimal("101"), datetime(2026, 8, 10, 14, 0, tzinfo=UTC))
    # flat day: price hovers at open -> inside noise -> long position must exit
    prices = [100.0] * 35
    events = _feed_session(strat, ctx, d + timedelta(days=7), prices, position=pos)
    exits = [s for _, s in events if s.kind == SignalKind.EXIT]
    assert exits, "long position inside the noise band must be exited at a decision mark"
