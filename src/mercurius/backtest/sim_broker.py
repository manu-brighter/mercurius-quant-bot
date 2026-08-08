"""Simulated broker for backtests.

Fill model (deliberately pessimistic, never optimistic):
- Entry/exit orders queued on bar N fill at bar N+1's OPEN, moved against us
  by (slippage_bps + spread_haircut_bps).
- Protective stops are checked against each bar's range: gap through the stop
  fills at the open (worse), otherwise at the stop price, again with slippage.
No lookahead: nothing ever fills on the bar whose close produced the signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from mercurius.core.enums import Side
from mercurius.core.models import Bar, Fill, Position, TradeIntent, round_to_tick


@dataclass
class _PendingOrder:
    intent: TradeIntent


class SimBroker:
    def __init__(
        self,
        cash: Decimal,
        slippage_bps: Decimal = Decimal("1.5"),
        spread_haircut_bps: Decimal = Decimal("1.0"),
    ) -> None:
        self.cash = cash
        self._cost_frac = (slippage_bps + spread_haircut_bps) / Decimal("10000")
        self.positions: dict[str, Position] = {}
        self._pending: list[_PendingOrder] = []
        self.fills: list[Fill] = []

    # -- order intake ------------------------------------------------------
    def submit(self, intent: TradeIntent) -> None:
        self._pending.append(_PendingOrder(intent))

    # -- bar processing ----------------------------------------------------
    def on_bar_open(self, bar: Bar) -> list[Fill]:
        """Fill queued orders at this bar's open (with adverse costs)."""
        fills: list[Fill] = []
        still_pending: list[_PendingOrder] = []
        for po in self._pending:
            if po.intent.instrument != bar.symbol:
                still_pending.append(po)
                continue
            fills.append(self._fill(po.intent, bar, bar.open))
        self._pending = still_pending
        return fills

    def check_stops(self, bar: Bar) -> list[Fill]:
        """Trigger protective stops inside this bar's range."""
        pos = self.positions.get(bar.symbol)
        if pos is None or pos.qty == 0 or pos.protective_stop_price is None:
            return []
        stop = pos.protective_stop_price
        triggered = (pos.is_long and bar.low <= stop) or (not pos.is_long and bar.high >= stop)
        if not triggered:
            return []
        # Gap through the stop -> fill at open; otherwise at the stop itself.
        if pos.is_long:
            base = min(bar.open, stop)
            side = Side.SELL
        else:
            base = max(bar.open, stop)
            side = Side.BUY
        intent = TradeIntent(
            instrument=bar.symbol,
            side=side,
            qty=abs(pos.qty),
            signal=_stop_signal(pos, bar),
        )
        return [self._fill(intent, bar, base)]

    # -- internals ---------------------------------------------------------
    def _fill(self, intent: TradeIntent, bar: Bar, base_price: Decimal) -> Fill:
        adverse = 1 if intent.side == Side.BUY else -1
        price = round_to_tick(base_price * (1 + adverse * self._cost_frac))
        fill = Fill(
            client_order_id=intent.client_order_id,
            instrument=intent.instrument,
            side=intent.side,
            qty=intent.qty,
            price=price,
            ts_utc=bar.ts_utc,
        )
        self._apply(fill, intent)
        self.fills.append(fill)
        return fill

    def _apply(self, fill: Fill, intent: TradeIntent) -> None:
        signed = fill.qty if fill.side == Side.BUY else -fill.qty
        self.cash -= signed * fill.price
        pos = self.positions.get(fill.instrument)
        if pos is None or pos.qty == 0:
            self.positions[fill.instrument] = Position(
                instrument=fill.instrument,
                qty=signed,
                avg_entry=fill.price,
                opened_at=fill.ts_utc,
                strategy_id=intent.signal.strategy_id,
                protective_stop_price=intent.protective_stop,
            )
        else:
            new_qty = pos.qty + signed
            if new_qty == 0:
                self.positions.pop(fill.instrument)
            elif (new_qty > 0) == (pos.qty > 0) and abs(new_qty) > abs(pos.qty):
                total_cost = pos.avg_entry * pos.qty + fill.price * signed
                pos.avg_entry = total_cost / new_qty
                pos.qty = new_qty
            else:
                pos.qty = new_qty  # partial close keeps avg_entry

    def equity(self, marks: dict[str, Decimal]) -> Decimal:
        eq = self.cash
        for sym, pos in self.positions.items():
            eq += pos.qty * marks.get(sym, pos.avg_entry)
        return eq


def _stop_signal(pos: Position, bar: Bar):
    from mercurius.core.enums import SignalKind
    from mercurius.core.models import Signal

    return Signal(
        strategy_id=pos.strategy_id or "stop",
        symbol=bar.symbol,
        kind=SignalKind.EXIT,
        bar_ts=bar.ts_utc,
        reason="protective_stop",
    )
