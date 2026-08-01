"""Exception hierarchy for :mod:`dynamic_search`.

All configuration problems raise a subclass of :class:`ConfigurationError`,
which itself subclasses Django's :class:`~django.core.exceptions.ImproperlyConfigured`
so that misconfiguration surfaces early and integrates with Django tooling.
"""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured

__all__ = [
    "ConfigurationError",
    "DuplicateMatcherError",
    "DynamicSearchError",
    "ElasticsearchError",
    "ElasticsearchNotInstalled",
    "InvalidConfigurationError",
    "InvalidJoinError",
    "InvalidLookupError",
    "InvalidRegexError",
    "MatcherError",
    "MissingFieldError",
]


class DynamicSearchError(Exception):
    """Base class for every error raised by the library."""


class ConfigurationError(DynamicSearchError, ImproperlyConfigured):
    """Base class for configuration-time errors."""


class InvalidRegexError(ConfigurationError):
    """Raised when a matcher regex fails to compile."""


class DuplicateMatcherError(ConfigurationError):
    """Raised when two matchers share the same name."""


class InvalidLookupError(ConfigurationError):
    """Raised when a lookup is not one of the supported lookups."""


class InvalidConfigurationError(ConfigurationError):
    """Raised when a configuration entry is structurally invalid."""


class MissingFieldError(ConfigurationError):
    """Raised when a configured field does not exist on the model."""


class InvalidJoinError(ConfigurationError):
    """Raised when a ``join`` relation path cannot be resolved on the model."""


class MatcherError(ConfigurationError):
    """Raised when a matcher specification is invalid."""


class ElasticsearchError(DynamicSearchError):
    """Base class for Elasticsearch integration errors (runtime, not config)."""


class ElasticsearchNotInstalled(ConfigurationError):
    """Raised when Elasticsearch is enabled but the client library is missing."""
