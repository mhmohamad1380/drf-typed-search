"""Tests for the startup system check (``dynamic_search.E001``)."""

from __future__ import annotations

from django.test import override_settings

from dynamic_search.apps import check_dynamic_search_settings
from dynamic_search.settings import reset_cache


def test_check_passes_for_valid_settings():
    reset_cache()
    errors = check_dynamic_search_settings(app_configs=None)
    assert errors == []


@override_settings(
    DYNAMIC_SEARCH={"MATCHERS": {"bad": {"pattern": r"(", "lookup": "exact"}}}
)
def test_check_reports_invalid_regex():
    reset_cache()
    errors = check_dynamic_search_settings(app_configs=None)
    assert len(errors) == 1
    assert errors[0].id == "dynamic_search.E001"
    reset_cache()


@override_settings(
    DYNAMIC_SEARCH={"MATCHERS": {"bad": {"pattern": r"\d+", "lookup": "nope"}}}
)
def test_check_reports_invalid_lookup():
    reset_cache()
    errors = check_dynamic_search_settings(app_configs=None)
    assert len(errors) == 1
    assert errors[0].id == "dynamic_search.E001"
    reset_cache()
