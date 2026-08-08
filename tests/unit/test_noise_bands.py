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


def _warm(strat, ctx, d, sessions=5):
    for i in range(sessions):
        _feed_session(strat, ctx, d + timedelta(days=i), _quiet_session_prices())


def _long_position():
    from datetime import UTC, datetime

    from mercurius.core.models import Position

    return Position("SPY", Decimal("1"), Decimal("101"), datetime(2026, 8, 10, 14, 0, tzinfo=UTC))


def test_exit_is_continuous_not_only_at_decision_marks():
    """Fidelity: the paper closes 'immediately' when the trail is crossed.

    Our pre-audit version only checked exits at :00/:30, which held losers up
    to 29 minutes too long. The exit must be able to fire on any bar.
    """
    strat = NoiseBandsStrategy(lookback_days=5)
    ctx = StrategyContext("SPY")
    d = date(2026, 8, 3)
    _warm(strat, ctx, d)
    # flat day at the open: price sits inside the noise -> immediate exit
    prices = [100.0] * 35
    events = _feed_session(strat, ctx, d + timedelta(days=7), prices, position=_long_position())
    exits = [(b, s) for b, s in events if s.kind == SignalKind.EXIT]
    assert exits, "a long below its trail must exit"
    first_exit_bar = exits[0][0]
    assert first_exit_bar.ts_utc.minute not in (0, 30), (
        "exit fired only on a decision mark — the continuous trailing check regressed"
    )


def test_winner_is_held_while_above_trail():
    """A rallying long must NOT be churned out at the next decision mark.

    This is the economic point of the audit: fewer round trips per unit of
    signal means less cost drag.
    """
    strat = NoiseBandsStrategy(lookback_days=5)
    ctx = StrategyContext("SPY")
    d = date(2026, 8, 3)
    _warm(strat, ctx, d)

    # Drive the session like the engine does: open flat, adopt the position the
    # strategy asks for, then keep rallying and check it is never churned out.
    from datetime import UTC, datetime

    from mercurius.core.models import Position

    strat.on_session_start(ctx)
    ctx._set_position(None)
    entered = False
    exits = []
    for bar in minute_bars("SPY", d + timedelta(days=7), [100.0 + 0.04 * i for i in range(35)]):
        ctx._push_bar(bar)
        for sig in strat.on_bar(ctx, bar):
            if sig.kind == SignalKind.ENTER_LONG:
                entered = True
                ctx._set_position(Position("SPY", Decimal("1"), bar.close, datetime.now(tz=UTC)))
            elif sig.kind == SignalKind.EXIT:
                exits.append((bar, sig))
    assert entered, "expected the rally to trigger an entry"
    assert not exits, f"held position exited during an ongoing rally: {exits}"


def test_entry_stop_is_the_band_not_a_fixed_percentage():
    strat = NoiseBandsStrategy(lookback_days=5)
    ctx = StrategyContext("SPY")
    d = date(2026, 8, 3)
    _warm(strat, ctx, d)
    prices = [100.0 + 0.04 * i for i in range(35)]
    events = _feed_session(strat, ctx, d + timedelta(days=7), prices)
    longs = [(b, s) for b, s in events if s.kind == SignalKind.ENTER_LONG]
    assert longs
    bar, sig = longs[0]
    assert sig.stop_price is not None
    # The band is anchored to the SESSION OPEN (100.0) plus a tiny width, so the
    # stop sits near the open. A fixed 0.5% trail would instead sit just under
    # the ENTRY price, which is ~1% higher on this rally — the two are far apart.
    day_open = Decimal("100.0")
    assert abs(sig.stop_price - day_open) / day_open < Decimal("0.005")
    fixed_pct_trail = bar.close * Decimal("0.995")
    assert abs(sig.stop_price - fixed_pct_trail) > Decimal("0.25")
