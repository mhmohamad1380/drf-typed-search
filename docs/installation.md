# Installation

## Install from PyPI

```bash
pip install drf-typed-search
```

## Register the app

Adding the app to `INSTALLED_APPS` enables the startup system check that
validates your `DYNAMIC_SEARCH` configuration (invalid regexes, lookups,
duplicate matchers, …) before the first request.

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "dynamic_search",
]
```

## Requirements

| Dependency | Version |
|---|---|
| Python | ≥ 3.9 |
| Django | ≥ 3.2 |
| Django REST Framework | ≥ 3.12 |

## Optional extras

```bash
# PostgreSQL trigram / full-text helpers
pip install "drf-typed-search[postgres]"

# Development (tests, linters, type-checking, docs)
pip install "drf-typed-search[dev]"
```

## Verify

```python
>>> import dynamic_search
>>> dynamic_search.__version__
'1.1.0'
```
