# Mercurius Quant Bot

> **ARCHIVED — 2026-08-08. Concluded: no edge found, no money risked.**
>
> All three pre-registered hypotheses failed their gates. Nothing built here
> beat passively holding the index. The paper account finished untouched at
> $2,000 and no real capital was ever deployed. The full record is in
> [`docs/backtests.md`](docs/backtests.md); the rules that produced it are in
> [`CLAUDE.md`](CLAUDE.md).
>
> **This repository is kept as a lab notebook and as working infrastructure —
> not as a trading system to switch on.** Read the Conclusion below before
> resurrecting any part of it.

An automated intraday trading bot for US equities (SPY/QQQ), built to go
**backtest → paper → (maybe) live** against Alpaca, with honest validation and
fail-closed risk controls.

## Read this first: honest expectations

The large academic samples on retail day trading (Taiwan full-exchange data,
Brazilian futures cohorts) find roughly **1–3% of persistent day traders are
durably profitable after costs**. Published strategy edges decay after
publication. This project's realistic purpose is to **discover cheaply and
honestly whether an edge exists** — the validation gates below are designed to
say "no edge" quickly, and hitting that outcome is the process *working*, not
failing. Do not fund this beyond planned capital ($2,000), and never from
savings on the strength of a lucky week.

## Conclusion (2026-08-08): all three hypotheses failed

Read `docs/backtests.md` for the full record. Summary of the whole project:

