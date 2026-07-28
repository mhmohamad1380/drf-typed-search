# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2024-01-01

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

[Unreleased]: https://github.com/mhmohamad1380/drf-typed-search/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/mhmohamad1380/drf-typed-search/releases/tag/v1.0.0
