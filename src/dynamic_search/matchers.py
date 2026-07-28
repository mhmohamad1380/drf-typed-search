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
from re import Pattern
from typing import Callable, Protocol, Union, runtime_checkable

from .exceptions import InvalidRegexError, MatcherError

__all__ = [
    "CallableMatcher",
    "Matcher",
    "MatcherSpec",
    "RegexMatcher",
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

    @property
    def priority(self) -> int:  # pragma: no cover - protocol
        """Routing priority; higher wins when several matchers could match."""
        ...

    def matches(self, value: str) -> bool:  # pragma: no cover - protocol
        """Return ``True`` if ``value`` conforms to this matcher's shape."""
        ...


@dataclass(frozen=True)
class RegexMatcher:
    """Match a value against a fully-anchored compiled regex.

    The pattern is compiled once at construction time and reused for every
    request (compiled regexes are cached by :func:`build_matcher`).

    Optional *cheap pre-filters* (``min_len`` / ``max_len`` / ``prefix``) are
    checked with O(1) string operations before the regex engine runs. They let
    a matcher reject an obviously-wrong value in nanoseconds, keeping routing
    fast even with a large number of registered matchers. They are pure
    optimisation hints: a value that passes them still must satisfy the regex,
    so they can never change results — only skip work.
    """

    name: str
    pattern: Pattern[str]
    lookup: str
    priority: int = 0
    min_len: int | None = None
    max_len: int | None = None
    prefix: str | None = None

    def matches(self, value: str) -> bool:
        length = len(value)
        if self.min_len is not None and length < self.min_len:
            return False
        if self.max_len is not None and length > self.max_len:
            return False
        if self.prefix is not None and not value.startswith(self.prefix):
            return False
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
    priority: int = 0

    def matches(self, value: str) -> bool:

        try:
            return bool(self.predicate(value))
        except Exception:
            return False


def _compile_pattern(name: str, pattern: str | Pattern[str]) -> Pattern[str]:
    if isinstance(pattern, re.Pattern):
        return pattern
    try:
        return re.compile(pattern)
    except re.error as exc:  # invalid regex
        raise InvalidRegexError(
            f"Matcher {name!r} has an invalid regex pattern: {exc}"
        ) from exc


def build_matcher(
    name: str,
    spec: MatcherSpec,
    lookup: str,
    *,
    priority: int = 0,
    min_len: int | None = None,
    max_len: int | None = None,
    prefix: str | None = None,
) -> Matcher:
    """Construct the appropriate :class:`Matcher` for ``spec``.

    ``spec`` may be:

    * a regex *string* — becomes a :class:`RegexMatcher`,
    * a *compiled* ``re.Pattern`` — becomes a :class:`RegexMatcher`,
    * a *callable* predicate — becomes a :class:`CallableMatcher`.

    ``min_len`` / ``max_len`` / ``prefix`` are optional O(1) pre-filters applied
    only to :class:`RegexMatcher` (see its docstring). They are ignored for
    callable matchers, which own their own fast-path logic.

    Raises :class:`MatcherError` for unsupported spec types and
    :class:`InvalidRegexError` for un-compilable patterns.
    """
    if isinstance(spec, (str, re.Pattern)):
        return RegexMatcher(
            name=name,
            pattern=_compile_pattern(name, spec),
            lookup=lookup,
            priority=priority,
            min_len=min_len,
            max_len=max_len,
            prefix=prefix,
        )
    if callable(spec):
        return CallableMatcher(
            name=name, predicate=spec, lookup=lookup, priority=priority
        )

    raise MatcherError(
        f"Matcher {name!r} must be a regex string, compiled pattern, or callable; "
        f"got {type(spec).__name__!r}."
    )
