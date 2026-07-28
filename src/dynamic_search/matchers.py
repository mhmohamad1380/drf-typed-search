"""Matchers — the *strategy* used to detect the shape of a search value.

A :class:`Matcher` decides whether a raw search string "looks like" a certain
kind of value (a national code, a UUID, an integer, ...). Two concrete
strategies ship with the library:

* :class:`RegexMatcher` — matches against a (compiled, cached) regular
  expression.
* :class:`CallableMatcher` — delegates to a user-supplied predicate.

Both implement the :class:`Matcher` protocol, so new strategies can be added
by users without modifying package source (Open/Closed Principle).

Matchers are *stateless and immutable* once built, which makes them safe to
cache and share across threads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Pattern, Protocol, Union, runtime_checkable

from .exceptions import InvalidRegexError, MatcherError

__all__ = [
    "Matcher",
    "RegexMatcher",
    "CallableMatcher",
    "MatcherSpec",
    "build_matcher",
]

#: A user-supplied predicate: ``value -> bool``.
MatcherCallable = Callable[[str], bool]

#: The accepted matcher *specification* value in settings/config.
MatcherSpec = Union[str, Pattern[str], MatcherCallable]


@runtime_checkable
class Matcher(Protocol):
    """Strategy protocol: decide whether a value matches a shape."""

    @property
    def name(self) -> str:  # pragma: no cover - protocol
        """The matcher's unique name (key used in ``search_fields_config``)."""
        ...

    @property
    def lookup(self) -> str:  # pragma: no cover - protocol
        """The ORM lookup applied when this matcher wins routing."""
        ...

    def matches(self, value: str) -> bool:  # pragma: no cover - protocol
        """Return ``True`` if ``value`` conforms to this matcher's shape."""
        ...


@dataclass(frozen=True)
class RegexMatcher:
    """Match a value against a fully-anchored compiled regex.

    The pattern is compiled once at construction time and reused for every
    request (compiled regexes are cached by :func:`build_matcher`).
    """

    name: str
    pattern: Pattern[str]
    lookup: str

    def matches(self, value: str) -> bool:
        return self.pattern.fullmatch(value) is not None


@dataclass(frozen=True)
class CallableMatcher:
    """Match a value using a user-supplied predicate.

    The predicate must accept the raw (stripped) search string and return a
    boolean. Exceptions raised by the predicate are swallowed and treated as a
    non-match to keep a single bad input from breaking the whole request.
    """

    name: str
    predicate: MatcherCallable
    lookup: str

    def matches(self, value: str) -> bool:
        try:
            return bool(self.predicate(value))
        except Exception:  # noqa: BLE001 - a matcher must never break a request
            return False


def _compile_pattern(name: str, pattern: Union[str, Pattern[str]]) -> Pattern[str]:
    if isinstance(pattern, re.Pattern):
        return pattern
    try:
        return re.compile(pattern)
    except re.error as exc:  # invalid regex
        raise InvalidRegexError(
            f"Matcher {name!r} has an invalid regex pattern: {exc}"
        ) from exc


def build_matcher(name: str, spec: MatcherSpec, lookup: str) -> Matcher:
    """Construct the appropriate :class:`Matcher` for ``spec``.

    ``spec`` may be:

    * a regex *string* — becomes a :class:`RegexMatcher`,
    * a *compiled* ``re.Pattern`` — becomes a :class:`RegexMatcher`,
    * a *callable* predicate — becomes a :class:`CallableMatcher`.

    Raises :class:`MatcherError` for unsupported spec types and
    :class:`InvalidRegexError` for un-compilable patterns.
    """
    if isinstance(spec, (str, re.Pattern)):
        return RegexMatcher(
            name=name,
            pattern=_compile_pattern(name, spec),
            lookup=lookup,
        )
    if callable(spec):
        return CallableMatcher(name=name, predicate=spec, lookup=lookup)
    raise MatcherError(
        f"Matcher {name!r} must be a regex string, compiled pattern, or callable; "
        f"got {type(spec).__name__!r}."
    )
