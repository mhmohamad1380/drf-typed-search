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


def check_dynamic_search_settings(app_configs: Any, **kwargs: Any) -> list[Error]:
    """System check: eagerly build the matcher registry to validate settings."""
    from .exceptions import ConfigurationError
    from .settings import get_settings, reset_cache

    errors: list[Error] = []
    reset_cache()
    try:
        get_settings()
    except ConfigurationError as exc:
        errors.append(
            Error(
                str(exc),
                id="dynamic_search.E001",
                hint="Fix the DYNAMIC_SEARCH setting.",
            )
        )
    return errors
