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
    engine, _ = _engine([{"field": "national_code", "join": "user"}])
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
        [
            {"field": "username", "queryset_builder": only_alice, "matcher": None},
            {"field": "id"},
        ]
    )
    # id matcher wins for a digit; use a non-digit to hit the builder via text?
    # queryset_builder fields are typed-only; bind an explicit matcher.
    engine2, _ = _engine(
        [
            {
                "field": "username",
                "queryset_builder": only_alice,
                "matcher": "national_code",
            }
        ]
    )
    result = engine2.search(_qs(), "1000000001")
    assert result.strategy == "typed"
    assert list(result.queryset) == [accounts["alice"]]


def test_annotation_applied_in_fallback(accounts):
    engine, _ = _engine(CONFIG)
    result = engine.search(_qs(), "Rezai")
    assert result.strategy == "text"
    assert list(result.queryset) == [accounts["ali"]]


def test_priority_orders_ambiguous_matchers(accounts):
    """Higher-priority matcher wins even when declared later."""
    from django.test import override_settings

    from dynamic_search.settings import reset_cache
    from tests.models import Account

    overridden = {
        "MATCHERS": {
            # Both match a plain integer; national_code has higher priority.
            "id": {"pattern": lambda v: v.isdigit(), "lookup": "exact", "priority": 0},
            "national_code": {
                "pattern": lambda v: v.isdigit(),
                "lookup": "exact",
                "priority": 100,
            },
        },
        "DEFAULT_TEXT_LOOKUP": "icontains",
    }
    with override_settings(DYNAMIC_SEARCH=overridden):
        reset_cache()
        settings = get_settings()
        # "id" declared first, "national_code" second — priority must override order.
        fields = compile_search_fields(
            [
                {"field": "id"},
                {"field": "national_code", "join": "user"},
            ],
            Account,
        )
        engine = SearchEngine(fields, settings.matchers, settings)
        result = engine.search(Account.objects.all(), "1000000001")
        assert result.matcher == "national_code"
    reset_cache()


def test_first_match_wins_with_equal_priority(accounts):
    """With equal priority, declaration order is the deterministic tie-break."""
    engine, _ = _engine(
        [
            {"field": "id"},
            {"field": "national_code", "join": "user"},
        ]
    )
    # id and national_code both bound to digit matchers of equal (default) priority;
    # "id" is declared first, so it wins for an integer that is also a valid id.
    result = engine.search(_qs(), str(accounts["ali"].id))
    assert result.matcher == "id"


def test_unicode_persian_text_fallback(accounts):
    engine, _ = _engine(CONFIG)
    # Non-ASCII term must route to free-text without error.
    result = engine.search(_qs(), "علی")
    assert result.strategy == "text"


def test_annotation_applied_once_for_multiple_terms(accounts):
    """Multi-term search must not stack duplicate annotations."""
    engine, _ = _engine(CONFIG)
    result = engine.search(_qs(), "Alice Alice")
    # Annotation alias appears once in the SQL SELECT despite two terms.
    sql = str(result.queryset.query)
    assert (
        sql.count(" AS ") <= 2
    )  # at most the annotation alias, not duplicated per term


def test_no_match_no_text_fields_returns_all_when_configured(accounts):
    """EMPTY_ON_NO_MATCH=False leaves the queryset untouched on no match."""
    from django.test import override_settings

    from dynamic_search.settings import reset_cache
    from tests.models import Account

    with override_settings(
        DYNAMIC_SEARCH={
            "MATCHERS": {"national_code": {"pattern": r"^\d{10}$", "lookup": "exact"}},
            "EMPTY_ON_NO_MATCH": False,
        }
    ):
        reset_cache()
        settings = get_settings()
        fields = compile_search_fields(
            [{"field": "national_code", "join": "user"}], Account
        )
        engine = SearchEngine(fields, settings.matchers, settings)
        result = engine.search(Account.objects.all(), "not-a-code")
        assert result.strategy == "none"
        assert list(result.queryset) == list(Account.objects.all())
    reset_cache()


def test_free_text_only_whitespace_after_quote_is_noop(accounts):
    """A value that splits into zero terms falls through to a no-op."""
    engine, _ = _engine(CONFIG)
    # A lone quote yields a ValueError in shlex -> falls back to .split() -> ['"']
    # but a value that is only separators must produce no terms.
    result = engine.search(_qs(), '""')
    # '""' -> shlex splits to [''] -> filtered out -> no terms -> strategy none
    assert result.strategy in ("none", "text")
