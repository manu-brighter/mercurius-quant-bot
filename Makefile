.PHONY: install lint test smoke backtest run-paper

install:
	uv sync --extra dev

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

fmt:
	uv run ruff format src tests
	uv run ruff check --fix src tests

test:
	uv run pytest -q

smoke:
	MERCURIUS_SMOKE=1 uv run pytest -q -m smoke

backtest:
	uv run python -m mercurius backtest --config config/backtest.yaml

run-paper:
	uv run python -m mercurius run --config config/default.yaml
