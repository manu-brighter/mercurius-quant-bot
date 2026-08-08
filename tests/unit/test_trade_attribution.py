"""Per-strategy attribution must survive two strategies sharing one symbol.

A real broker nets positions per symbol, so the simulator must too — which
means `noise_bands_SPY` and `orb_SPY` compete for one position slot. Before
these tests, that collision silently produced trades attributed to `None` (the
`[?]` bucket) and let one strategy absorb another's fills.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from mercurius.backtest.engine import run_backtest
from mercurius.backtest.sim_broker import SimBroker
from mercurius.config.schema import AppConfig
from mercurius.core.enums import Side, SignalKind
from mercurius.core.models import Bar, Signal, TradeIntent
from tests.helpers import minute_bars


def _intent(strategy_id: str, symbol: str, side: Side, qty: str, ts: datetime) -> TradeIntent:
    return TradeIntent(
        instrument=symbol,
        side=side,
        qty=Decimal(qty),
        signal=Signal(strategy_id, symbol, SignalKind.ENTER_LONG, ts, "test"),
    )


def _bar(symbol: str, ts: datetime, price: str = "100") -> Bar:
    p = Decimal(price)
    return Bar(symbol=symbol, ts_utc=ts, open=p, high=p, low=p, close=p, volume=1000)


def test_fill_carries_the_opening_strategy():
    """Attribution comes from the intent, not from a position that may be gone."""
    broker = SimBroker(Decimal("10000"))
    ts = datetime(2025, 3, 4, 15, 0, tzinfo=UTC)
    broker.submit(_intent("alpha", "SPY", Side.BUY, "10", ts))
    fills = broker.on_bar_open(_bar("SPY", ts + timedelta(minutes=1)))
    assert len(fills) == 1
    assert fills[0].strategy_id == "alpha"


def test_closing_fill_keeps_the_opening_strategy():
    """The exit is attributed to whoever opened, even via a generic close."""
    broker = SimBroker(Decimal("10000"))
    ts = datetime(2025, 3, 4, 15, 0, tzinfo=UTC)
    broker.submit(_intent("alpha", "SPY", Side.BUY, "10", ts))
    broker.on_bar_open(_bar("SPY", ts + timedelta(minutes=1)))

    # a flatten submitted by the engine, carrying a different strategy_id
    broker.submit(_intent("engine", "SPY", Side.SELL, "10", ts))
    fills = broker.on_bar_open(_bar("SPY", ts + timedelta(minutes=2)))
    assert fills[0].strategy_id == "alpha"
    assert "SPY" not in broker.positions


def test_second_strategy_cannot_merge_into_a_held_symbol():
    """A real broker would net these into one position, destroying attribution.
    The simulator must refuse the second entry rather than silently merge."""
    broker = SimBroker(Decimal("10000"))
    ts = datetime(2025, 3, 4, 15, 0, tzinfo=UTC)
    broker.submit(_intent("alpha", "SPY", Side.BUY, "10", ts))
    broker.on_bar_open(_bar("SPY", ts + timedelta(minutes=1)))

    broker.submit(_intent("beta", "SPY", Side.BUY, "5", ts))
    fills = broker.on_bar_open(_bar("SPY", ts + timedelta(minutes=2)))

    assert fills == []
    assert broker.positions["SPY"].qty == Decimal("10")
    assert broker.positions["SPY"].strategy_id == "alpha"
    assert broker.rejected_conflicts == 1


def test_same_strategy_may_still_add_to_its_own_position():
    broker = SimBroker(Decimal("10000"))
    ts = datetime(2025, 3, 4, 15, 0, tzinfo=UTC)
    broker.submit(_intent("alpha", "SPY", Side.BUY, "10", ts))
    broker.on_bar_open(_bar("SPY", ts + timedelta(minutes=1)))
    broker.submit(_intent("alpha", "SPY", Side.BUY, "5", ts))
    broker.on_bar_open(_bar("SPY", ts + timedelta(minutes=2)))
    assert broker.positions["SPY"].qty == Decimal("15")
    assert broker.rejected_conflicts == 0


def test_no_unattributed_trades_when_two_strategies_share_a_symbol():
    """End-to-end: the `[?]` bucket must be empty."""
    from mercurius.strategies.base import StrategyContext

    class AlwaysEnter:
        strategy_id = "always"
        symbol = "SPY"
        warmup_bars = 1
        intraday = True

        def on_session_start(self, ctx: StrategyContext) -> None:
            self._done = False

        def on_bar(self, ctx: StrategyContext, bar: Bar) -> list[Signal]:
            if self._done:
                return []
            self._done = True
            return [
                Signal(
                    self.strategy_id,
                    self.symbol,
                    SignalKind.ENTER_LONG,
                    bar.ts_utc,
                    "test",
                    stop_price=bar.close * Decimal("0.99"),
                )
            ]

    class AlsoEnter(AlwaysEnter):
        strategy_id = "also"

    cfg = AppConfig()
    bars = minute_bars("SPY", datetime(2025, 3, 4).date(), [100.0 + i * 0.1 for i in range(60)])
    result = run_backtest(cfg, [AlwaysEnter(), AlsoEnter()], bars)

    assert all(t["strategy_id"] for t in result.trades), (
        f"unattributed trades: {[t for t in result.trades if not t['strategy_id']]}"
    )
