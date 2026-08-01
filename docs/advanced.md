# Annotations & custom SQL

## Annotations

Use the generic `concat_annotation` helper (no business logic) for computed
fields such as a full name:

```python
from dynamic_search import concat_annotation

search_fields_config = [
    {
        "field": "full_name",
        "annotate": concat_annotation("full_name", ["first_name", "last_name"], join="user"),
        "lookup": "icontains",
        "matcher": None,   # free-text only
    },
]
```

The annotation is applied **once** per request, before filtering, and
de-duplicated across multi-term free-text searches.

You can also pass any callable `(queryset, prefix) -> queryset`:

```python
from django.db.models import F, Value
from django.db.models.functions import Concat

def full_name(qs, prefix):
    base = f"{prefix}__" if prefix else ""
    return qs.annotate(
        full_name=Concat(F(f"{base}first_name"), Value(" "), F(f"{base}last_name"))
    )
```

## Custom queryset builders

For anything the default `Q` construction can't express — PostgreSQL trigram
similarity, full-text search, custom SQL — use a `queryset_builder`
`(queryset, value) -> queryset`. The field then owns filtering entirely.

```python
from django.contrib.postgres.search import TrigramSimilarity

def fuzzy_name(qs, value):
    return (
        qs.annotate(sim=TrigramSimilarity("user__full_name", value))
          .filter(sim__gt=0.3)
          .order_by("-sim")
    )

search_fields_config = [
    {"field": "full_name", "queryset_builder": fuzzy_name, "matcher": "name_like"},
]
```

!!! note
    `queryset_builder` fields are **typed-route only** — they are excluded from
    the OR free-text chain. Bind them to a matcher (or field name) so routing can
    select them.

## PostgreSQL full-text example

```python
from django.contrib.postgres.search import SearchQuery, SearchVector

def fulltext(qs, value):
    return qs.annotate(
        _sv=SearchVector("user__first_name", "user__last_name", config="simple")
    ).filter(_sv=SearchQuery(value, config="simple"))

search_fields_config = [
    {"field": "name_fts", "queryset_builder": fulltext, "matcher": "name_like"},
]
```

## Related fields & joins

`join` prepends a relation path to `field` when building the ORM lookup:

```python
search_fields_config = [
    {"field": "national_code", "join": "user"},        # user__national_code
    {"field": "city", "join": "loan__user__address"},  # loan__user__address__city
]
```

Each hop of the `join` path is validated against the model on startup; a bad
relation raises `InvalidJoinError`, a missing final field raises
`MissingFieldError`.
