"""Order lifecycle: TradeIntent -> broker order -> fills -> protective stop.

Guarantees:
- Idempotency: before submitting, the broker is queried by client_order_id;
  an existing order is adopted, never duplicated. The intent is journaled
  BEFORE submission so a crash between journal and submit is recoverable.
- Every filled entry gets a broker-side protective stop (when the intent
  carries one); exits cancel the paired stop first (manual OCO — Alpaca has
  no native bracket for all cases we use).
- Partial fills accumulate on the tracked Order; exits always close the
  broker-reported position quantity, not the originally intended one.
- Orders unfilled past `order_timeout_s` are cancelled.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from mercurius.core.clock import Clock
from mercurius.core.enums import OrderStatus, Side
from mercurius.core.models import Fill, Order, TradeIntent
from mercurius.execution.broker import Broker
from mercurius.journal import db as evk
from mercurius.journal.writer import JournalWriter

log = logging.getLogger(__name__)

STOP_SUFFIX = "-stp"


class Executor:
    def __init__(
        self,
        broker: Broker,
        writer: JournalWriter,
        clock: Clock,
        order_timeout_s: int = 90,
    ) -> None:
        self.broker = broker
        self.writer = writer
        self.clock = clock
        self.order_timeout_s = order_timeout_s
        self._tracked: dict[str, Order] = {}
        self._intents: dict[str, TradeIntent] = {}

    # -- submission --------------------------------------------------------
    def execute(self, intent: TradeIntent) -> Order:
        coid = intent.client_order_id
        self.writer.intent(self.clock.now_utc(), intent)

        existing = self.broker.get_order(coid)
        if existing is not None:
            log.info("adopting existing order %s (%s)", coid, existing.status)
            self._tracked[coid] = existing
            self._intents[coid] = intent
            return existing

        order = self.broker.submit(intent)
        self.writer.j.append(
            self.clock.now_utc(),
            evk.ORDER_SUBMITTED,
            {
                "client_order_id": coid,
                "instrument": intent.instrument,
                "side": str(intent.side),
                "qty": intent.qty,
            },
        )
        self._tracked[coid] = order
        self._intents[coid] = intent
        return order

    # -- fill events (from trade_updates stream, or polling fallback) ------
    def on_fill(self, fill: Fill) -> None:
        self.writer.fill(fill)
        order = self._tracked.get(fill.client_order_id)
        if order is None:
            log.warning("fill for untracked order %s", fill.client_order_id)
            return
        prev_filled = order.filled_qty
        order.filled_qty = prev_filled + fill.qty
        if order.avg_fill_price is None:
            order.avg_fill_price = fill.price
        else:
            total = order.avg_fill_price * prev_filled + fill.price * fill.qty
            order.avg_fill_price = total / order.filled_qty
        order.status = (
            OrderStatus.FILLED if order.filled_qty >= order.qty else OrderStatus.PARTIALLY_FILLED
        )
        if order.status == OrderStatus.FILLED:
            self._after_full_fill(order)

    def _after_full_fill(self, order: Order) -> None:
        intent = self._intents.get(order.client_order_id)
        if intent is None:
            return
        if intent.protective_stop is not None and not order.client_order_id.endswith(STOP_SUFFIX):
            stop_id = order.client_order_id + STOP_SUFFIX
            if self.broker.get_order(stop_id) is None:
                self.broker.submit_stop(
                    intent.instrument, order.filled_qty, intent.protective_stop, stop_id
                )
                log.info(
                    "protective stop %s @ %s for %s",
                    stop_id,
                    intent.protective_stop,
                    intent.instrument,
                )

    # -- exits -------------------------------------------------------------
    def close_position(self, instrument: str, signal, limit_price: Decimal | None = None):
        """Cancel the paired protective stop, then close the broker-reported qty."""
        pos = self.broker.get_positions().get(instrument)
        if pos is None or pos.qty == 0:
            log.info("close requested but no position in %s", instrument)
            return None
        for order in self.broker.get_open_orders():
            if order.instrument == instrument and order.client_order_id.endswith(STOP_SUFFIX):
                self.broker.cancel(order.client_order_id)
        actual = TradeIntent(
            instrument=instrument,
            side=Side.SELL if pos.qty > 0 else Side.BUY,
            qty=abs(pos.qty),  # broker truth, not intended size
            signal=signal,
            limit_price=limit_price,
        )
        return self.execute(actual)

    # -- maintenance -------------------------------------------------------
    def cancel_stale(self, now: datetime | None = None) -> list[str]:
        now = now or self.clock.now_utc()
        cancelled = []
        for coid, order in list(self._tracked.items()):
            if order.status.is_terminal or order.submitted_at is None:
                continue
            if order.client_order_id.endswith(STOP_SUFFIX):
                continue  # protective stops rest until hit or explicitly cancelled
            if now - order.submitted_at > timedelta(seconds=self.order_timeout_s):
                self.broker.cancel(coid)
                order.status = OrderStatus.CANCELED
                cancelled.append(coid)
                self.writer.note(now, f"cancelled stale order {coid}")
        return cancelled

    def open_entry_qty(self, instrument: str) -> Decimal:
        return sum(
            (o.filled_qty for o in self._tracked.values() if o.instrument == instrument),
            Decimal("0"),
        )
