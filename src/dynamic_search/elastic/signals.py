"""Optional auto-sync signal handlers.

When ``DYNAMIC_SEARCH['ELASTICSEARCH']['AUTO_SYNC']`` is ``True`` (the default),
connecting these handlers keeps each configured index in step with the database:
saving a row (re)indexes it, deleting a row removes its document.

The handlers are **fail-soft**: a search-index error must never break a database
write. Any exception during (de)indexing is swallowed (and would typically be
logged by the application). If you need strict consistency, disable ``AUTO_SYNC``
and drive indexing explicitly (e.g. from a Celery task after ``transaction.commit``).

Connection is idempotent and driven by :func:`connect_signals`, called from the
app's ``ready()`` only when the Elasticsearch text backend is active.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db.models.signals import post_delete, post_save

from ..settings import get_settings
from .indexing import delete_document, get_index_config, index_instance, resolve_model

__all__ = ["connect_signals", "disconnect_signals"]

logger = logging.getLogger("dynamic_search.elastic")

_DISPATCH_UID = "dynamic_search.elastic.autosync"


def _on_post_save(sender: Any, instance: Any, **kwargs: Any) -> None:
    config = get_index_config(type(instance))
    if config is None:
        return
    try:
        index_instance(instance, config)
    except Exception:  # pragma: no cover - fail-soft by design
        logger.exception("dynamic_search: failed to index %r", instance)


def _on_post_delete(sender: Any, instance: Any, **kwargs: Any) -> None:
    config = get_index_config(type(instance))
    if config is None:
        return
    try:
        delete_document(instance, config)
    except Exception:  # pragma: no cover - fail-soft by design
        logger.exception("dynamic_search: failed to de-index %r", instance)


def connect_signals() -> None:
    """Connect auto-sync handlers for every configured, indexed model.

    Handlers are bound per-model (via ``sender=``) so unrelated model writes pay
    zero overhead. Uses a stable ``dispatch_uid`` so repeated calls (e.g. app
    reloads in tests) do not attach duplicate receivers.
    """
    es = get_settings().elasticsearch
    if not es.auto_sync:
        return
    for label in es.indexes:
        try:
            model = resolve_model(label)
        except LookupError:
            # Model not yet loaded / bad label — surfaced by the system check.
            continue
        post_save.connect(
            _on_post_save,
            sender=model,
            dispatch_uid=f"{_DISPATCH_UID}.save.{label}",
        )
        post_delete.connect(
            _on_post_delete,
            sender=model,
            dispatch_uid=f"{_DISPATCH_UID}.delete.{label}",
        )


def disconnect_signals() -> None:
    """Disconnect all auto-sync handlers (used in tests / teardown)."""
    es = get_settings().elasticsearch
    for label in es.indexes:
        try:
            model = resolve_model(label)
        except LookupError:
            continue
        post_save.disconnect(
            sender=model, dispatch_uid=f"{_DISPATCH_UID}.save.{label}"
        )
        post_delete.disconnect(
            sender=model, dispatch_uid=f"{_DISPATCH_UID}.delete.{label}"
        )
