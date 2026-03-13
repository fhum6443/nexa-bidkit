.PHONY: test lint typecheck ci

test:
	poetry run pytest --cov=nexa_bidkit --cov-report=term-missing --cov-fail-under=80

lint:
	poetry run ruff check src

typecheck:
	poetry run mypy src

ci: lint typecheck test
