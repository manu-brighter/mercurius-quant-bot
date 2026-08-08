"""Typed helpers over the raw journal — used by backtest AND live."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from mercurius.core.models import Fill, Signal, TradeIntent
from mercurius.journal import db
from mercurius.journal.db import Journal


class JournalWriter:
    def __init__(self, journal: Journal) -> None:
        self.j = journal

    def signal(self, s: Signal) -> None:
        self.j.append(
            s.bar_ts,
            db.SIGNAL,
            {
                "strategy_id": s.strategy_id,
                "symbol": s.symbol,
                "signal_kind": str(s.kind),
                "reason": s.reason,
                "stop_price": s.stop_price,
                "target_price": s.target_price,
            },
        )

    def intent(self, ts: datetime, i: TradeIntent) -> None:
        self.j.append(
            ts,
            db.INTENT,
            {
                "client_order_id": i.client_order_id,
                "instrument": i.instrument,
                "side": str(i.side),
                "qty": i.qty,
                "limit_price": i.limit_price,
                "protective_stop": i.protective_stop,
                "strategy_id": i.signal.strategy_id,
            },
        )

    def intent_rejected(self, ts: datetime, i: TradeIntent, reason: str) -> None:
        self.j.append(
            ts,
            db.INTENT_REJECTED,
            {
                "client_order_id": i.client_order_id,
                "instrument": i.instrument,
                "strategy_id": i.signal.strategy_id,
                "rejection_reason": reason,
            },
        )

    def fill(self, f: Fill) -> None:
        self.j.append(
            f.ts_utc,
            db.FILL,
            {
                "client_order_id": f.client_order_id,
                "instrument": f.instrument,
                "side": str(f.side),
                "qty": f.qty,
                "price": f.price,
                "fee": f.fee,
            },
        )

    def trade_closed(
        self,
        ts: datetime,
        instrument: str,
        strategy_id: str | None,
        qty: Decimal,
        entry_price: Decimal,
        exit_price: Decimal,
        pnl: Decimal,
    ) -> None:
        self.j.append(
            ts,
            db.TRADE_CLOSED,
            {
                "instrument": instrument,
                "strategy_id": strategy_id,
                "qty": qty,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": pnl,
            },
        )

    def equity(self, ts: datetime, equity: Decimal, cash: Decimal) -> None:
        self.j.append(ts, db.EQUITY, {"equity": equity, "cash": cash})

    def risk_halt(self, ts: datetime, reason: str) -> None:
        self.j.append(ts, db.RISK_HALT, {"halt_reason": reason})

    def session(self, ts: datetime, kind: str, trading_date: str) -> None:
        self.j.append(ts, kind, {"trading_date": trading_date})

    def note(self, ts: datetime, text: str) -> None:
        self.j.append(ts, db.NOTE, {"text": text})
