from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from mercurius.core import clock
from mercurius.core.clock import (
    ET,
    SimClock,
    et_minute,
    is_market_open,
    is_trading_day,
    minutes_to_close,
    next_session,
    session_for,
)

ZURICH = ZoneInfo("Europe/Zurich")


def test_holiday_and_weekend():
    assert not is_trading_day(date(2026, 7, 3))  # July 4th observed
    assert not is_trading_day(date(2026, 8, 8))  # Saturday
    assert is_trading_day(date(2026, 8, 7))


def test_early_close():
    s = session_for(date(2026, 11, 27))  # day after Thanksgiving, 1pm close
    assert s is not None
    assert s.close_utc.astimezone(ET).hour == 13


def test_calendar_year_guard():
    with pytest.raises(ValueError, match="calendar table"):
        is_trading_day(date(2030, 1, 2))


def test_session_open_close_utc_normal():
    s = session_for(date(2026, 8, 7))
    assert s is not None
    # EDT: 9:30 ET == 13:30 UTC
    assert s.open_utc == datetime(2026, 8, 7, 13, 30, tzinfo=UTC)
    assert s.close_utc == datetime(2026, 8, 7, 20, 0, tzinfo=UTC)


def test_dst_divergence_week_march():
    """US switches 2026-03-08; EU switches 2026-03-29. In between, the NYSE
    open is 14:30 Swiss time instead of the usual 15:30 — session math must
    come from ET, never from a fixed UTC or Swiss offset."""
    s = session_for(date(2026, 3, 10))
    assert s is not None
    open_zurich = s.open_utc.astimezone(ZURICH)
    assert (open_zurich.hour, open_zurich.minute) == (14, 30)

    # After both switched (April): back to 15:30 Swiss.
    s2 = session_for(date(2026, 4, 10))
    assert s2 is not None
    open_zurich2 = s2.open_utc.astimezone(ZURICH)
    assert (open_zurich2.hour, open_zurich2.minute) == (15, 30)


def test_dst_divergence_week_autumn():
    """EU switches 2026-10-25; US switches 2026-11-01. In between: 14:30 open."""
    s = session_for(date(2026, 10, 27))
    assert s is not None
    open_zurich = s.open_utc.astimezone(ZURICH)
    assert (open_zurich.hour, open_zurich.minute) == (14, 30)


def test_sim_clock_monotonic():
    c = SimClock(datetime(2026, 8, 7, 13, 30, tzinfo=UTC))
    c.advance_to(datetime(2026, 8, 7, 13, 31, tzinfo=UTC))
    with pytest.raises(ValueError):
        c.advance_to(datetime(2026, 8, 7, 13, 30, tzinfo=UTC))


def test_market_open_and_minutes_to_close():
    c = SimClock(datetime(2026, 8, 7, 19, 30, tzinfo=UTC))  # 15:30 ET
    assert is_market_open(c)
    assert minutes_to_close(c) == pytest.approx(30.0)

    c2 = SimClock(datetime(2026, 8, 8, 15, 0, tzinfo=UTC))  # Saturday
    assert not is_market_open(c2)
    assert minutes_to_close(c2) is None


def test_next_session_skips_weekend():
    s = next_session(datetime(2026, 8, 7, 21, 0, tzinfo=UTC))  # Fri after close
    assert s.trading_date == date(2026, 8, 10)  # Monday


def test_et_minute():
    assert et_minute(datetime(2026, 8, 7, 13, 30, tzinfo=UTC)) == (9, 30)


def test_all_sessions_iterable_2024_2026():
    # calendar smoke: trading day counts should land near 250-253/yr
    for year, expected in [(2024, 252), (2025, 250), (2026, 251)]:
        n = sum(
            1
            for d in range(1, 367)
            if (dt := date.fromordinal(date(year, 1, 1).toordinal() + d - 1)).year == year
            and clock.is_trading_day(dt)
        )
        assert abs(n - expected) <= 2, f"{year}: {n} trading days looks wrong"
