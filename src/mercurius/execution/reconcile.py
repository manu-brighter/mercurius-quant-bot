"""Startup reconciliation: the broker is the source of truth.

Scenarios handled:
- Broker has a position the journal doesn't know -> policy `adopt` (manage it)
  or `flatten` (close immediately). Either way: journal note + alert.
- Journal believes a position exists but the broker is flat -> mark stale.
- Orphaned protective stops (stop order with no position) -> cancel.
Also replays today's persisted halt latch so a crash-restart cannot reset the
daily loss budget.
"""

from __future__ import annotations

import logging
from datetime import datetime

from mercurius.config.schema import AppConfig
from mercurius.core.clock import ET
from mercurius.execution.broker import Broker
from mercurius.execution.executor import STOP_SUFFIX
from mercurius.journal import db as evk
from mercurius.journal.db import Journal
from mercurius.journal.writer import JournalWriter
from mercurius.risk.engine import RiskEngine

log = logging.getLogger(__name__)


def journal_open_positions(journal: Journal) -> set[str]:
    """Instruments the journal believes are open: signed fill qty nets != 0."""
    from decimal import Decimal

    net: dict[str, Decimal] = {}
    for ev in journal.events(evk.FILL):
        qty = Decimal(str(ev["qty"]))
        signed = qty if ev["side"] == "buy" else -qty
        net[ev["instrument"]] = net.get(ev["instrument"], Decimal("0")) + signed
    return {i for i, q in net.items() if q != 0}


def reconcile(
    cfg: AppConfig,
    broker: Broker,
    journal: Journal,
    risk: RiskEngine,
    now_utc: datetime,
) -> dict:
    writer = JournalWriter(journal)
    report = {"adopted": [], "flattened": [], "stale_journal": [], "cancelled_stops": []}

    broker_positions = broker.get_positions()
    journal_open = journal_open_positions(journal)

    for instrument, pos in broker_positions.items():
        if pos.qty == 0:
            continue
        if instrument not in journal_open:
            if cfg.risk.on_unknown_position == "adopt":
                report["adopted"].append(instrument)
                writer.note(now_utc, f"reconcile: adopted unknown position {instrument} {pos.qty}")
            else:
                report["flattened"].append(instrument)
                writer.note(now_utc, f"reconcile: flattening unknown position {instrument}")
        risk.state.positions[instrument] = pos

    if report["flattened"]:
        broker.flatten_all()

    for instrument in journal_open:
        if instrument not in broker_positions or broker_positions[instrument].qty == 0:
            report["stale_journal"].append(instrument)
            writer.note(now_utc, f"reconcile: journal position {instrument} not at broker; stale")

    for order in broker.get_open_orders():
        if order.client_order_id.endswith(STOP_SUFFIX):
            pos = broker_positions.get(order.instrument)
            if pos is None or pos.qty == 0:
                broker.cancel(order.client_order_id)
                report["cancelled_stops"].append(order.client_order_id)
                writer.note(now_utc, f"reconcile: cancelled orphan stop {order.client_order_id}")

    # replay today's halt latch (fail closed across restarts)
    last_halt = journal.last_event(evk.RISK_HALT)
    if last_halt is not None:
        halt_date = datetime.fromisoformat(last_halt["ts_utc"]).astimezone(ET).date()
        if halt_date == now_utc.astimezone(ET).date():
            risk.restore_halt(last_halt.get("halt_reason", "restored"))
            log.warning("restored risk halt from journal: %s", risk.state.halt_reason)
            report["halt_restored"] = True

    log.info("reconcile report: %s", report)
    return report


def reconcile_cli(cfg: AppConfig) -> int:
    from datetime import UTC

    from mercurius.execution.alpaca_broker import AlpacaBroker
    from mercurius.journal.db import Journal as J
    from mercurius.risk.engine import RiskEngine as RE

    broker = AlpacaBroker(cfg)
    journal = J(cfg.journal.db_path)
    risk = RE(cfg.risk, broker.account_mode())
    report = reconcile(cfg, broker, journal, risk, datetime.now(tz=UTC))
    print(report)
    return 0
