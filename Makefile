.PHONY: install lint format type test cov build check clean

install:
	pip install -e ".[dev]"

lint:
	ruff check .

format:
	black .

type:
	mypy

test:
	pytest

cov:
	pytest --cov=dynamic_search --cov-report=term-missing

build:
	python -m build
	twine check dist/*

check: lint type test

clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml
