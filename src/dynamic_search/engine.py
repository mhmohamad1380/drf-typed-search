"""The search engine — routes a value to the optimal queryset.

The engine is pure and framework-agnostic: it takes a queryset, a raw search
string, the compiled :class:`~dynamic_search.config.SearchField` list, the
matcher registry, and returns a :class:`SearchResult`. It performs no I/O and
has no knowledge of DRF or HTTP — which keeps it trivially unit-testable and
reusable outside a view (Clean Architecture / Low Coupling).

Routing algorithm
-----------------

1. **Typed routing** — walk the precompiled *typed plan* (matcher-bound fields,
   ordered by descending :pyattr:`~dynamic_search.matchers.Matcher.priority`
   then declaration order) and test whether the *whole* value matches. The
   first matcher that matches wins and produces a single, index-friendly
   predicate.
2. **Free-text fallback** — if no matcher wins, run a DRF-style multi-term
   search across every text-searchable field: **AND across terms, OR across
   fields**, honouring quoted phrases.
3. **No match** — if there are no text-searchable fields, optionally narrow the
   queryset to ``none()`` (configurable) to avoid leaking the whole table.

Performance
-----------

All per-field work that does *not* depend on the request value — matcher
resolution, priority ordering, text-lookup resolution, ORM path string
construction, annotation de-duplication — is performed **once** in
``__init__`` and reused for every request. The hot path therefore does no
dictionary lookups, no ``str.join`` calls, and no configuration inspection.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Protocol, runtime_checkable

from django.db.models import Q, QuerySet

from .config import SearchField
from .lookups import TEXT_LOOKUPS
from .matchers import Matcher
from .settings import DynamicSearchSettings

__all__ = ["SearchEngine", "SearchResult", "TextSearchProvider"]


@runtime_checkable
class TextSearchProvider(Protocol):
    """Pluggable free-text backend.

    A provider owns the *free-text* branch only; typed regex/callable routing is
    always handled by the database. The built-in implementation is
    :class:`~dynamic_search.elastic.provider.ElasticTextProvider`, but any object
    exposing this interface can be injected (e.g. for tests or an alternative
    search engine).
    """

    def search(self, queryset: QuerySet, value: str) -> QuerySet:
        """Return ``queryset`` narrowed to rows matching the free-text ``value``."""
        ...



@dataclass(frozen=True)
class SearchResult:
    """Outcome of a search.

    ``queryset``      the (possibly filtered) queryset.
    ``matched_fields`` list of field names that were searched.
    ``strategy``      one of ``"typed"``, ``"text"``, ``"none"`` or ``"empty"``.
    ``matcher``       the winning matcher name for typed routing (else ``None``).
    """

    queryset: QuerySet
    matched_fields: list[str] = dc_field(default_factory=list)
    strategy: str = "none"
    matcher: str | None = None

    @property
    def search_field(self) -> str | None:
        """Comma-joined matched fields, or ``None`` — handy for paginators."""
        return ",".join(self.matched_fields) if self.matched_fields else None


def _split_terms(value: str) -> list[str]:
    """Split into terms, honouring simple quoting (``"a b"`` -> one term)."""
    value = value.strip()
    try:
        terms = shlex.split(value)
    except ValueError:
        terms = value.split()
    return [t for t in terms if t]


class SearchEngine:
    """Stateless engine that applies the routing algorithm.

    An instance binds the compiled fields, matcher registry and settings and
    precomputes its routing plans. It is immutable after construction and safe
    to cache and reuse across requests and threads. It never mutates its inputs.
    """

    __slots__ = (
        "_annotation_fields",
        "_settings",
        "_text_field_names",
        "_text_plan",
        "_text_provider",
        "_typed_plan",
    )

    def __init__(
        self,
        fields: Sequence[SearchField],
        matchers: dict[str, Matcher],
        settings: DynamicSearchSettings,
        text_provider: TextSearchProvider | None = None,
    ) -> None:
        self._settings = settings
        # Optional pluggable free-text backend (e.g. Elasticsearch). When set,
        # it replaces the ORM free-text branch; typed routing is unaffected.
        self._text_provider = text_provider


        # --- typed routing plan (built once) --------------------------------
        # Resolve every matcher-bound field to its Matcher up front and drop
        # fields whose matcher is not registered. Order by descending matcher
        # priority; Python's stable sort preserves declaration order among
        # equal priorities, giving deterministic "first match wins" semantics.
        typed_plan: list[tuple[SearchField, Matcher]] = []
        for sf in fields:
            if not sf.matcher:
                continue
            matcher = matchers.get(sf.matcher)
            if matcher is None:
                continue
            typed_plan.append((sf, matcher))
        typed_plan.sort(key=lambda pair: -pair[1].priority)
        self._typed_plan: tuple[tuple[SearchField, Matcher], ...] = tuple(typed_plan)

        # --- free-text plan (built once) ------------------------------------
        # Precompute the final ORM lookup path for every text-searchable field
        # so the hot loop only does dict construction, never str.join.
        text_plan: list[tuple[str, SearchField]] = []
        text_names: list[str] = []
        for sf in fields:
            if not sf.is_text_searchable:
                continue
            lookup = (
                sf.lookup
                if (sf.lookup is not None and sf.lookup in TEXT_LOOKUPS)
                else settings.default_text_lookup
            )
            text_plan.append((sf.orm_path(lookup), sf))
            text_names.append(sf.field)
        self._text_plan: tuple[tuple[str, SearchField], ...] = tuple(text_plan)
        self._text_field_names: tuple[str, ...] = tuple(text_names)

        # De-duplicated annotation callables for the fallback (apply each once).
        annotation_fields: list[SearchField] = []
        seen_ann: set[str] = set()
        for _key, sf in text_plan:
            if sf.annotate is not None and sf.field not in seen_ann:
                annotation_fields.append(sf)
                seen_ann.add(sf.field)
        self._annotation_fields: tuple[SearchField, ...] = tuple(annotation_fields)

    # --- public API ---------------------------------------------------------

    def search(self, queryset: QuerySet, value: str) -> SearchResult:
        value = value.strip()
        if not value:
            return SearchResult(queryset=queryset, strategy="none")

        typed = self._route_typed(queryset, value)
        if typed is not None:
            return typed

        # Free-text branch. When a provider is configured (e.g. Elasticsearch)
        # it fully owns this branch; otherwise fall back to the ORM search.
        if self._text_provider is not None:
            qs = self._text_provider.search(queryset, value)
            return SearchResult(
                queryset=qs,
                matched_fields=list(self._text_field_names),
                strategy="text",
            )

        if self._text_plan:
            return self._free_text(queryset, value)

        if self._settings.empty_on_no_match:

            return SearchResult(queryset=queryset.none(), strategy="empty")
        return SearchResult(queryset=queryset, strategy="none")

    # --- typed routing ------------------------------------------------------

    def _route_typed(self, queryset: QuerySet, value: str) -> SearchResult | None:
        for search_field, matcher in self._typed_plan:
            if not matcher.matches(value):
                continue

            if search_field.queryset_builder is not None:
                qs = search_field.queryset_builder(queryset, value)
                return SearchResult(
                    queryset=qs,
                    matched_fields=[search_field.field],
                    strategy="typed",
                    matcher=matcher.name,
                )

            if search_field.annotate is not None:
                queryset = search_field.annotate(queryset, search_field.join)

            lookup = search_field.lookup or matcher.lookup
            queryset = queryset.filter(search_field.build_q(value, lookup))
            return SearchResult(
                queryset=queryset,
                matched_fields=[search_field.field],
                strategy="typed",
                matcher=matcher.name,
            )
        return None

    # --- free-text fallback -------------------------------------------------

    def _free_text(self, queryset: QuerySet, value: str) -> SearchResult:
        terms = _split_terms(value)
        if not terms:
            return SearchResult(queryset=queryset, strategy="none")

        # Apply each required annotation exactly once, before filtering.
        for sf in self._annotation_fields:
            queryset = sf.annotate(queryset, sf.join)  # type: ignore[misc]

        text_plan = self._text_plan
        for term in terms:  # AND across terms
            term_q = Q()
            for key, _sf in text_plan:  # OR across fields (precompiled paths)
                term_q |= Q(**{key: term})
            queryset = queryset.filter(term_q)

        return SearchResult(
            queryset=queryset,
            matched_fields=list(self._text_field_names),
            strategy="text",
        )
