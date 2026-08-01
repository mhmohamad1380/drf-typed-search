"""Optional Elasticsearch integration for :mod:`dynamic_search`.

This subpackage is **entirely optional**. Nothing here is imported at package
import time; it is only loaded when ``DYNAMIC_SEARCH['TEXT_BACKEND']`` is set to
``"elasticsearch"`` (or when you explicitly reach for these helpers). That keeps
the core library free of a hard dependency on the ``elasticsearch`` client.

What lives here
---------------

``client``
    Lazily-constructed, cached Elasticsearch client built from settings.
``query``
    Pure query-builder that turns a free-text value + field list into an
    Elasticsearch query body — no I/O, trivially unit-testable.
``indexing``
    Index creation, model-instance serialisation and (bulk) (de)indexing.
``provider``
    The :class:`~dynamic_search.elastic.provider.ElasticTextProvider` that the
    :class:`~dynamic_search.engine.SearchEngine` delegates its free-text branch
    to; it maps Elasticsearch hits back onto a Django queryset.
``signals``
    Optional ``post_save`` / ``post_delete`` handlers that keep indexes in sync.

Install the extra with::

    pip install drf-typed-search[elasticsearch]
"""

from __future__ import annotations

from .client import close_client, get_client
from .indexing import (
    delete_document,
    ensure_index,
    index_instance,
    reindex_model,
    serialize_instance,
)
from .provider import ElasticTextProvider, build_text_provider
from .query import build_search_query

__all__ = [
    "ElasticTextProvider",
    "build_search_query",
    "build_text_provider",
    "close_client",
    "delete_document",
    "ensure_index",
    "get_client",
    "index_instance",
    "reindex_model",
    "serialize_instance",
]
