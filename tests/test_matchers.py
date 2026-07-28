"""Tests for the Matcher strategies and the matcher factory."""

from __future__ import annotations

import re

import pytest

from dynamic_search.exceptions import InvalidRegexError, MatcherError
from dynamic_search.matchers import (
    CallableMatcher,
    Matcher,
    RegexMatcher,
    build_matcher,
)


def test_regex_matcher_full_match():
    m = build_matcher("nc", r"\d{10}", "exact")
    assert isinstance(m, RegexMatcher)
    assert m.matches("1234567890")
    assert not m.matches("123")  # too short
    assert not m.matches("12345678901")  # too long
    assert not m.matches("abcdefghij")


def test_regex_matcher_is_anchored():
    m = build_matcher("nc", r"\d{10}", "exact")
    # fullmatch semantics: embedded digits in a longer string must not match.
    assert not m.matches("x1234567890x")


def test_build_matcher_from_compiled_pattern():
    compiled = re.compile(r"09\d{9}")
    m = build_matcher("phone", compiled, "exact")
    assert isinstance(m, RegexMatcher)
    assert m.matches("09123456789")


def test_callable_matcher():
    m = build_matcher("id", lambda v: v.isdigit(), "exact")
    assert isinstance(m, CallableMatcher)
    assert m.matches("42")
    assert not m.matches("42a")


def test_callable_matcher_swallows_exceptions():
    def boom(_value: str) -> bool:
        raise RuntimeError("nope")

    m = build_matcher("bad", boom, "exact")
    assert m.matches("anything") is False


def test_invalid_regex_raises():
    with pytest.raises(InvalidRegexError):
        build_matcher("bad", r"(", "exact")


def test_invalid_spec_type_raises():
    with pytest.raises(MatcherError):
        build_matcher("bad", 123, "exact")  # type: ignore[arg-type]


def test_matchers_satisfy_protocol():
    regex = build_matcher("a", r"\d+", "exact")
    call = build_matcher("b", lambda v: True, "exact")
    assert isinstance(regex, Matcher)
    assert isinstance(call, Matcher)
    assert regex.name == "a"
    assert call.lookup == "exact"
