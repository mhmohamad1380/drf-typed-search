# drf-typed-search

**A type-aware, matcher-routed search backend for Django REST Framework.**

Instead of blindly searching *every* configured field with `LIKE`, `dynamic_search`
inspects the **shape** of the incoming query and routes it to the single, correct,
index-friendly field. A 10-digit code hits an indexed `exact` lookup; a phone
number goes to `phone_number`; an integer goes to the primary key; free-text falls
back to a DRF-style multi-field search.

```python
from dynamic_search import DynamicSearchBackend

class UserViewSet(ModelViewSet):
    filter_backends = [DynamicSearchBackend]

    search_fields_config = [
        {"field": "national_code", "join": "user"},
        {"field": "phone_number", "join": "user"},
        {"field": "id"},
        {"field": "full_name", "join": "user", "lookup": "icontains"},
    ]
```

## Why?

<div class="grid cards" markdown>

- :material-target: **Precise routing**

    One indexed lookup per request instead of a 30-column `ILIKE` scan.

- :material-cog: **Zero business logic**

    All regexes/matchers live in *your* settings. The package ships none.

- :material-puzzle: **Extensible by config**

    Add matchers, annotations, and custom SQL without touching package source
    (Open/Closed Principle, Strategy pattern).

- :material-lightning-bolt: **Fast**

    Compiled regexes, cached settings & matchers, precompiled routing plans,
    minimal SQL.

</div>

## Quick links

- [Installation](installation.md)
- [Configuration](configuration.md)
- [Usage](usage.md)
- [API reference](api.md)
- [Benchmarks](BENCHMARKS.md)

- [Comparison with DRF `SearchFilter`](comparison.md)

## Install

```bash
pip install drf-typed-search
```

Requirements: Python ≥ 3.9, Django ≥ 3.2, DRF ≥ 3.12.
