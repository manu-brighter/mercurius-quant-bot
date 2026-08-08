# Mercurius — rules of engagement

Read this before changing anything. It is short on purpose.

This project's most valuable asset is not a strategy — it is a validation gate
that can say "no edge" cheaply and honestly. Two results have already come back
negative. That is the gate working. The way this project fails is not a losing
backtest; it is someone quietly adjusting things until a backtest turns green,
which converts *no edge, no money lost* into *imaginary edge, real money lost*.

## Status

- **Hypothesis #1 — intraday** (`noise_bands`, `orb`): **FAILED the M2 gate,
  and the book is now CLOSED.** The SSRN 4824172 fidelity audit ran on
  2026-08-08: it was a real improvement (trade frequency 1.06→1.48/day, into the
  paper's band; gross edge/trade $0.069→$0.130) but delivered 1.9x of the ~4x
  needed. Hit ratio 17.7% against the paper's ~43%; expectancy still negative.
- **Hypothesis #2 — swing** (`rsi2`, `ibs`, daily bars): **RAN 2026-08-08,
  FAILED on condition 3.** Conditions 1 and 2 passed well — +$1.06/trade after
  costs, gross/cost 5.83x — so the cost thesis behind the pivot held. It failed
  the DSR check: best instance 0.745 against a ~0.95 threshold. Note the
  pre-registered *interpretation* of failure ("does not clear costs") is wrong
  for this result; it cleared costs and lost on statistical strength.
- **Trial count is now 5** (`trials/trials.jsonl`). Carry it into every future DSR.
- **Known defect, unfixed:** two strategies on the same symbol share one
  position slot and one `open_trades` key, so portfolio-mode per-strategy
  attribution is unreliable. All 2026-08-08 verdicts rest on isolated runs.
- **Hypothesis #3** — reserved, unspent. If it fails, strategy search ends.
- No real money has been risked. Paper account sits untouched at $2,000.

## Open question to settle BEFORE hypothesis #3

Condition 3 applies the DSR to a *daily-return* Sharpe, but the swing book holds
a position only ~31% of days, so flat days mechanically depress it. Whether that
is the right denominator is a legitimate question — and it must be answered in
writing *before* #3 is run. Changing it now, having seen the number it produced,
is the forbidden move. If the rule does change, the swing run is re-scored as a
new dated section; the existing one is not edited.

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
