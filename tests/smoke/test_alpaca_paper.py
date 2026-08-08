"""Opt-in smoke tests against the real Alpaca PAPER API.

Run manually before each milestone sign-off:
    MERCURIUS_SMOKE=1 uv run pytest -q -m smoke
Requires paper keys in .env. Never runs in CI; skipped without the env flag.
"""

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(
        os.environ.get("MERCURIUS_SMOKE") != "1",
        reason="smoke tests are opt-in: set MERCURIUS_SMOKE=1",
    ),
]

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def cfg():
    from mercurius.config import load_config

    c = load_config(ROOT / "config" / "default.yaml")
    if not c.secrets.alpaca_api_key.get_secret_value():
        pytest.skip("no Alpaca keys configured")
    assert c.secrets.alpaca_paper, "smoke tests must run against PAPER"
    return c


@pytest.fixture(scope="module")
def broker(cfg):
    from mercurius.execution.alpaca_broker import AlpacaBroker

    return AlpacaBroker(cfg)


def test_auth_and_account(broker):
    eq = broker.equity()
    assert eq > 0
    mode = broker.account_mode()
    assert mode is not None


def test_historical_bars_fetch(cfg):
    from mercurius.data.alpaca_hist import download_bars, load_cached_bars

    end = datetime.now(tz=UTC)
    start = end - timedelta(days=5)
    n = download_bars(cfg, "SPY", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    assert n > 0
    bars = load_cached_bars(cfg, "SPY", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    assert bars and bars[0].ts_utc.tzinfo is not None


def test_submit_and_cancel_far_limit_order(broker):
    """1-share limit far below market: must accept, then cancel cleanly."""
    from mercurius.core.enums import Side, SignalKind
    from mercurius.core.models import Signal, TradeIntent

    sig = Signal("smoke", "SPY", SignalKind.ENTER_LONG, datetime.now(tz=UTC), "smoke test order")
    intent = TradeIntent(
        instrument="SPY",
        side=Side.BUY,
        qty=Decimal("1"),
        signal=sig,
        limit_price=Decimal("1.00"),  # never fills
    )
    order = broker.submit(intent)
    assert order.broker_order_id
    found = broker.get_order(intent.client_order_id)
    assert found is not None
    broker.cancel(intent.client_order_id)


def test_option_chain_snapshot(cfg):
    from mercurius.data.chain_snapshots import snapshot_chain

    n = snapshot_chain(cfg, "SPY")
    assert n > 0
