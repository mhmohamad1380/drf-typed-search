# API Reference

## `dynamic_search.DynamicSearchBackend`

A DRF `BaseFilterBackend`. Add it to a view's `filter_backends` and declare
`search_fields_config`.

- `filter_queryset(request, queryset, view)` — DRF entrypoint. Reads
  `?<SEARCH_PARAM>=`, routes via the engine, sets `view.search_field`, and
  applies `.distinct()` when a filter actually ran.
- `config_attr` — the view attribute name (default `"search_fields_config"`).
- `get_schema_operation_parameters(view)` — OpenAPI/browsable-API integration.

Compiled configuration is cached per view class keyed by `(view class, config
identity)`.

## `dynamic_search.SearchEngine`

Framework-agnostic router.

```python
SearchEngine(fields: Sequence[SearchField], matchers: dict[str, Matcher], settings: DynamicSearchSettings)
```

- `search(queryset, value) -> SearchResult`

### `dynamic_search.SearchResult`

Frozen dataclass:

| attribute        | type                | meaning |
|------------------|---------------------|---------|
| `queryset`       | `QuerySet`          | the filtered queryset |
| `matched_fields` | `list[str]`         | field names searched |
| `strategy`       | `str`               | `"typed"`, `"text"`, `"none"`, `"empty"` |
| `matcher`        | `str \| None`       | winning matcher name for typed routes |
| `search_field`   | `str \| None` (property) | comma-joined matched fields |

## `dynamic_search.config`

- `SearchField` — compiled, immutable field descriptor. Key methods:
  `orm_path(lookup)`, `build_q(value, lookup)`, and property `is_text_searchable`.
- `compile_search_fields(config, model) -> list[SearchField]` — validate/compile.

## `dynamic_search.matchers`

- `Matcher` — runtime-checkable `Protocol` with `name`, `lookup`, `matches(str) -> bool`.
- `RegexMatcher` — regex strategy (compiled once, `fullmatch` semantics).
- `CallableMatcher` — wraps a `(str) -> bool` predicate (exceptions → `False`).
- `build_matcher(name, spec, lookup) -> Matcher` — factory.

## `dynamic_search.settings`

- `get_settings() -> DynamicSearchSettings` — cached, invalidated on setting change.
- `get_matcher_registry() -> dict[str, Matcher]`.
- `reset_cache()` — clear caches (used in tests).

`DynamicSearchSettings` fields: `matchers`, `default_text_lookup`,
`search_param`, `empty_on_no_match`.

## `dynamic_search.lookups`

Constants: `VALID_LOOKUPS`, `TEXT_LOOKUPS`, `EXACT_LOOKUPS`; helper
`is_text_lookup(lookup) -> bool`.

## `dynamic_search.helpers`

- `concat_annotation(alias, fields, *, separator=" ", join=None)` — build an
  `annotate` callable that concatenates fields.

## Exceptions

All inherit from `DynamicSearchError`:

`ConfigurationError`, `InvalidRegexError`, `DuplicateMatcherError`,
`InvalidLookupError`, `InvalidConfigurationError`, `MissingFieldError`,
`InvalidJoinError`, `MatcherError`.
