"""Global settings access and the cached matcher registry.

Users configure matchers once, globally, in Django settings::

    DYNAMIC_SEARCH = {
        "MATCHERS": {
            "national_code": {"pattern": r"^\\d{10}$", "lookup": "exact"},
            "phone_number": {"pattern": r"^09\\d{9}$", "lookup": "exact"},
            "uuid": {"pattern": UUID_REGEX, "lookup": "exact"},
        },
        # optional knobs
        "DEFAULT_TEXT_LOOKUP": "icontains",
        "SEARCH_PARAM": "search",
        "EMPTY_ON_NO_MATCH": True,
        # Which backend serves the free-text fallback. Typed (regex/callable)
        # routing is always handled by the database; only the *free-text* branch
        # is affected. Either ``"database"`` (default) or ``"elasticsearch"``.
        "TEXT_BACKEND": "database",
        "ELASTICSEARCH": {
            "HOSTS": ["http://localhost:9200"],
            "INDEX_PREFIX": "",
            "AUTO_SYNC": True,
            "INDEXES": {
                # "app_label.ModelName": {"fields": ["title", "body"]},
            },
        },
    }

The registry is *built once* and cached. Because matchers are immutable, the
cached objects (including compiled regexes) are shared safely across requests
and threads. The cache is automatically invalidated when settings change via
Django's ``setting_changed`` signal (useful in tests / ``override_settings``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings as django_settings
from django.core.signals import setting_changed
from django.dispatch import receiver

from .exceptions import (
    DuplicateMatcherError,
    InvalidConfigurationError,
    InvalidLookupError,
)
from .lookups import VALID_LOOKUPS
from .matchers import Matcher, build_matcher

__all__ = [
    "SETTINGS_KEY",
    "TEXT_BACKEND_DATABASE",
    "TEXT_BACKEND_ELASTICSEARCH",
    "DynamicSearchSettings",
    "ElasticIndexConfig",
    "ElasticsearchSettings",
    "get_matcher_registry",
    "get_settings",
    "reset_cache",
]

SETTINGS_KEY = "DYNAMIC_SEARCH"

#: Recognised free-text backends.
TEXT_BACKEND_DATABASE = "database"
TEXT_BACKEND_ELASTICSEARCH = "elasticsearch"
_VALID_TEXT_BACKENDS = frozenset({TEXT_BACKEND_DATABASE, TEXT_BACKEND_ELASTICSEARCH})

_ES_DEFAULTS: dict[str, Any] = {
    "HOSTS": ["http://localhost:9200"],
    "INDEX_PREFIX": "",
    "AUTO_SYNC": True,
    "INDEXES": {},
    # Extra keyword arguments forwarded verbatim to the Elasticsearch client
    # constructor (e.g. ``basic_auth``, ``api_key``, ``verify_certs``).
    "CLIENT_KWARGS": {},
    # Number of hits Elasticsearch returns per free-text query.
    "RESULT_SIZE": 1000,
}

_DEFAULTS: dict[str, Any] = {
    "MATCHERS": {},
    "DEFAULT_TEXT_LOOKUP": "icontains",
    "SEARCH_PARAM": "search",
    # When nothing matches and no free-text fields exist, return an empty
    # queryset instead of leaking the entire table.
    "EMPTY_ON_NO_MATCH": True,
    # Free-text backend; typed regex/callable routing always hits the database.
    "TEXT_BACKEND": TEXT_BACKEND_DATABASE,
    "ELASTICSEARCH": {},
}


@dataclass(frozen=True)
class ElasticIndexConfig:
    """Compiled definition of a single model's Elasticsearch index."""

    label: str  # "app_label.ModelName"
    index_name: str  # resolved, prefix-applied index name
    fields: tuple[str, ...]  # model fields whose text is indexed / searched


@dataclass(frozen=True)
class ElasticsearchSettings:
    """Typed, validated view over ``DYNAMIC_SEARCH['ELASTICSEARCH']``."""

    hosts: tuple[str, ...]
    index_prefix: str
    auto_sync: bool
    result_size: int
    client_kwargs: Mapping[str, Any]
    indexes: Mapping[str, ElasticIndexConfig]  # keyed by "app_label.ModelName"


@dataclass(frozen=True)
class DynamicSearchSettings:
    """Typed, validated view over the ``DYNAMIC_SEARCH`` settings dict."""

    matchers: dict[str, Matcher]
    default_text_lookup: str
    search_param: str
    empty_on_no_match: bool
    text_backend: str
    elasticsearch: ElasticsearchSettings
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def use_elasticsearch(self) -> bool:
        """Whether the free-text fallback should be served by Elasticsearch."""
        return self.text_backend == TEXT_BACKEND_ELASTICSEARCH


