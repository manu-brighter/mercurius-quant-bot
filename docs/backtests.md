# Frozen backtest baseline

**Run date:** 2026-08-08 · **Status:** M2 gate **FAILED** for both strategies.

This is the reference result every future change is compared against. It is
frozen: do not re-run it into this file with different parameters to make it
look better. Add a new dated section instead.

## What was run

| | |
|---|---|
| Command | `uv run python -m mercurius backtest --config config/backtest.yaml` |
| Period | 2024-01-02 → 2025-12-31 (501 sessions) |
| Data | Alpaca **IEX** 1-minute bars, `adjustment=all`, local parquet cache |
| Bars replayed | 365,804 regular-hours (SPY 189,285 · QQQ 176,519) |
| Costs modeled | 1.5 bps slippage + 1.0 bps spread haircut, fills at next-bar open |
| Strategies | `noise_bands` and `orb`, both on SPY and QQQ, default frozen params |
| Holdout | 2026 data untouched (lives in `data/holdout/`, never loaded here) |

## Result

```
initial capital : 2000
final equity    : 1555.19848
trading days    : 501
sharpe (daily)  : -2.49
max drawdown    : 22.6%
trades          : 1168
win rate        : 33.0%
profit factor   : 0.71
net pnl         : -441.89
expectancy w/o top 5% : -0.85
  [orb_SPY]         n=160 win=33.1% pf=0.70 pnl=-57.48
  [orb_QQQ]         n=239 win=35.6% pf=0.59 pnl=-155.25
  [noise_bands_SPY] n=389 win=32.9% pf=0.70 pnl=-139.01
  [noise_bands_QQQ] n=371 win=32.1% pf=0.82 pnl=-84.39
  [?]               n=9   win=0.0%  pf=0.00 pnl=-5.75
risk rejections : 914
```

**Every strategy/symbol combination is negative.** No cherry-picking survives:
the best of the four (`noise_bands_QQQ`) still has a profit factor of 0.82.

## Why it loses: the edge is smaller than the spread

A zero-cost re-run (diagnostic only — `run_backtest` does not write to
`trials/trials.jsonl`, so this consumed no DSR trial budget):

| | net PnL | per trade |
|---|---|---|
| Gross (costs set to zero) | **+143.87** | +0.12 |
| Net (1.5 + 1.0 bps modeled) | **−441.89** | −0.38 |
| Implied cost drag | −585.76 | −0.50 |

Both strategies are *marginally positive before costs and decisively negative
after*. This is the textbook retail day-trading outcome the README's opening
section warns about, reproduced on this project's own data.

Note the interaction with the feed measurement in the README: for QQQ the p95
IEX-vs-SIP close divergence (4.41 bps) is **larger than the 2.5 bps of cost the
backtest charges**. The modeled cost is therefore optimistic, not conservative —
the true net result is likely worse than −441.89, not better.

## Verdict against the pre-registered M2 gate

> "A strategy ships to paper only if holdout expectancy is positive after
> modeled costs AND the DSR survives the cumulative trial count."

Expectancy after modeled costs is **negative** for all four combinations, so the
gate fails at the first clause and the DSR is not reached. Per the project's own
rules this is the gate working, not a bug to engineer around.

What this result does **not** license:
- tuning `noise_bands.lookback_days` (frozen per SSRN 4824172),
- adding day-of-week or other filters until something turns positive
  (documented overfitting signature),
- lowering the modeled cost assumptions,
- touching the 2026 holdout to "check whether it works now".

The honest next questions are about cost structure, not parameters: the entry
mechanism pays the spread on every trade at a per-trade edge of ~1.2 cents on
~$1,000 of notional. Nothing survives that.

## Isolated per-strategy runs (2026-08-08)

The portfolio baseline above ran all four instances against **one** risk engine
(`max_trades_per_day: 4`, `max_concurrent_positions: 2`), so they competed for
the same budget — 914 rejected signals against 1,168 executions. That made the
per-strategy lines above unreliable: a starved strategy and a bad strategy look
alike. Each instance was therefore re-run alone with the full budget.

| strategy | trades | rejected | win% | PF | net | gross | cost drag | sharpe | maxDD |
|---|---|---|---|---|---|---|---|---|---|
| noise_bands_SPY | 530 | 2 | 33.0% | 0.69 | −228.71 | +36.47 | 265.18 | −2.08 | 12.2% |
| noise_bands_QQQ | 500 | 5 | 30.8% | 0.84 | −148.06 | +102.03 | 250.09 | −0.78 | 8.2% |
| orb_SPY | 171 | 0 | 42.1% | 0.77 | −78.77 | +7.09 | 85.86 | −0.99 | 5.2% |
| orb_QQQ | 256 | 0 | 44.9% | 0.87 | −85.36 | +42.12 | 127.48 | −0.75 | 6.2% |

