"""RSI(2) and IBS swing strategies on synthetic daily bars."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from mercurius.config import load_config
from mercurius.core.enums import SignalKind
from mercurius.core.models import Bar, Position
from mercurius.strategies.base import StrategyContext
from mercurius.strategies.ibs_reversion import IbsReversionStrategy, internal_bar_strength
from mercurius.strategies.registry import build_strategies
from mercurius.strategies.rsi2_reversion import Rsi2ReversionStrategy

ROOT = Path(__file__).resolve().parents[2]
START = datetime(2020, 1, 2, 21, 0, tzinfo=UTC)  # a session close in UTC


def daily_bars(closes, symbol="SPY", ibs_pos: float | None = None, offset=0) -> list[Bar]:
    """One bar per element. `ibs_pos` (0..1) places the close inside the range."""
    out = []
    for j, c in enumerate(closes):
        i = j + offset
        close = Decimal(str(round(c, 4)))
        if ibs_pos is None:
            lo, hi = close - Decimal("0.5"), close + Decimal("0.5")
        else:
            rng = Decimal("1.0")
            lo = close - rng * Decimal(str(ibs_pos))
            hi = lo + rng
        out.append(
            Bar(
                symbol=symbol,
                ts_utc=START + timedelta(days=i),
                open=close,
                high=max(hi, close),
                low=min(lo, close),
                close=close,
                volume=1_000_000,
            )
        )
    return out


def run(strat, bars, position_on_entry=True):
    """Feed bars, adopting/dropping a position the way the engine would."""
    ctx = StrategyContext(strat.symbol, history_len=1000)
    events = []
    pos = None
    for bar in bars:
        ctx._push_bar(bar)
        ctx._set_position(pos)
        for sig in strat.on_bar(ctx, bar):
            events.append((bar, sig))
            if not position_on_entry:
                continue
            if sig.kind == SignalKind.ENTER_LONG:
                pos = Position(strat.symbol, Decimal("1"), bar.close, bar.ts_utc)
            elif sig.kind == SignalKind.EXIT:
                pos = None
    return events


def _uptrend(n=260, start=100.0, step=0.25):
    return [start + step * i for i in range(n)]


# -- RSI(2) ----------------------------------------------------------------
def test_rsi2_is_swing_not_intraday():
    assert Rsi2ReversionStrategy().intraday is False
    assert IbsReversionStrategy().intraday is False


def test_rsi2_silent_during_warmup():
    strat = Rsi2ReversionStrategy(trend_sma=200)
    bars = daily_bars(_uptrend(150))
    assert run(strat, bars) == []


def test_rsi2_enters_on_pullback_in_uptrend_and_exits_on_recovery():
    strat = Rsi2ReversionStrategy(trend_sma=50, exit_sma=5)
    # 200 sessions of uptrend, a sharp 3-day pullback, then recovery
    closes = _uptrend(200) + [148.0, 144.0, 141.0] + [150.0, 156.0, 162.0]
    events = run(strat, daily_bars(closes))
    kinds = [s.kind for _, s in events]
    assert SignalKind.ENTER_LONG in kinds, "expected an oversold entry above the trend SMA"
    entry_idx = kinds.index(SignalKind.ENTER_LONG)
    assert SignalKind.EXIT in kinds[entry_idx:], "expected an exit once RSI/SMA recovered"
    entry_bar, entry_sig = events[entry_idx]
    assert entry_sig.stop_price is not None and entry_sig.stop_price < entry_bar.close


def test_rsi2_no_entry_below_trend_filter():
    strat = Rsi2ReversionStrategy(trend_sma=50)
    # long downtrend: oversold readings occur but the trend filter must block them
    closes = [200.0 - 0.4 * i for i in range(260)]
    events = run(strat, daily_bars(closes))
    assert not [s for _, s in events if s.kind == SignalKind.ENTER_LONG]


def test_rsi2_disaster_stop_is_below_entry():
    strat = Rsi2ReversionStrategy(trend_sma=50, disaster_stop_pct=Decimal("0.05"))
    closes = _uptrend(200) + [148.0, 144.0, 141.0]
    events = run(strat, daily_bars(closes))
    entries = [(b, s) for b, s in events if s.kind == SignalKind.ENTER_LONG]
    assert entries
    bar, sig = entries[0]
    assert sig.stop_price == bar.close * Decimal("0.95")


# -- IBS -------------------------------------------------------------------
def test_internal_bar_strength_math():
    bar = Bar("SPY", START, Decimal("100"), Decimal("110"), Decimal("100"), Decimal("102"), 1)
    assert internal_bar_strength(bar) == Decimal("0.2")
    flat = Bar("SPY", START, Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 1)
    assert internal_bar_strength(flat) is None  # no range: undefined, never traded


def test_ibs_enters_on_weak_close_and_exits_on_strong_close():
    strat = IbsReversionStrategy(trend_sma=50)
    trend = daily_bars(_uptrend(200), ibs_pos=0.5)
    weak = daily_bars([150.0], ibs_pos=0.05, offset=200)  # closes near the low
    strong = daily_bars([151.0], ibs_pos=0.95, offset=201)  # closes near the high
    events = run(strat, trend + weak + strong)
    kinds = [s.kind for _, s in events]
    assert kinds[:2] == [SignalKind.ENTER_LONG, SignalKind.EXIT]


def test_ibs_no_entry_below_trend():
    strat = IbsReversionStrategy(trend_sma=50)
    closes = [200.0 - 0.4 * i for i in range(260)]
    events = run(strat, daily_bars(closes, ibs_pos=0.05))
    assert not [s for _, s in events if s.kind == SignalKind.ENTER_LONG]


# -- registry / config -----------------------------------------------------
def test_swing_config_builds_only_swing_strategies():
    cfg = load_config(ROOT / "config" / "default.yaml", ROOT / "config" / "swing.yaml")
    strategies = build_strategies(cfg)
    ids = sorted(s.strategy_id for s in strategies)
    assert ids == ["ibs_QQQ", "ibs_SPY", "rsi2_QQQ", "rsi2_SPY"]
    assert all(s.intraday is False for s in strategies)


def test_swing_strategies_disabled_by_default():
    cfg = load_config(ROOT / "config" / "default.yaml")
    ids = {s.strategy_id for s in build_strategies(cfg)}
    assert not any(i.startswith(("rsi2", "ibs")) for i in ids)
