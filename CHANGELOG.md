# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-07-28

### Added
- **Matcher priority.** Matchers may declare an integer `priority` in
  `DYNAMIC_SEARCH["MATCHERS"]`. When several matchers could match the same
  value, the highest priority wins; ties fall back to declaration order. This
  makes routing for overlapping patterns (e.g. `id` vs `national_code`)
  explicit and deterministic. Default priority is `0` (fully backward
  compatible).
- **Cheap regex pre-filters** (`min_len`, `max_len`, `prefix`) that reject an
  obviously-wrong value with O(1) string checks *before* the regex engine runs.
- Reproducible Python-side benchmark harnesses at `benchmarks/bench_engine.py`
  and `benchmarks/bench_routing_30.py` (worst-case 30-matcher routing cost),
  plus a before/after section in `docs/BENCHMARKS.md`.

- Regression tests for priority routing, deterministic tie-breaks, Unicode /
  Persian free-text, and single-application of annotations across multi-term
  searches.

### Changed
- **Performance: routing plans are precompiled once.** `SearchEngine` now
  resolves matchers, orders them by priority, resolves text lookups and builds
  ORM lookup-path strings a single time in `__init__` (stored as immutable
  tuples). The per-request hot path no longer does dictionary lookups,
  `str.join`, or configuration inspection.
- **Performance: the backend caches the fully-built engine per view** keyed by
  `(view class, config identity, settings identity)`. Previously a new
  `SearchEngine` was constructed on every request; it is now built once and
  reused, yielding a consistent ~4–9 % per-request reduction (see benchmarks).
  The settings-identity component transparently invalidates cached engines on
  settings changes (e.g. `override_settings`).
- `SearchEngine` gained `__slots__` for lower memory and faster attribute
  access.

### Compatibility
- **No public API changes.** `DynamicSearchBackend`, `SearchEngine`,
  `search_fields_config`, matchers, and all documented settings behave exactly
  as before. `priority` and the pre-filter keys are optional additions.
- The private backend cache attribute was renamed
  `_compiled_cache` → `_engine_cache` (internal only).

## [1.0.0] - 2026-07-28


### Added
- Initial public release.
- `DynamicSearchBackend` — DRF filter backend with type-aware routing.
- Global matcher registry via the `DYNAMIC_SEARCH` setting supporting **regex**
  and **callable** matchers (Strategy pattern).
- Per-view `search_fields_config` with `field`, `join`, `lookup`, `matcher`,
  `annotate`, `queryset_builder`, `text`.
- Framework-agnostic `SearchEngine` performing typed routing and a DRF-style
  free-text fallback (AND across terms, OR across fields, quoted phrases).
- Startup validation via a Django system check (`dynamic_search.E001`).
- Support for all standard text lookups: `exact`, `iexact`, `contains`,
  `icontains`, `startswith`, `istartswith`, `endswith`, `iendswith`.
- `concat_annotation` generic annotation helper.
- Performance features: compiled regexes, cached settings & matcher objects,
  minimal queryset cloning and annotations.
- Full type hints, `py.typed` marker, MyPy-strict compliance.
- Comprehensive pytest suite (matchers, settings, config, engine, backend,
  performance/SQL regression).

[Unreleased]: https://github.com/mhmohamad1380/drf-typed-search/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/mhmohamad1380/drf-typed-search/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/mhmohamad1380/drf-typed-search/releases/tag/v1.0.0

