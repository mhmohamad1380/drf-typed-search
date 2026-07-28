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
    }

The registry is *built once* and cached. Because matchers are immutable, the
cached objects (including compiled regexes) are shared safely across requests
and threads. The cache is automatically invalidated when settings change via
Django's ``setting_changed`` signal (useful in tests / ``override_settings``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping

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
    "DynamicSearchSettings",
    "get_settings",
    "get_matcher_registry",
    "reset_cache",
]

SETTINGS_KEY = "DYNAMIC_SEARCH"

_DEFAULTS: Dict[str, Any] = {
    "MATCHERS": {},
    "DEFAULT_TEXT_LOOKUP": "icontains",
    "SEARCH_PARAM": "search",
    # When nothing matches and no free-text fields exist, return an empty
    # queryset instead of leaking the entire table.
    "EMPTY_ON_NO_MATCH": True,
}


@dataclass(frozen=True)
class DynamicSearchSettings:
    """Typed, validated view over the ``DYNAMIC_SEARCH`` settings dict."""

    matchers: Dict[str, Matcher]
    default_text_lookup: str
    search_param: str
    empty_on_no_match: bool
    raw: Mapping[str, Any] = field(default_factory=dict)


def _build_matcher_registry(raw_matchers: Any) -> Dict[str, Matcher]:
    if not isinstance(raw_matchers, Mapping):
        raise InvalidConfigurationError(
            f"{SETTINGS_KEY}['MATCHERS'] must be a mapping of name -> spec; "
            f"got {type(raw_matchers).__name__!r}."
        )

    registry: Dict[str, Matcher] = {}
    for name, spec in raw_matchers.items():
        if not isinstance(name, str) or not name:
            raise InvalidConfigurationError(
                f"Matcher names must be non-empty strings; got {name!r}."
            )
        if name in registry:  # dict can't actually collide, but guards subclasses
            raise DuplicateMatcherError(f"Duplicate matcher name: {name!r}.")

        pattern, lookup = _parse_matcher_spec(name, spec)
        if lookup not in VALID_LOOKUPS:
            raise InvalidLookupError(
                f"Matcher {name!r} uses invalid lookup {lookup!r}. "
                f"Valid lookups: {sorted(VALID_LOOKUPS)}."
            )
        registry[name] = build_matcher(name, pattern, lookup)
    return registry


def _parse_matcher_spec(name: str, spec: Any):
    """Normalise a matcher spec into ``(pattern_or_callable, lookup)``.

    Accepts either a full mapping ``{"pattern": ..., "lookup": ...}`` or a bare
    spec (regex string / compiled pattern / callable), in which case the lookup
    defaults to ``exact``.
    """
    if isinstance(spec, Mapping):
        if "pattern" not in spec and "matcher" not in spec:
            raise InvalidConfigurationError(
                f"Matcher {name!r} must define a 'pattern' (regex/callable) key."
            )
        pattern = spec.get("pattern", spec.get("matcher"))
        lookup = spec.get("lookup", "exact")
        return pattern, lookup
    # Bare spec: value is the pattern/callable, lookup defaults to exact.
    return spec, "exact"


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
            f"{SETTINGS_KEY}['DEFAULT_TEXT_LOOKUP'] = {default_text_lookup!r} is invalid."
        )

    return DynamicSearchSettings(
        matchers=_build_matcher_registry(merged["MATCHERS"]),
        default_text_lookup=default_text_lookup,
        search_param=str(merged["SEARCH_PARAM"]),
        empty_on_no_match=bool(merged["EMPTY_ON_NO_MATCH"]),
        raw=user,
    )


# --- caching -----------------------------------------------------------------

_CACHE: Dict[str, DynamicSearchSettings] = {}


def get_settings() -> DynamicSearchSettings:
    """Return the cached, validated settings, building them on first access."""
    cached = _CACHE.get("settings")
    if cached is None:
        cached = _load()
        _CACHE["settings"] = cached
    return cached


def get_matcher_registry() -> Dict[str, Matcher]:
    """Return the cached ``name -> Matcher`` registry."""
    return get_settings().matchers


def reset_cache(**_kwargs: Any) -> None:
    """Clear the settings cache (used on ``setting_changed``)."""
    _CACHE.pop("settings", None)


@receiver(setting_changed)
def _on_setting_changed(sender: Any, setting: str, **kwargs: Any) -> None:
    if setting == SETTINGS_KEY:
        reset_cache()
