# Comparison with DRF `SearchFilter`

| | DRF `SearchFilter` | `dynamic_search` |
|---|---|---|
| Fields searched | **All** configured fields, every request | The **one** field the input shape matches |
| Lookup | `icontains` (or prefixed) for everything | Per-matcher (`exact` for IDs/codes, `icontains` for text) |
| Index usage | Poor (`%term%` can't use a B-tree) | Excellent for typed routes (`exact`, `startswith`) |
| Extensibility | Per-view `search_fields` | Global matchers + per-view config (Strategy pattern) |
| Custom SQL | No | Yes (`queryset_builder`) |
| Annotations | Manual in `get_queryset` | Declarative `annotate` |
| Ambiguity control | — | `priority` |

## The core difference

DRF `SearchFilter` builds one big OR of `ILIKE '%term%'` across **every** field:

```sql
WHERE col1 ILIKE '%term%' OR col2 ILIKE '%term%' OR … OR col30 ILIKE '%term%'
```

A leading-wildcard `ILIKE` **cannot use a B-tree index**, so this is a
sequential scan touching every column — costly and it worsens with more fields.

`dynamic_search` inspects the *shape* of the input and, when it matches, emits a
single indexed predicate:

```sql
WHERE user.national_code = '1234567890'   -- index seek, sub-millisecond
```

Only genuine free-text falls back to a multi-field `LIKE` (same cost class as
DRF, but narrowed to just the text fields you mark).

## When to prefer which

**Use `dynamic_search`** when your search box receives structured identifiers —
IDs, national codes, phone numbers, UUIDs, IBANs — mixed with occasional
free-text. This is the common "one box searches everything" admin/CRM case.

**Plain `SearchFilter` is fine** when you *only* ever do fuzzy text matching over
a handful of columns and indexing isn't a concern.

See [Benchmarks](BENCHMARKS.md) for numbers.

