# Matchers

A **matcher** decides whether a raw search string "looks like" a certain kind of
value — a national code, a UUID, an integer, and so on. Matchers implement the
[Strategy pattern](https://refactoring.guru/design-patterns/strategy): the
engine depends only on the `Matcher` protocol, so you can add new strategies
**without modifying package source** (Open/Closed Principle).

Two concrete strategies ship with the library:

- **`RegexMatcher`** — matches against a compiled, anchored regex (`fullmatch`).
- **`CallableMatcher`** — delegates to a user-supplied predicate `(str) -> bool`.

Both are immutable and stateless once built, so they are cached and shared
safely across threads.

## Regex matchers

```python
DYNAMIC_SEARCH = {
    "MATCHERS": {
        "national_code": {"pattern": r"^\d{10}$", "lookup": "exact"},
        "iban":          {"pattern": r"^[A-Z]{2}\d{2}[A-Z0-9]{1,30}$", "lookup": "iexact"},
    }
}
```

You may pass a **compiled** pattern too, which is convenient for reuse and flags:

```python
import re
UUID_REGEX = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-...", re.IGNORECASE)

"uuid": {"pattern": UUID_REGEX, "lookup": "exact"}
```

## Callable matchers

Anything callable that returns a bool works — great for logic that is awkward to
express as a regex:

```python
DYNAMIC_SEARCH = {
    "MATCHERS": {
        "id":       {"pattern": lambda v: v.isdigit(), "lookup": "exact"},
        "even_id":  {"pattern": lambda v: v.isdigit() and int(v) % 2 == 0, "lookup": "exact"},
    }
}
```

!!! tip "Exceptions are safe"
    If a callable matcher raises, the exception is swallowed and treated as a
    non-match, so one bad input can never break a whole request.

## Adding a new matcher

Because a matcher is *just* a regex or callable in your settings, adding one
**never** requires touching the package:

```python
DYNAMIC_SEARCH = {
    "MATCHERS": {
        "postal_code": {"pattern": r"^\d{5}(-\d{4})?$", "lookup": "exact"},
    }
}
```

Then reference it from a view (implicitly by field name, or explicitly):

```python
search_fields_config = [
    {"field": "zip", "matcher": "postal_code"},
]
```

## Priority & pre-filters

See [Configuration → priority](configuration.md#resolving-ambiguous-matches-with-priority)
and [Configuration → pre-filters](configuration.md#cheap-pre-filters) for
resolving overlapping matchers and shaving worst-case routing cost.

## Building matchers programmatically

For tests or advanced integrations you can build matcher objects directly:

```python
from dynamic_search import build_matcher, RegexMatcher, CallableMatcher

m = build_matcher("national_code", r"^\d{10}$", "exact", priority=100)
assert isinstance(m, RegexMatcher)
assert m.matches("1234567890")
```

See the [API reference](api.md#matchers) for full signatures.
