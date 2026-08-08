# Weekly AI analyst — setup

The analyst is a scheduled, read-only Claude (Opus) session that reviews the
trade journal weekly and writes a report. It never edits code or parameters —
see PROMPT.md for its full instructions and the reasoning (daily automated
re-tuning is an overfitting machine; monitoring is not).

## Option A: Claude Code Routine (recommended)
In a Claude Code session in this repo, ask:
  "Create a weekly Routine, Saturdays 08:00 UTC, that runs the instructions in
   analyst/PROMPT.md against this repo and sends me the report."

## Option B: cron + Claude Code CLI
```cron
0 8 * * 6  cd /path/to/mercurius-quant-bot && claude -p "$(cat analyst/PROMPT.md)" > data/analyst_$(date +\%F).md
```

## Quarterly (human-triggered, not scheduled)
Re-validation via walk-forward with cumulative trial counting:
- `mercurius.backtest.sweep.walk_forward(...)` — see module docstring.
- The trial log (`trials/trials.jsonl`) must never be deleted: the Deflated
  Sharpe Ratio is only honest if N includes every trial ever run. It is tracked
  in git for exactly that reason — see `trials/README.md`.
