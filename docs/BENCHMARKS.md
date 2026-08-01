# Benchmarks

These benchmarks cover two distinct questions:

1. **Database efficiency** (§ *Database results*) — the core value proposition:
   routing a query to the **one** correct, indexed field instead of `OR`-ing an
   `icontains` across every field.
2. **Python-side overhead** (§ *Python-side optimization: before / after*) — the
   internal engine refactor in v1.1.0, measured with the reproducible harness in
   [`benchmarks/bench_engine.py`](https://github.com/mhmohamad1380/drf-typed-search/blob/main/benchmarks/bench_engine.py).


---

## Python-side optimization: before / after

Run it yourself (SQLite in-memory, no DB rows evaluated — this isolates *Python*
cost, not query execution):

```bash
DJANGO_SETTINGS_MODULE=tests.settings PYTHONPATH=src:. python benchmarks/bench_engine.py
```

**Methodology.** 20,000 iterations per case after a 1,000-iteration warm-up;
median (p50) reported in microseconds; identical fields, matchers, settings and
query strings for every variant on the same machine/Python/Django. The queryset
is built lazily and never evaluated, so no database time is included.

### What changed in v1.1.0

The engine now precomputes its typed and free-text **routing plans once** (in
`__init__`) instead of per request: matcher resolution, priority ordering,
text-lookup resolution, and ORM-path (`str.join`) construction are all lifted
out of the hot path. Crucially, the **backend now caches the fully-built engine
per view** — previously a new `SearchEngine` was constructed on every request.

### Result — real user-facing path (backend rebuilt engine before, caches now)

Measured on the reference machine (your absolute numbers will differ; the
*ratio* is the point):

| Benchmark            | Previous (µs) | New (µs) | Improvement |
| -------------------- | ------------: | -------: | ----------: |
| Typed national code  |         82.03 |    75.18 |      ~8.4 % |
| Typed phone          |         81.53 |    75.03 |      ~8.0 % |
| Typed ID             |         74.29 |    68.15 |      ~8.3 % |
| Free-text single     |        121.90 |   113.84 |      ~6.6 % |
| Multi-term search    |        212.43 |   204.42 |      ~3.8 % |
| No-match search      |        120.74 |   111.90 |      ~7.3 % |

`SearchEngine` build cost is ~4 µs and is now paid **once** (cached), where it
was previously paid on **every** request.

### Honest caveat — routing precompute in isolation

When the engine is reused on *both* sides (so only the plan-precompute differs),
the improvement is within measurement noise (±5 %):

| Benchmark            | Previous (µs) | New (µs) | Improvement |
| -------------------- | ------------: | -------: | ----------: |
| Typed national code  |         69.41 |    71.09 |      ~noise |
| Multi-term search    |        218.15 |   212.36 |      ~2.7 % |

This is expected and worth stating plainly: **per-request time is dominated by
Django's `QuerySet.filter()` / `Q` construction (~60–210 µs), not by our
routing.** The measurable win comes from *not rebuilding the engine per
request* (the caching), plus deterministic priority ordering and lower
allocations (`__slots__`, tuple plans). The routing itself was already
microsecond-cheap and remains so.

---

## Database results

Numbers in this section are **indicative** and were **not executed in the
current CI environment** (no PostgreSQL with a million-row fixture available
here). Reproduce them locally against your own PostgreSQL using the setup in
*Methodology* below.


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
