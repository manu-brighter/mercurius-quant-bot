# Cumulative trial log

`trials.jsonl` records **every parameter combination ever evaluated** by
`backtest/sweep.py`, across the entire life of this project. One JSON object
per line, appended, never rewritten.

## Why this is tracked in git

The Deflated Sharpe Ratio corrects a strategy's observed Sharpe for
multiple testing. Its correction depends on *N*, the total number of trials
ever run — not the number in the current sweep. If N is understated, the DSR
is too generous and a lucky sweep winner looks real.

So this file has a property nothing else in the project has: **it cannot be
regenerated.** The bar cache re-downloads, the journal rebuilds, chain
snapshots resume. A lost trial log is lost permanently, and the loss is
silent — the next sweep simply starts counting from zero and reports a
flattering DSR that nobody can tell is wrong.

It lived under `data/` originally, which is gitignored as runtime state. That
put the one irreplaceable file in the project inside the one directory that is
safe to delete. It now lives here, in version control, where the git history
is itself a tamper-evident record of the trial count over time.

## Rules

- **Never delete or truncate it.** Not to "start clean", not to fix a bad run.
- **Never rewrite past entries.** Append only.
- Commit it after any sweep, so the count survives this machine.
- A trial that was run and then discarded still counts. That is the point —
  discarding bad trials without counting them *is* the bias the DSR corrects.

`run_backtest` does not write here; only `run_sweep` and `walk_forward` do.
Plain backtests and diagnostics cost no trial budget.
