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

---

# 2026-08-08 (later still) — Attribution bug fixed; benchmark run

## The cross-strategy collision defect is fixed

Three changes, five regression tests (`tests/unit/test_trade_attribution.py`),
all of which fail against the previous code:

1. **`Fill.strategy_id`** — attribution now travels on the fill. It could not be
   recovered from broker state afterwards, because by the time a closing fill is
   processed the position it belonged to has already been popped. That was the
   direct cause of the `[?]` bucket.
2. **Cross-strategy merges are refused, and counted.** `SimBroker` nets per
   symbol (as a real broker does), so a second strategy entering a held symbol
   used to silently merge into one position with one average price — after
   which neither strategy could be measured or exited independently. That entry
   is now rejected and surfaces as `symbol conflicts` in the summary.
3. **Phantom round trips removed.** A closing fill with no open round trip on
   the books is logged and skipped instead of being recorded as an un-closable
   "opening" trade.

`intraday=True/False` and the netting model are unchanged: the simulator still
mirrors the live broker rather than giving each strategy a private position,
because diverging there would make every backtest optimistic.

**Verification.** Unattributed trades: `[?]` = 0 in every run (was 9, then 123).
Conflicts surfaced: 7 intraday, 51 swing. Isolated runs are essentially
unchanged, as expected — a single strategy per symbol cannot collide — so the
recorded verdicts stand:

| | before fix | after fix |
|---|---|---|
| intraday book (portfolio) | 1354 trades, −467.23, 123 unattributed | 1231 trades, −375.21, **0** unattributed |
| swing book (portfolio) | 399 trades, +484.15 | 398 trades, +470.18, 51 conflicts |
| ibs_SPY (isolated) | 186 trades, +131.17 | 185 trades, +141.89 |

Trial count is now **7**; re-scoring the swing DSR at N=7 only tightens it
(book 0.265, best instance `ibs_QQQ` 0.683, threshold ~0.95). Verdict unchanged.

## The benchmark the scorecard requires — and it is not close

The go/no-go scorecard has always required a buy-and-hold comparison. Over the
identical 2016-01-04 → 2025-12-31 daily sample, on the same $2,000:

| | total return | final equity | Sharpe | maxDD |
|---|---|---|---|---|
| **buy & hold QQQ** | **+505.1%** | $12,102 | **0.92** | 35.0% |
| **buy & hold 50/50** | **+394.5%** | $9,889 | **0.91** | 30.9% |
| **buy & hold SPY** | **+296.4%** | $7,928 | **0.87** | 33.8% |
| swing book (all four) | +23.5% | $2,470 | 0.24 | 8.4% |

The swing book returns roughly **one seventeenth** of a 50/50 buy-and-hold, at
**about a quarter of the risk-adjusted return**.

The fair objection is that the book is in the market only ~31% of days and
deploys a fraction of capital per trade, so the *total return* comparison
flatters buy-and-hold. That objection is why the Sharpe column matters: Sharpe
is return per unit of risk and is scale-free with respect to deployment. On
that measure the book loses 0.24 to 0.91. Being idle does not explain it away —
under-deployment is a choice the strategy makes, and the risk-adjusted return of
what it does deploy is still far worse.

## What this means for "make it profitable"

The strategies *are* profitable in the narrow sense: +$470 net over ten years,
after costs, with every instance positive. That is not the question the project
was built to answer. Against the two bars that were set in advance — the DSR,
and the buy-and-hold benchmark — the answer is no, on both, decisively.

The remaining ways to turn any of these backtests green are, exhaustively:
search parameters until one passes, add filters, relax the cost model, relax the
gate, or spend the 2026 holdout looking for a friendlier regime. `CLAUDE.md`
forbids all five, and forbids them precisely because they convert *no edge, no
money lost* into *imaginary edge, real money lost*.

The honest profitable answer visible in this table is buy-and-hold, which is not
a strategy-search result and costs no hypothesis budget.

Hypothesis #3 remains unspent. Before it is spent, the DSR-denominator question
recorded in `CLAUDE.md` must be settled in writing, and #3 should be something
with a plausible mechanism for beating a passive benchmark on a risk-adjusted
basis — not another short-horizon reversal read on the same two ETFs, which is
what #1 and #2 both were.

---

# Settled 2026-08-08, BEFORE hypothesis #3 — the DSR denominator

`CLAUDE.md` required this to be decided in writing before #3 runs, because
deciding it after seeing a number it produced is the forbidden move.

**Decision: the gate keeps the account-level daily-return Sharpe. No change.**

The objection was that a book idle ~69% of days has its Sharpe dragged down by
flat days. True, but it is answering the right question. There are two different
questions and only one of them gates capital:

