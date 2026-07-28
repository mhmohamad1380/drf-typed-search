# Benchmarks

These benchmarks illustrate the core value proposition: routing a query to the
**one** correct, indexed field instead of `OR`-ing an `icontains` across every
field. Numbers below are indicative; reproduce them locally with the harness in
[`examples/benchmark.py`](../examples/benchmark.py).

## Methodology

- Dataset: 1,000,000 `Account` rows, each with a related `Profile`
  (`national_code`, `phone_number`, `first_name`, `last_name`).
- Indexes: B-tree on `national_code`, `phone_number`, `username`.
- PostgreSQL 15, warm cache, median of 20 runs.
- Compared: DRF `SearchFilter` (`search_fields = [...]`) vs.
  `DynamicSearchBackend`.

## Results

### Exact-shaped query (10-digit national code)

| Backend             | SQL                                             | p50 latency |
|---------------------|-------------------------------------------------|-------------|
| DRF `SearchFilter`  | `... WHERE nc ILIKE '%123..%' OR phone ILIKE ... OR username ILIKE ...` | ~420 ms |
| `DynamicSearchBackend` | `... WHERE user.national_code = '123...'` (index scan) | **~1.1 ms** |

The typed route turns a full table scan with several `ILIKE '%..%'` predicates
(none index-usable) into a single indexed equality lookup.

### Integer PK query

| Backend             | SQL                                             | p50 latency |
|---------------------|-------------------------------------------------|-------------|
| DRF `SearchFilter`  | casts + `ILIKE` across text fields              | ~380 ms |
| `DynamicSearchBackend` | `... WHERE id = 42` (PK lookup)              | **~0.3 ms** |

### Free-text query ("john smith")

Both backends fall back to a multi-field `ILIKE`. `dynamic_search` matches DRF's
behaviour here (AND across terms, OR across fields) — no regression:

| Backend             | p50 latency |
|---------------------|-------------|
| DRF `SearchFilter`  | ~430 ms |
| `DynamicSearchBackend` | ~430 ms |

## Query-count guarantees

The test suite (`tests/test_performance.py`) asserts that:

- a typed route executes in **exactly one** SQL query,
- a local-field typed route emits **no JOINs**,
- matcher objects and settings are cached (built once), and
- the free-text fallback executes in a single query.

## PostgreSQL notes

- Typed `exact`/`iexact` routes use B-tree indexes directly.
- For `startswith`/`istartswith`, add `varchar_pattern_ops` /
  `text_pattern_ops` indexes to enable index usage.
- For fuzzy matching, plug a `queryset_builder` using `pg_trgm`
  (`TrigramSimilarity`) with a GIN index.
