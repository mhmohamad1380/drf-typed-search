# drf-typed-search

**A type-aware, matcher-routed search backend for Django REST Framework.**

Instead of blindly searching *every* configured field with `LIKE`, `dynamic_search`
inspects the **shape** of the incoming query and routes it to the single, correct,
index-friendly field. A 10-digit code hits an indexed `exact` lookup on
`national_code`; a phone number goes to `phone_number`; an integer goes to the
primary key; free-text falls back to a DRF-style multi-field search.

```python
class UserViewSet(ModelViewSet):
    filter_backends = [DynamicSearchBackend]

    search_fields_config = [
        {"field": "national_code", "join": "user"},
        {"field": "phone_number", "join": "user"},
        {"field": "id"},
        {"field": "full_name", "join": "user", "lookup": "icontains"},
    ]
```

- **Zero business logic in the package.** All regexes/matchers live in *your* settings.
- **Extensible by configuration**, not by modifying source (Open/Closed).
- **Strongly typed**, `py.typed`, MyPy-strict.
- **Fast**: compiled regexes, cached settings & matcher objects, minimal SQL, no needless queryset cloning.

---

## Installation

```bash
pip install drf-typed-search
```

Add the app so configuration is validated at startup:

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "dynamic_search",
]
```

Requirements: Python ≥ 3.9, Django ≥ 3.2, DRF ≥ 3.12.

---

## Configuration

Matchers are declared **globally** in settings. Each matcher is either a
**regex** (string or compiled pattern) or a **callable** `(str) -> bool`, plus
the `lookup` to use when it wins routing.

```python
import re

UUID_REGEX = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

DYNAMIC_SEARCH = {
    "MATCHERS": {
        "national_code": {"pattern": r"^\d{10}$", "lookup": "exact"},
        "phone_number":  {"pattern": r"^09\d{9}$", "lookup": "exact"},
        "uuid":          {"pattern": UUID_REGEX, "lookup": "exact"},
        "id":            {"pattern": lambda v: v.isdigit(), "lookup": "exact"},
    },
    "DEFAULT_TEXT_LOOKUP": "icontains",   # used for the free-text fallback
    "SEARCH_PARAM": "search",             # ?search=...
    "EMPTY_ON_NO_MATCH": True,            # return none() when nothing matches
}
```

> Regexes are matched with **`fullmatch`** semantics — the *whole* value must
> match, so a matcher never fires on a substring.

### Performance & the routing cost

Regexes are **compiled once at startup** and the whole matcher registry is
cached, so a request only runs `pattern.fullmatch()` calls — no per-request
compilation, no per-request settings parsing. In practice routing costs a few
**microseconds** (≈3 µs for 5 matchers, worst case), which is 100–700× cheaper
than the single DB query it saves. If a request feels slow, the time is almost
always in the SQL query, missing indexes, N+1 relations, or serialization —
not routing.

For very large matcher sets you can add **O(1) pre-filters** so a matcher
rejects an obviously-wrong value (by length or prefix) *before* the regex runs:

```python
DYNAMIC_SEARCH = {
    "MATCHERS": {
        "national_code": {
            "pattern": r"^\d{10}$", "lookup": "exact",
            "min_len": 10, "max_len": 10,          # skip regex unless len == 10
        },
        "phone_number": {
            "pattern": r"^09\d{9}$", "lookup": "exact",
            "prefix": "09", "min_len": 11, "max_len": 11,
        },
    }
}
```

These hints are pure optimisations — a value that passes them still must
satisfy the regex, so results never change. Also order your `search_fields_config`
so the most common input shapes come first (routing early-exits on first match).


### Resolving ambiguous matches with `priority`

When two matchers can both match the same input (e.g. an integer that is valid
for both `id` and a numeric `national_code`), give the one that should win a
higher `priority`. Routing tries matchers in **descending priority**, and ties
fall back to declaration order in `search_fields_config`. Default is `0`.

```python
DYNAMIC_SEARCH = {
    "MATCHERS": {
        "id":            {"pattern": lambda v: v.isdigit(), "lookup": "exact", "priority": 0},
        "national_code": {"pattern": r"^\d{10}$",           "lookup": "exact", "priority": 100},
    }
}
```

Here a 10-digit value routes to `national_code` even if `id` is declared first,
while shorter integers still fall through to `id`. Because ordering is resolved
**once** when the engine is built (not per request), priority adds zero runtime
cost.


### How a field is bound to a matcher


Each config entry is bound to a matcher named after its `field` by default.
So `{"field": "national_code", ...}` is routed by the `national_code` matcher
automatically. Override with `"matcher": "some_name"`, or disable typed routing
for a field with `"matcher": None` (it then only participates in free-text).

---

## The `search_fields_config` reference

| Key                | Type                              | Description |
|--------------------|-----------------------------------|-------------|
| `field`            | `str` (required)                  | Model field, related field, or annotation alias. |
| `join`             | `str`                             | Relation prefix, e.g. `"user"` or `"loan__user"`. |
| `lookup`           | `str`                             | Override lookup (routing or free-text). |
| `matcher`          | `str \| None`                     | Matcher name; defaults to `field`; `None` disables routing. |
| `annotate`         | `(qs, prefix) -> qs`              | Add a computed annotation before filtering. |
| `queryset_builder` | `(qs, value) -> qs`               | Fully custom filtering (trigram, full-text, …). |
| `text`             | `bool`                            | Force into the free-text fallback. |

### Supported lookups

`exact`, `iexact`, `contains`, `icontains`, `startswith`, `istartswith`,
`endswith`, `iendswith`.

---

## Search flow

1. Read the cached matcher registry.
2. For each declared field (in order), test its bound matcher against the whole value.
3. First match wins → build one precise, index-friendly filter.
4. Otherwise → DRF-style free-text search (**AND across terms, OR across fields**, quoted phrases supported).
5. If there are no text fields and nothing matched → `none()` (configurable).

The winning field name(s) are written to `view.search_field` for paginators/logging.

---

## Annotations

Use the generic `concat_annotation` helper (no business logic) for computed fields:

```python
from dynamic_search import concat_annotation

