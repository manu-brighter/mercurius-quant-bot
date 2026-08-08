import random
from decimal import Decimal

import pandas as pd

from mercurius.strategies.indicators import IncrementalEMA, RollingMedian, SessionATR


def test_ema_matches_pandas():
    random.seed(7)
    xs = [Decimal(str(round(100 + random.uniform(-5, 5), 2))) for _ in range(200)]
    ema = IncrementalEMA(20)
    ours = [ema.update(x) for x in xs]
    ref = (
        pd.Series([float(x) for x in xs]).ewm(span=20, adjust=False, min_periods=20).mean().tolist()
    )
    # pandas seeds differently pre-window; compare after warmup where both defined
    # our SMA seed differs from pandas' recursive start: allow convergence tolerance
    for i in range(60, 200):
        assert ours[i] is not None
        assert abs(float(ours[i]) - ref[i]) < 0.05


def test_ema_none_during_warmup():
    ema = IncrementalEMA(10)
    for _ in range(9):
        assert ema.update(Decimal("100")) is None
    assert ema.update(Decimal("100")) == Decimal("100")


def test_rolling_median_matches_pandas():
    random.seed(11)
    xs = [Decimal(random.randint(100, 10_000)) for _ in range(100)]
    rm = RollingMedian(20)
    ours = [rm.update(x) for x in xs]
    ref = pd.Series([float(x) for x in xs]).rolling(20).median().tolist()
    for i in range(19, 100):
        assert ours[i] is not None
        assert float(ours[i]) == ref[i]


def test_session_atr_true_range_with_gaps():
    atr = SessionATR(3)
    atr.push_session(Decimal("105"), Decimal("100"), Decimal("104"))  # tr=5 (first: h-l)
    atr.push_session(
        Decimal("103"), Decimal("101"), Decimal("102")
    )  # tr=max(2,|103-104|,|101-104|)=3
    atr.push_session(Decimal("110"), Decimal("108"), Decimal("109"))  # gap: tr=max(2,8,6)=8
    assert atr.value == (Decimal("5") + Decimal("3") + Decimal("8")) / 3
    assert atr.n_sessions == 3


def test_session_atr_none_until_period():
    atr = SessionATR(14)
    for _ in range(13):
        atr.push_session(Decimal("101"), Decimal("100"), Decimal("100.5"))
    assert atr.value is None
