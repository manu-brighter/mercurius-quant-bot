"""Alpaca implementation of the Broker protocol (paper by default).

Notes:
- Fractional quantities require simple DAY market orders on Alpaca; whole-share
  orders use marketable limit orders when the intent carries a limit price.
- Protective stops are plain stop orders (supported for single-leg equities);
  OCO pairing is managed by the Executor, not the broker.
- `ALPACA_PAPER=false` is the single switch to live — everything else is
  identical by construction.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from mercurius.config.schema import AppConfig
from mercurius.core.enums import AccountMode, OrderStatus, Side
from mercurius.core.models import Order, Position, TradeIntent, round_to_tick

log = logging.getLogger(__name__)

_STATUS_MAP = {
    "new": OrderStatus.SUBMITTED,
    "accepted": OrderStatus.SUBMITTED,
    "pending_new": OrderStatus.SUBMITTED,
    "partially_filled": OrderStatus.PARTIALLY_FILLED,
    "filled": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELED,
    "pending_cancel": OrderStatus.CANCELED,
    "rejected": OrderStatus.REJECTED,
    "expired": OrderStatus.EXPIRED,
    "done_for_day": OrderStatus.EXPIRED,
}


class AlpacaBroker:
    def __init__(self, cfg: AppConfig) -> None:
        from alpaca.trading.client import TradingClient

        self.cfg = cfg
        self._client = TradingClient(
            api_key=cfg.secrets.alpaca_api_key.get_secret_value(),
            secret_key=cfg.secrets.alpaca_secret_key.get_secret_value(),
            paper=cfg.secrets.alpaca_paper,
        )

    # -- orders ------------------------------------------------------------
    def submit(self, intent: TradeIntent) -> Order:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

        side = OrderSide.BUY if intent.side == Side.BUY else OrderSide.SELL
        is_fractional = intent.qty != intent.qty.to_integral_value()
        if is_fractional or intent.limit_price is None:
            req = MarketOrderRequest(
                symbol=intent.instrument,
                qty=float(intent.qty),
                side=side,
                time_in_force=TimeInForce.DAY,
                client_order_id=intent.client_order_id,
            )
        else:
            req = LimitOrderRequest(
                symbol=intent.instrument,
                qty=float(intent.qty),
                side=side,
                time_in_force=TimeInForce.DAY,
                limit_price=float(round_to_tick(intent.limit_price)),
                client_order_id=intent.client_order_id,
            )
        raw = self._client.submit_order(req)
        return self._to_order(raw)

    def submit_stop(
        self, instrument: str, qty: Decimal, stop_price: Decimal, client_order_id: str
    ) -> Order:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import StopOrderRequest

        positions = self.get_positions()
        pos = positions.get(instrument)
        side = OrderSide.SELL if (pos is None or pos.qty > 0) else OrderSide.BUY
        req = StopOrderRequest(
            symbol=instrument,
            qty=float(qty),
            side=side,
            time_in_force=TimeInForce.DAY,
            stop_price=float(round_to_tick(stop_price)),
            client_order_id=client_order_id,
        )
        raw = self._client.submit_order(req)
        return self._to_order(raw)

    def cancel(self, client_order_id: str) -> None:
        order = self._raw_by_client_id(client_order_id)
        if order is not None:
            self._client.cancel_order_by_id(str(order.id))

    def get_order(self, client_order_id: str) -> Order | None:
        raw = self._raw_by_client_id(client_order_id)
        return None if raw is None else self._to_order(raw)

    def get_open_orders(self) -> list[Order]:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        raws = self._client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500))
        return [self._to_order(r) for r in raws]

    # -- account -----------------------------------------------------------
    def get_positions(self) -> dict[str, Position]:
        out: dict[str, Position] = {}
        for p in self._client.get_all_positions():
            qty = Decimal(str(p.qty))
            out[p.symbol] = Position(
                instrument=p.symbol,
                qty=qty,
                avg_entry=Decimal(str(p.avg_entry_price)),
                opened_at=datetime.now(tz=UTC),  # Alpaca doesn't expose open time
            )
        return out

    def flatten_all(self) -> None:
        log.warning("flatten_all: closing all positions and cancelling all orders")
        self._client.cancel_orders()
        self._client.close_all_positions(cancel_orders=True)

    def equity(self) -> Decimal:
        return Decimal(str(self._client.get_account().equity))

    def account_mode(self) -> AccountMode:
        acct = self._client.get_account()
        equity = Decimal(str(acct.equity))
        multiplier = int(float(acct.multiplier or 1))
        if multiplier > 1 and equity >= Decimal("2000"):
            return AccountMode.MARGIN
        return AccountMode.CASH

    # -- helpers -----------------------------------------------------------
    def _raw_by_client_id(self, client_order_id: str):
        from alpaca.common.exceptions import APIError

        try:
            return self._client.get_order_by_client_id(client_order_id)
        except APIError as e:
            if getattr(e, "status_code", None) == 404 or "not found" in str(e).lower():
                return None
            raise

    def _to_order(self, raw) -> Order:
        qty = Decimal(str(raw.qty)) if raw.qty is not None else Decimal("0")
        filled = Decimal(str(raw.filled_qty or "0"))
        return Order(
            client_order_id=raw.client_order_id,
            instrument=raw.symbol,
            side=Side.BUY if str(raw.side).endswith("buy") else Side.SELL,
            qty=qty,
            status=_STATUS_MAP.get(str(raw.status).split(".")[-1].lower(), OrderStatus.SUBMITTED),
            broker_order_id=str(raw.id),
            limit_price=Decimal(str(raw.limit_price)) if raw.limit_price else None,
            filled_qty=filled,
            avg_fill_price=(Decimal(str(raw.filled_avg_price)) if raw.filled_avg_price else None),
            submitted_at=raw.submitted_at,
        )
