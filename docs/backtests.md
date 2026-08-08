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
