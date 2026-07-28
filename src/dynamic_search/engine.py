"""The search engine — routes a value to the optimal queryset.

The engine is pure and framework-agnostic: it takes a queryset, a raw search
string, the compiled :class:`~dynamic_search.config.SearchField` list, the
matcher registry, and returns a :class:`SearchResult`. It performs no I/O and
has no knowledge of DRF or HTTP — which keeps it trivially unit-testable and
reusable outside a view (Clean Architecture / Low Coupling).

Routing algorithm
-----------------

1. **Typed routing** — for each registered matcher, in the order the fields are
   declared, test whether the *whole* value matches. The first matcher that
   both (a) matches the value and (b) is bound to a declared field wins. A
   single, index-friendly predicate is produced.
2. **Free-text fallback** — if no matcher wins, run a DRF-style multi-term
   search across every text-searchable field: **AND across terms, OR across
   fields**, honouring quoted phrases.
3. **No match** — if there are no text-searchable fields, optionally narrow the
   queryset to ``none()`` (configurable) to avoid leaking the whole table.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field as dc_field
from typing import Dict, List, Optional, Sequence, Tuple

from django.db.models import Q, QuerySet

from .config import SearchField
from .lookups import TEXT_LOOKUPS
from .matchers import Matcher
from .settings import DynamicSearchSettings

__all__ = ["SearchResult", "SearchEngine"]


@dataclass(frozen=True)
class SearchResult:
    """Outcome of a search.

    ``queryset``      the (possibly filtered) queryset.
    ``matched_fields`` list of field names that were searched.
    ``strategy``      one of ``"typed"``, ``"text"``, ``"none"`` or ``"empty"``.
    ``matcher``       the winning matcher name for typed routing (else ``None``).
    """

    queryset: QuerySet
    matched_fields: List[str] = dc_field(default_factory=list)
    strategy: str = "none"
    matcher: Optional[str] = None

    @property
    def search_field(self) -> Optional[str]:
        """Comma-joined matched fields, or ``None`` — handy for paginators."""
        return ",".join(self.matched_fields) if self.matched_fields else None


def _split_terms(value: str) -> List[str]:
    """Split into terms, honouring simple quoting (``"a b"`` -> one term)."""
    value = value.strip()
    try:
        terms = shlex.split(value)
    except ValueError:
        terms = value.split()
    return [t for t in terms if t]


class SearchEngine:
    """Stateless engine that applies the routing algorithm.

    An instance binds the compiled fields, matcher registry and settings; it is
    cheap to build and safe to reuse. It never mutates its inputs.
    """

    def __init__(
        self,
        fields: Sequence[SearchField],
        matchers: Dict[str, Matcher],
        settings: DynamicSearchSettings,
    ) -> None:
        self._fields = list(fields)
        self._matchers = matchers
        self._settings = settings
        self._text_fields = [f for f in self._fields if f.is_text_searchable]

    # --- public API ---------------------------------------------------------

    def search(self, queryset: QuerySet, value: str) -> SearchResult:
        value = value.strip()
        if not value:
            return SearchResult(queryset=queryset, strategy="none")

        typed = self._route_typed(queryset, value)
        if typed is not None:
            return typed

        if self._text_fields:
            return self._free_text(queryset, value)

        if self._settings.empty_on_no_match:
            return SearchResult(queryset=queryset.none(), strategy="empty")
        return SearchResult(queryset=queryset, strategy="none")

    # --- typed routing ------------------------------------------------------

    def _route_typed(self, queryset: QuerySet, value: str) -> Optional[SearchResult]:
        match = self._find_matching_field(value)
        if match is None:
            return None
        search_field, matcher = match

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

    def _find_matching_field(
        self, value: str
    ) -> Optional[Tuple[SearchField, Matcher]]:
        """First declared field whose bound matcher matches the whole value."""
        for search_field in self._fields:
            if not search_field.matcher:
                continue
            matcher = self._matchers.get(search_field.matcher)
            if matcher is None:
                continue
            if matcher.matches(value):
                return search_field, matcher
        return None

    # --- free-text fallback -------------------------------------------------

    def _free_text(self, queryset: QuerySet, value: str) -> SearchResult:
        terms = _split_terms(value)
        if not terms:
            return SearchResult(queryset=queryset, strategy="none")

        queryset = self._apply_annotations(queryset)

        # Fields backed by a custom queryset_builder cannot join a Q-OR chain;
        # they are excluded from the free-text OR (they only serve typed routing).
        q_fields = [f for f in self._text_fields if f.queryset_builder is None]
        if not q_fields:
            return SearchResult(queryset=queryset, strategy="none")

        for term in terms:  # AND across terms
            term_q = Q()
            for sf in q_fields:  # OR across fields
                lookup = self._text_lookup_for(sf)
                term_q |= sf.build_q(term, lookup)
            queryset = queryset.filter(term_q)

        return SearchResult(
            queryset=queryset,
            matched_fields=[f.field for f in q_fields],
            strategy="text",
        )

    def _text_lookup_for(self, sf: SearchField) -> str:
        if sf.lookup is not None and sf.lookup in TEXT_LOOKUPS:
            return sf.lookup
        return self._settings.default_text_lookup

    def _apply_annotations(self, queryset: QuerySet) -> QuerySet:
        seen: set[str] = set()
        for sf in self._text_fields:
            if sf.annotate is not None and sf.field not in seen:
                queryset = sf.annotate(queryset, sf.join)
                seen.add(sf.field)
        return queryset
