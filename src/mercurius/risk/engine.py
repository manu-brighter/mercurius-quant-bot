"""Risk engine: pre-trade checks + daily-loss halt latch.

Shared by backtest and live — the backtest feeds it SimClock timestamps and
simulated equity; the live loop feeds it broker-account equity. The halt
latch, once set, stays set for the rest of the session and is persisted by
the caller (journal event) so a crash-restart cannot reset the loss budget.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from mercurius.config.schema import RiskConfig
from mercurius.core.clock import ET
from mercurius.core.enums import AccountMode, SignalKind
from mercurius.core.models import Position, TradeIntent

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Rejected:
    reason: str


@dataclass(frozen=True)
class Approved:
    pass


@dataclass
class RiskState:
    session_date: date | None = None
    session_open_equity: Decimal | None = None
    halted: bool = False
    halt_reason: str = ""
    trades_today: int = 0
    peak_equity: Decimal = Decimal("0")
    positions: dict[str, Position] = field(default_factory=dict)


class RiskEngine:
    def __init__(
        self,
        cfg: RiskConfig,
        account_mode: AccountMode = AccountMode.MARGIN,
    ) -> None:
        self.cfg = cfg
        self.account_mode = account_mode
        self.state = RiskState()

    # -- session lifecycle -------------------------------------------------
    def on_session_start(self, ts_utc: datetime, equity: Decimal) -> None:
        d = ts_utc.astimezone(ET).date()
        if self.state.session_date == d:
            return  # restart mid-session: keep halted latch and counters
        self.state.session_date = d
        self.state.session_open_equity = equity
        self.state.trades_today = 0
        self.state.halted = False
        self.state.halt_reason = ""
        self.state.peak_equity = max(self.state.peak_equity, equity)

    def restore_halt(self, reason: str) -> None:
        """Re-apply a persisted halt after restart (journal replay)."""
        self.state.halted = True
        self.state.halt_reason = reason

    # -- equity monitoring -------------------------------------------------
    def on_equity(self, ts_utc: datetime, equity: Decimal) -> str | None:
        """Feed current equity. Returns a halt reason when a limit trips."""
        st = self.state
        st.peak_equity = max(st.peak_equity, equity)
        if st.session_open_equity is None or st.halted:
            return None
        loss = st.session_open_equity - equity
        max_loss = min(
            self.cfg.max_daily_loss_usd,
            st.session_open_equity * self.cfg.max_daily_loss_pct,
        )
        if loss >= max_loss:
            st.halted = True
            st.halt_reason = f"daily loss {loss} >= limit {max_loss}"
            log.warning("RISK HALT: %s", st.halt_reason)
            return st.halt_reason
        return None

    # -- pre-trade check ---------------------------------------------------
    def check(self, intent: TradeIntent, equity: Decimal) -> Approved | Rejected:
        st = self.state
        if intent.signal.kind == SignalKind.EXIT:
            return Approved()  # exits are always allowed — even (especially) when halted

        if st.halted:
            return Rejected(f"halted: {st.halt_reason}")

        if st.trades_today >= self.cfg.max_trades_per_day:
            return Rejected("max_trades_per_day reached")
        open_positions = sum(1 for p in st.positions.values() if p.qty != 0)
        if open_positions >= self.cfg.max_concurrent_positions:
            return Rejected("max_concurrent_positions reached")
        if intent.instrument in st.positions and st.positions[intent.instrument].qty != 0:
            return Rejected("position already open for instrument")
        if intent.signal.kind == SignalKind.ENTER_SHORT and self.account_mode != AccountMode.MARGIN:
            return Rejected("short selling requires a margin account (>= $2k equity)")

        if intent.limit_price is not None:
            notional = intent.qty * intent.limit_price
            cap = min(self.cfg.max_position_notional_usd, equity)
            if notional > cap:
                return Rejected(f"notional {notional} exceeds cap {cap}")
        if intent.qty <= 0:
            return Rejected("non-positive qty")
        return Approved()

    def record_entry(self, position: Position) -> None:
        self.state.trades_today += 1
        self.state.positions[position.instrument] = position

    def record_exit(self, instrument: str) -> None:
        self.state.positions.pop(instrument, None)

    def sync_positions(self, positions: dict[str, Position]) -> None:
        self.state.positions = dict(positions)
