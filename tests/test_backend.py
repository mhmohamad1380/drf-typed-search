"""Integration tests for the DRF filter backend."""

from __future__ import annotations

import pytest
from rest_framework.test import APIRequestFactory

from dynamic_search.backend import DynamicSearchBackend
from dynamic_search.exceptions import InvalidConfigurationError
from dynamic_search.helpers import concat_annotation

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()


class _View:
    search_fields_config = [
        {"field": "national_code", "join": "user"},
        {"field": "phone_number", "join": "user"},
        {"field": "id"},
        {
            "field": "full_name",
            "annotate": concat_annotation(
                "full_name", ["first_name", "last_name"], join="user"
            ),
            "lookup": "icontains",
            "matcher": None,
        },
        {"field": "username", "lookup": "icontains", "matcher": None},
    ]


def _filter(query, view=None):
    from tests.models import Account

    view = view or _View()
    request = factory.get("/", {"search": query} if query is not None else {})
    from rest_framework.request import Request

    backend = DynamicSearchBackend()
    return backend.filter_queryset(Request(request), Account.objects.all(), view), view


def test_backend_typed_route(accounts):
    qs, view = _filter("1000000001")
    assert list(qs) == [accounts["alice"]]
    assert view.search_field == "national_code"


def test_backend_text_fallback(accounts):
    qs, view = _filter("Smith")
    assert list(qs) == [accounts["alice"]]
    assert view.search_field == "full_name,username"


def test_backend_no_search_param_returns_all(accounts):
    qs, view = _filter(None)
    assert list(qs) == list(accounts.values())
    assert view.search_field is None


def test_backend_blank_search_returns_all(accounts):
    qs, _ = _filter("   ")
    assert set(qs) == set(accounts.values())


def test_backend_missing_config_raises(accounts):
    class Bad:
        pass

    with pytest.raises(InvalidConfigurationError):
        _filter("x", view=Bad())


def test_backend_caches_compiled_fields(accounts):
    DynamicSearchBackend._engine_cache.clear()
    _filter("1000000001")
    first = dict(DynamicSearchBackend._engine_cache)
    assert len(first) == 1
    _filter("1000000002")
    # Same key reused: no new engine built, and the cached engine is identical.
    assert DynamicSearchBackend._engine_cache.keys() == first.keys()
    (engine,) = set(DynamicSearchBackend._engine_cache.values())
    assert engine is next(iter(first.values()))


def test_backend_schema_parameters():
    params = DynamicSearchBackend().get_schema_operation_parameters(_View())
    assert params[0]["name"] == "search"
