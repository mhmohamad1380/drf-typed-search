# With vs without Elasticsearch

`drf-typed-search` always routes a search value the same way:

1. **Typed routing** (regex / callable matchers, or a field's own regex) → a
   precise, index-friendly **database** lookup. This branch is *identical*
   whether or not Elasticsearch is enabled — it never touches ES.
2. **Free-text fallback** → the only branch that changes. By default it runs an
   ORM `icontains` (`OR` across fields, `AND` across terms). Set
   `TEXT_BACKEND = "elasticsearch"` and it is served by Elasticsearch instead.

This page compares those two configurations of the **free-text branch** — what
changes, when to use each, and how they perform.

For setup and configuration details see the
[Elasticsearch backend guide](elasticsearch.md).

---

## At a glance

| Aspect | Without Elasticsearch (database) | With Elasticsearch |
| --- | --- | --- |
| Typed routing | Database, indexed lookup | **Same** — database, indexed lookup |
| Free-text matching | `ILIKE '%term%'` across fields | Analyzer + `multi_match` in ES |
| Typo tolerance | None | Yes (`fuzziness: AUTO`) |
| Relevance ranking | None (DB order) | Yes (ES score), preserved in the queryset |
| Cost model (free text) | Sequential scan, grows with table size | Bounded `pk IN (...)` fetch + ES query |
| Dependencies | None | `elasticsearch>=8.0,<9.0`, a running cluster |
| Data freshness | Always live (single source) | DB is source of truth; index synced via signals |
| Operational overhead | None | Cluster to run, indexes to build/keep in sync |
| Result shape | Real Django `QuerySet` | Real Django `QuerySet` (identical downstream) |

Key point: **both return a real Django `QuerySet`**, so DRF serializers,
pagination, permissions and `select_related`/`prefetch_related` behave the same
either way. Switching backends is a settings change, not an API change.

---

## How each free-text path works

### Without Elasticsearch (default)

The engine builds a single ORM query:

```sql
SELECT ... FROM account
WHERE (username ILIKE '%john%' OR email ILIKE '%john%')
  AND (username ILIKE '%smith%' OR email ILIKE '%smith%')
```

- One SQL statement regardless of term/field count.
- `%term%` (leading wildcard) means the database **cannot use a normal B-tree
  index** — it scans the table, so latency grows with row count.
- No typo tolerance and no relevance ordering.

### With Elasticsearch

The free-text value goes to Elasticsearch (`multi_match`, AND across terms, OR
across fields, `fuzziness: AUTO`); ES does the matching and ranking and returns
**only document ids** (`_source=False`). Those ids are the model primary keys,
so the provider re-selects the rows from the database and preserves ES relevance
order:

```sql
SELECT ... FROM account
WHERE id IN (42, 17, 88, ...)          -- bounded by RESULT_SIZE
ORDER BY CASE id WHEN 42 THEN 0 WHEN 17 THEN 1 ... END
```

- The **text matching** is done by ES out of band.
- The **database** only does an indexed primary-key fetch, whose cost is bounded
  by `RESULT_SIZE`, not the table size.
- You gain fuzzy matching and relevance ranking that SQL `LIKE` cannot provide.

> There are two round-trips (ES for ids, DB for rows), but they do different
> jobs — ES never re-runs in the DB, and the DB never runs a text scan.

---

## Real-world query times (live cluster)

This is the comparison most people want: **actual free-text query latency
without Elasticsearch vs with Elasticsearch**, measured end-to-end against a
**real, running Elasticsearch cluster**. Reproduce with
[`benchmarks/bench_elastic_realworld.py`](https://github.com/mhmohamad1380/drf-typed-search/blob/main/benchmarks/bench_elastic_realworld.py):

```bash
ES_HOST=http://localhost:9200 PYTHONPATH=src:. \
    python benchmarks/bench_elastic_realworld.py
```

**Methodology.** A disk-backed SQLite `Account` table is populated with
whitespace-separated full names (`"john smith 42"`) at growing sizes, and the
same rows are indexed into a real Elasticsearch cluster. Each configuration runs
the *same* `SearchEngine`, and every queryset is fully evaluated (`list()`), so
timings include query build, real DB/ES I/O (including network to the cluster),
row fetch and object construction. Median of 50–100 iterations after warm-up.

Two queries are run:

- **exact** — `"john smith"`, a phrase present verbatim (both backends match).
- **typo** — `"jonh smith"`, one character off (the LIKE backend cannot match).

### Result (Elasticsearch 9.x, file-backed SQLite — measured)

| rows | query | DB ms (no ES) | ES ms (with ES) | ES hits | DB hits |
| ---: | :--- | ---: | ---: | ---: | ---: |
| 1,000 | exact | 0.82 | 9.24 | 18 | 18 |
| 1,000 | typo | 0.65 | 7.58 | 18 | **0** |
| 10,000 | exact | 3.83 | 24.54 | 140 | 140 |
| 10,000 | typo | 2.26 | 24.58 | 140 | **0** |
| 50,000 | exact | 17.18 | 124.79 | 759 | 759 |
| 50,000 | typo | 10.69 | 128.53 | 759 | **0** |

**What this actually shows:**

- **Correctness parity on exact queries** — ES and DB return the identical row
  count (18 / 140 / 759), confirming the ES path maps hits back to the right
  rows.
- **Capability, not just speed** — on the *typo* query the database `ILIKE`
  returns **0 rows** at every size, while Elasticsearch still finds all 759
  (via `fuzziness: AUTO`). This is the difference `LIKE` can never close at any
  latency.
- **Latency on this setup** — against **in-process SQLite** the `LIKE` scan runs
  in optimised C and is very fast, so the DB path has *lower latency* here; the
  ES path pays a real network round-trip plus the `Case/When` relevance-ordering
  over the returned pks. The DB scan still climbs with row count (0.8 → 17 ms)
  while ES's *own* query stays modest — the SQLite `Case/When` re-ordering over
  hundreds of pks is what inflates the ES column at 50k rows.

**Why production flips this:** SQLite is a best case for `LIKE`. On PostgreSQL
with millions of rows an unindexed `ILIKE '%term%'` is a full sequential scan
measured in **hundreds of milliseconds to seconds** (see the million-row figures
in [Benchmarks](BENCHMARKS.md): a multi-field `ILIKE` is ~430 ms), whereas
Elasticsearch answers from an inverted index in a few milliseconds and the
follow-up `pk IN (...)` fetch is bounded by `RESULT_SIZE`. That is the regime
where ES wins on **both** capability and latency. Re-run the harness against your
own PostgreSQL to see the crossover on your data.

---

## DB-side cost breakdown (no cluster required)

To isolate *just the database work* each strategy generates — without a running
cluster and without network noise — use
[`benchmarks/bench_elastic_vs_db.py`](https://github.com/mhmohamad1380/drf-typed-search/blob/main/benchmarks/bench_elastic_vs_db.py):

```bash
DJANGO_SETTINGS_MODULE=tests.settings PYTHONPATH=src:. \
    python benchmarks/bench_elastic_vs_db.py
```


**Methodology.** A real (in-memory SQLite) `Account` table is populated at
growing sizes; a selective term matches 1 in every 200 rows. Elasticsearch is
replaced by an in-process fake that returns a bounded, relevance-ordered list of
primary keys — exactly what a real cluster returns with `_source=False` — so we
measure **the database work each strategy generates**, not a network round-trip.
Median of many iterations after warm-up.

Columns:

- **DB scan** — full database free-text path (`ILIKE '%term%'` over all rows).
- **ES total** — full ES-path DB cost: `pk IN (...)` + `Case/When` ordering.
- **ES fetch** — just the indexed `pk IN (...)` fetch, without ordering.

### Result (SQLite, in-memory — indicative)

| rows | matches | DB scan (ms) | ES total (ms) | ES fetch (ms) |
| ---: | ---: | ---: | ---: | ---: |
| 100 | 1 | 0.38 | 0.69 | 0.28 |
| 1,000 | 5 | 0.57 | 1.42 | 0.32 |
| 10,000 | 50 | 2.86 | 8.32 | 0.88 |
| 50,000 | 250 | 12.84 | 41.81 | 3.08 |

**Reading it honestly:**

- The raw **ES fetch** (indexed pk lookup) stays cheap and grows slowly — it is
  bounded by `RESULT_SIZE`, not by table size. This is the structural advantage.
- On **in-memory SQLite** the `LIKE` scan runs in optimised C over a tiny table,
  so it is extremely fast; the `Case/When` relevance ordering the ES path adds
  actually dominates here, which is why *"ES total"* looks slower. Treat SQLite
  as a **lower bound** for the DB scan, not as production.
- On **PostgreSQL** an unindexed `ILIKE '%term%'` is a genuine sequential scan
  whose cost rises steeply with row count (see the million-row figures in
  [Benchmarks](BENCHMARKS.md), where a multi-field `ILIKE` is ~430 ms). That is
  the regime where the bounded ES fetch wins decisively. Re-run the harness with
  `DYNAMIC_SEARCH_TEST_DB=postgres` to see the crossover on your database.
- **Not measured:** the real Elasticsearch value also includes fuzzy/typo
  tolerance and relevance ranking that `LIKE` cannot do at all, at the cost of a
  network round-trip and running a cluster.

---

## When to use which

**Stay on the database (no Elasticsearch) when:**

- Free text is a minor feature, or your tables are small/medium.
- You want zero extra infrastructure and always-live data.
- Exact/typed lookups (ids, codes, phone numbers) are the common case — those
  are already fast and unaffected by this choice.

**Reach for Elasticsearch when:**

- Free-text search over large tables is a core feature and `ILIKE '%..%'` scans
  are too slow.
- You need typo tolerance, relevance ranking, or analyzer-based matching
  (stemming, multi-language).
- You can operate a cluster and accept eventual-consistency on the index (kept
  in sync automatically via `AUTO_SYNC`, rebuildable via `reindex_search`).

Because typed routing is identical either way, enabling Elasticsearch only
changes the free-text fallback — and only for the models you list in `INDEXES`.
Unindexed models transparently fall back to the database, so you can adopt it
incrementally.

---

## Correctness parity

`tests/test_elastic_vs_db.py` verifies that the same engine behaves consistently
across both configurations:

- database free-text returns the expected substring matches,
- the Elasticsearch path preserves ES relevance order in the resulting queryset,
- an empty ES result yields an empty queryset, and
- typed routing (e.g. a national code or integer id) routes to the database in
  **both** configurations and never hits Elasticsearch.
