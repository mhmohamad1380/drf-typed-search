"""Behavioural comparison: the free-text branch with vs without Elasticsearch.

These tests prove that the *same* :class:`~dynamic_search.engine.SearchEngine`
produces correct results whether its free-text branch is served by the database
(no provider) or by Elasticsearch (an injected provider), and that typed routing
is identical in both configurations (it never touches the free-text backend).

No live Elasticsearch cluster is required: a tiny in-memory fake client stands
in for the real one, so the tests assert on *routing* and *result mapping*, not
on Lucene scoring.
"""

from __future__ import annotations

from typing import Any

import pytest

from dynamic_search.config import compile_search_fields
from dynamic_search.elastic.provider import ElasticTextProvider
from dynamic_search.engine import SearchEngine
from dynamic_search.settings import ElasticIndexConfig, get_settings

pytestmark = pytest.mark.django_db


CONFIG = [
    {"field": "national_code", "join": "user"},  # typed (regex matcher)
    {"field": "id"},                              # typed (callable matcher)
    {"field": "username", "lookup": "icontains", "matcher": None},  # free-text
    {"field": "email", "lookup": "icontains", "matcher": None},     # free-text
]


def _fields():
    from tests.models import Account

    return compile_search_fields(CONFIG, Account)


def _db_engine() -> SearchEngine:
    """Engine whose free-text branch is served by the database (no provider)."""
    s = get_settings()
    return SearchEngine(_fields(), s.matchers, s)


class _FakeIndices:
    def exists(self, index: str) -> bool:  # pragma: no cover - unused here
        return True


class _FakeClient:
    """Returns canned hits (document ids == model pks) in the given order."""

    def __init__(self, hits: list[str]) -> None:
        self.indices = _FakeIndices()
        self._hits = hits
        self.last_search: dict[str, Any] | None = None

    def search(self, index: str, **body: Any) -> dict:
        self.last_search = {"index": index, **body}
        return {"hits": {"hits": [{"_id": pk} for pk in self._hits]}}


def _es_engine(monkeypatch, hits: list[str]) -> tuple[SearchEngine, _FakeClient]:
    """Engine whose free-text branch is served by a fake Elasticsearch."""
    fake = _FakeClient(hits=hits)

    import dynamic_search.elastic.provider as provider_module

    monkeypatch.setattr(provider_module, "get_client", lambda: fake)

    config = ElasticIndexConfig(
        label="tests.Account",
        index_name="tests_account",
        fields=("username", "email"),
    )
    provider = ElasticTextProvider(config, result_size=1000)

    s = get_settings()
    engine = SearchEngine(_fields(), s.matchers, s, text_provider=provider)
    return engine, fake


# --- free-text branch: DB vs ES ---------------------------------------------


def test_db_free_text_matches_substring(accounts):
    """Without a provider, free text runs an ORM icontains across fields."""
    engine = _db_engine()
    result = engine.search(accounts["alice"].__class__.objects.all(), "ali")
    assert result.strategy == "text"
    usernames = {a.username for a in result.queryset}
    # 'ali' is a substring of both 'ali' and (case-insensitively) nothing else
    # here, but 'alice' contains 'ali' too -> both match.
    assert usernames == {"ali", "alice"}


def test_es_free_text_uses_provider_and_preserves_ranking(monkeypatch, accounts):
    """With a provider, free text is served by ES; ES ranking is preserved."""
    from tests.models import Account

    # ES decides relevance: return bob first, then alice.
    engine, fake = _es_engine(
        monkeypatch, hits=[str(accounts["bob"].pk), str(accounts["alice"].pk)]
    )

    result = engine.search(Account.objects.all(), "whatever")
    assert result.strategy == "text"

    ordered = [a.pk for a in result.queryset]
    assert ordered == [accounts["bob"].pk, accounts["alice"].pk]

    # The DB was queried only by primary key (no icontains), and ES got the
    # free-text value across the configured fields.
    body = fake.last_search
    assert body is not None
    must = body["query"]["bool"]["must"]
    assert must[0]["multi_match"]["fields"] == ["username", "email"]


def test_es_free_text_no_hits_returns_empty(monkeypatch, accounts):
    from tests.models import Account

    engine, _ = _es_engine(monkeypatch, hits=[])
    result = engine.search(Account.objects.all(), "nomatch-xyz")
    assert result.strategy == "text"
    assert list(result.queryset) == []


# --- typed routing is identical in both configurations -----------------------


@pytest.mark.parametrize("value", ["1000000001", "5"])
def test_typed_routing_identical_regardless_of_backend(monkeypatch, accounts, value):
    """A typed value must route to the DB in *both* configurations."""
    from tests.models import Account

    db_engine = _db_engine()

    class _ExplodingClient:
        indices = _FakeIndices()

        def search(self, *a: Any, **k: Any) -> Any:  # pragma: no cover
            raise AssertionError("ES must not be hit for typed routing")

    import dynamic_search.elastic.provider as provider_module

    monkeypatch.setattr(provider_module, "get_client", lambda: _ExplodingClient())
    config = ElasticIndexConfig(
        label="tests.Account",
        index_name="tests_account",
        fields=("username", "email"),
    )
    s = get_settings()
    es_engine = SearchEngine(
        _fields(),
        s.matchers,
        s,
        text_provider=ElasticTextProvider(config, result_size=1000),
    )

    db_result = db_engine.search(Account.objects.all(), value)
    es_result = es_engine.search(Account.objects.all(), value)

    assert db_result.strategy == "typed"
    assert es_result.strategy == "typed"
    assert db_result.matcher == es_result.matcher
