"""Market clock. All session logic lives in US/Eastern; storage stays UTC.

Swiss local time must never appear anywhere in this codebase — the two DST
regimes (US switches mid-March/early-Nov, EU late-March/late-Oct) diverge for
a couple of weeks each year, and reasoning in ET is the only safe frame.

The NYSE calendar here is a small static table (full holidays + early closes)
covering 2023–2027. Refresh it yearly; `known_calendar_years` guards misuse.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)

# Full-day NYSE holidays.
_HOLIDAYS: frozenset[date] = frozenset(
    {
        # 2023
        date(2023, 1, 2),
        date(2023, 1, 16),
        date(2023, 2, 20),
        date(2023, 4, 7),
        date(2023, 5, 29),
        date(2023, 6, 19),
        date(2023, 7, 4),
        date(2023, 9, 4),
        date(2023, 11, 23),
        date(2023, 12, 25),
        # 2024
        date(2024, 1, 1),
        date(2024, 1, 15),
        date(2024, 2, 19),
        date(2024, 3, 29),
        date(2024, 5, 27),
        date(2024, 6, 19),
        date(2024, 7, 4),
        date(2024, 9, 2),
        date(2024, 11, 28),
        date(2024, 12, 25),
        # 2025
        date(2025, 1, 1),
        date(2025, 1, 9),
        date(2025, 1, 20),
        date(2025, 2, 17),
        date(2025, 4, 18),
        date(2025, 5, 26),
        date(2025, 6, 19),
        date(2025, 7, 4),
        date(2025, 9, 1),
        date(2025, 11, 27),
        date(2025, 12, 25),
        # 2026
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
        # 2027
        date(2027, 1, 1),
        date(2027, 1, 18),
        date(2027, 2, 15),
        date(2027, 3, 26),
        date(2027, 5, 31),
        date(2027, 6, 18),
        date(2027, 7, 5),
        date(2027, 9, 6),
        date(2027, 11, 25),
        date(2027, 12, 24),
    }
)

# 1:00 PM ET early closes.
_EARLY_CLOSES: frozenset[date] = frozenset(
    {
        date(2023, 7, 3),
        date(2023, 11, 24),
        date(2024, 7, 3),
        date(2024, 11, 29),
        date(2024, 12, 24),
        date(2025, 7, 3),
        date(2025, 11, 28),
        date(2025, 12, 24),
        date(2026, 11, 27),
        date(2026, 12, 24),
        date(2027, 11, 26),
    }
)

known_calendar_years: range = range(2023, 2028)


def _check_year(d: date) -> None:
    if d.year not in known_calendar_years:
        raise ValueError(
            f"NYSE calendar table covers {known_calendar_years.start}-"
            f"{known_calendar_years.stop - 1}; {d.year} needs a table refresh"
        )


def is_trading_day(d: date) -> bool:
    _check_year(d)
    return d.weekday() < 5 and d not in _HOLIDAYS


def close_time_et(d: date) -> time:
    _check_year(d)
    return EARLY_CLOSE if d in _EARLY_CLOSES else MARKET_CLOSE


@dataclass(frozen=True)
class Session:
    trading_date: date
    open_utc: datetime
    close_utc: datetime


def session_for(d: date) -> Session | None:
    if not is_trading_day(d):
        return None
    open_et = datetime.combine(d, MARKET_OPEN, tzinfo=ET)
    close_et = datetime.combine(d, close_time_et(d), tzinfo=ET)
    return Session(d, open_et.astimezone(UTC), close_et.astimezone(UTC))


def next_session(after_utc: datetime) -> Session:
    d = after_utc.astimezone(ET).date()
    for _ in range(10):
        s = session_for(d)
        if s is not None and s.open_utc > after_utc:
            return s
        d += timedelta(days=1)
    raise RuntimeError("no trading session found within 10 days")


class Clock(Protocol):
    def now_utc(self) -> datetime: ...


class WallClock:
    def now_utc(self) -> datetime:
        return datetime.now(tz=UTC)


class SimClock:
    """Driven by replayed bar timestamps so backtests share session logic."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("SimClock start must be tz-aware")
        self._now = start.astimezone(UTC)

    def now_utc(self) -> datetime:
        return self._now

    def advance_to(self, ts: datetime) -> None:
        ts = ts.astimezone(UTC)
        if ts < self._now:
            raise ValueError("SimClock cannot move backwards")
        self._now = ts


def is_market_open(clock: Clock) -> bool:
    now = clock.now_utc()
    s = session_for(now.astimezone(ET).date())
    return s is not None and s.open_utc <= now < s.close_utc


def minutes_to_close(clock: Clock) -> float | None:
    now = clock.now_utc()
    s = session_for(now.astimezone(ET).date())
    if s is None or not (s.open_utc <= now < s.close_utc):
        return None
    return (s.close_utc - now).total_seconds() / 60.0


def et_minute(ts_utc: datetime) -> tuple[int, int]:
    """(hour, minute) of a UTC timestamp in ET — for session-time rules."""
    et = ts_utc.astimezone(ET)
    return et.hour, et.minute