- *Is the signal skilful?* → in-market Sharpe. A research question.
- *Should this account get the $2,000 rather than an alternative?* → account
  Sharpe over all calendar days. **This is the go-live question**, and idle
  capital is a real cost of the strategy, not an artifact of measurement.

Deploying capital is an alternative-cost decision, so the denominator must
include the days the strategy chose not to trade.

Two supporting notes, recorded for honesty:
- This choice does **not** rescue the failing swing book — it is the stricter
  reading. Adopting the rule that would have helped is exactly the bias this
  process exists to prevent, and it is worth noting that the principled answer
  landed on the unhelpful side.
- Using daily observations is already the *generous* choice on the other axis:
  n_obs = 2513 rather than 120 monthly observations, and larger n_obs raises the
  DSR. Switching to monthly returns would make the swing book look worse, not
  better.

**In-market Sharpe may be reported as a diagnostic, clearly labelled, and never
as the gate.**

---

# Pre-registration — hypothesis #3 (written BEFORE the run)

This spends the **final** hypothesis in the budget. Per `CLAUDE.md`, if it
fails, strategy search ends.

## Why this hypothesis, and not another reversal read

#1 (intraday momentum/breakout) and #2 (short-horizon reversal) were both
short-holding-period bets on the same two ETFs, and both died on the same
arithmetic: edge per trade too small relative to a fixed round-trip cost. A
third variation of that shape would be a third way of asking the same question.

The benchmark run on 2026-08-08 changed what the open question is. Buy-and-hold
50/50 returned +394.5% at Sharpe 0.91 over the same sample; everything built so
far loses to it on risk-adjusted return. So the only interesting remaining
question is not "can we find a trade" but:

**Hypothesis #3: can a published, non-fitted trend filter improve the
risk-adjusted return of simply holding the index?**

## What is being tested

The Faber 10-month moving-average timing rule (Faber, *A Quantitative Approach
to Tactical Asset Allocation*, 2007 — the most-replicated tactical rule in the
literature):

- Decide **only on the last trading day of each month**.
- Long the index if the monthly close > 10-month SMA of monthly closes.
- Otherwise flat (cash).
- Long-only, fully invested when on. No stop: the exit *is* the signal.
- Parameters frozen by the source: **10 months, monthly decisions**. Nothing
  searched. No variant tested. If 10 months fails, 12 months is not then tried.

Sample: SPY and QQQ, daily bars 2016-01-04 → 2025-12-31, same data and the same
1.5 + 1.0 bps cost model. 2026 stays locked.

## Expected trade count

~1–3 round trips per year per symbol (~20–60 over the sample across both).
Materially outside that range is an implementation smell, not a finding.

## Honest prior, recorded before the run

**I expect this to underperform buy-and-hold on total return, and I am not
confident it beats it on Sharpe either.** The 2016–2025 sample is a strong bull
market containing three sharp V-shaped drawdowns (Q4 2018, Mar 2020, 2022). A
monthly trend filter characteristically exits *after* the drop and re-enters
*after* the recovery has begun — whipsaw. Faber's published edge rests on
century-scale samples containing prolonged bear markets (1930s, 2000–2002,
2008), which this sample does not contain.

The mechanism being tested is drawdown reduction, not return enhancement. A
result of "lower return, materially lower drawdown, higher Sharpe" is the
success case. "Lower return and no Sharpe improvement" is failure.

## Pass condition — all three required

1. **Sharpe ≥ the buy-and-hold benchmark for the same symbol** over the same
   sample. Merely positive is not enough; #2 already cleared that and was still
   the wrong place for the money.
2. **Max drawdown materially below buy-and-hold** (the mechanism's actual
   claim), and positive expectancy after modeled costs.
3. **Survives the DSR** against the cumulative trial count, using the
   account-level daily denominator settled above.

## Fail condition and its meaning

Anything else. Interpretation, stated in advance: **no rule in this project's
reach improves on passively holding the index**, the hypothesis budget is spent,
and strategy search ends. The correct use of the infrastructure at that point is
recording and risk-managing a passive allocation, not searching for a fourth
idea.

Note the asymmetry that makes this test worth running: condition 1 is measured
against a benchmark that is itself already profitable. Failing it costs nothing
except the conclusion that buy-and-hold was the answer all along.

---

# 2026-08-08 — Hypothesis #3 result: FAILED. Budget spent.

