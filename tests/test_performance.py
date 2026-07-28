"""Performance regression tests: bounded query counts and minimal cloning."""

from __future__ import annotations

import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection

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
