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
    ElasticsearchError,
    ElasticsearchNotInstalled,
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

__version__ = "1.2.0"


default_app_config = "dynamic_search.apps.DynamicSearchConfig"

__all__ = [
    "EXACT_LOOKUPS",
    "TEXT_LOOKUPS",
    "VALID_LOOKUPS",
    "CallableMatcher",
    "ConfigurationError",
    "DuplicateMatcherError",
    "DynamicSearchBackend",
    "DynamicSearchError",
    "ElasticsearchError",
    "ElasticsearchNotInstalled",
    "InvalidConfigurationError",

    "InvalidJoinError",
    "InvalidLookupError",
    "InvalidRegexError",
    "Matcher",
    "MatcherError",
    "MissingFieldError",
    "RegexMatcher",
    "SearchEngine",
    "SearchField",
    "SearchResult",
    "__version__",
    "build_matcher",
    "compile_search_fields",
    "concat_annotation",
    "get_matcher_registry",
    "get_settings",
]
