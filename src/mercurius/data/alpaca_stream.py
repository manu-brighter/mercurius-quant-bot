"""Live 1-minute bar stream (Alpaca websocket, IEX on the free plan).

Responsibilities beyond "receive bars":

- **Normalization**: emits the same close-stamped, Decimal-priced `Bar` the
  backtest replays, so strategy code cannot tell live from simulated.
- **Reconnect with gap backfill**: a dropped socket means missed minutes. On
  reconnect the gap is refetched over REST and replayed into the queue in
  order, so session indicators (ATR, EMA, opening range) never silently skip a
  bar.
- **Staleness reporting**: `staleness_seconds()` is what the runner uses to
  block new entries when the tape goes quiet. Never entering on stale data is a
  fail-closed behavior, so this must keep working even while reconnecting.

Extended-hours bars are dropped here for the same reason the cache filters them
on load: the session logic assumes the first bar of the day closes at 09:31 ET.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from mercurius.config.schema import AppConfig
from mercurius.core.models import Bar
from mercurius.data.alpaca_hist import in_regular_hours, to_bar

log = logging.getLogger(__name__)

_RECONNECT_BACKOFF_S = (1, 2, 5, 10, 30)
_BACKFILL_LOOKBACK_MINUTES = 120


class AlpacaStream:
    def __init__(self, cfg: AppConfig, symbols: list[str]) -> None:
        self.cfg = cfg
        self.symbols = [s.upper() for s in symbols]
        self.queue: asyncio.Queue[Bar] = asyncio.Queue()
        self._stream = None
        self._stopped = False
        self._last_bar_at: datetime | None = None
        self._last_ts: dict[str, datetime] = {}
        self._attempt = 0

    # -- health ------------------------------------------------------------
    def staleness_seconds(self) -> float | None:
        """Seconds since the last bar arrived, or None if none has yet."""
        if self._last_bar_at is None:
            return None
        return (datetime.now(tz=UTC) - self._last_bar_at).total_seconds()

    # -- lifecycle ---------------------------------------------------------
    def _build(self):
        from alpaca.data.enums import DataFeed
        from alpaca.data.live.stock import StockDataStream

        return StockDataStream(
            api_key=self.cfg.secrets.alpaca_api_key.get_secret_value(),
            secret_key=self.cfg.secrets.alpaca_secret_key.get_secret_value(),
            feed=DataFeed(self.cfg.data.feed.lower()),
        )

    async def _on_bar(self, raw) -> None:
        symbol = getattr(raw, "symbol", None)
        if symbol is None:
            return
        bar = to_bar(symbol, raw)
        self._last_bar_at = datetime.now(tz=UTC)
        if not in_regular_hours(bar.ts_utc):
            return
        prev = self._last_ts.get(bar.symbol)
        if prev is not None and bar.ts_utc <= prev:
            return  # duplicate or out-of-order replay
        self._last_ts[bar.symbol] = bar.ts_utc
        await self.queue.put(bar)

    async def _stream_once(self) -> None:
        self._stream = self._build()
        self._stream.subscribe_bars(self._on_bar, *self.symbols)
        log.info("stream connecting: %s (%s)", self.symbols, self.cfg.data.feed)
        # `run()` is synchronous and calls asyncio.run() internally, which cannot
        # be used from inside the runner's event loop; `_run_forever()` is the
        # in-loop entrypoint. Fall back to a worker thread if the SDK drops it.
        runner = getattr(self._stream, "_run_forever", None)
        if runner is None:  # pragma: no cover - depends on SDK internals
            await asyncio.to_thread(self._stream.run)
        else:
            await runner()

    async def run(self) -> None:
        while not self._stopped:
            connected_at = datetime.now(tz=UTC)
            try:
                await self._stream_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                if self._stopped:
                    return
                log.exception("stream error")
            if self._stopped:
                return
            # A connection that survived a while was healthy: restart the
            # backoff ladder so a long session doesn't inherit an old streak.
            if (datetime.now(tz=UTC) - connected_at).total_seconds() > 60:
                self._attempt = 0
            delay = _RECONNECT_BACKOFF_S[min(self._attempt, len(_RECONNECT_BACKOFF_S) - 1)]
            self._attempt += 1
            log.warning("stream down; reconnecting in %ss (attempt %d)", delay, self._attempt)
            await asyncio.sleep(delay)
            await self._backfill_gap()

    def stop(self) -> None:
        """Signal the socket to close. Safe to call from inside the event loop.

        The SDK's own `stop()` does `run_coroutine_threadsafe(...).result(5)`,
        which assumes it is being called from *another* thread. The runner
        calls us from the loop the stream itself runs on, where that blocks the
        loop for the full 5s timeout on a coroutine that cannot run, then
        raises — and the runner's teardown (the final flatten) is downstream of
        this call. Signal the stop queue directly instead.
        """
        self._stopped = True
        stream = self._stream
        if stream is None:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:  # not on a loop: the SDK's threadsafe path is correct here
                stream.stop()
            except Exception:  # pragma: no cover - best-effort teardown
                log.debug("stream stop() raised during teardown", exc_info=True)
            return
        stream._should_run = False
        if stream._stop_stream_queue.empty():
            stream._stop_stream_queue.put_nowait({"should_stop": True})

    # -- gap recovery ------------------------------------------------------
    async def _backfill_gap(self) -> None:
        """Refetch and enqueue minutes missed while the socket was down.

        Only the blocking REST call runs off-loop. `asyncio.Queue` is not
        thread-safe, so every enqueue and every mutation of the stream's state
        happens back on the event loop.
        """
        try:
            recovered = await asyncio.to_thread(self._fetch_gap_bars)
        except Exception:
            log.exception("gap backfill failed; continuing with a hole in the tape")
            return
        for bar in recovered:
            self._last_ts[bar.symbol] = bar.ts_utc
            self.queue.put_nowait(bar)
        if recovered:
            self._last_bar_at = datetime.now(tz=UTC)
            log.warning("backfilled %d missed bars", len(recovered))

    def _fetch_gap_bars(self) -> list[Bar]:
        """Blocking REST fetch of the missed window. Runs in a worker thread."""
        from mercurius.data.alpaca_hist import fetch_bars

        now = datetime.now(tz=UTC)
        default_from = now - timedelta(minutes=_BACKFILL_LOOKBACK_MINUTES)
        out: list[Bar] = []
        for symbol in self.symbols:
            since = self._last_ts.get(symbol, default_from)
            if now - since < timedelta(minutes=2):
                continue
            out.extend(
                b
                for b in fetch_bars(
                    self.cfg, symbol, since.date(), now.date(), self.cfg.data.feed.lower()
                )
                if b.ts_utc > since and in_regular_hours(b.ts_utc)
            )
        out.sort(key=lambda b: b.ts_utc)
        return out
