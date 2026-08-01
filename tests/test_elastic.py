"""Tests for the optional Elasticsearch integration.

None of these require a running Elasticsearch cluster: the pure query builder is
tested directly, and the client is replaced with a small in-memory fake so we can
assert on the query shape, pk mapping, relevance ordering and indexing calls.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.test import override_settings

from dynamic_search.elastic.query import build_search_query, split_terms
from dynamic_search.engine import SearchEngine
from dynamic_search.exceptions import ElasticsearchError, InvalidConfigurationError
from dynamic_search.settings import get_settings, reset_cache

pytestmark = pytest.mark.django_db


# --- pure query builder ------------------------------------------------------


def test_split_terms_detects_phrases():
    assert split_terms('alice "credit card" bob') == [
        ("alice", False),
        ("credit card", True),
        ("bob", False),
    ]


def test_split_terms_empty():
    assert split_terms("   ") == []


def test_build_query_empty_is_match_none():
    body = build_search_query("", ["title"])
    assert body["query"] == {"match_none": {}}


def test_build_query_no_fields_is_match_none():
    body = build_search_query("hello", [])
    assert body["query"] == {"match_none": {}}


def test_build_query_and_across_terms_or_across_fields():
    body = build_search_query("alice smith", ["first_name", "last_name"], size=50)
    assert body["size"] == 50
    must = body["query"]["bool"]["must"]
    # One clause per term (AND across terms).
    assert len(must) == 2
    for clause, term in zip(must, ("alice", "smith")):
        mm = clause["multi_match"]
        assert mm["query"] == term
        assert mm["fields"] == ["first_name", "last_name"]  # OR across fields
        assert mm["operator"] == "and"
        assert mm["fuzziness"] == "AUTO"


def test_build_query_phrase_uses_phrase_type():
    body = build_search_query('"credit card"', ["notes"])
    mm = body["query"]["bool"]["must"][0]["multi_match"]
    assert mm["type"] == "phrase"
    assert "fuzziness" not in mm


# --- settings compilation ----------------------------------------------------

_ES_SETTINGS = {
    "MATCHERS": {},
    "TEXT_BACKEND": "elasticsearch",
    "ELASTICSEARCH": {
        "HOSTS": ["http://es:9200"],
        "INDEX_PREFIX": "test_",
        "RESULT_SIZE": 42,
        "INDEXES": {
            "tests.Account": {"fields": ["username", "email"]},
        },
    },
}


@override_settings(DYNAMIC_SEARCH=_ES_SETTINGS)
def test_settings_compile_elasticsearch():
    reset_cache()
    settings = get_settings()
    assert settings.use_elasticsearch is True
    es = settings.elasticsearch
    assert es.hosts == ("http://es:9200",)
    assert es.result_size == 42
    cfg = es.indexes["tests.Account"]
    assert cfg.index_name == "test_tests_account"
    assert cfg.fields == ("username", "email")


@override_settings(
    DYNAMIC_SEARCH={"ELASTICSEARCH": {"INDEXES": {"bad-label": {"fields": ["x"]}}}}
)
def test_settings_bad_index_label_raises():
    reset_cache()
    with pytest.raises(InvalidConfigurationError):
        get_settings()


@override_settings(
    DYNAMIC_SEARCH={"ELASTICSEARCH": {"INDEXES": {"tests.Account": {}}}}
)
def test_settings_missing_fields_raises():
    reset_cache()
    with pytest.raises(InvalidConfigurationError):
        get_settings()


@override_settings(DYNAMIC_SEARCH={"TEXT_BACKEND": "bogus"})
def test_settings_invalid_text_backend_raises():
    reset_cache()
    with pytest.raises(InvalidConfigurationError):
        get_settings()


# --- fake Elasticsearch client ----------------------------------------------


class _FakeIndices:
    def __init__(self) -> None:
        self.created: list[str] = []
        self._exists: set[str] = set()

    def exists(self, index: str) -> bool:
        return index in self._exists

    def create(self, index: str, mappings: dict) -> None:
        self.created.append(index)
        self._exists.add(index)

    def delete(self, index: str) -> None:
        self._exists.discard(index)

    def refresh(self, index: str) -> None:
        pass


class FakeClient:
    """Records calls and returns canned search hits."""

    def __init__(self, hits: list[str] | None = None) -> None:
        self.indices = _FakeIndices()
        self._hits = hits or []
        self.indexed: list[tuple[str, str, dict]] = []
        self.deleted: list[tuple[str, str]] = []
        self.last_search: dict[str, Any] | None = None

    def search(self, index: str, **body: Any) -> dict:
        self.last_search = {"index": index, **body}
        return {"hits": {"hits": [{"_id": pk} for pk in self._hits]}}

    def index(self, index: str, id: str, document: dict) -> None:
        self.indexed.append((index, id, document))

    def delete(self, index: str, id: str, **kwargs: Any) -> None:
        self.deleted.append((index, id))


@pytest.fixture()
def fake_es(monkeypatch):
    """Install a FakeClient as the cached ES client and enable the ES backend."""
    from dynamic_search.elastic import client as client_module

    holder: dict[str, FakeClient] = {}

    def _install(hits: list[str] | None = None) -> FakeClient:
        fake = FakeClient(hits=hits)
        holder["client"] = fake
        monkeypatch.setattr(client_module, "get_client", lambda: fake)
        # provider/indexing import get_client at call time from client_module,
        # so patching there is enough — but they also import the name directly.
        import dynamic_search.elastic.indexing as indexing_module
        import dynamic_search.elastic.provider as provider_module

        monkeypatch.setattr(indexing_module, "get_client", lambda: fake)
        monkeypatch.setattr(provider_module, "get_client", lambda: fake)
        return fake

    return _install


# --- provider ----------------------------------------------------------------


@override_settings(DYNAMIC_SEARCH=_ES_SETTINGS)
def test_provider_maps_hits_to_queryset_in_order(fake_es, accounts):
    reset_cache()
    from dynamic_search.elastic.provider import build_text_provider
    from tests.models import Account

    # Return bob then alice; provider must preserve that ranking.
    fake = fake_es(hits=[str(accounts["bob"].pk), str(accounts["alice"].pk)])
    provider = build_text_provider(Account)
    assert provider is not None

    result = provider.search(Account.objects.all(), "whatever")
    ordered = list(result)
    assert [a.pk for a in ordered] == [accounts["bob"].pk, accounts["alice"].pk]
    # Query was executed against the prefixed index name.
    assert fake.last_search["index"] == "test_tests_account"


@override_settings(DYNAMIC_SEARCH=_ES_SETTINGS)
def test_provider_no_hits_returns_empty(fake_es, accounts):
    reset_cache()
    from dynamic_search.elastic.provider import build_text_provider
    from tests.models import Account

    fake_es(hits=[])
    provider = build_text_provider(Account)
    result = provider.search(Account.objects.all(), "nomatch")
    assert list(result) == []


@override_settings(DYNAMIC_SEARCH=_ES_SETTINGS)
def test_provider_none_for_unindexed_model(fake_es):
    reset_cache()
    from dynamic_search.elastic.provider import build_text_provider
    from tests.models import Profile

    fake_es()
    # Profile is not in INDEXES -> no provider -> DB fallback.
    assert build_text_provider(Profile) is None


@override_settings(DYNAMIC_SEARCH=_ES_SETTINGS)
def test_provider_wraps_client_errors(monkeypatch, accounts):
    reset_cache()
    from dynamic_search.elastic import provider as provider_module
    from dynamic_search.elastic.provider import build_text_provider
    from tests.models import Account

    class Boom:
        def search(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("cluster down")

    monkeypatch.setattr(provider_module, "get_client", lambda: Boom())
    provider = build_text_provider(Account)
    with pytest.raises(ElasticsearchError):
        provider.search(Account.objects.all(), "x")


# --- engine routing ----------------------------------------------------------


def test_engine_uses_text_provider_for_free_text():
    from dynamic_search.config import compile_search_fields
    from tests.models import Account

    class StubProvider:
        def __init__(self) -> None:
            self.called_with: str | None = None

        def search(self, queryset, value):
            self.called_with = value
            return queryset.none()

    fields = compile_search_fields(
        [{"field": "username", "lookup": "icontains"}], Account
    )
    settings = get_settings()
    provider = StubProvider()
    engine = SearchEngine(
        fields, settings.matchers, settings, text_provider=provider
    )

    result = engine.search(Account.objects.all(), "free text")
    assert provider.called_with == "free text"
    assert result.strategy == "text"


def test_engine_typed_routing_bypasses_provider():
    from dynamic_search.config import compile_search_fields
    from tests.models import Account

    class ExplodingProvider:
        def search(self, queryset, value):  # pragma: no cover - must not run
            raise AssertionError("provider should not be used for typed routing")

    fields = compile_search_fields([{"field": "id"}], Account)
    settings = get_settings()
    engine = SearchEngine(
        fields, settings.matchers, settings, text_provider=ExplodingProvider()
    )

    # A bare integer routes to the 'id' callable matcher (typed), not free-text.
    result = engine.search(Account.objects.all(), "5")
    assert result.strategy == "typed"


# --- indexing ----------------------------------------------------------------


@override_settings(DYNAMIC_SEARCH=_ES_SETTINGS)
def test_index_instance_serializes_configured_fields(fake_es, accounts):
    reset_cache()
    from dynamic_search.elastic.indexing import get_index_config, index_instance
    from tests.models import Account

    fake = fake_es()
    account = accounts["alice"]
    index_instance(account, get_index_config(Account))

    assert len(fake.indexed) == 1
    index_name, doc_id, document = fake.indexed[0]
    assert index_name == "test_tests_account"
    assert doc_id == str(account.pk)
    assert document["username"] == "alice"
    assert document["email"] == "alice@example.com"
    assert document["pk"] == account.pk


@override_settings(DYNAMIC_SEARCH=_ES_SETTINGS)
def test_reindex_model_bulk_indexes(fake_es, accounts, monkeypatch):
    reset_cache()
    import sys

    from dynamic_search.elastic.indexing import reindex_model

    fake = fake_es()

    # Stub helpers.bulk so we don't need the real elasticsearch package.
    captured: dict[str, Any] = {}

    def fake_bulk(client, actions, **kwargs):
        acts = list(actions)
        captured["actions"] = acts
        return len(acts), []

    fake_helpers = type("helpers", (), {"bulk": staticmethod(fake_bulk)})
    fake_es_module = type("es", (), {"helpers": fake_helpers})
    monkeypatch.setitem(sys.modules, "elasticsearch", fake_es_module)

    count = reindex_model("tests.Account")

    assert count == 3
    assert "test_tests_account" in fake.indices.created
    # Each action targets the right index and carries a serialized document.
    for action in captured["actions"]:
        assert action["_index"] == "test_tests_account"
        assert "username" in action["_source"]