**Starvation was real, and it was not the cause of the losses.** Rejections
collapse from 914 to 0–5 and trade counts rise substantially (noise_bands_SPY
389 → 530), confirming the shared cap was binding. But every strategy is still
negative in isolation, so the baseline's verdict survives the correction.

Two things worth noticing:

- The isolated results sum to **−540.90**, *worse* than the portfolio's
  −441.89. The shared risk cap was reducing losses by rationing access to a
  negative-expectancy system. That is not a strategy working; it is a brake.
- ORB looks structurally healthier than noise_bands — win rates of 42–45%
  against 31–33%, and a third of the trade count — yet still loses, because
  its gross edge is even thinner per trade.

### What cost level would break even

Cost scales with the bps assumption, so the break-even is roughly
`2.5 bps × gross / cost drag` (linear estimate from the table above, not a
re-run):

| strategy | break-even round-trip cost |
|---|---|
| noise_bands_QQQ | ~1.02 bps |
| orb_QQQ | ~0.83 bps |
| noise_bands_SPY | ~0.34 bps |
| orb_SPY | ~0.21 bps |

The best case needs total round-trip costs under **~1 bp**. For reference, the
measured IEX-vs-SIP median close divergence on QQQ alone is 0.74 bps — before
any spread or slippage is paid at all. There is no realistic execution
improvement that closes this gap.

## Known issues in this run

- **`[?]` bucket, 9 trades (−5.75).** Trades whose `strategy_id` was `None` at
  the opening fill (`engine._track_trade` reads it from the position, which is
  absent for those fills). Cosmetic for this result — 0.8% of trades — but the
  same attribution path feeds the live per-strategy reports, so it should be
  fixed before the paper record is used for the scorecard.
- **914 risk rejections** versus 1,168 executed trades. Worth understanding
  before paper trading: the risk engine is refusing a large share of signals,
  so the live trade rate may differ substantially from this backtest.

## Reproducing

```bash
uv run python -m mercurius download-data --symbols SPY,QQQ --start 2024-01-01 --end 2025-12-31
uv run python -m mercurius backtest --config config/backtest.yaml
```

Deterministic: same cache, same result.

---

# 2026-08-08 (later) — Fidelity audit of `noise_bands` + swing pivot

Two things changed after the gate failure above. Neither is a retune of the
failed strategy: the first is a bug-class correction, the second is a new
hypothesis.

## A. `noise_bands` was not faithful to SSRN 4824172

Re-reading the paper's spec (via multiple independent secondary sources — the
PDF host is unreachable from the build environment) surfaced three deviations
in our implementation. All three pushed in the same direction: **more round
trips per unit of signal**, which is precisely what the cost arithmetic
punishes.

| | Our pre-audit version | The paper |
|---|---|---|
| Exit check | only at :00/:30 marks | **continuously**, "closed immediately" |
| Trailing level | fixed 0.5% from entry (our invention) | **max(band, session VWAP)** for longs; min(...) for shorts |
| Hold horizon | exit whenever price re-entered the band at a mark | hold toward the 16:00 close unless the trail is crossed |

The audited implementation now matches the paper on all three. Entries remain
half-hour level checks; the 14-day lookback stays frozen.

**Remaining known deviations** (documented in the module docstring, not fixed):
gap-adjustment arithmetic is unverified (we anchor to max/min of open and prior
close); sizing is %-risk with no leverage rather than the paper's 2%-daily-vol
target with up to 4x. The second affects return scale, not the sign of the
per-trade edge — which is what the gate tests.

**This is verification, not tuning.** No parameter was searched, so no DSR trial
budget was consumed by the change itself. The re-run below is one trial.

### Re-run (to be executed locally — the bar cache lives there)

```
uv run python -m mercurius backtest --config config/backtest.yaml
```

Compare against the paper's reported statistics before drawing conclusions:

| Statistic | Paper (2007 – early 2024) | Our audited run |
|---|---|---|
| Annualized return | 19.6% (with up to 4x leverage) | _fill in_ |
| Sharpe | 1.33 | _fill in_ |
| Hit ratio | ~43% (highly convex: avg win >> avg loss) | _fill in_ |
| Trades | ~1.3–1.8/day across configurations | _fill in_ |

