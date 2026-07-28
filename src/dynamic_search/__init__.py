"""dynamic_search — a type-aware, matcher-routed search backend for DRF.

Public API
----------

>>> from dynamic_search import DynamicSearchBackend
>>> from dynamic_search import SearchEngine, SearchResult          # advanced
>>> from dynamic_search import concat_annotation                   # helper
>>> from dynamic_search import RegexMatcher, CallableMatcher       # matchers
"""

from __future__ import annotations

from .backend import DynamicSearchBackend
from .config import SearchField, compile_search_fields
from .engine import SearchEngine, SearchResult
from .exceptions import (
    ConfigurationError,
    DuplicateMatcherError,
    DynamicSearchError,
    InvalidConfigurationError,
    InvalidJoinError,
    InvalidLookupError,
    InvalidRegexError,
    MatcherError,
    MissingFieldError,
)
from .helpers import concat_annotation
from .lookups import EXACT_LOOKUPS, TEXT_LOOKUPS, VALID_LOOKUPS
from .matchers import CallableMatcher, Matcher, RegexMatcher, build_matcher
from .settings import get_matcher_registry, get_settings

__version__ = "1.0.0"

default_app_config = "dynamic_search.apps.DynamicSearchConfig"

__all__ = [
    "__version__",
    "DynamicSearchBackend",
    "SearchEngine",
    "SearchResult",
    "SearchField",
    "compile_search_fields",
    "concat_annotation",
    "Matcher",
    "RegexMatcher",
    "CallableMatcher",
    "build_matcher",
    "get_settings",
    "get_matcher_registry",
    "EXACT_LOOKUPS",
    "TEXT_LOOKUPS",
    "VALID_LOOKUPS",
    "DynamicSearchError",
    "ConfigurationError",
    "InvalidRegexError",
    "DuplicateMatcherError",
    "InvalidLookupError",
    "InvalidConfigurationError",
    "MissingFieldError",
    "InvalidJoinError",
    "MatcherError",
]