Faber 10-month SMA timing, published parameters, run exactly as pre-registered
above. Allocation study on the same daily bars, 2.5 bps charged per transition
(matching the engine's per-fill charge). Window starts 2016-11-01, the first
month end with 10 monthly closes behind it; buy-and-hold is measured over the
identical window.

| | return | Sharpe | maxDD | final |
|---|---|---|---|---|
| SPY trend | +132.6% | 0.80 | 25.6% | $4,651 |
| SPY buy & hold | +271.1% | **0.88** | 33.8% | $7,422 |
| QQQ trend | +388.5% | **1.04** | 28.6% | $9,769 |
| QQQ buy & hold | +461.8% | 0.94 | 35.0% | $11,236 |
| 50/50 trend blend | +243.0% | **1.01** | **20.4%** | $6,859 |
| 50/50 buy & hold | +394.5% | 0.91 | 30.9% | $9,889 |

Round trips: 1.04/yr (SPY), 0.60/yr (QQQ) — inside the pre-registered 1–3/yr
band. Exposure ~82% of days. Costs are negligible at this frequency, which is
the one lesson from #1 and #2 that transferred.

## Verdict against the pre-registered conditions

| | SPY | QQQ |
|---|---|---|
| 1. Sharpe ≥ buy & hold | **FAIL** (0.80 vs 0.88) | PASS (1.04 vs 0.94) |
| 2. Lower maxDD, positive expectancy | PASS (25.6% vs 33.8%) | PASS (28.6% vs 35.0%) |
| 3. Survives DSR | **FAIL** (0.815) | **FAIL** (0.947) |

**FAILED.** All three were required.

The honest prior written before the run was half right: the filter did
underperform badly on total return in a bull sample, as predicted. But the
mechanism it actually claims — drawdown reduction — worked on every measure,
and on QQQ and the blend it did improve risk-adjusted return. This is the
closest anything in this project has come to clearing its bar.

## Disclosure: the QQQ verdict turned on my bookkeeping, not on the data

QQQ's DSR is **0.947** against a 0.95 threshold. That margin is smaller than a
judgment call I made earlier in the session, and the user is entitled to know
it:

| trial count N | QQQ DSR | |
|---|---|---|
| 7 | 0.9603 | would PASS |
| **9 (used)** | **0.9474** | **FAILS** |

N went from 7 to 9 because I chose to log the two corrected-engine re-runs as
trials, reasoning at the time — **before this result existed** — that
"re-measurement is still an evaluation" and that erring high was the safe
direction. There is a real counter-argument: those re-runs evaluated *identical
parameters* after an engine bug fix, and offered no new configuration to
cherry-pick from, which is what N is supposed to count.

I am not resolving that in favour of the passing answer. Three reasons:

1. Hard rule #2 forbids deleting, resetting or rotating the trial log, and
   un-logging entries to reach a pass is the purest form of the thing this
   project exists to prevent.
2. `CLAUDE.md`: *"If a change makes a previously failing strategy pass, the
   burden is to explain why the old version was wrong, not why the new one is
   better."* I cannot make that case cleanly now, because I am looking at the
   answer while making it.
3. Even at N=7, **SPY still fails condition 1 on the data** (Sharpe 0.80 vs
   0.88) — no accounting convention touches that.

If the trial-counting convention should change, it should change as a written
rule, decided on principle, and this run re-scored under it as a **new dated
section** — not by me picking the convenient N today. The sensitivity is
recorded here so that decision can be made with the numbers visible.

Also worth noting: the 50/50 blend (Sharpe 1.01, maxDD 20.4%) beats buy-and-hold
on both risk measures, but the blend was **not** the pre-registered unit of
analysis. Promoting it to one now, after seeing that it looks better than the
per-symbol sleeves, would be inventing the test after the result.

## Budget is spent — strategy search ends

- #1 intraday — failed.
- #2 swing — failed.
- #3 trend overlay — failed.

Per `CLAUDE.md`, strategy search now **ends**. Going past three requires a
deliberate written decision recorded here.

## What the ten years of evidence actually support

Stated plainly, because it is the useful output of the whole exercise:

1. **Nothing this project built beats passively holding the index after costs**,
   on the pre-registered bars.
2. **Buy-and-hold was profitable throughout** (+394.5%, Sharpe 0.91) and cost no
   hypothesis budget.
3. **The trend overlay is the one idea with a defensible mechanism**: it cut
   maximum drawdown from 30.9% to 20.4% and raised blended Sharpe from 0.91 to
   1.01. It failed the statistical bar, marginally, and its return cost over
   this sample was large (+243% vs +394%).
4. The infrastructure — journal, risk engine, watchdog, reconciliation,
   append-only records — is independently useful for running *any* allocation,
   including a passive one, and none of the above is an argument against it.

No real money has been risked at any point. That is the process working.
