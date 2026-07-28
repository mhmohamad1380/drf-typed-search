"""The DRF filter backend — the thin adapter between HTTP and the engine.

This is the *only* module that knows about Django REST Framework. It reads the
search parameter from the request, delegates all decision-making to
:class:`~dynamic_search.engine.SearchEngine`, and writes the result back onto
the view (``view.search_field``) for downstream consumers such as paginators.

Compiled configuration is cached per *view class* keyed by ``(model, config
identity)`` so the (relatively expensive) validation runs once, not per request.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from rest_framework.filters import BaseFilterBackend

from .config import SearchField, compile_search_fields
from .engine import SearchEngine
from .exceptions import InvalidConfigurationError
from .settings import get_settings

__all__ = ["DynamicSearchBackend"]


class DynamicSearchBackend(BaseFilterBackend):
    """Type-aware, matcher-routed search backend.

    Usage::

        class UserViewSet(ModelViewSet):
            filter_backends = [DynamicSearchBackend]
            search_fields_config = [
                {"field": "national_code", "join": "user"},
                {"field": "id"},
                {"field": "full_name", "join": "user", "lookup": "icontains"},
            ]

    Behaviour:

    * ``?search=`` is routed by input *shape* to a precise, index-friendly
      typed field (see :class:`~dynamic_search.engine.SearchEngine`).
    * If no matcher wins, a DRF-style multi-term free-text search runs across
      every text-searchable field.
    * The matched field(s) are exposed on ``view.search_field``.
    * ``distinct()`` is applied only when a filter actually ran.
    """

    #: Attribute the view must define.
    config_attr = "search_fields_config"

    #: Per view-class cache of compiled + validated fields.
    _compiled_cache: Dict[Tuple[int, int], List[SearchField]] = {}

    # --- DRF entrypoint -----------------------------------------------------

    def filter_queryset(self, request: Any, queryset: Any, view: Any) -> Any:
        settings = get_settings()

        # Always expose the attribute so paginators can read it unconditionally.
        if not hasattr(view, "search_field"):
            view.search_field = None

        raw_config = self._get_raw_config(view)
        fields = self._get_compiled_fields(view, raw_config, queryset.model)

        value = request.query_params.get(settings.search_param)
        if not value or not value.strip():
            return queryset

        engine = SearchEngine(fields, settings.matchers, settings)
        result = engine.search(queryset, value)

        view.search_field = result.search_field

        if result.strategy in ("none", "empty"):
            return result.queryset
        # A filter ran: de-duplicate rows that relation joins may have fanned out.
        return result.queryset.distinct()

    # --- helpers ------------------------------------------------------------

    def _get_raw_config(self, view: Any) -> List[Dict[str, Any]]:
        config = getattr(view, self.config_attr, None)
        if config is None:
            raise InvalidConfigurationError(
                f"{view.__class__.__name__} must define "
                f"'{self.config_attr}' to use DynamicSearchBackend."
            )
        return config

    def _get_compiled_fields(
        self, view: Any, raw_config: Any, model: type
    ) -> List[SearchField]:
        cache_key = (id(view.__class__), id(raw_config))
        cached = self._compiled_cache.get(cache_key)
        if cached is not None:
            return cached
        compiled = compile_search_fields(raw_config, model)
        self._compiled_cache[cache_key] = compiled
        return compiled

    # --- DRF browsable API integration -------------------------------------

    def get_schema_operation_parameters(self, view: Any) -> List[Dict[str, Any]]:
        return [
            {
                "name": get_settings().search_param,
                "required": False,
                "in": "query",
                "description": "A search term routed to the best-matching field.",
                "schema": {"type": "string"},
            }
        ]