**Decision rule, pre-registered before the run:** positive after-cost
expectancy AND trade frequency/hit ratio in the paper's neighbourhood → the
intraday verdict was a false negative, and the strategy proceeds to the normal
paper gate. Anything else → the intraday book is closed. Note the prior: our
pre-audit gross edge was +$0.12/trade against $0.50 of cost, so the audit has
to find roughly a 4x improvement in gross edge per trade to flip the verdict.
That is a high bar and it is *supposed* to be.

## B. Swing book (new hypothesis, same gate)

Round-trip cost is roughly fixed in bps. Against an intraday move it was ~400%
of gross edge; against a multi-day move of 0.5–1% it is ~3%. That is the whole
argument for the pivot — and it is a different question, not a second attempt
at the same one.

Two strategies, both daily bars, both long-only above the 200-day SMA, both
with published parameters (nothing searched):

- **`rsi2`** — Connors RSI(2) < 10 entry, exit on RSI(2) > 65 or close > 5-day
  SMA. ~15–30 trades/year/symbol.
- **`ibs`** — Internal Bar Strength < 0.2 entry, exit > 0.8. ~19–25
  trades/year/symbol.

Both are *short-term reversal* reads. They are correlated: if both fail, that
is one verdict on the effect, not two independent ones.

**Health warning recorded in advance:** RSI(2) is the most-published,
most-arbitraged pattern in retail quant. Long-sample studies report 65–79% win
rates; out-of-sample work covering 2024–2026 reports win rates collapsing
toward ~30%. Expect decay, and read a good backtest with suspicion.

Run (locally, after downloading daily bars):

```
uv run python -m mercurius download-data --timeframe daily --symbols SPY,QQQ
uv run python -m mercurius backtest --config config/swing.yaml
```

Same M2 gate as the intraday book. 2026 stays locked.

---

# Pre-registration — swing book (written 2026-08-08, BEFORE the run)

The swing backtest has not been run. This section is written now precisely
because it cannot be written honestly afterwards: once the numbers are visible,
any "expectation" is contaminated by them.

## What is being tested

Hypothesis #2: **short-term reversal on liquid ETFs clears costs at a multi-day
holding period, where the same fixed round-trip cost that killed the intraday
book is ~3% of a typical move instead of ~400% of it.**

`rsi2` and `ibs`, both on SPY and QQQ, daily bars, 2015-01-01 → 2025-12-31,
published parameters only, nothing searched. Run:

```
uv run python -m mercurius download-data --timeframe daily --symbols SPY,QQQ
uv run python -m mercurius backtest --config config/swing.yaml
```

## Expected trade counts (from the source literature, not from our data)

| Strategy | Published trades/yr/symbol | Expected over 11 yrs × 2 symbols |
|---|---|---|
| `rsi2` | ~15–30 | ~330–660 |
| `ibs`  | ~19–25 | ~420–550 |

A result far outside these ranges is an **implementation smell**, not a finding —
check the strategy before interpreting the P&L. (Note the 200-session warmup:
signals only begin ~10 months into the sample.)

## Pass condition — all three required

1. Positive expectancy per trade after modeled costs over the fit era.
2. **Gross edge per trade ≥ 2× the modeled round-trip cost.** This ratio is
   stated in advance because it is exactly what the intraday book failed
   (0.24×) and exactly the number that is easiest to rationalize away after the
   fact. A strategy that clears costs by a hair has no margin for the live
   slippage that always exceeds the model.
3. Survives a Deflated Sharpe Ratio check against the cumulative trial count in
   `trials/trials.jsonl`.

Passing means: proceed to the paper-trading gate. It does **not** mean the
strategy works.

## Fail condition and its meaning

Anything else. Interpretation, stated in advance: short-term reversal on liquid
index ETFs does not clear costs for a retail account at this size.

`rsi2` and `ibs` are correlated reads of the *same* effect. If both fail, that
is **one** verdict on short-term reversal, not two independent data points — do
not treat it as "we tried two things."

## Standing prior (recorded so a good result gets read with suspicion)

RSI(2) is the most-published, most-arbitraged pattern in retail quant.
Long-sample studies report 65–79% win rates; out-of-sample work covering
2024–2026 reports win rates collapsing toward ~30%. A backtest here that looks
like the 2008 book's numbers is more likely to indicate a lookahead bug than a
surviving edge. Check the implementation first.

