"""Tests for the routing engine: typed routing, fallback, annotations, SQL."""

from __future__ import annotations

import pytest

from dynamic_search.config import compile_search_fields
from dynamic_search.engine import SearchEngine
from dynamic_search.helpers import concat_annotation
from dynamic_search.settings import get_settings

pytestmark = pytest.mark.django_db


def _engine(config):
    from tests.models import Account

    settings = get_settings()
    fields = compile_search_fields(config, Account)
    return SearchEngine(fields, settings.matchers, settings), settings


def _qs():
    from tests.models import Account

    return Account.objects.all()


CONFIG = [
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


def test_routes_national_code_to_exact(accounts):
    engine, _ = _engine(CONFIG)
    result = engine.search(_qs(), "1000000001")
    assert result.strategy == "typed"
    assert result.matcher == "national_code"
    assert result.matched_fields == ["national_code"]
    assert list(result.queryset) == [accounts["alice"]]


def test_routes_phone_number(accounts):
    engine, _ = _engine(CONFIG)
    result = engine.search(_qs(), "09120000002")
    assert result.matcher == "phone_number"
    assert list(result.queryset) == [accounts["bob"]]


def test_routes_integer_id(accounts):
    engine, _ = _engine(CONFIG)
    target = accounts["ali"]
    result = engine.search(_qs(), str(target.id))
    assert result.matcher == "id"
    assert list(result.queryset) == [target]


def test_free_text_fallback_username(accounts):
    engine, _ = _engine(CONFIG)
    result = engine.search(_qs(), "ali")
    assert result.strategy == "text"
    # "ali" matches both the "ali" account and the annotated full name "Alice ..".
    usernames = {a.username for a in result.queryset}
    assert "ali" in usernames


def test_free_text_multi_term_and_across_terms(accounts):
    engine, _ = _engine(CONFIG)
    result = engine.search(_qs(), "Alice Smith")
    assert result.strategy == "text"
    assert list(result.queryset) == [accounts["alice"]]


def test_no_match_returns_empty(accounts):
    # Config with no text-searchable fields.
    engine, _ = _engine(
        [{"field": "national_code", "join": "user"}]
    )
    result = engine.search(_qs(), "zzz-nomatch")
    assert result.strategy == "empty"
    assert list(result.queryset) == []


def test_empty_value_is_noop(accounts):
    engine, _ = _engine(CONFIG)
    result = engine.search(_qs(), "   ")
    assert result.strategy == "none"
    assert list(result.queryset) == list(_qs())


def test_uuid_routing(profiles):
    from tests.models import Profile

    settings = get_settings()
    fields = compile_search_fields([{"field": "id", "matcher": "uuid"}], Profile)
    engine = SearchEngine(fields, settings.matchers, settings)
    target = profiles["alice"]
    result = engine.search(Profile.objects.all(), str(target.id))
    assert result.matcher == "uuid"
    assert list(result.queryset) == [target]


def test_generated_sql_uses_exact_for_typed(accounts):
    engine, _ = _engine(CONFIG)
    result = engine.search(_qs(), "1000000001")
    sql = str(result.queryset.query).lower()
    assert "like" not in sql  # exact, not LIKE
    assert "national_code" in sql


def test_generated_sql_uses_like_for_text(accounts):
    engine, _ = _engine(CONFIG)
    result = engine.search(_qs(), "ali")
    sql = str(result.queryset.query).lower()
    assert "like" in sql


def test_custom_queryset_builder(accounts):
    def only_alice(qs, value):
        return qs.filter(username="alice")

    engine, _ = _engine(
        [{"field": "username", "queryset_builder": only_alice, "matcher": None},
         {"field": "id"}]
    )
    # id matcher wins for a digit; use a non-digit to hit the builder via text?
    # queryset_builder fields are typed-only; bind an explicit matcher.
    engine2, _ = _engine(
        [{"field": "username", "queryset_builder": only_alice,
          "matcher": "national_code"}]
    )
    result = engine2.search(_qs(), "1000000001")
    assert result.strategy == "typed"
    assert list(result.queryset) == [accounts["alice"]]


def test_annotation_applied_in_fallback(accounts):
    engine, _ = _engine(CONFIG)
    result = engine.search(_qs(), "Rezai")
    assert result.strategy == "text"
    assert list(result.queryset) == [accounts["ali"]]
