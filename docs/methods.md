# Methods reference & customization

This page documents every public class, method and function in
`dynamic_search`, and — for each extension point — how to override it with your
own implementation. The library is designed so you can replace almost any piece
without editing package source (Open/Closed Principle).

The modules are listed roughly in request order: backend → config → matchers →
engine → free-text providers → Elasticsearch internals.

---

## `dynamic_search.backend`

### `DynamicSearchBackend`

The DRF filter backend — the only class that touches Django REST Framework. Add
it to a view's `filter_backends`.

| Member | Signature | What it does |
| ------ | --------- | ------------ |
| `config_attr` | `= "search_fields_config"` | Name of the view attribute holding the search config. |
| `filter_queryset` | `(self, request, queryset, view) -> QuerySet` | DRF entrypoint. Reads the search param, builds/caches the engine, runs it, writes `view.search_field`, and applies `distinct()` only when a filter ran. |
| `get_schema_operation_parameters` | `(self, view) -> list[dict]` | Advertises the `?search=` query param to the browsable API / OpenAPI schema. |
| `_get_raw_config` | `(self, view) -> list[dict]` | Reads `view.search_fields_config`; raises if absent. |
| `_get_engine` | `(self, view, raw_config, model, settings) -> SearchEngine` | Builds and caches a `SearchEngine` per `(view class, config id, settings id)`. |
| `_build_text_provider` | `(self, view, model, settings) -> TextSearchProvider \| None` | Decides whether the free-text branch uses Elasticsearch for this view/model. |

**Overriding**

Change the config attribute name:

```python
class MyBackend(DynamicSearchBackend):
    config_attr = "search_config"
```

Force a view to use (or skip) Elasticsearch regardless of the global setting —
no subclass needed, just set an attribute on the view:

```python
class ArticleViewSet(ModelViewSet):
    filter_backends = [DynamicSearchBackend]
    search_fields_config = [...]
    search_text_backend = "elasticsearch"   # or "database" to opt out
```

Fully swap how the free-text provider is chosen (e.g. plug a Solr/Meilisearch
provider):

```python
class MyBackend(DynamicSearchBackend):
    def _build_text_provider(self, view, model, settings):
        if getattr(view, "use_solr", False):
            return SolrTextProvider(model)      # your TextSearchProvider
        return super()._build_text_provider(view, model, settings)
```

Change post-filter behaviour (e.g. never call `distinct()`):

```python
class MyBackend(DynamicSearchBackend):
    def filter_queryset(self, request, queryset, view):
        result_qs = super().filter_queryset(request, queryset, view)
        return result_qs  # customize as needed
```

---

## `dynamic_search.config`

### `SearchField` (frozen dataclass)

A compiled, validated searchable field. You rarely build these by hand — they
are produced by `compile_search_fields` — but the methods are useful when
writing a custom `queryset_builder` or provider.

| Member | Signature | What it does |
| ------ | --------- | ------------ |
| `orm_path` | `(self, lookup=None) -> str` | Builds the ORM path, e.g. `user__national_code__exact`. Annotation aliases are not join-prefixed. |
| `build_q` | `(self, value, lookup) -> Q` | Builds a `Q(**{path: value})` for the field. |
| `is_text_searchable` | *property* `-> bool` | Whether the field joins the free-text fallback. |

### `compile_search_fields(config, model) -> list[SearchField]`

Compiles and validates a whole `search_fields_config`, detecting duplicate field
paths. Call it directly if you use the engine outside a DRF view.

### `compile_entry(index, entry, model) -> SearchField`

Compiles and validates one config dict. Override the whole compilation step by
subclassing the backend and calling your own compiler in `_get_engine`.

**Config keys** (each dict in `search_fields_config`):

| Key | Type | Purpose |
| --- | ---- | ------- |
| `field` (required) | `str` | Model field / related field / annotation alias. |
| `join` | `str` | Relation prefix, e.g. `"user"` or `"loan__user"`. |
| `lookup` | `str` | Override lookup for typed win or free-text participation. |
| `matcher` | `str \| None` | Bind to a named matcher. Defaults to `field`; `None` disables typed routing. |
| `annotate` | `(qs, prefix) -> qs` | Applied before filtering (computed fields). |
| `queryset_builder` | `(qs, value) -> qs` | Fully owns filtering for this field (custom SQL/trigram/full-text). |
| `text` | `bool` | Force the field into the free-text fallback. |

**Customizing via callables** — the two per-field hooks are the primary
no-subclass extension points:

```python
from django.contrib.postgres.search import SearchVector, SearchQuery

def full_text_builder(queryset, value):
    return queryset.annotate(
        _v=SearchVector("title", "body")
    ).filter(_v=SearchQuery(value))

search_fields_config = [
    {"field": "title", "queryset_builder": full_text_builder, "matcher": "title"},
]
```