| # | hypothesis | result |
|---|---|---|
| 1 | **Intraday** (`noise_bands`, `orb`) | **FAILED.** +$0.12 gross per trade against ~$0.50 of cost. A fidelity audit against SSRN 4824172 genuinely improved it (trade frequency into the paper's band, gross edge per trade nearly doubled) but delivered 1.9x of the ~4x needed. Hit ratio 17.7% vs the paper's ~43%. |
| 2 | **Swing** (`rsi2`, `ibs`, daily bars) | **FAILED.** The cost thesis held — +$1.06/trade after costs, gross edge 5.83x cost — but the Deflated Sharpe check failed (0.265 for the book, 0.745 best instance, against ~0.95). It cleared costs and was still not distinguishable from luck. |
| 3 | **Trend overlay** (Faber 10-month SMA) | **FAILED**, but closest. Cut blended max drawdown 30.9% → 20.4% and raised blended Sharpe 0.91 → 1.01. SPY's sleeve lost to its own benchmark on the data (0.80 vs 0.88), and both sleeves missed the DSR (SPY 0.815, QQQ **0.947** vs 0.95). |

**The benchmark beat everything.** Over the same 2016–2025 sample, 50/50
buy-and-hold returned **+394.5% at Sharpe 0.91**; the best thing built here
returned less at comparable or worse risk-adjusted return.

Two findings worth carrying forward:

- **Cost is the binding constraint at short holding periods.** Round-trip cost
  is roughly fixed in bps, so it was ~400% of gross edge intraday and ~17% at a
  multi-day horizon. Hypothesis #1 did not die of a bad signal; it died of
  arithmetic.
- **Clearing costs is not the same as having an edge.** #2 cleared costs by
  5.83x and still failed, because a Sharpe near 0.4 over ten years cannot be
  told apart from luck once you correct for the number of things you tried.

**Unresolved, deliberately.** Hypothesis #3's QQQ sleeve scores DSR 0.947 at
N=9 but 0.960 at N=7 — the verdict turned on whether re-measuring identical
parameters after a bug fix counts as a trial. It was left failing rather than
resolved toward the passing answer while the answer was visible. See
`CLAUDE.md`. SPY fails on the data at any N.

Total capital risked: **$0**. That is the process working, not failing.

## What's implemented

- **Intraday strategies** (evidence-ranked, parameters frozen where the source
  papers froze them) — *currently failing the gate; see above*:
  - `noise_bands` — intraday momentum per Zarattini/Aziz/Barbon
    (SSRN 4824172): gap-aware bands, entries only at :00/:30 ET, continuous
    trailing exit at max(band, session VWAP). Published on SPY; also run on
    QQQ as an honest transfer of the mechanic.
  - `orb` — 5-minute opening range breakout with non-fitted filters (doji,
    ATR-relative range width, volume surge, EMA gate), one trade/day, 2R
    target, 15:45 ET time stop. Day-of-week filters deliberately forbidden.
- **Swing strategies** (daily bars, multi-day holds, long-only above the
  200-day SMA, disabled by default — enable via `config/swing.yaml`):
  - `rsi2` — Connors RSI(2) < 10 entry; exit on RSI(2) > 65 or close > 5-day
    SMA. Heavily published and heavily arbitraged: expect decay.
  - `ibs` — Internal Bar Strength < 0.2 entry, exit > 0.8. A less-crowded read
    on the same short-reversal effect; correlated with `rsi2`, not independent.
  - Overnight holds are supported end-to-end: swing positions are exempt from
    the forced flatten before the close, and their protective stops are GTC.
    A risk halt still flattens everything, swing included.
- **Backtesting**: same strategy/risk/journal code as live; deterministic;
  pessimistic fills (next-bar open + slippage + spread haircut, no same-bar
  fills); stop gap-through modeled.
- **Validation**: parameter sweeps log every trial to a cumulative
  `trials/trials.jsonl` (tracked in git — it is the one project artifact that
  cannot be regenerated); the winner is scored with the **Deflated Sharpe Ratio**
  against the project-lifetime trial count; walk-forward fit/test; **2026+
  data is a locked holdout** the sweep physically refuses to read.
- **Live paper loop**: Alpaca IEX stream (reconnect + gap backfill), warmup
  replay, marketable-limit entries, broker-side protective stops, equity-poll
  daily-loss halt (latched, persisted, restart-proof), kill-switch file,
  forced flatten before close.
- **Dead-man's switch**: independent watchdog process flattens everything if
  the bot's heartbeat goes stale during market hours.
- **Journal**: append-only SQLite event log; daily/weekly reports and the
  go/no-go scorecard render from it.

## Quickstart

```bash
# 1. install (Python 3.11+, uv)
make install

# 2. keys: create a free Alpaca account, generate PAPER API keys
cp .env.example .env   # fill in the two keys; keep ALPACA_PAPER=true

# 3. IMPORTANT: reset the paper account to ~$2,000 in the Alpaca dashboard.
#    The bot refuses to start if broker equity is far from configured capital —
#    results on the default $100k paper account would be meaningless.

# 4. sanity: run the test suite, then the opt-in smoke tests
make test
MERCURIUS_SMOKE=1 uv run pytest -q -m smoke

# 5. data + first backtest
uv run python -m mercurius download-data --symbols SPY,QQQ --start 2024-01-01 --end 2025-12-31
uv run python -m mercurius backtest

# 6. feed reality check (numbers recorded below under "Feed reality check"):
uv run python -m mercurius feed-diagnostic --symbol SPY --start 2026-07-27 --end 2026-07-31

# 7. paper trading (two processes):
uv run python -m mercurius run        # the bot
uv run python -m mercurius watchdog   # the dead-man's switch, separate terminal
```

Ops notes: run on a machine that stays up during US market hours
(15:30–22:00 Swiss time; **14:30–21:00 during the two DST-divergence windows**
in mid-March and late October/early November — the bot handles this itself,
your expectations should too). A ~$5/mo VPS in us-east beats a home machine.
Keep the host clock NTP-synced.

## Feed reality check (measured 2026-08-08, week of 2026-07-27..07-31)

The bot trades the free **IEX** tape — one venue, a few percent of consolidated
volume — because that is what the free plan streams live. Backtesting the same
tape is deliberate. This is what it costs, measured against SIP:

| | SPY | QQQ |
|---|---|---|
| SIP regular-hours minutes | 1950 | 1950 |
| IEX regular-hours minutes | 1950 | 1941 |
| minutes missing from IEX | 0 (0.00%) | 9 (0.46%) |
| close divergence, median | 0.27 bps | 0.74 bps |
| close divergence, p95 | 1.49 bps | 4.41 bps |
| close divergence, max | 4.63 bps | 11.09 bps |
| IEX share of consolidated volume | 3.43% | 1.45% |

Read this honestly: **QQQ's p95 divergence (4.41 bps) is larger than the
modeled round-trip cost (1.5 slippage + 1.0 spread = 2.5 bps).** For QQQ the
price the backtest fills at is routinely wrong by more than the cost the
backtest charges. Missing minutes are minutes the live bot is simply blind
during, and they cluster in quiet periods where IEX prints nothing.

Over the full 2024–2025 cache the coverage gap is much larger than one calm
week suggests: SPY 189,285 and QQQ 176,519 usable session minutes against
~195,000 possible — QQQ is missing roughly 9% of all session minutes.

## The gates (pre-registered — do not renegotiate after seeing results)

1. **M2 gate**: a strategy ships to paper only if holdout expectancy is
   positive after modeled costs AND the DSR survives the cumulative trial
   count. This gate can fail. That is the point.
2. **Go/no-go scorecard** (`mercurius report --period weekly`): ≥150 trades,
   ≥40 sessions, profit factor ≥1.2, positive expectancy without the top 5% of
   trades, bootstrap 5th-percentile mean > 0, max DD <15%, slippage ≤1.5×
   modeled, all sessions ended cleanly, plus manual benchmarks (buy-and-hold
   SPY, random-entry control). Passing = permission to *discuss* going live
   with $2,000. (Amended before any live results existed: originally 60
   sessions; compressed to 40 together with running both strategies on both
   symbols, which doubles the trade rate — the 150-trade statistical core is
   unchanged. Expect ~6–8 weeks.)
2b. **Live pilot (optional, after ~1 clean month)**: once ≥20 paper sessions
   completed with zero incidents and positive net PnL, a **$200–300** live
   tranche via `config/pilot.yaml` is permitted — its purpose is measuring
   real fills/slippage vs the paper simulator, not making money. Paper
   continues in parallel at full config. The $2,000 deployment still requires
   the complete scorecard. Never skip ahead of this ladder on the strength of
   a good week.
3. **Options are v2**, gated on: real-time OPRA data (Alpaca Algo Trader Plus,
   $99/mo — the free options feed is indicative/delayed and cannot be traded
   on), a quote-freshness spike, capital where one contract ≤10% of the
   account, and an underlying edge ≥2× the option round-trip cost. Chain
   snapshots are recorded daily from day one (`mercurius snapshot-chains`) so
   months of spread/decay data exist before that decision.

## Weekly AI analyst (never activated)

`analyst/` contains the prompt and setup for a **read-only** weekly Claude
review of the journal: live-vs-backtest divergence, risk events, regime flags,
recommendations. It never edits parameters — daily automated re-tuning is
rejected by design (uncounted selection bias, destroys the out-of-sample
record, chases the regime that just ended). Re-optimization is quarterly, via
walk-forward, with the cumulative trial log.

Never scheduled: it reviews a live journal, and there was never a live session
to review.

## If you resurrect any of this

The infrastructure is sound and reusable — append-only journal, latched
risk halt, dead-man's-switch watchdog, deterministic backtest engine,
Alpaca adapters (smoke-tested against the real paper API), parquet bar cache
with holdout separation. What failed was strategy search, not plumbing.

Non-negotiables if you continue, all learned the hard way here:

1. **Pre-register the decision rule before the run.** Every verdict in
   `docs/backtests.md` is trustworthy only because its pass/fail condition was
   committed to git before the number existed.
2. **`trials/trials.jsonl` is cumulative and permanent.** N=9 at archive time.
   A DSR computed against a reset counter is a lie you tell yourself.
3. **Benchmark against buy-and-hold, early.** This project ran three
   hypotheses before measuring the thing that beat all of them. That should
   have been step one.
4. **Two strategies on one symbol share a broker position.** The simulator nets
   per symbol because real brokers do; portfolio-mode per-strategy attribution
   is only meaningful because entries that would merge are now refused and
   counted. Evaluate strategies in isolation.

## Go-live checklist — NOT REACHED, and now moot

Retained for the record. No item below was actioned: the gates above were never
passed, so the ladder was never climbed. If any part of this repo is ever
resurrected, this list starts again from the top *after* a strategy passes.

- [ ] Confirm Switzerland is on Alpaca's supported-country list
      (alpaca.markets/support/countries-alpaca-is-available) or email
      support@alpaca.markets; fallback broker: Interactive Brokers (the
      `Broker` protocol isolates the port to one adapter).
- [ ] Confirm the broker's post-PDT-elimination margin rollout status.
- [ ] Fund via Rapyd (a wire from a Swiss bank costs $25–50 ≈ 2.5% of capital).
- [ ] W-8BEN (routine; 15% US-CH treaty rate on dividends).
- [ ] **Swiss tax**: an intraday bot breaches the Kreisschreiben 36
      private-investor safe harbors (≥6-month holding, turnover ≤5× portfolio,
      derivatives only for hedging, no leverage financing). That creates a
      real risk of "gewerbsmässiger Wertschriftenhändler" classification —
      trading gains taxed as income + AHV. Talk to a Swiss tax advisor before
      scaling. The journal doubles as your record-keeping.

## Disclaimer

This is experimental software for personal use. Nothing here is financial
advice. Paper results do not predict live results; simulated fills are
optimistic by nature. You can lose everything you put at risk.
