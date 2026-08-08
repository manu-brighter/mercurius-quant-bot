"""Stream teardown and gap-recovery invariants (no network, no SDK).

Both properties here are safety-critical and cheap to break silently:
teardown must not stall the event loop the runner flattens on, and the
worker thread must not touch the (non-thread-safe) asyncio queue.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from queue import Queue

from mercurius.config.schema import AppConfig
from mercurius.core.models import Bar
from mercurius.data.alpaca_stream import AlpacaStream


class _FakeSdkStream:
    """Stands in for alpaca-py's DataStream teardown surface."""

    def __init__(self) -> None:
        self._should_run = True
        self._stop_stream_queue = Queue()
        self.sync_stop_calls = 0

    def stop(self) -> None:
        self.sync_stop_calls += 1


def _stream(tmp_path) -> AlpacaStream:
    cfg = AppConfig()
    cfg.data.cache_dir = tmp_path / "cache"
    return AlpacaStream(cfg, ["spy"])


def _bar(ts: datetime) -> Bar:
    return Bar(
        symbol="SPY",
        ts_utc=ts,
        open=Decimal("500"),
        high=Decimal("501"),
        low=Decimal("499"),
        close=Decimal("500.5"),
        volume=100,
    )


def test_symbols_are_normalized(tmp_path):
    assert _stream(tmp_path).symbols == ["SPY"]


def test_staleness_is_none_before_the_first_bar(tmp_path):
    assert _stream(tmp_path).staleness_seconds() is None


def test_stop_before_connect_is_safe(tmp_path):
    s = _stream(tmp_path)
    s.stop()
    assert s._stopped is True


async def test_stop_on_the_loop_avoids_the_blocking_sdk_path(tmp_path):
    """The SDK's stop() blocks the calling loop for 5s, then raises.

    The runner calls stop() from the loop, with the final flatten downstream
    of it, so this must signal the socket directly instead.
    """
    s = _stream(tmp_path)
    fake = _FakeSdkStream()
    s._stream = fake

    s.stop()

    assert s._stopped is True
    assert fake.sync_stop_calls == 0
    assert fake._should_run is False
    assert not fake._stop_stream_queue.empty()


def test_stop_off_the_loop_uses_the_sdk_path(tmp_path):
    s = _stream(tmp_path)
    fake = _FakeSdkStream()
    s._stream = fake

    s.stop()

    assert fake.sync_stop_calls == 1


def test_gap_fetch_is_sorted_and_never_touches_the_queue(tmp_path, monkeypatch):
    """Enqueueing belongs on the event loop; the worker thread only fetches."""
    s = _stream(tmp_path)
    s._last_ts["SPY"] = datetime(2025, 3, 4, 14, 59, tzinfo=UTC)  # 09:59 ET
    base = datetime(2025, 3, 4, 15, 0, tzinfo=UTC)  # 10:00 ET, a Tuesday
    unsorted = [_bar(base + timedelta(minutes=i)) for i in (2, 0, 1)]
    monkeypatch.setattr("mercurius.data.alpaca_hist.fetch_bars", lambda *a, **k: unsorted)

    got = s._fetch_gap_bars()

    assert [b.ts_utc for b in got] == sorted(b.ts_utc for b in unsorted)
    assert s.queue.empty()


def test_gap_fetch_drops_bars_already_seen_and_outside_hours(tmp_path, monkeypatch):
    s = _stream(tmp_path)
    s._last_ts["SPY"] = datetime(2025, 3, 4, 15, 0, tzinfo=UTC)  # 10:00 ET
    candidates = [
        _bar(datetime(2025, 3, 4, 14, 30, tzinfo=UTC)),  # already seen
        _bar(datetime(2025, 3, 4, 15, 1, tzinfo=UTC)),  # new, regular hours
        _bar(datetime(2025, 3, 4, 23, 0, tzinfo=UTC)),  # after the close
    ]
    monkeypatch.setattr("mercurius.data.alpaca_hist.fetch_bars", lambda *a, **k: candidates)

    got = s._fetch_gap_bars()

    assert [b.ts_utc for b in got] == [datetime(2025, 3, 4, 15, 1, tzinfo=UTC)]
