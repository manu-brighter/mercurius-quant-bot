<img src="https://capsule-render.vercel.app/api?type=waving&color=0:0b1f32,50:147d84,100:dfac55&height=190&section=header&text=Mercurius&fontSize=52&fontColor=f4f7f8&fontAlignY=35&desc=A%20quant%20research%20bot%20that%20knew%20when%20to%20stop&descSize=18&descAlignY=56&descColor=f4f7f8" width="100%" alt="Mercurius" />

<div align="center">

![Status](https://img.shields.io/badge/status-archived-dfac55?style=for-the-badge&labelColor=0b1f32)
![Research](https://img.shields.io/badge/3%20hypotheses-0%20passed-147d84?style=for-the-badge&labelColor=0b1f32)
![Capital](https://img.shields.io/badge/real%20capital%20risked-%240-3b9bb0?style=for-the-badge&labelColor=0b1f32)

**Backtest → validate → stop.** An Alpaca-based SPY/QQQ trading research project with a
deterministic backtester, paper-trading infrastructure, and a validation gate designed
to reject weak strategies.

[Results](#the-result) · [Inside the project](#inside-the-project) ·
[Reproduce](#reproduce-the-research) · [Research record](docs/backtests.md)

</div>

> [!IMPORTANT]
> **Archived on 2026-08-08. No trading edge was found.** All three pre-registered
> hypotheses failed. Nothing built here beat passive holding, the paper account
> stayed untouched, and no real money was deployed. This repository is a research
> record and reusable infrastructure, **not a trading system ready to switch on**.

## The result

| Hypothesis | What happened | Verdict |
|---|---|---|
| **1 · Intraday** — noise bands + opening-range breakout | A published-strategy fidelity audit improved trade frequency and gross edge, but net expectancy remained negative. | **Failed** |
| **2 · Swing** — RSI(2) + internal bar strength | Cleared modeled costs by 5.83×, but the best instance's Deflated Sharpe Ratio was 0.745 against a ~0.95 threshold. | **Failed** |
| **3 · Trend overlay** — Faber 10-month SMA | Improved blended drawdown and Sharpe; SPY lagged its benchmark and both sleeves missed the DSR gate. QQQ scored 0.947 against 0.95. | **Failed** |

The 2016–2025 50/50 SPY/QQQ buy-and-hold benchmark returned **+394.5% at Sharpe
0.91**. The swing book returned **+23.5% at Sharpe 0.24** over the same sample.
The [dated backtest record](docs/backtests.md) has the full methods, numbers, and
pre-registered decisions. The [trial log](trials/trials.jsonl) contains all nine
recorded evaluations.

<img src="https://capsule-render.vercel.app/api?type=rect&color=0:0b1f32,50:147d84,100:dfac55&height=3&section=header" width="100%" alt="" />

## Inside the project

| Layer | What it does |
|---|---|
| **Strategies** | Intraday noise bands and opening-range breakout; daily RSI(2) and IBS mean reversion. Published parameters are frozen, not tuning knobs. |
| **Backtest & validation** | Deterministic simulation with next-bar fills, slippage, spread haircut, stop gaps, walk-forward evaluation, a cumulative trial count, and Deflated Sharpe Ratio. The 2026 holdout is locked against sweeps. |
| **Execution & risk** | Alpaca paper adapter, IEX stream with reconnect and gap backfill, protective stops, position limits, a persistent daily-loss halt, kill switch, and an independent watchdog. |
| **Research record** | Append-only SQLite journal, reports and scorecard, dated decisions, and a tracked trial log that cannot be reset without invalidating the statistics. |

Intraday and swing strategies use different bar timeframes and must run in separate
backtests. The swing configuration lives in [`config/swing.yaml`](config/swing.yaml).

### Why the gate matters

This project treated a negative result as a successful decision: no edge means no
deployment. The three-hypothesis budget is spent. Continuing strategy search would
require a new written decision in [`docs/backtests.md`](docs/backtests.md), not a
quiet parameter change. The [project rules](CLAUDE.md) document the frozen parameters,
cost assumptions, holdout, and trial-count convention.

One result remains deliberately unresolved: QQQ's trend-overlay DSR would be 0.960
at N=7 instead of 0.947 at N=9. Two corrected-engine re-runs were counted as trials
before the result existed. The convention was not changed after seeing that it would
flip the verdict; SPY fails independently of trial count.

## Reproduce the research

Requires **Python 3.11+**, [`uv`](https://docs.astral.sh/uv/), and an Alpaca paper
account for historical bars. Market data, credentials, the local journal, and the
untouched 2026 holdout are not included in the repository.

```bash
git clone https://github.com/manu-brighter/mercurius-quant-bot.git
cd mercurius-quant-bot
uv sync --extra dev
uv run pytest -q

cp .env.example .env  # add Alpaca PAPER keys; keep MERCURIUS_ALPACA_PAPER=true
uv run python -m mercurius download-data --symbols SPY,QQQ --start 2023-01-01 --end 2025-12-31
uv run python -m mercurius backtest --config config/backtest.yaml
```

For the separate daily-bar swing book:

```bash
uv run python -m mercurius download-data --timeframe daily --symbols SPY,QQQ --start 2015-01-01 --end 2025-12-31
uv run python -m mercurius backtest --config config/swing.yaml
```

These commands reproduce a research workflow, **not a new gate result**. Every new
strategy evaluation must be counted in [`trials/trials.jsonl`](trials/trials.jsonl);
never delete or rotate that file. Do not load or probe 2026 holdout data.

### Data and cost reality

The free Alpaca live stream uses IEX rather than the consolidated US market feed.
In the measured week of 2026-07-27, QQQ's p95 IEX-vs-SIP close divergence was
**4.41 bps**, above the backtest's **2.5 bps** modeled round-trip cost. Across the
2024–2025 cache, QQQ lacked roughly **9%** of possible regular-session minutes.
These gaps matter when interpreting any result. The measurement below gives the
one-week comparison; the [backtest record](docs/backtests.md) discusses its impact.

<details>
<summary><b>IEX vs SIP measurement · 2026-07-27 to 2026-07-31</b></summary>

| | SPY | QQQ |
|---|---:|---:|
| SIP regular-hours minutes | 1,950 | 1,950 |
| IEX regular-hours minutes | 1,950 | 1,941 |
| Missing IEX minutes | 0 | 9 |
| Median close divergence | 0.27 bps | 0.74 bps |
| p95 close divergence | 1.49 bps | 4.41 bps |
| Maximum close divergence | 4.63 bps | 11.09 bps |
| IEX share of consolidated volume | 3.43% | 1.45% |

</details>

## Historical deployment gates — never reached

The M2 gate required positive holdout expectancy after costs and a DSR that survived
the cumulative trial count. No strategy passed it, so paper trading and the later
go/no-go scorecard were never reached. That scorecard required at least 150 trades,
40 clean sessions, profit factor ≥1.2, positive robust expectancy, max drawdown
under 15%, controlled slippage, and manual buy-and-hold and random-entry benchmarks.
Passing would only have allowed a discussion about live deployment. The optional
`config/pilot.yaml` and options plan remain historical designs, not approvals to trade.

<details>
<summary><b>Historical go-live checklist · no item completed</b></summary>

- [ ] Confirm broker availability and margin rules for Switzerland.
- [ ] Confirm funding path and submit W-8BEN where required.
- [ ] Get Swiss tax advice before any live deployment. Frequent automated trading
      may fail the private-investor criteria in [ESTV Kreisschreiben 36](https://www.estv.admin.ch/dam/estv/de/dokumente/dbst/kreisschreiben/dbst-ks-2012-1-036-d-de.pdf.download.pdf/dbst-ks-2012-1-036-d-de.pdf).
      Failing those criteria calls for a case-by-case assessment; classification
      as professional securities trading could make gains taxable as income.
- [ ] Revisit the complete scorecard and risk controls after a strategy passes a
      newly pre-registered fit-era gate. Only a human can spend the holdout once.

</details>

## Research notes

- **Cost versus signal:** intraday modeled costs were roughly four times the gross
  edge. Moving to a multi-day horizon cleared costs, but did not establish a
  statistically defensible edge.
- **Benchmark early:** passive holding beat all three hypotheses. The benchmark
  comparison should have happened earlier in this project.
- **Account-level returns:** idle capital counts. The gate uses the Sharpe Ratio of
  the entire account, not only days with a position open.
- **No optimization after failure:** weekday filters, lower cost assumptions, or
  parameter tweaks would turn a negative finding into an overfit backtest.

The historical [weekly analyst runbook](analyst/README.md) was never activated:
there was no live session to review. The project includes an optional pilot config
as part of its historical design, but its prerequisites were never met.

## Disclaimer

Experimental research software. Nothing here is financial advice. Simulated fills
and paper results do not predict live performance.

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:dfac55,50:147d84,100:0b1f32&height=100&section=footer" width="100%" alt="" />