search_fields_config = [
    {
        "field": "full_name",
        "annotate": concat_annotation("full_name", ["first_name", "last_name"], join="user"),
        "lookup": "icontains",
        "matcher": None,
    },
]
```

---

## Custom matchers

A matcher is *just* a regex or a callable in your settings — **adding one never
requires touching the package**:

```python
DYNAMIC_SEARCH = {
    "MATCHERS": {
        "iban": {"pattern": r"^[A-Z]{2}\d{2}[A-Z0-9]{1,30}$", "lookup": "iexact"},
        "even_id": {"pattern": lambda v: v.isdigit() and int(v) % 2 == 0, "lookup": "exact"},
    }
}
```

For advanced needs (PostgreSQL trigram / full-text), use a `queryset_builder`:

```python
from django.contrib.postgres.search import TrigramSimilarity

def fuzzy_name(qs, value):
    return (
        qs.annotate(sim=TrigramSimilarity("user__full_name", value))
          .filter(sim__gt=0.3)
          .order_by("-sim")
    )

search_fields_config = [
    {"field": "full_name", "queryset_builder": fuzzy_name, "matcher": "name_like"},
]
```

---

## Comparison with DRF `SearchFilter`

| | DRF `SearchFilter` | `dynamic_search` |
|---|---|---|
| Fields searched | **All** configured fields, every request | The **one** field the input shape matches |
| Lookup | `icontains` (or prefixed) for everything | Per-matcher (`exact` for IDs/codes, `icontains` for text) |
| Index usage | Poor (`%term%` can't use B-tree) | Excellent for typed routes (`exact`, `startswith`) |
| Extensibility | Per-view `search_fields` | Global matchers + per-view config, Strategy pattern |
| Custom SQL | No | Yes (`queryset_builder`) |
| Annotations | Manual in `get_queryset` | Declarative `annotate` |

See [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md) for numbers.

---

## Limitations

- Typed routing tests the **whole** value; it does not tokenise mixed inputs.
- `queryset_builder` fields are typed-route only (excluded from the OR free-text chain).
- Trigram/full-text helpers require the relevant PostgreSQL extensions.

---

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check . && black --check . && mypy
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).