def _build_matcher_registry(raw_matchers: Any) -> dict[str, Matcher]:
    if not isinstance(raw_matchers, Mapping):
        raise InvalidConfigurationError(
            f"{SETTINGS_KEY}['MATCHERS'] must be a mapping of name -> spec; "
            f"got {type(raw_matchers).__name__!r}."
        )

    registry: dict[str, Matcher] = {}
    for name, spec in raw_matchers.items():
        if not isinstance(name, str) or not name:
            raise InvalidConfigurationError(
                f"Matcher names must be non-empty strings; got {name!r}."
            )
        if name in registry:  # dict can't actually collide, but guards subclasses
            raise DuplicateMatcherError(f"Duplicate matcher name: {name!r}.")

        pattern, lookup, hints = _parse_matcher_spec(name, spec)
        if lookup not in VALID_LOOKUPS:
            raise InvalidLookupError(
                f"Matcher {name!r} uses invalid lookup {lookup!r}. "
                f"Valid lookups: {sorted(VALID_LOOKUPS)}."
            )
        registry[name] = build_matcher(name, pattern, lookup, **hints)
    return registry


#: Optional O(1) pre-filter hints a matcher spec may declare.
_PREFILTER_KEYS = ("min_len", "max_len", "prefix")


def _parse_matcher_spec(name: str, spec: Any):
    """Normalise a matcher spec into ``(pattern_or_callable, lookup, hints)``.

    Accepts either a full mapping ``{"pattern": ..., "lookup": ...}`` or a bare
    spec (regex string / compiled pattern / callable), in which case the lookup
    defaults to ``exact``.

    ``hints`` collects the optional cheap pre-filters (``min_len`` / ``max_len``
    / ``prefix``) that let :class:`~dynamic_search.matchers.RegexMatcher` reject
    obviously-wrong values before running the regex.
    """
    if isinstance(spec, Mapping):
        if "pattern" not in spec and "matcher" not in spec:
            raise InvalidConfigurationError(
                f"Matcher {name!r} must define a 'pattern' (regex/callable) key."
            )
        pattern = spec.get("pattern", spec.get("matcher"))
        lookup = spec.get("lookup", "exact")
        hints = _parse_prefilters(name, spec)
        return pattern, lookup, hints
    # Bare spec: value is the pattern/callable, lookup defaults to exact.
    return spec, "exact", {}


