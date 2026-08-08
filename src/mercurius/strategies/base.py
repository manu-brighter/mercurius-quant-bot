"""Strategy interface. Strategies are pure: bars in, signals out.

They never see the broker, the network, or wall-clock time — only the
`StrategyContext` view handed to them. All per-day state must be reset in
`on_session_start`, which the engine calls on the first bar of each session.
"""

from __future__ import annotations

from collections import deque
from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

from mercurius.core.models import Bar, Position, Signal


class StrategyContext:
    """Read-only market view for one strategy."""

    def __init__(self, symbol: str, history_len: int = 500) -> None:
        self.symbol = symbol
        self.bars: deque[Bar] = deque(maxlen=history_len)
        self._position: Position | None = None
        self.session_date: date | None = None

    @property
    def position(self) -> Position | None:
        return self._position

    def _set_position(self, pos: Position | None) -> None:  # engine-only
        self._position = pos

    def _push_bar(self, bar: Bar) -> None:  # engine-only
        self.bars.append(bar)

    @property
    def last_close(self) -> Decimal | None:
        return self.bars[-1].close if self.bars else None


@runtime_checkable
class Strategy(Protocol):
    strategy_id: str
    symbol: str
    warmup_bars: int
    # True (default) = day-trading: engine force-flattens before the close.
    # False = swing: positions may be held overnight; protective stops are GTC.
    # Engines read this via getattr(strategy, "intraday", True).
    intraday: bool

    def on_session_start(self, ctx: StrategyContext) -> None: ...

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> list[Signal]: ...

    def on_session_end(self, ctx: StrategyContext) -> None: ...
