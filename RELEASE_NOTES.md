# Release Notes — drf-typed-search v1.2.0

**Release date:** 2026-08-01
**Type:** Minor, feature release — **100% backward compatible** (no public API changes)

---

## TL;DR

This release adds an **optional Elasticsearch backend for the free-text
branch** of search — without changing any public API or adding a hard
dependency. Typed/regex routing still goes straight to the database; only the
free-text fallback can now be served by Elasticsearch, per model. Everything
defaults off, so upgrading is a drop-in `pip install -U`.

```bash
pip install -U drf-typed-search            # core, unchanged
pip install -U 'drf-typed-search[elasticsearch]'   # opt into the new backend
```

---

## ✨ Highlights

### Optional Elasticsearch free-text backend

Every search value flows through the same two-stage pipeline as before:

1. **Typed routing first** — a value matching a matcher or a field regex
   (national code, UUID, phone number, …) becomes a precise **database** lookup.
   Elasticsearch is never involved.
2. **Free-text fallback second** — only *this* branch can now be routed to
   Elasticsearch.

Turn it on globally and index just your hot models:

```python
DYNAMIC_SEARCH = {
    "MATCHERS": {
        "national_code": {"pattern": r"^\d{10}$", "lookup": "exact"},
    },
    "DEFAULT_TEXT_LOOKUP": "icontains",

    # "database" (default) keeps the old behaviour; "elasticsearch" opts in.
    "TEXT_BACKEND": "elasticsearch",

    "ELASTICSEARCH": {
        "HOSTS": ["http://localhost:9200"],
        "INDEX_PREFIX": "myproject_",
        "AUTO_SYNC": True,
        "RESULT_SIZE": 1000,
        "CLIENT_KWARGS": {},
        "INDEXES": {
            "blog.Article": {"fields": ["title", "body", "tags"]},
            "shop.Product": {"fields": ["name", "description"], "index": "products"},
        },
    },
}
```

This gives you **three tiers per value**:

| Tier          | Handled by            | When                                          |
| ------------- | --------------------- | --------------------------------------------- |
| Regex/typed   | Database (ORM lookup) | Value matches a matcher or a field regex      |
| Elasticsearch | ES index              | Free text **and** model is in `INDEXES`       |
| Normal text   | Database (ORM lookup) | Free text and model is *not* indexed          |

Models not listed in `INDEXES` transparently fall back to the database
`icontains` branch — so you can index only what benefits and leave the rest on
the ORM with zero extra config.

### Automatic index sync + reindex command

With `AUTO_SYNC = True` (default), `post_save` / `post_delete` signals keep
indexes current. For the initial backfill or a rebuild after a mapping change:

```bash
python manage.py reindex_search                              # all configured models
python manage.py reindex_search blog.Article --recreate      # rebuild one index
python manage.py reindex_search --chunk-size 1000            # tune bulk size
```

The command is a thin wrapper over
`dynamic_search.elastic.indexing.reindex_model`, so the same logic runs from a
Celery task or data migration.

### Relevance-ranked, still a real queryset

Free-text values are tokenised (with `"quoted phrases"` kept intact) into a
`bool` query that is **AND across terms** and **OR across fields**
(`multi_match` with `fuzziness: AUTO`, `phrase` match for quotes). Only document
ids are fetched; the provider then filters your original queryset by those pks
and re-orders it with a `Case`/`When` expression so DB results preserve ES
relevance. Because it returns a real Django queryset, DRF serializers,
pagination, permissions and `select_related` all keep working unchanged.

---

## 🧩 What's new under the hood

- New optional extra: `elasticsearch>=8.0,<9.0`. **No hard dependency** —
  nothing under `dynamic_search.elastic` is imported at package import time; the
  client is built lazily on first use.
- New `dynamic_search.elastic` subpackage:
  - `client` — lazily-constructed, cached Elasticsearch client from settings.
  - `query` — pure `build_search_query` (no I/O, trivially unit-testable).
  - `indexing` — `ensure_index`, `serialize_instance`, `index_instance`,
    `delete_document`, `reindex_model`.
  - `provider` — `ElasticTextProvider` / `build_text_provider`.
  - `signals` — optional `post_save` / `post_delete` sync handlers.
- New management command `reindex_search`.
- New exceptions `ElasticsearchNotInstalled` (missing package, with install
  hint) and `ElasticsearchError` (cluster unreachable), both catchable for
  graceful degradation back to the database.
- New guide: `docs/elasticsearch.md`.

---

## 🔁 Compatibility & upgrade notes

- **No public API changes and no breaking changes.** `TEXT_BACKEND` defaults to
  `"database"`, so existing installs behave exactly as in 1.1.0.
- Because the feature is purely additive, this is a **minor** release
  (1.1.0 → 1.2.0), per [Semantic Versioning](https://semver.org/).
- Nothing to change on upgrade — install and, optionally, add
  `TEXT_BACKEND` + `ELASTICSEARCH` config where it helps.

---

## 📚 Links

- Changelog: [`CHANGELOG.md`](https://github.com/mhmohamad1380/drf-typed-search/blob/main/CHANGELOG.md)
- Elasticsearch guide: [`docs/elasticsearch.md`](https://github.com/mhmohamad1380/drf-typed-search/blob/main/docs/elasticsearch.md)
- Full diff: https://github.com/mhmohamad1380/drf-typed-search/compare/v1.1.0...v1.2.0
