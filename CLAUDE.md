# Mercurius — rules of engagement

Read this before changing anything. It is short on purpose.

This project's most valuable asset is not a strategy — it is a validation gate
that can say "no edge" cheaply and honestly. Two results have already come back
negative. That is the gate working. The way this project fails is not a losing
backtest; it is someone quietly adjusting things until a backtest turns green,
which converts *no edge, no money lost* into *imaginary edge, real money lost*.

## Status

- **Hypothesis #1 — intraday** (`noise_bands`, `orb`): **FAILED the M2 gate.**
  +$0.12 gross per trade against ~$0.50 of cost. See `docs/backtests.md`.
- **Fidelity audit** of `noise_bands` (corrected to SSRN 4824172): code done,
  **re-run pending** on the local machine, decision rule pre-registered in
  `docs/backtests.md`. Prior: needs ~4x gross-edge improvement to flip. Unlikely.
- **Hypothesis #2 — swing** (`rsi2`, `ibs`, daily bars): built, **not yet run**,
  disabled by default. Expectations pre-registered in `docs/backtests.md`.
- No real money has been risked. Paper account sits untouched at $2,000.

## Hard rules

These are not preferences. Breaking one invalidates the project's results.

1. **The 2026 holdout is never swept, tuned on, or "just checked."** It is spent
   once, by a human, on a strategy that already passed the fit-era gate.
   `sweep._assert_no_holdout` enforces this — do not weaken it.
2. **Never delete, reset, or rotate `trials/trials.jsonl`.** The Deflated Sharpe
   Ratio is only honest if N counts every trial ever run, across the project's
   whole life. It is git-tracked for this reason (`trials/README.md`).
3. **Published parameters are frozen, not knobs.** `noise_bands.lookback_days`
   =14; ORB 5-min range / 2R / doji / ATR-width / volume filters; RSI(2) 10 in,
   65 out, 200d trend, 5d exit; IBS 0.2 in, 0.8 out. `tests/unit/
   test_frozen_params.py` fails if these drift.
4. **No day-of-week filters, ever.** Independent sources "found" different bad
   days in the same data — it is a documented overfitting signature.
5. **Never lower `slippage_bps` or `spread_haircut_bps` to improve a result.**
   The modeled 2.5 bps is already optimistic: measured p95 IEX-vs-SIP divergence
   on QQQ is 4.41 bps.
6. **`ALPACA_PAPER` stays `true`.** Going live is a human decision gated by the
   scorecard, never a code change made in passing.
7. **Options are v2 and blocked** on paid OPRA data plus more capital. The free
   feed is indicative/delayed and must never be treated as tradable. Keep
   `snapshot-chains` running (free, and the history cannot be bought later).

## What a negative result licenses

**Allowed:** record it in `docs/backtests.md` as a dated, frozen section; test a
*different* hypothesis with *published* parameters; fix an implementation that
provably deviates from its published source (that is verification, not tuning —
document the deviation and log it as one trial).

**Not allowed:** re-running the same strategy with new parameters until it
passes; adding filters until something turns positive; relaxing the gate,
scorecard thresholds, or cost assumptions; treating "it would have worked with
X" as a result.

If a change makes a previously failing strategy pass, the burden is to explain
*why the old version was wrong*, not why the new one is better.

## Hypothesis budget: 3

#1 intraday (failed) · #2 swing (unrun) · #3 reserved.

If #2 and #3 both fail, **strategy search ends.** The infrastructure stays and is
worth keeping; the searching stops. Going past 3 requires a deliberate written
decision recorded in `docs/backtests.md` — the point of the budget is that "just
one more idea" cannot quietly run forever.

## Where things are written down

- `docs/backtests.md` — frozen baselines and pre-registered decision rules. Add
  new dated sections; never edit an existing one to look better.
- `trials/README.md` — why the trial log is sacred.
- `README.md` — setup, gates, go-live checklist, Swiss tax warning.
- `analyst/PROMPT.md` — the weekly read-only review; it may alert and halt, but
  never edits parameters.

## Practical notes

- Backtests run on the **local** machine (the bar cache lives there). Cloud
  sessions do code and docs.
- Intraday and swing strategies cannot share a backtest run (different bar
  timeframes); use `config/swing.yaml` for the swing book.
- `make lint test` must be green before any commit.
