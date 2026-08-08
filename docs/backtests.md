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
