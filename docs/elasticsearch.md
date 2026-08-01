# Elasticsearch free-text backend

`drf-typed-search` routes every incoming search value through the same pipeline:

1. **Typed routing first.** If the value matches a configured regex/callable
   matcher (national code, UUID, phone number, …) or a field's own regex, it is
   turned into a precise ORM lookup. This *always* runs against the database and
   is never sent to Elasticsearch.
2. **Free-text fallback second.** If nothing typed matches, the value is treated
   as free text. This is the only branch the Elasticsearch integration touches.

By default the free-text branch runs an ORM query (`icontains` / your
`DEFAULT_TEXT_LOOKUP`). You can switch it to Elasticsearch globally, and still
keep some models on the database — giving you three tiers per value:

| Tier         | Handled by            | When                                              |
| ------------ | --------------------- | ------------------------------------------------- |
| Regex/typed  | Database (ORM lookup) | Value matches a matcher or a field regex          |
| Elasticsearch| ES index              | Free text **and** model is in `INDEXES`           |
| Normal text  | Database (ORM lookup) | Free text and model is *not* indexed              |

## Installation

The `elasticsearch` package is an optional dependency:

```bash
pip install drf-typed-search[elasticsearch]
```

Importing `dynamic_search` never requires it — the client is only constructed
the first time an Elasticsearch-backed query or index operation runs. If the
package is missing at that point you get a clear
`ElasticsearchNotInstalled` error with install instructions.

## Configuration

Everything lives under `DYNAMIC_SEARCH`. Set `TEXT_BACKEND` to
`"elasticsearch"` and declare which models to index:

```python
DYNAMIC_SEARCH = {
    # existing matcher config still applies to typed routing
    "MATCHERS": {
        "national_code": {"pattern": r"^\d{10}$", "lookup": "exact"},
    },
    "DEFAULT_TEXT_LOOKUP": "icontains",

    # Route the free-text fallback to Elasticsearch.
    # "database" (default) keeps the old behaviour.
    "TEXT_BACKEND": "elasticsearch",

    "ELASTICSEARCH": {
        "HOSTS": ["http://localhost:9200"],
        "INDEX_PREFIX": "myproject_",   # optional, prepended to every index name
        "AUTO_SYNC": True,              # keep indexes in sync via model signals
        "RESULT_SIZE": 1000,            # max hits pulled back per query
        "CLIENT_KWARGS": {              # forwarded to the Elasticsearch() client
            # "basic_auth": ("elastic", "changeme"),
            # "verify_certs": False,
        },
        "INDEXES": {
            # "app_label.ModelName": {"fields": [...]}
            "blog.Article": {"fields": ["title", "body", "tags"]},
            "shop.Product": {
                "fields": ["name", "description"],
                "index": "products",   # optional override; else derived from label
            },
        },
    },
}
```

### Settings reference

| Key             | Default                      | Meaning                                                                 |
| --------------- | ---------------------------- | ----------------------------------------------------------------------- |
| `TEXT_BACKEND`  | `"database"`                 | `"database"` or `"elasticsearch"`. Only affects the free-text branch.   |
| `HOSTS`         | `["http://localhost:9200"]`  | One host string or a list of them.                                      |
| `INDEX_PREFIX`  | `""`                         | Prepended to every resolved index name.                                 |
| `AUTO_SYNC`     | `True`                       | Index/update/delete documents automatically on model `save`/`delete`.   |
| `RESULT_SIZE`   | `1000`                       | Number of hits fetched per free-text query.                             |
| `CLIENT_KWARGS` | `{}`                         | Extra kwargs passed verbatim to the `Elasticsearch()` constructor.      |
| `INDEXES`       | `{}`                         | `"app_label.ModelName"` → `{"fields": [...], "index": "..."}` mapping.  |

The index name for a model defaults to `<prefix><app_label>_<modelname>` in
lower case (e.g. `myproject_blog_article`), unless you set an explicit `index`
key on that model's spec.

## Routing rules — which value goes where

Given a request's search value:

- **Matches a matcher or field regex →** database (typed lookup). Elasticsearch
  is bypassed entirely, so exact identifiers stay fast and precise.
- **Free text, model is in `INDEXES` and `TEXT_BACKEND="elasticsearch"` →**
  Elasticsearch. Results come back in relevance order.
- **Free text, model is *not* in `INDEXES` →** database `icontains` fallback,
  even though the global backend is Elasticsearch. This lets you index only your
  hot models and leave everything else on the ORM.

This per-model fallback is automatic: if `build_text_provider(model)` finds no
index config it returns `None`, and the engine uses the database branch.

## Keeping indexes in sync

With `AUTO_SYNC = True` (the default), `dynamic_search` connects `post_save` and
`post_delete` signals for each configured model, so new and changed rows are
indexed and deleted rows are removed automatically.

For the initial backfill, or to rebuild after a mapping change, use the
management command:

```bash
# Reindex every configured model
python manage.py reindex_search

# Reindex specific models, recreating the indexes first (purges stale docs)
python manage.py reindex_search blog.Article shop.Product --recreate

# Tune bulk chunk size
python manage.py reindex_search --chunk-size 1000
```

The command is a thin wrapper over
`dynamic_search.elastic.indexing.reindex_model`, so you can also call that
directly from a Celery task or data migration.

## Graceful degradation

If Elasticsearch is unreachable, the provider raises `ElasticsearchError`. If
you prefer the request to fall back to the database rather than error out, catch
it around your search call:

```python
from dynamic_search.exceptions import ElasticsearchError

try:
    queryset = search_backend.filter_queryset(request, queryset, view)
except ElasticsearchError:
    # fall back to a plain DB filter, log, etc.
    ...
```

## How the query is built

Free-text values are tokenised into terms, with `"quoted phrases"` kept intact.
The builder produces a `bool` query that is **AND across terms** and **OR across
fields**, using `multi_match` with `fuzziness: AUTO` for single terms and a
`phrase` match for quoted phrases. Only document ids are requested (`_source`
is disabled); those ids are the model primary keys.

The provider then filters your original queryset by those pks and re-orders it
with a `Case`/`When` expression so the database result preserves Elasticsearch
relevance ranking. Because it returns a real Django queryset, DRF serializers,
pagination, permissions and `select_related` all keep working unchanged.
