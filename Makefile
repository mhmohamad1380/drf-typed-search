.PHONY: install lint format type test cov build check clean docs docs-serve docs-deploy

install:
	pip install -e ".[dev]"

docs:
	pip install -e ".[docs]"
	DJANGO_SETTINGS_MODULE=tests.settings PYTHONPATH=src mkdocs build --strict

docs-serve:
	pip install -e ".[docs]"
	DJANGO_SETTINGS_MODULE=tests.settings PYTHONPATH=src mkdocs serve

docs-deploy:
	pip install -e ".[docs]"
	DJANGO_SETTINGS_MODULE=tests.settings PYTHONPATH=src mkdocs gh-deploy --force



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