def _parse_prefilters(name: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    hints: dict[str, Any] = {}
    if spec.get("priority") is not None:
        priority = spec["priority"]
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise InvalidConfigurationError(
                f"Matcher {name!r} 'priority' must be an int."
            )
        hints["priority"] = priority
    for key in ("min_len", "max_len"):

        if key in spec and spec[key] is not None:
            value = spec[key]
            if not isinstance(value, int) or value < 0:
                raise InvalidConfigurationError(
                    f"Matcher {name!r} {key!r} must be a non-negative int."
                )
            hints[key] = value
    if spec.get("prefix") is not None:
        prefix = spec["prefix"]
        if not isinstance(prefix, str):
            raise InvalidConfigurationError(
                f"Matcher {name!r} 'prefix' must be a string."
            )
        hints["prefix"] = prefix
    return hints


def _build_index_config(label: str, spec: Any, prefix: str) -> ElasticIndexConfig:
    """Compile a single ``INDEXES`` entry into an :class:`ElasticIndexConfig`."""
    if not isinstance(label, str) or "." not in label:
        raise InvalidConfigurationError(
            f"{SETTINGS_KEY}['ELASTICSEARCH']['INDEXES'] keys must be "
            f"'app_label.ModelName'; got {label!r}."
        )
    if not isinstance(spec, Mapping):
        raise InvalidConfigurationError(
            f"Elasticsearch index spec for {label!r} must be a mapping; "
            f"got {type(spec).__name__!r}."
        )

    raw_fields = spec.get("fields")
    if not raw_fields or not isinstance(raw_fields, (list, tuple)):
        raise InvalidConfigurationError(
            f"Elasticsearch index spec for {label!r} must define a non-empty "
            f"'fields' list."
        )
    fields = tuple(str(f) for f in raw_fields)

    index_name = spec.get("index")
    if index_name is None:
        index_name = f"{prefix}{label.replace('.', '_').lower()}"
    else:
        index_name = f"{prefix}{index_name}"

    return ElasticIndexConfig(label=label, index_name=str(index_name), fields=fields)


def _build_elasticsearch_settings(raw: Any) -> ElasticsearchSettings:
    """Compile ``DYNAMIC_SEARCH['ELASTICSEARCH']`` into typed settings."""
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise InvalidConfigurationError(
            f"{SETTINGS_KEY}['ELASTICSEARCH'] must be a dict; "
            f"got {type(raw).__name__!r}."
        )

    merged = {**_ES_DEFAULTS, **raw}

    hosts = merged["HOSTS"]
    if isinstance(hosts, str):
        hosts = [hosts]
    if not isinstance(hosts, (list, tuple)) or not hosts:
        raise InvalidConfigurationError(
            f"{SETTINGS_KEY}['ELASTICSEARCH']['HOSTS'] must be a non-empty "
            f"list of host strings."
        )

    result_size = merged["RESULT_SIZE"]
    if (
        not isinstance(result_size, int)
        or isinstance(result_size, bool)
        or result_size <= 0
    ):

        raise InvalidConfigurationError(
            f"{SETTINGS_KEY}['ELASTICSEARCH']['RESULT_SIZE'] must be a "
            f"positive int."
        )

    client_kwargs = merged["CLIENT_KWARGS"] or {}
    if not isinstance(client_kwargs, Mapping):
        raise InvalidConfigurationError(
            f"{SETTINGS_KEY}['ELASTICSEARCH']['CLIENT_KWARGS'] must be a dict."
        )

    prefix = str(merged["INDEX_PREFIX"] or "")

    raw_indexes = merged["INDEXES"] or {}
    if not isinstance(raw_indexes, Mapping):
        raise InvalidConfigurationError(
            f"{SETTINGS_KEY}['ELASTICSEARCH']['INDEXES'] must be a mapping of "
            f"'app_label.ModelName' -> spec."
        )
    indexes = {
        label: _build_index_config(label, spec, prefix)
        for label, spec in raw_indexes.items()
    }

    return ElasticsearchSettings(
        hosts=tuple(str(h) for h in hosts),
        index_prefix=prefix,
        auto_sync=bool(merged["AUTO_SYNC"]),
        result_size=result_size,
        client_kwargs=dict(client_kwargs),
        indexes=indexes,
    )


def _load() -> DynamicSearchSettings:
    user = getattr(django_settings, SETTINGS_KEY, {}) or {}
    if not isinstance(user, Mapping):
        raise InvalidConfigurationError(
            f"{SETTINGS_KEY} must be a dict; got {type(user).__name__!r}."
        )

    merged = {**_DEFAULTS, **user}

    default_text_lookup = merged["DEFAULT_TEXT_LOOKUP"]
    if default_text_lookup not in VALID_LOOKUPS:
        raise InvalidLookupError(
            f"{SETTINGS_KEY}['DEFAULT_TEXT_LOOKUP'] = "
            f"{default_text_lookup!r} is invalid."
        )

    text_backend = str(merged["TEXT_BACKEND"])
    if text_backend not in _VALID_TEXT_BACKENDS:
        raise InvalidConfigurationError(
            f"{SETTINGS_KEY}['TEXT_BACKEND'] = {text_backend!r} is invalid. "
            f"Valid values: {sorted(_VALID_TEXT_BACKENDS)}."
        )

    return DynamicSearchSettings(
        matchers=_build_matcher_registry(merged["MATCHERS"]),
        default_text_lookup=default_text_lookup,
        search_param=str(merged["SEARCH_PARAM"]),
        empty_on_no_match=bool(merged["EMPTY_ON_NO_MATCH"]),
        text_backend=text_backend,
        elasticsearch=_build_elasticsearch_settings(merged["ELASTICSEARCH"]),
        raw=user,
    )


# --- caching -----------------------------------------------------------------

_CACHE: dict[str, DynamicSearchSettings] = {}


def get_settings() -> DynamicSearchSettings:
    """Return the cached, validated settings, building them on first access."""
    cached = _CACHE.get("settings")
    if cached is None:
        cached = _load()
        _CACHE["settings"] = cached
    return cached


def get_matcher_registry() -> dict[str, Matcher]:
    """Return the cached ``name -> Matcher`` registry."""
    return get_settings().matchers


def reset_cache(**_kwargs: Any) -> None:
    """Clear the settings cache (used on ``setting_changed``)."""
    _CACHE.pop("settings", None)


@receiver(setting_changed)
def _on_setting_changed(sender: Any, setting: str, **kwargs: Any) -> None:
    if setting == SETTINGS_KEY:
        reset_cache()