## Binding constraint on what happens next

**No parameter may change after these numbers are seen.** If a parameter is
changed anyway, the result is a new trial: log it in `trials/trials.jsonl`, add
a new dated section here, and carry the increased N into every future DSR
calculation. There is no version of this where a retuned run replaces the
original in this document.

---

# 2026-08-08 (local execution) — Results: both runs FAILED their gates

Executed on the local machine (the bar cache lives here). Two pre-registered
decision rules were applied as written. Both fail. Five trials were appended to
`trials/trials.jsonl`, bringing the project-lifetime count to **5**.

## Blocker resolved first: the NYSE calendar stopped at 2023

The swing run could not start — `core/clock.py` covered 2023–2027, and both
`session_for()` (called per bar by the engine) and the daily-bar loader raise
outside that range. Extending it was a prerequisite, not a choice.

The 2016–2022 holidays were **derived from Alpaca's consolidated daily bars** (a
weekday with no bar was a closure) rather than typed from memory, because the
dangerous error direction is silent: a wrongly-listed holiday drops a real
session from every backtest without complaint. The derived table was then
cross-checked against the published NYSE calendar — they agree exactly,
including the 2018-12-05 national day of mourning and the *absence* of a New
Year's holiday in 2022 (Jan 1 was a Saturday).

Verified after the change: 2,514 Alpaca sessions 2016–2025, **0 real sessions
dropped, 0 phantom sessions invented**. Early closes cannot be derived from bar
data (an early close still prints a bar) and come from the published calendar;
they shift a daily bar's close stamp by three hours and never change bar
ordering, so residual error there cannot alter a swing signal or fill.

**Alpaca daily history begins 2016-01-04.** The swing pre-registration named
2015-01-01 as the start; that data does not exist. The sample is therefore 10
years, not 11, and the expected trade-count bands below are scaled accordingly
(~9.2 effective years after the 200-session warmup).

## A. `noise_bands` fidelity re-run — VERDICT: intraday book CLOSED

Isolated per instance, because `noise_bands_SPY` and `orb_SPY` both trade SPY
and share one broker position slot and one `open_trades[instrument]` key — the
portfolio run cannot attribute either honestly. (Symptom in the portfolio run:
the unattributed `[?]` bucket grew from 9 trades to 123, and ORB's win rate
"changed" despite the audit not touching ORB.)

| | Paper (SSRN 4824172) | Audited SPY | Audited QQQ | Pre-audit SPY |
|---|---|---|---|---|
| Trades/day | 1.3–1.8 | **1.48** | **1.43** | 1.06 |
| Hit ratio | ~43% | 17.7% | 20.6% | 33.0% |
| Sharpe | 1.33 | −3.11 | −2.60 | — |
| Annualized | 19.6% (≤4x lev) | −7.4% | −7.6% | — |
| Net PnL | — | −276.14 | −290.59 | −228.71 |
| Gross PnL | — | +96.21 | +65.99 | +36.47 |
| Avg win : avg loss | ">>" convex | 2.91 : 1.08 | 3.22 : 1.35 | — |

