"""The free-text provider that bridges Elasticsearch back to the ORM.

The core :class:`~dynamic_search.engine.SearchEngine` owns *routing* (regex /
callable matchers first, free-text second). When the free-text branch is
configured to use Elasticsearch, the engine delegates to an
:class:`ElasticTextProvider` instead of building ORM ``Q`` objects.

Design
------

The provider deliberately returns a **Django queryset**, not raw Elasticsearch
hits, so that everything downstream of search — DRF serializers, pagination,
permissions, ``select_related`` — keeps working unchanged. It does this by:

1. Building a pure query body via
   :func:`~dynamic_search.elastic.query.build_search_query`.

2. Executing it against the model's configured index.
3. Collecting the matching primary keys (in relevance order).
4. Filtering the original queryset to those pks, preserving ES ranking via a
   ``Case``/``When`` ordering.

If Elasticsearch is unreachable, the provider raises
:class:`~dynamic_search.exceptions.ElasticsearchError`; callers that prefer a
graceful degradation can catch it and fall back to the database engine.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Case, IntegerField, QuerySet, When

from ..exceptions import ElasticsearchError
from ..settings import ElasticIndexConfig, get_settings
from .client import get_client
from .indexing import get_index_config
from .query import build_search_query

__all__ = ["ElasticTextProvider", "build_text_provider"]


class ElasticTextProvider:
    """Serve the engine's free-text branch from an Elasticsearch index.

    An instance is bound to a single model's :class:`ElasticIndexConfig` and is
    immutable, so it is safe to cache and reuse across requests (mirroring the
    ``SearchEngine`` lifecycle).
    """

    __slots__ = ("_config", "_result_size")

    def __init__(self, config: ElasticIndexConfig, result_size: int) -> None:
        self._config = config
        self._result_size = result_size

    @property
    def fields(self) -> tuple[str, ...]:
        return self._config.fields

    def search(self, queryset: QuerySet, value: str) -> QuerySet:
        """Return ``queryset`` narrowed (and ranked) by an ES free-text query."""
        pks = self._search_pks(value)
        if not pks:
            return queryset.none()

        # Preserve Elasticsearch relevance order when re-selecting from the DB.
        ordering = Case(
            *[When(pk=pk, then=pos) for pos, pk in enumerate(pks)],
            output_field=IntegerField(),
        )
        return queryset.filter(pk__in=pks).order_by(ordering)

    # --- internals ----------------------------------------------------------

    def _search_pks(self, value: str) -> list[Any]:
        body = build_search_query(
            value,
            self._config.fields,
            size=self._result_size,
            source=False,
        )
        client = get_client()
        try:
            response = client.search(index=self._config.index_name, **body)
        except Exception as exc:  # network / cluster / mapping errors
            raise ElasticsearchError(
                f"Elasticsearch query against {self._config.index_name!r} failed: "
                f"{exc}"
            ) from exc
        return _extract_pks(response)


def _extract_pks(response: Any) -> list[Any]:
    """Pull document ids out of an Elasticsearch search response.

    The document ``_id`` is the model primary key (see
    :func:`~dynamic_search.elastic.indexing.index_instance`), so we can read pks
    straight from the hit metadata without requesting ``_source``.
    """
    hits = response.get("hits", {}).get("hits", []) if hasattr(response, "get") else []
    pks: list[Any] = []
    for hit in hits:
        pk = hit.get("_id")
        if pk is not None:
            pks.append(pk)
    return pks


def build_text_provider(model: type) -> ElasticTextProvider | None:
    """Build a provider for ``model`` if it has a configured ES index.

    Returns ``None`` when the model is not indexed, letting the engine fall back
    to the database free-text branch for that model even though the global
    ``TEXT_BACKEND`` is ``"elasticsearch"``.
    """
    config = get_index_config(model)
    if config is None:
        return None
    return ElasticTextProvider(config, get_settings().elasticsearch.result_size)
