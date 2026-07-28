# Release Notes — drf-typed-search v1.1.0

**Release date:** 2026-07-28
**Type:** Minor, feature + performance release — **100% backward compatible** (no public API changes)

---

## TL;DR

This release makes routing **explicit, deterministic, and faster** without
changing any public API. You get a new `priority` knob for overlapping
matchers, optional O(1) regex pre-filters, and a precompiled/cached hot path.
Upgrading is a drop-in `pip install -U`.

```bash
pip install -U drf-typed-search
```

---

## ✨ Highlights

### 1. Matcher `priority` — deterministic routing for overlapping shapes
When two matchers can match the same input (classic example: a plain integer
that is valid for both `id` and a numeric `national_code`), you can now decide
the winner explicitly:

```python
DYNAMIC_SEARCH = {
    "MATCHERS": {
        "id":            {"pattern": lambda v: v.isdigit(), "lookup": "exact", "priority": 0},
        "national_code": {"pattern": r"^\d{10}$",           "lookup": "exact", "priority": 100},
    }
}
```

- Routing tries matchers in **descending priority**; ties fall back to
  declaration order in `search_fields_config`.
- Default is `priority: 0`, so existing configs behave exactly as before.
- Ordering is resolved **once** when the engine is built — zero per-request cost.

### 2. Cheap O(1) regex pre-filters
Matchers may declare `min_len`, `max_len`, and/or `prefix`. These are checked
with plain string ops **before** the regex engine runs, letting a matcher
reject obviously-wrong values in nanoseconds:

```python
"phone_number": {
    "pattern": r"^09\d{9}$", "lookup": "exact",
    "prefix": "09", "min_len": 11, "max_len": 11,
}
```

They are pure optimisations — a value that passes them must still satisfy the
regex, so **results never change**.

---

## ⚡ Performance

All value-independent work — matcher resolution, priority ordering, text-lookup
resolution, ORM path construction, annotation de-duplication — now happens
**once** in `SearchEngine.__init__` and is stored as immutable tuples. The
per-request hot path does no dict lookups, no `str.join`, and no config
inspection. The backend also **caches the fully-built engine per view class**,
so validation + plan construction run once, not per request.

Measured worst case (**30 regex matchers**, matching one placed *last* so all
29 others run and fail; `benchmarks/bench_routing_30.py`):

| Scenario | Per request | Throughput (1 core) |
|---|---|---|
| Compiled regex (no pre-filter) | ~8–12 µs | ~84k–118k routes/sec |
| Compiled regex + pre-filter | ~7.7–9 µs | ~111k–129k routes/sec |
| Naive `re.compile` per request (avoided) | ~21–23 µs | — |

**Context:** at 1000 req/s with 30 matchers, worst-case routing costs ≈ **~1% of
one CPU core**. The decisive win over DRF `SearchFilter` remains at the database
layer — routing a typed input to a single **indexed `exact`** lookup instead of a
30-column unindexed `ILIKE '%term%'` sequential scan.

`SearchEngine` also gained `__slots__` for lower memory and faster attribute
access.

---

## 🧪 Quality

- **84 tests**, **97% coverage** (`pytest --cov`).
- New regression tests: priority routing, deterministic tie-breaks, Unicode /
  Persian free-text, single-application of annotations across multi-term
  searches, engine-reuse (no per-request rebuild), and bounded query counts.
- Green quality gate: `ruff`, `black --check`, `mypy --strict`.
- `python -m build` + `twine check dist/*` both **PASS** (sdist + wheel).

---

## 🔁 Compatibility & upgrade notes

- **No public API changes.** `DynamicSearchBackend`, `SearchEngine`,
  `search_fields_config`, matchers, and all documented settings behave exactly
  as before. `priority` and the pre-filter keys are optional additions.
- Internal only: the backend's private cache attribute was renamed
  `_compiled_cache` → `_engine_cache`. If you relied on that private name
  (you shouldn't have), update accordingly.

Nothing to change on upgrade — just install and, optionally, add `priority` /
pre-filters where they help.

---

## 📚 Links

- Changelog: [`CHANGELOG.md`](CHANGELOG.md)
- Benchmarks: [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md),
  [`benchmarks/bench_routing_30.py`](benchmarks/bench_routing_30.py)
- Full diff: https://github.com/mhmohamad1380/drf-typed-search/compare/v1.0.0...v1.1.0
