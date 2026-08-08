"""Command-line entrypoint: `python -m mercurius <command>`."""

from __future__ import annotations

import argparse
import logging
import sys

from mercurius.core.logging import setup_logging

log = logging.getLogger(__name__)


def _add_config_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--config",
        action="append",
        default=None,
        help="YAML config path (repeatable; later files override earlier). "
        "Defaults to config/default.yaml",
    )


def _load(args: argparse.Namespace):
    from mercurius.config import load_config

    paths = args.config or ["config/default.yaml"]
    if "config/default.yaml" not in paths:
        paths = ["config/default.yaml", *paths]
    return load_config(*paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mercurius", description="Mercurius day-trading bot")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_ in [
        ("run", "run the live paper-trading loop"),
        ("backtest", "run a backtest"),
        ("download-data", "download and cache historical bars"),
        ("feed-diagnostic", "compare IEX vs SIP bars and report divergence"),
        ("snapshot-chains", "record today's option chain snapshot"),
        ("report", "generate daily/weekly report + go/no-go scorecard"),
        ("reconcile", "reconcile journal state against broker"),
        ("kill", "raise the kill switch (flatten + halt)"),
        ("watchdog", "run the dead-man's-switch watchdog process"),
    ]:
        p = sub.add_parser(name, help=help_)
        _add_config_arg(p)
        if name == "download-data":
            p.add_argument("--symbols", default=None, help="comma-separated, default from config")
            p.add_argument("--start", default=None)
            p.add_argument("--end", default=None)
            p.add_argument(
                "--timeframe",
                choices=["minute", "daily"],
                default="minute",
                help="minute bars for intraday strategies, daily for swing",
            )
        if name == "backtest":
            p.add_argument("--strategy", default=None, help="single strategy id (default: all)")
        if name == "feed-diagnostic":
            p.add_argument("--symbol", default="SPY")
            p.add_argument("--start", required=True, help="YYYY-MM-DD")
            p.add_argument("--end", required=True, help="YYYY-MM-DD")
        if name == "report":
            p.add_argument("--period", choices=["daily", "weekly"], default="daily")

    args = parser.parse_args(argv)
    setup_logging()
    cfg = _load(args)

    if args.command == "run":
        from mercurius.live.runner import run_live

        return run_live(cfg)
    if args.command == "backtest":
        from mercurius.backtest.engine import run_backtest_cli

        return run_backtest_cli(cfg, strategy=args.strategy)
    if args.command == "download-data":
        symbols = args.symbols.split(",") if args.symbols else cfg.symbols
        if args.timeframe == "daily":
            from mercurius.data.daily_bars import download_daily_cli

            return download_daily_cli(cfg, symbols, args.start, args.end)
        from mercurius.data.alpaca_hist import download_cli

        return download_cli(cfg, symbols, args.start, args.end)
    if args.command == "feed-diagnostic":
        from mercurius.data.alpaca_hist import feed_diagnostic_cli

        return feed_diagnostic_cli(cfg, args.symbol, args.start, args.end)
    if args.command == "snapshot-chains":
        from mercurius.data.chain_snapshots import snapshot_cli

        return snapshot_cli(cfg)
    if args.command == "report":
        from mercurius.journal.report import report_cli

        return report_cli(cfg, args.period)
    if args.command == "reconcile":
        from mercurius.execution.reconcile import reconcile_cli

        return reconcile_cli(cfg)
    if args.command == "kill":
        cfg.risk.kill_switch_file.parent.mkdir(parents=True, exist_ok=True)
        cfg.risk.kill_switch_file.touch()
        log.warning("kill switch raised at %s", cfg.risk.kill_switch_file)
        return 0
    if args.command == "watchdog":
        from mercurius.watchdog.deadman import watchdog_cli

        return watchdog_cli(cfg)
    return 2


if __name__ == "__main__":
    sys.exit(main())
