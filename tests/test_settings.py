"""Tests for settings loading, caching, and validation."""

from __future__ import annotations

import pytest
from django.test import override_settings

from dynamic_search.exceptions import (
    InvalidConfigurationError,
    InvalidLookupError,
    InvalidRegexError,
)
from dynamic_search.matchers import CallableMatcher, RegexMatcher
from dynamic_search.settings import get_matcher_registry, get_settings, reset_cache


def test_defaults_loaded():
    s = get_settings()
    assert s.search_param == "search"
    assert s.default_text_lookup == "icontains"
    assert s.empty_on_no_match is True


def test_registry_built_from_settings():
    registry = get_matcher_registry()
    assert isinstance(registry["national_code"], RegexMatcher)
    assert isinstance(registry["id"], CallableMatcher)


def test_settings_are_cached():
    first = get_settings()
    second = get_settings()
    assert first is second


def test_setting_changed_invalidates_cache():
    first = get_settings()
    with override_settings(
        DYNAMIC_SEARCH={"MATCHERS": {"x": {"pattern": r"\d+", "lookup": "exact"}}}
    ):
        changed = get_settings()
        assert changed is not first
        assert set(changed.matchers) == {"x"}
    reset_cache()


@override_settings(
    DYNAMIC_SEARCH={"MATCHERS": {"bad": {"pattern": r"(", "lookup": "exact"}}}
)
def test_invalid_regex_in_settings_raises():
    reset_cache()
    with pytest.raises(InvalidRegexError):
        get_settings()


@override_settings(
    DYNAMIC_SEARCH={"MATCHERS": {"bad": {"pattern": r"\d+", "lookup": "weird"}}}
)
def test_invalid_lookup_in_settings_raises():
    reset_cache()
    with pytest.raises(InvalidLookupError):
        get_settings()


@override_settings(DYNAMIC_SEARCH={"MATCHERS": "not-a-dict"})
def test_non_mapping_matchers_raises():
    reset_cache()
    with pytest.raises(InvalidConfigurationError):
        get_settings()


@override_settings(DYNAMIC_SEARCH="not-a-dict")
def test_non_mapping_settings_raises():
    reset_cache()
    with pytest.raises(InvalidConfigurationError):
        get_settings()


@override_settings(DYNAMIC_SEARCH={"MATCHERS": {"x": {"lookup": "exact"}}})
def test_matcher_missing_pattern_raises():
    reset_cache()
    with pytest.raises(InvalidConfigurationError):
        get_settings()


@override_settings(DYNAMIC_SEARCH={"DEFAULT_TEXT_LOOKUP": "nope"})
def test_invalid_default_text_lookup_raises():
    reset_cache()
    with pytest.raises(InvalidLookupError):
        get_settings()


@override_settings(DYNAMIC_SEARCH={"MATCHERS": {"x": r"\d+"}})
def test_bare_regex_spec_defaults_to_exact():
    reset_cache()
    m = get_matcher_registry()["x"]
    assert m.lookup == "exact"
    assert m.matches("123")


@override_settings(
    DYNAMIC_SEARCH={
        "MATCHERS": {
            "nc": {
                "pattern": r"\d{10}",
                "lookup": "exact",
                "min_len": 10,
                "max_len": 10,
                "prefix": "1",
            }
        }
    }
)
def test_prefilters_parsed_from_settings():
    reset_cache()
    m = get_matcher_registry()["nc"]
    assert m.min_len == 10
    assert m.max_len == 10
    assert m.prefix == "1"
    assert m.matches("1234567890")
    assert not m.matches("2234567890")  # wrong prefix, rejected cheaply


@override_settings(
    DYNAMIC_SEARCH={"MATCHERS": {"x": {"pattern": r"\d+", "min_len": -1}}}
)
def test_invalid_prefilter_raises():
    reset_cache()
    with pytest.raises(InvalidConfigurationError):
        get_settings()


@override_settings(
    DYNAMIC_SEARCH={
        "MATCHERS": {
            "x": {"pattern": r"\d+", "lookup": "exact", "priority": 50},
        }
    }
)
def test_priority_parsed_from_settings():
    reset_cache()
    m = get_matcher_registry()["x"]
    assert m.priority == 50
    reset_cache()


def test_priority_defaults_to_zero():
    assert get_matcher_registry()["national_code"].priority == 0


@override_settings(
    DYNAMIC_SEARCH={"MATCHERS": {"x": {"pattern": r"\d+", "priority": "high"}}}
)
def test_invalid_priority_raises():
    reset_cache()
    with pytest.raises(InvalidConfigurationError):
        get_settings()
    reset_cache()


@override_settings(
    DYNAMIC_SEARCH={"MATCHERS": {"x": {"pattern": r"\d+", "priority": True}}}
)
def test_bool_priority_rejected():
    """bool is an int subclass — must be rejected explicitly."""
    reset_cache()
    with pytest.raises(InvalidConfigurationError):
        get_settings()
    reset_cache()
