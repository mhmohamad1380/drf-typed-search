"""Index management and model-instance (de)indexing.

Responsibilities:

* Resolve a configured ``"app_label.ModelName"`` label to its Django model.
* Serialise a model instance into an Elasticsearch document containing only the
  configured fields (plus the primary key, which is used to map hits back to
  rows).
* Create an index with a sensible default text mapping if it does not exist.
* Index / delete single instances and bulk-reindex an entire model.

These functions perform I/O against Elasticsearch and are therefore kept out of
the pure query builder. They are deliberately defensive: indexing failures for a
single instance are surfaced to the caller, but the *auto-sync* signal handlers
(see :mod:`dynamic_search.elastic.signals`) swallow errors so a search-index
hiccup never breaks a database write.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from django.apps import apps as django_apps
from django.db.models import Model

from ..settings import ElasticIndexConfig, get_settings
from .client import get_client

__all__ = [
    "delete_document",
    "ensure_index",
    "get_index_config",
    "index_instance",
    "reindex_model",
    "resolve_model",
    "serialize_instance",
]


def resolve_model(label: str) -> type[Model]:
    """Resolve ``"app_label.ModelName"`` to its model class."""
    app_label, _, model_name = label.partition(".")
    return django_apps.get_model(app_label, model_name)


def get_index_config(model: type[Model]) -> ElasticIndexConfig | None:
    """Return the :class:`ElasticIndexConfig` for ``model``, or ``None``.

    Matching is done on the model's ``app_label.ModelName`` label so the same
    lookup works regardless of how the caller obtained the model class.
    """
    label = f"{model._meta.app_label}.{model.__name__}"
    return get_settings().elasticsearch.indexes.get(label)


def serialize_instance(instance: Model, config: ElasticIndexConfig) -> dict[str, Any]:
    """Serialise ``instance`` into an Elasticsearch document body.

    Only the configured fields are included. Related fields are resolved via
    Django's attribute access, and any value is coerced with ``str`` when it is
    not a JSON-native scalar so the document is always serialisable.
    """
    doc: dict[str, Any] = {}
    for field_name in config.fields:
        value = _resolve_attr(instance, field_name)
        doc[field_name] = _coerce(value)
    # Always store the primary key so hits can be mapped back to rows.
    doc["pk"] = instance.pk
    return doc


def _resolve_attr(instance: Any, path: str) -> Any:
    """Resolve a possibly-nested attribute path (``"user__full_name"``)."""
    current = instance
    for part in path.split("__"):
        if current is None:
            return None
        current = getattr(current, part, None)
    return current


def _coerce(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def ensure_index(config: ElasticIndexConfig) -> None:
    """Create ``config.index_name`` with a default mapping if it is absent.

    The mapping declares every configured field as ``text`` (analysed, for
    full-text matching) with a ``keyword`` sub-field (for exact/sort use), which
    is the conventional Elasticsearch default and covers the vast majority of
    search cases. Users who need custom analysers can pre-create the index
    themselves; this function never overwrites an existing index.
    """
    client = get_client()
    if client.indices.exists(index=config.index_name):
        return

    properties: dict[str, Any] = {
        field_name: {
            "type": "text",
            "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
        }
        for field_name in config.fields
    }
    properties["pk"] = {"type": "keyword"}

    client.indices.create(
        index=config.index_name,
        mappings={"properties": properties},
    )


def index_instance(instance: Model, config: ElasticIndexConfig | None = None) -> None:
    """Index (create or replace) a single model instance."""
    if config is None:
        config = get_index_config(type(instance))
        if config is None:
            return
    client = get_client()
    client.index(
        index=config.index_name,
        id=str(instance.pk),
        document=serialize_instance(instance, config),
    )


def delete_document(instance_or_pk: Any, config: ElasticIndexConfig) -> None:
    """Remove a single document by instance or primary key (idempotent)."""
    pk = getattr(instance_or_pk, "pk", instance_or_pk)
    client = get_client()
    client.delete(index=config.index_name, id=str(pk), ignore=[404])


def _bulk_actions(
    queryset: Iterable[Model], config: ElasticIndexConfig
) -> Iterator[dict[str, Any]]:
    for instance in queryset:
        yield {
            "_op_type": "index",
            "_index": config.index_name,
            "_id": str(instance.pk),
            "_source": serialize_instance(instance, config),
        }


def reindex_model(
    label: str,
    *,
    recreate: bool = False,
    chunk_size: int = 500,
) -> int:
    """(Re)index every row of the model identified by ``label``.

    Args:
        label: ``"app_label.ModelName"`` — must be present in the configured
            ``INDEXES``.
        recreate: When ``True`` the index is deleted and recreated first,
            guaranteeing stale documents are purged.
        chunk_size: Bulk helper chunk size.

    Returns:
        The number of documents indexed.
    """
    config = get_settings().elasticsearch.indexes.get(label)
    if config is None:
        raise KeyError(
            f"No Elasticsearch index is configured for {label!r}. "
            f"Add it to DYNAMIC_SEARCH['ELASTICSEARCH']['INDEXES']."
        )

    client = get_client()
    if recreate and client.indices.exists(index=config.index_name):
        client.indices.delete(index=config.index_name)
    ensure_index(config)

    model = resolve_model(label)
    queryset = model._default_manager.all().iterator(chunk_size=chunk_size)

    # ``helpers.bulk`` is the standard, efficient path; import lazily so the
    # optional dependency is only required when actually indexing.
    from elasticsearch import helpers

    indexed, _errors = helpers.bulk(
        client,
        _bulk_actions(queryset, config),
        chunk_size=chunk_size,
    )
    client.indices.refresh(index=config.index_name)
    return indexed