---

## `dynamic_search.matchers`

### `Matcher` (protocol)

The strategy that decides whether a value "looks like" a shape. Any object with
`name`, `lookup`, `priority` properties and a `matches(value) -> bool` method
satisfies it.

### `RegexMatcher` (frozen dataclass)

Matches a fully-anchored compiled regex, with optional O(1) pre-filters.

| Member | Signature | What it does |
| ------ | --------- | ------------ |
| `matches` | `(self, value) -> bool` | Applies `min_len`/`max_len`/`prefix` cheap checks, then `pattern.fullmatch`. |

### `CallableMatcher` (frozen dataclass)

Delegates to a user predicate; exceptions are swallowed as a non-match.

| Member | Signature | What it does |
| ------ | --------- | ------------ |
| `matches` | `(self, value) -> bool` | Returns `bool(predicate(value))`, `False` on error. |

### `build_matcher(name, spec, lookup, *, priority=0, min_len=None, max_len=None, prefix=None) -> Matcher`

Factory that returns a `RegexMatcher` for a regex string/compiled pattern, or a
`CallableMatcher` for a callable.

**Overriding — write your own matcher strategy**

Because `Matcher` is a protocol, you can register any object that implements it.
The simplest route is a callable in settings:

```python
DYNAMIC_SEARCH = {
    "MATCHERS": {
        # regex string
        "national_code": {"pattern": r"^\d{10}$", "lookup": "exact"},
        # callable predicate
        "even_id": {"pattern": lambda v: v.isdigit() and int(v) % 2 == 0,
                     "lookup": "exact"},
    }
}
```

For a fully custom strategy class, implement the protocol and inject the built
registry when constructing the engine yourself:

```python
class LuhnMatcher:
    name = "card"; lookup = "exact"; priority = 10
    def matches(self, value: str) -> bool:
        return _passes_luhn(value)

engine = SearchEngine(fields, {"card": LuhnMatcher()}, settings)
```

`priority` controls routing order — higher wins when several matchers could
match the same value.

---

## `dynamic_search.engine`

### `SearchEngine`

Pure, framework-agnostic router. Immutable after construction and safe to cache.

| Member | Signature | What it does |
| ------ | --------- | ------------ |
| `__init__` | `(self, fields, matchers, settings, text_provider=None)` | Precomputes the typed and free-text plans once. Pass a `text_provider` to own the free-text branch. |
| `search` | `(self, queryset, value) -> SearchResult` | Runs the routing algorithm: typed → free-text (provider or ORM) → none/empty. |
| `_route_typed` | `(self, queryset, value) -> SearchResult \| None` | Walks the priority-ordered typed plan; first matcher that matches wins. |
| `_free_text` | `(self, queryset, value) -> SearchResult` | ORM multi-term search: AND across terms, OR across fields. |

### `SearchResult` (frozen dataclass)

| Member | Signature | What it does |
| ------ | --------- | ------------ |
| `queryset` / `matched_fields` / `strategy` / `matcher` | fields | The outcome; `strategy` is `"typed"`, `"text"`, `"none"`, or `"empty"`. |
| `search_field` | *property* `-> str \| None` | Comma-joined matched field names (handy for paginators). |

### `TextSearchProvider` (protocol)

The pluggable free-text backend contract — implement one method:

```python
def search(self, queryset: QuerySet, value: str) -> QuerySet: ...
```

**Overriding — custom free-text backend**

Any object satisfying `TextSearchProvider` can replace the ORM free-text branch.
Typed routing is never affected. Return a real queryset so DRF pagination,
serializers and permissions keep working:

```python
class SolrTextProvider:
    def __init__(self, model):
        self.model = model
    def search(self, queryset, value):
        ids = solr_client.search(value)          # your search call
        return queryset.filter(pk__in=ids)
```

Inject it either through a custom `DynamicSearchBackend._build_text_provider`
(see above) or directly when constructing a `SearchEngine`.

---

## `dynamic_search.helpers`

### `concat_annotation(alias, fields, *, separator=" ", join=None) -> Callable`

Returns an `annotate` callable that `Concat`s several fields into `alias` — the
common "full name" case. Use it as a config `annotate` value. Write your own
`(queryset, prefix) -> queryset` callable for anything more complex.

---

## `dynamic_search.lookups`

Curated, index-friendly lookup sets and helpers.

| Name | What it is |
| ---- | ---------- |
| `EXACT_LOOKUPS` | `{"exact", "iexact"}` — used for typed routing. |
| `TEXT_LOOKUPS` | `{"contains", "icontains", "startswith", ...}` — free-text fallback. |
| `VALID_LOOKUPS` | Union of the two. |
| `is_text_lookup(lookup) -> bool` | Whether a lookup joins the free-text branch. |
| `is_valid_lookup(lookup) -> bool` | Whether a lookup is supported. |

