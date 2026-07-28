"""Performance regression tests: bounded query counts and minimal cloning."""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from dynamic_search.config import compile_search_fields
from dynamic_search.engine import SearchEngine
from dynamic_search.settings import get_settings

pytestmark = pytest.mark.django_db


CONFIG = [
    {"field": "national_code", "join": "user"},
    {"field": "id"},
    {"field": "username", "lookup": "icontains", "matcher": None},
]


def _engine():
    from tests.models import Account

    s = get_settings()
    return SearchEngine(compile_search_fields(CONFIG, Account), s.matchers, s)


def _qs():
    from tests.models import Account

    return Account.objects.all()


@pytest.mark.benchmark
def test_typed_route_single_query(accounts):
    engine = _engine()
    with CaptureQueriesContext(connection) as ctx:
        list(engine.search(_qs(), "1000000001").queryset)
    assert len(ctx.captured_queries) == 1


@pytest.mark.benchmark
def test_text_route_single_query(accounts):
    engine = _engine()
    with CaptureQueriesContext(connection) as ctx:
        list(engine.search(_qs(), "ali").queryset)
    assert len(ctx.captured_queries) == 1


@pytest.mark.benchmark
def test_typed_route_produces_no_join_for_local_field(accounts):
    engine = _engine()
    result = engine.search(_qs(), "5")  # integer id -> local field
    sql = str(result.queryset.query).lower()
    assert "join" not in sql


@pytest.mark.benchmark
def test_matcher_objects_are_cached():
    first = get_settings().matchers["national_code"]
    second = get_settings().matchers["national_code"]
    assert first is second


@pytest.mark.benchmark
def test_engine_reused_across_requests_not_rebuilt(accounts):
    """The backend must build the engine once and reuse it per view class."""
    from rest_framework.request import Request
    from rest_framework.test import APIRequestFactory

    from dynamic_search.backend import DynamicSearchBackend
    from tests.models import Account

    class _View:
        search_fields_config = CONFIG

    DynamicSearchBackend._engine_cache.clear()
    backend = DynamicSearchBackend()
    factory = APIRequestFactory()

    def run(term: str) -> None:
        req = Request(factory.get("/", {"search": term}))
        backend.filter_queryset(req, Account.objects.all(), _View())

    run("1000000001")
    assert len(DynamicSearchBackend._engine_cache) == 1
    engine_after_first = next(iter(DynamicSearchBackend._engine_cache.values()))

    for term in ("09120000002", "5", "ali", "nomatch"):
        run(term)

    # Still exactly one engine, and the very same instance — never rebuilt.
    assert len(DynamicSearchBackend._engine_cache) == 1
    assert next(iter(DynamicSearchBackend._engine_cache.values())) is engine_after_first


@pytest.mark.benchmark
def test_multi_term_text_search_single_query(accounts):
    engine = _engine()
    with CaptureQueriesContext(connection) as ctx:
        list(engine.search(_qs(), "mohammad hosseiny reza").queryset)
    # One SELECT regardless of the number of terms/fields.
    assert len(ctx.captured_queries) == 1
