"""Lazily-constructed, cached Elasticsearch client.

The ``elasticsearch`` package is an *optional* dependency. Importing this module
does not require it; the client is only built the first time :func:`get_client`
is called. If the package is missing we raise a clear
:class:`~dynamic_search.exceptions.ElasticsearchNotInstalled` with install
instructions rather than a bare ``ImportError``.

The client is cached at module scope and rebuilt automatically whenever the
``DYNAMIC_SEARCH`` setting changes (via Django's ``setting_changed`` signal),
which keeps ``override_settings`` in tests working transparently.
"""

from __future__ import annotations

import contextlib
from typing import Any

from django.core.signals import setting_changed
from django.dispatch import receiver

from ..exceptions import ElasticsearchNotInstalled
from ..settings import SETTINGS_KEY, ElasticsearchSettings, get_settings

__all__ = ["close_client", "get_client"]

_CLIENT: dict[str, Any] = {}


def _import_elasticsearch() -> Any:
    """Import and return the ``Elasticsearch`` class, or raise a clear error."""
    try:
        from elasticsearch import Elasticsearch
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise ElasticsearchNotInstalled(
            "Elasticsearch support requires the 'elasticsearch' package. "
            "Install it with: pip install drf-typed-search[elasticsearch]"
        ) from exc
    return Elasticsearch


def _build_client(es_settings: ElasticsearchSettings) -> Any:
    Elasticsearch = _import_elasticsearch()
    return Elasticsearch(
        list(es_settings.hosts),
        **dict(es_settings.client_kwargs),
    )


def get_client() -> Any:
    """Return the cached Elasticsearch client, building it on first use."""
    client = _CLIENT.get("client")
    if client is None:
        client = _build_client(get_settings().elasticsearch)
        _CLIENT["client"] = client
    return client


def close_client(**_kwargs: Any) -> None:
    """Close and drop the cached client (called on ``setting_changed``)."""
    client = _CLIENT.pop("client", None)
    if client is not None:
        close = getattr(client, "close", None)
        if callable(close):
            with contextlib.suppress(Exception):  # pragma: no cover - cleanup
                close()



@receiver(setting_changed)
def _on_setting_changed(sender: Any, setting: str, **kwargs: Any) -> None:
    if setting == SETTINGS_KEY:
        close_client()
