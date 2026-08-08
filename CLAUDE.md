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
- **That defect is now FIXED** (2026-08-08): `Fill.strategy_id` carries
  attribution, cross-strategy merges into a held symbol are refused and counted
  as `symbol conflicts`, and phantom round trips are gone. `[?]` is 0 in every
  run. Both books were re-run on the corrected engine; both verdicts unchanged.
- **Buy-and-hold benchmark run** (scorecard requirement): over the same
  2016–2025 sample the swing book returns +23.5% at Sharpe 0.24 against 50/50
  buy-and-hold's +394.5% at Sharpe 0.91. It loses on risk-adjusted return, so
  under-deployment does not explain the gap. **Nothing built so far beats
  passive holding.**
- **Hypothesis #3 — trend overlay** (Faber 10-month SMA, published params):
  **RAN 2026-08-08, FAILED.** Closest anything has come. It cut blended maxDD
  30.9% → 20.4% and raised blended Sharpe 0.91 → 1.01, but SPY's sleeve failed
  Sharpe-vs-benchmark on the data (0.80 vs 0.88) and both sleeves failed the
  DSR (SPY 0.815, QQQ **0.947** against 0.95).
- **STRATEGY SEARCH IS OVER.** All three hypotheses are spent. Going past three
  requires a deliberate written decision recorded in `docs/backtests.md`.
- **Trial count is now 9.** Carry it into any future DSR.
- No real money has been risked. Paper account sits untouched at $2,000.

## Unresolved: the trial-counting convention

QQQ's hypothesis-#3 DSR is 0.947 at N=9 but 0.960 at N=7 — i.e. **the verdict
turned on a bookkeeping judgment, not on data.** N rose to 9 because the two
corrected-engine re-runs were logged as trials ("re-measurement is still an
evaluation", decided before that result existed). The counter-argument is that
they re-evaluated identical parameters and offered nothing to cherry-pick from.

This was deliberately **not** resolved in favour of the passing answer: hard
rule #2 forbids rotating the log, and the burden for a change that flips a fail
to a pass is to show the old version was wrong — which cannot be argued cleanly
while looking at the answer. If the convention changes, change it as a written
rule and re-score as a new dated section. Note SPY fails on the data at any N.

## The DSR denominator (settled 2026-08-08, before #3)

Keeps the **account-level daily-return Sharpe**. Idle capital is a real cost of
a strategy, and the go-live question is alternative-cost: should this account
get the money rather than a passive alternative. In-market Sharpe answers a
research question and may be reported as a labelled diagnostic, never as the
gate. Recorded that this is the stricter reading and did not rescue anything.

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