To support extra lookups, extend these frozensets before Django loads settings
(e.g. in your app's `apps.ready`), or supply a `queryset_builder` per field.

---

## `dynamic_search.settings`

### `get_settings() -> DynamicSearchSettings`

Returns the cached, validated settings (built on first access; invalidated on
Django's `setting_changed`). This is the reader you call from custom code.

### `get_matcher_registry() -> dict[str, Matcher]`

Convenience accessor for the compiled `name -> Matcher` registry.

### `reset_cache(**_) -> None`

Clears the settings cache. Useful in tests; automatically called when
`DYNAMIC_SEARCH` changes.

### Data classes

- `DynamicSearchSettings` — typed view over the settings dict; `use_elasticsearch`
  property tells you whether the free-text backend is ES.
- `ElasticsearchSettings` — typed view over the `ELASTICSEARCH` block.
- `ElasticIndexConfig` — compiled per-model index definition (`label`,
  `index_name`, `fields`).

All configuration is data-driven, so you customize behaviour by editing the
`DYNAMIC_SEARCH` dict rather than subclassing. See
[Configuration](configuration.md) and [Elasticsearch backend](elasticsearch.md).

---

## `dynamic_search.apps`

### `DynamicSearchConfig.ready(self)`

Registers the startup system check and connects Elasticsearch auto-sync signals
(fail-soft) when the ES backend is active.

### `check_dynamic_search_settings(app_configs, **kwargs) -> list[Error]`

Django system check that eagerly builds the matcher registry (surfacing bad
regexes/lookups at boot) and validates Elasticsearch wiring (`E001`–`E003`).

---

## `dynamic_search.elastic` (optional)

Only imported when the `elasticsearch` extra is installed and the ES backend is
active. See [Elasticsearch backend](elasticsearch.md) for the settings.

### `elastic.client`

- `get_client() -> Elasticsearch` — returns the lazily-built, cached client
  configured from `HOSTS` + `CLIENT_KWARGS`. Raises `ElasticsearchNotInstalled`
  if the package is missing. Override the whole client construction by
  monkeypatching this in tests, or by providing `CLIENT_KWARGS`.
- `close_client(**_) -> None` — closes and drops the cached client. Called
  automatically on `setting_changed`; call it yourself in teardown if needed.

### `elastic.provider`

- `build_text_provider(model) -> ElasticTextProvider | None` — returns a provider
  when the model has an index config, else `None` (so unindexed models fall back
  to the database).
- `ElasticTextProvider.search(self, queryset, value) -> QuerySet` — runs the ES
  query, then re-filters and re-orders the original queryset by hit pks
  (relevance-preserving `Case`/`When`). Wraps client failures in
  `ElasticsearchError`.

To use a different engine (Solr, Meilisearch, OpenSearch), write a class with the
same `search` signature and return it from `_build_text_provider` — you do not
need this module at all.

### `elastic.query` (pure, no I/O)

- `split_terms(value) -> list[tuple[str, bool]]` — tokenises into
  `(term, is_phrase)`, honouring quotes.
- `build_search_query(value, fields, *, size=1000, fuzziness="AUTO", source=False) -> dict`
  — builds the `bool` query body: AND across terms, OR across fields, phrase
  matches for quoted input, fuzziness for bare terms. Override query shape by
  wrapping this function in a custom provider.

### `elastic.indexing` (I/O)

| Function | Signature | What it does |
| -------- | --------- | ------------ |
| `resolve_model` | `(label) -> type[Model]` | `"app.Model"` → model class. |
| `get_index_config` | `(model) -> ElasticIndexConfig \| None` | Index config for a model, if any. |
| `serialize_instance` | `(instance, config) -> dict` | Builds the ES document (configured fields + `pk`). Override to change the document shape. |
| `ensure_index` | `(config) -> None` | Creates the index with a default text+keyword mapping if absent. Pre-create the index yourself for custom analysers. |
| `index_instance` | `(instance, config=None) -> None` | Indexes/replaces one row. |
| `delete_document` | `(instance_or_pk, config) -> None` | Removes one document (idempotent). |
| `reindex_model` | `(label, *, recreate=False, chunk_size=500) -> int` | Bulk (re)index a whole model. Call from Celery/migrations. |

### `elastic.signals`

- `connect_signals()` / `disconnect_signals()` — wire/unwire the fail-soft
  `post_save`/`post_delete` auto-sync handlers per configured model. Disable
  auto-sync (`AUTO_SYNC: False`) and drive `index_instance` / `reindex_model`
  yourself for strict, transaction-aware consistency.

---

## Management command

### `manage.py reindex_search [labels...] [--recreate] [--chunk-size N]`

Thin CLI wrapper over `reindex_model`. With no labels it reindexes every
configured model. See [Elasticsearch backend](elasticsearch.md#keeping-indexes-in-sync).
