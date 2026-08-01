"""The DRF filter backend — the thin adapter between HTTP and the engine.

This is the *only* module that knows about Django REST Framework. It reads the
search parameter from the request, delegates all decision-making to
:class:`~dynamic_search.engine.SearchEngine`, and writes the result back onto
the view (``view.search_field``) for downstream consumers such as paginators.

A fully-built :class:`~dynamic_search.engine.SearchEngine` — including its
precompiled typed/text routing plans — is cached per *view class*, keyed by
``(view class, config identity, settings identity)``. Both configuration
validation *and* plan construction therefore run once, not per request. The
settings identity in the key means a settings change (e.g. Django's
``override_settings`` in tests, which rebuilds the cached settings object)
transparently invalidates stale engines without any manual bookkeeping.
"""

from __future__ import annotations

from typing import Any, ClassVar

from rest_framework.filters import BaseFilterBackend

from .config import compile_search_fields
from .engine import SearchEngine
from .exceptions import InvalidConfigurationError
from .settings import DynamicSearchSettings, get_settings

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

    #: Per view-class cache of fully-built engines (plans precompiled once),
    #: keyed by ``(view class, raw config identity, settings identity)``.
    _engine_cache: ClassVar[dict[tuple[int, int, int], SearchEngine]] = {}

    # --- DRF entrypoint -----------------------------------------------------

    def filter_queryset(self, request: Any, queryset: Any, view: Any) -> Any:
        settings = get_settings()

        # Always expose the attribute so paginators can read it unconditionally.
        if not hasattr(view, "search_field"):
            view.search_field = None

        value = request.query_params.get(settings.search_param)
        if not value or not value.strip():
            return queryset

        raw_config = self._get_raw_config(view)
        engine = self._get_engine(view, raw_config, queryset.model, settings)
        result = engine.search(queryset, value)

        view.search_field = result.search_field

        if result.strategy in ("none", "empty"):
            return result.queryset
        # A filter ran: de-duplicate rows that relation joins may have fanned out.
        return result.queryset.distinct()

    # --- helpers ------------------------------------------------------------

    def _get_raw_config(self, view: Any) -> list[dict[str, Any]]:
        config = getattr(view, self.config_attr, None)
        if config is None:
            raise InvalidConfigurationError(
                f"{view.__class__.__name__} must define "
                f"'{self.config_attr}' to use DynamicSearchBackend."
            )
        return config

    def _get_engine(
        self,
        view: Any,
        raw_config: Any,
        model: type,
        settings: DynamicSearchSettings,
    ) -> SearchEngine:
        cache_key = (id(view.__class__), id(raw_config), id(settings))
        cached = self._engine_cache.get(cache_key)
        if cached is not None:
            return cached
        fields = compile_search_fields(raw_config, model)
        text_provider = self._build_text_provider(view, model, settings)
        engine = SearchEngine(
            fields, settings.matchers, settings, text_provider=text_provider
        )
        self._engine_cache[cache_key] = engine
        return engine

    def _build_text_provider(
        self, view: Any, model: type, settings: DynamicSearchSettings
    ) -> Any:
        """Build the free-text provider for this view, if one applies.

        Elasticsearch is used for the free-text branch only when *all* hold:

        * the global ``TEXT_BACKEND`` is ``"elasticsearch"`` (or the view opts in
          via ``search_text_backend = "elasticsearch"``);
        * the view has not opted *out* via ``search_text_backend = "database"``;
        * the queryset's model has a configured Elasticsearch index.

        Otherwise ``None`` is returned and the engine uses the ORM free-text
        search — so unindexed models transparently fall back to the database.
        This is what lets the same project route some models to Elasticsearch,
        some to the normal database search, while regex/typed routing always
        stays on the database.
        """
        from .settings import TEXT_BACKEND_ELASTICSEARCH

        # Per-view override wins over the global setting.
        backend = getattr(view, "search_text_backend", None) or settings.text_backend
        if backend != TEXT_BACKEND_ELASTICSEARCH:
            return None

        # Import lazily so the optional dependency is only touched when ES is on.
        from .elastic.provider import build_text_provider

        return build_text_provider(model)


    # --- DRF browsable API integration -------------------------------------

    def get_schema_operation_parameters(self, view: Any) -> list[dict[str, Any]]:
        return [
            {
                "name": get_settings().search_param,
                "required": False,
                "in": "query",
                "description": "A search term routed to the best-matching field.",
                "schema": {"type": "string"},
            }
        ]