**The audit was a genuine fidelity improvement**, and this deserves recording
because it is evidence the deviation was real: trade frequency moved from
1.06/day (below the paper's band) to 1.48/day (inside it), and the paper's
convex payoff signature is now present (~2.7:1 win/loss at a low hit rate).
Gross edge per trade on SPY nearly doubled, $0.069 → $0.130.

**It is still nowhere near enough.** The pre-registration stated the audit needed
roughly a 4x gross-edge improvement to flip the verdict; it delivered 1.9x.
Gross/cost went 0.14x → 0.26x, against 1.0x required merely to break even.

Applying the rule as written — *"positive after-cost expectancy AND trade
frequency/hit ratio in the paper's neighbourhood → false negative; anything else
→ the intraday book is closed"*: frequency now matches, **hit ratio is less than
half the paper's, and expectancy is negative.** → **CLOSED.**

Residual uncertainty, recorded but explicitly *not* grounds to reopen: two known
deviations remain unfixed (gap-adjustment arithmetic, and %-risk sizing vs the
paper's vol-target with leverage). Sizing affects return scale, not the sign of
per-trade edge. A hit ratio less than half the published figure is a large
enough gap that either the edge decayed severely after publication or a third
deviation remains — but "it might work if we fixed something else" is not a
result, and the budget for this hypothesis is spent.

## B. Swing book — VERDICT: FAILED (condition 3)

Portfolio run: 399 trades, 65.9% win, PF 1.48, net +484.15, Sharpe 0.36,
maxDD 7.1%.

The portfolio run again mis-attributes (`rsi2_SPY` and `ibs_SPY` share SPY;
`ibs` trades ~3.5x more often and crowds `rsi2` out), so the gate was evaluated
on isolated runs:

| strategy | trades | /yr/sym | published | win% | PF | net | gross | cost | gross/cost |
|---|---|---|---|---|---|---|---|---|---|
| rsi2_SPY | 73 | 7.9 | 15–30 | 71.2% | 1.25 | +48.49 | +63.50 | 15.01 | 4.23x |
| rsi2_QQQ | 73 | 7.9 | 15–30 | 75.3% | 1.63 | +132.30 | +148.01 | 15.71 | 9.42x |
| ibs_SPY | 186 | 20.2 | 19–25 | 64.0% | 1.34 | +131.17 | +171.37 | 40.21 | 4.26x |
| ibs_QQQ | 194 | 21.1 | 19–25 | 67.0% | 1.46 | +243.57 | +287.70 | 44.13 | 6.52x |
| **book** | **526** | | | | | **+555.52** | **+670.58** | **115.06** | **5.83x** |

Against the three pre-registered conditions, **all of which were required**:

1. **Positive expectancy per trade after modeled costs** — **PASS.**
   +$1.056/trade.
2. **Gross edge ≥ 2x modeled round-trip cost** — **PASS**, comfortably: 5.83x
   for the book, 4.23–9.42x per instance. The pivot's core claim held: at a
   multi-day horizon the same fixed cost is ~17% of gross edge, against ~400%
   intraday.
3. **Survives a DSR check against the cumulative trial count** — **FAIL.**

| | Sharpe | DSR (N=5) | |
|---|---|---|---|
| rsi2_SPY | 0.225 | 0.315 | FAIL |
| rsi2_QQQ | 0.468 | 0.612 | FAIL |
| ibs_SPY | 0.439 | 0.576 | FAIL |
| ibs_QQQ | 0.586 | 0.745 | FAIL |
| book | 0.362 | 0.481 | FAIL |

Threshold is ~0.95 per the README. The best instance reaches 0.745. **All three
conditions were required, so the swing book does not proceed to paper.**

### The failure mode is not the one that was predicted

Recorded because it matters more than the verdict. The pre-registered
interpretation of failure read: *"short-term reversal on liquid index ETFs does
not clear costs for a retail account at this size."* **That interpretation is
wrong for this result.** The strategies cleared costs by 5.83x. They failed on
statistical strength: a Sharpe of 0.36–0.59 is too weak to survive
multiple-testing deflation, even at N=5.

Two honest observations, neither of which changes the verdict:

- The DSR is computed on a **daily-return** Sharpe for a book that holds a
  position roughly 31% of days. Flat days mechanically drag that Sharpe down.
  Whether daily-return Sharpe is the right denominator for a
  sometimes-in-market strategy is a real question about **how condition 3 was
  written** — and revising it now, after seeing the number it produced, is
  exactly the move `CLAUDE.md` forbids. It must be settled in writing *before*
  hypothesis #3, and if it is changed, this run is re-scored under the new rule
  as a new dated section, not edited here.
- **`rsi2`'s trade count is unresolved**: 7.9/yr/symbol against a published
  15–30. Isolation raised it from ~4.8 to 7.9 but did not close the gap. Under
  the pre-registered implementation-smell clause this means `rsi2`'s P&L should
  not be read as a clean test of the published strategy at all. `ibs`, by
  contrast, landed squarely in its published band (20.2 and 21.1 vs 19–25).

## Cross-cutting bug found (affects every portfolio-mode result)

Two strategies trading the same symbol share one `broker.positions[symbol]` slot
and one `open_trades[symbol]` bookkeeping key. Consequences: per-strategy
attribution silently collides, trades land in the `[?]` bucket, and one strategy
suppresses another's entries. This corrupts *every* per-strategy line in a
portfolio-mode run, including the original frozen baseline at the top of this
document. Isolated runs are unaffected, and all verdicts here rest on those.

This is a backtest bookkeeping defect, not a strategy result. It should be fixed
before any multi-strategy run is used for a decision.

## Hypothesis budget

- #1 intraday — **failed** (closed after fidelity audit).
- #2 swing — **failed** (condition 3).
- #3 — reserved, unspent.

Per `CLAUDE.md`, if #3 also fails, strategy search ends.
