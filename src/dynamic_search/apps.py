"""Django app config with startup configuration validation.

Registering ``dynamic_search`` in ``INSTALLED_APPS`` triggers a Django system
check that validates ``DYNAMIC_SEARCH`` at startup, surfacing invalid regexes,
lookups, duplicate matchers, etc. before the first request.
"""

from __future__ import annotations

from typing import Any

from django.apps import AppConfig
from django.core.checks import Error, register


class DynamicSearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dynamic_search"
    verbose_name = "Dynamic Search"

    def ready(self) -> None:
        register(check_dynamic_search_settings)
        _connect_elasticsearch_signals()


def _connect_elasticsearch_signals() -> None:
    """Wire Elasticsearch auto-sync handlers when the ES text backend is active.

    Kept fail-soft: a settings problem here is already reported by the system
    check, so we never raise from ``ready()`` (which would break ``manage.py``).
    """
    from .exceptions import ConfigurationError
    from .settings import get_settings

    try:
        settings = get_settings()
    except ConfigurationError:
        return
    if not settings.use_elasticsearch:
        return
    try:
        from .elastic.signals import connect_signals
    except Exception:  # pragma: no cover - elasticsearch not installed
        return
    connect_signals()


def check_dynamic_search_settings(app_configs: Any, **kwargs: Any) -> list[Error]:
    """System check: eagerly build the matcher registry to validate settings."""
    from .exceptions import ConfigurationError
    from .settings import get_settings, reset_cache

    errors: list[Error] = []
    reset_cache()
    try:
        settings = get_settings()
    except ConfigurationError as exc:
        errors.append(
            Error(
                str(exc),
                id="dynamic_search.E001",
                hint="Fix the DYNAMIC_SEARCH setting.",
            )
        )
        return errors

    errors.extend(_check_elasticsearch(settings))
    return errors


def _check_elasticsearch(settings: Any) -> list[Error]:
    """Validate Elasticsearch wiring: indexed models resolve and the client lib
    is importable when the ES text backend is enabled."""
    errors: list[Error] = []
    es = settings.elasticsearch

    # Every configured index must point at a real model.
    from django.apps import apps as django_apps

    for label in es.indexes:
        try:
            django_apps.get_model(*label.split(".", 1))
        except (LookupError, ValueError):
            errors.append(
                Error(
                    f"DYNAMIC_SEARCH['ELASTICSEARCH']['INDEXES'] refers to "
                    f"unknown model {label!r}.",
                    id="dynamic_search.E002",
                    hint="Use a valid 'app_label.ModelName' key.",
                )
            )

    # If the ES backend is switched on, the client library must be installed.
    if settings.use_elasticsearch:
        try:
            import elasticsearch  # noqa: F401
        except ImportError:
            errors.append(
                Error(
                    "DYNAMIC_SEARCH['TEXT_BACKEND'] is 'elasticsearch' but the "
                    "'elasticsearch' package is not installed.",
                    id="dynamic_search.E003",
                    hint="pip install drf-typed-search[elasticsearch]",
                )
            )
    return errors

