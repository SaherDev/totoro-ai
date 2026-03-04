.PHONY: dev test lint format typecheck

dev:
	. scripts/env-setup.sh && poetry run uvicorn totoro_ai.api.main:app --reload --port $${AI_PORT:-8000}

test:
	. scripts/env-setup.sh && poetry run pytest

lint:
	poetry run ruff check src/ tests/

format:
	poetry run ruff format src/ tests/

typecheck:
	poetry run mypy src/
