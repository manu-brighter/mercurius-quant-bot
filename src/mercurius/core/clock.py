"""Market clock. All session logic lives in US/Eastern; storage stays UTC.

Swiss local time must never appear anywhere in this codebase — the two DST
regimes (US switches mid-March/early-Nov, EU late-March/late-Oct) diverge for
a couple of weeks each year, and reasoning in ET is the only safe frame.

The NYSE calendar here is a small static table (full holidays + early closes)
covering 2016–2027. Refresh it yearly; `known_calendar_years` guards misuse.
The 2016 floor is Alpaca's daily-history start, not an arbitrary cutoff.
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
#
# 2016-2022 were derived from Alpaca's consolidated daily bars (a weekday with
# no bar was a closure) and cross-checked against the published NYSE calendar —
# both agree, including the 2018-12-05 national day of mourning and the absence
# of a New Year's holiday in 2022 (Jan 1 fell on a Saturday). Deriving beats
# typing: a wrongly-listed holiday silently drops a real session from every
# backtest. Alpaca daily history begins 2016-01-04, so earlier years are moot.
_HOLIDAYS: frozenset[date] = frozenset(
    {
        # 2016
        date(2016, 1, 1),
        date(2016, 1, 18),
        date(2016, 2, 15),
        date(2016, 3, 25),
        date(2016, 5, 30),
        date(2016, 7, 4),
        date(2016, 9, 5),
        date(2016, 11, 24),
        date(2016, 12, 26),
        # 2017
        date(2017, 1, 2),
        date(2017, 1, 16),
        date(2017, 2, 20),
        date(2017, 4, 14),
        date(2017, 5, 29),
        date(2017, 7, 4),
        date(2017, 9, 4),
        date(2017, 11, 23),
        date(2017, 12, 25),
        # 2018
        date(2018, 1, 1),
        date(2018, 1, 15),
        date(2018, 2, 19),
        date(2018, 3, 30),
        date(2018, 5, 28),
        date(2018, 7, 4),
        date(2018, 9, 3),
        date(2018, 11, 22),
        date(2018, 12, 5),  # national day of mourning, George H. W. Bush
        date(2018, 12, 25),
        # 2019
        date(2019, 1, 1),
        date(2019, 1, 21),
        date(2019, 2, 18),
        date(2019, 4, 19),
        date(2019, 5, 27),
        date(2019, 7, 4),
        date(2019, 9, 2),
        date(2019, 11, 28),
        date(2019, 12, 25),
        # 2020
        date(2020, 1, 1),
        date(2020, 1, 20),
        date(2020, 2, 17),
        date(2020, 4, 10),
        date(2020, 5, 25),
        date(2020, 7, 3),  # Jul 4 fell on a Saturday
        date(2020, 9, 7),
        date(2020, 11, 26),
        date(2020, 12, 25),
        # 2021
        date(2021, 1, 1),
        date(2021, 1, 18),
        date(2021, 2, 15),
        date(2021, 4, 2),
        date(2021, 5, 31),
        date(2021, 7, 5),  # Jul 4 fell on a Sunday
        date(2021, 9, 6),
        date(2021, 11, 25),
        date(2021, 12, 24),  # Christmas fell on a Saturday
        # 2022
        date(2022, 1, 17),  # no New Year's holiday: Jan 1 was a Saturday
        date(2022, 2, 21),
        date(2022, 4, 15),
        date(2022, 5, 30),
        date(2022, 6, 20),  # first NYSE Juneteenth observance
        date(2022, 7, 4),
        date(2022, 9, 5),
        date(2022, 11, 24),
        date(2022, 12, 26),
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
#
# Unlike holidays these cannot be derived from bar data (an early close still
# produces a daily bar), so 2016-2022 come from the published NYSE calendar.
# They shift a daily bar's close stamp by three hours and never change bar
# ordering, so residual error here cannot alter a swing signal or fill.
_EARLY_CLOSES: frozenset[date] = frozenset(
    {
        date(2016, 11, 25),
        date(2017, 7, 3),
        date(2017, 11, 24),
        date(2018, 7, 3),
        date(2018, 11, 23),
        date(2018, 12, 24),
        date(2019, 7, 3),
        date(2019, 11, 29),
        date(2019, 12, 24),
        date(2020, 11, 27),
        date(2020, 12, 24),
        date(2021, 11, 26),
        date(2022, 11, 25),
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

known_calendar_years: range = range(2016, 2028)


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
