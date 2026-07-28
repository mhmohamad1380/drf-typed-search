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


def test_prefilter_min_max_len():
    m = build_matcher("nc", r"\d{10}", "exact", min_len=10, max_len=10)
    assert m.matches("1234567890")
    assert not m.matches("123")  # too short -> rejected before regex
    assert not m.matches("12345678901")  # too long -> rejected before regex


def test_prefilter_prefix():
    m = build_matcher("phone", r"09\d{9}", "exact", prefix="09")
    assert m.matches("09123456789")
    assert not m.matches("19123456789")  # wrong prefix -> rejected before regex


def test_prefilter_skips_regex_engine():
    """A value rejected by a pre-filter must NOT invoke the regex engine."""

    class SpyPattern:
        def __init__(self):
            self.calls = 0

        def fullmatch(self, value):
            self.calls += 1
            return None

    spy = SpyPattern()
    m = RegexMatcher(name="nc", pattern=spy, lookup="exact", min_len=10)  # type: ignore[arg-type]
    assert m.matches("short") is False
    assert spy.calls == 0  # pre-filter short-circuited before the regex

    assert m.matches("longenough") is False
    assert spy.calls == 1  # passed pre-filter -> regex was consulted


def test_prefilter_passes_through_to_regex():
    # A value that passes the pre-filter but fails the regex still returns False.
    m = build_matcher("nc", r"\d{10}", "exact", min_len=10, max_len=10)
    assert m.matches("abcdefghij") is False  # right length, wrong content


def test_matchers_satisfy_protocol():

    regex = build_matcher("a", r"\d+", "exact")
    call = build_matcher("b", lambda v: True, "exact")
    assert isinstance(regex, Matcher)
    assert isinstance(call, Matcher)
    assert regex.name == "a"
    assert call.lookup == "exact"
