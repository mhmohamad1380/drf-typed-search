# Configuration

Matchers are declared **globally** in Django settings under the
`DYNAMIC_SEARCH` key. Each matcher is either a **regex** (string or compiled
pattern) or a **callable** `(str) -> bool`, plus the `lookup` to apply when it
wins routing.

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
    "DEFAULT_TEXT_LOOKUP": "icontains",   # free-text fallback lookup
    "SEARCH_PARAM": "search",             # ?search=...
    "EMPTY_ON_NO_MATCH": True,            # return none() when nothing matches
}
```

!!! note "fullmatch semantics"
    Regexes are matched with **`fullmatch`** — the *whole* value must match, so a
    matcher never fires on a substring.

## Global settings reference

| Key | Type | Default | Description |
|---|---|---|---|
| `MATCHERS` | `dict[str, spec]` | `{}` | Name → matcher spec (see below). |
| `DEFAULT_TEXT_LOOKUP` | `str` | `"icontains"` | Lookup used for the free-text fallback. |
| `SEARCH_PARAM` | `str` | `"search"` | Query parameter read from the request. |
| `EMPTY_ON_NO_MATCH` | `bool` | `True` | Return `none()` when nothing matches and there are no text fields. |

## Matcher spec keys

| Key | Type | Description |
|---|---|---|
| `pattern` | `str` \| `re.Pattern` \| `(str) -> bool` | The regex or predicate. |
| `lookup` | `str` | ORM lookup applied when this matcher wins. Default `"exact"`. |
| `priority` | `int` | Higher wins when several matchers could match. Default `0`. |
| `min_len` / `max_len` | `int` | O(1) length pre-filter (regex matchers only). |
| `prefix` | `str` | O(1) prefix pre-filter (regex matchers only). |

A bare spec is also allowed — the value *is* the pattern and `lookup` defaults
to `exact`:

```python
"MATCHERS": {"id": r"^\d+$"}          # same as {"pattern": r"^\d+$", "lookup": "exact"}
```

## Resolving ambiguous matches with `priority`

When two matchers can both match the same input (e.g. an integer valid for both
`id` and a numeric `national_code`), give the one that should win a higher
`priority`. Routing tries matchers in **descending priority**; ties fall back to
declaration order in `search_fields_config`.

```python
DYNAMIC_SEARCH = {
    "MATCHERS": {
        "id":            {"pattern": lambda v: v.isdigit(), "lookup": "exact", "priority": 0},
        "national_code": {"pattern": r"^\d{10}$",           "lookup": "exact", "priority": 100},
    }
}
```

Ordering is resolved **once** when the engine is built — priority adds zero
runtime cost.

## Cheap pre-filters

For very large matcher sets, add O(1) pre-filters so a matcher rejects an
obviously-wrong value (by length or prefix) *before* the regex runs:

```python
"national_code": {
    "pattern": r"^\d{10}$", "lookup": "exact",
    "min_len": 10, "max_len": 10,
},
"phone_number": {
    "pattern": r"^09\d{9}$", "lookup": "exact",
    "prefix": "09", "min_len": 11, "max_len": 11,
},
```

These are pure optimisations — a value that passes them still must satisfy the
regex, so results never change.

## Startup validation

Configuration is validated eagerly by a Django system check
(`dynamic_search.E001`) when the app is in `INSTALLED_APPS`. Clear errors are
raised for invalid regexes, invalid lookups, duplicate matchers, and malformed
specs. Run it explicitly with:

```bash
python manage.py check
```
