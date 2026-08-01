"""Pure Elasticsearch query builder.

This module contains **no I/O** — it only turns a free-text value and a list of
fields into an Elasticsearch query body (a plain ``dict``). Keeping it pure makes
the query shape trivially unit-testable without a running cluster and mirrors the
design of the core :mod:`dynamic_search.engine` (framework-agnostic, side-effect
free).

Query shape
-----------

The builder mirrors the database free-text semantics as closely as
Elasticsearch allows: **AND across terms, OR across fields**, with quoted
phrases preserved. It emits a ``bool`` query whose ``must`` clauses each match a
single term across every configured field (a ``multi_match``), so a document
must contain *every* term (in *some* field) to be returned — exactly like the
ORM ``.filter(term1).filter(term2)`` chain.

Quoted phrases (``"credit card"``) become ``phrase`` multi-matches; bare terms
use ``best_fields`` with fuzziness enabled so minor typos still match — the
behaviour that makes Elasticsearch worth reaching for over ``icontains``.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence

__all__ = ["build_search_query", "split_terms"]


def split_terms(value: str) -> list[tuple[str, bool]]:
    """Split ``value`` into ``(term, is_phrase)`` tuples, honouring quoting.

    A phrase is any run that was wrapped in quotes in the original input and
    contains whitespace, e.g. ``'"credit card"'`` -> ``[("credit card", True)]``.
    Because :func:`shlex.split` strips the quotes, we re-detect phrases by
    checking whether the token contains whitespace.
    """
    value = value.strip()
    if not value:
        return []
    try:
        tokens = shlex.split(value)
    except ValueError:
        tokens = value.split()
    return [(tok, " " in tok) for tok in tokens if tok]


def build_search_query(
    value: str,
    fields: Sequence[str],
    *,
    size: int = 1000,
    fuzziness: str = "AUTO",
    source: bool = False,
) -> dict:
    """Build an Elasticsearch search body for ``value`` over ``fields``.

    Args:
        value: The raw free-text search string (may contain quoted phrases).
        fields: The document fields to search across (OR).
        size: Maximum number of hits to request.
        fuzziness: Fuzziness applied to non-phrase terms (``"AUTO"`` by default).
        source: Whether to ask Elasticsearch to return ``_source``. The provider
            only needs document ids, so this defaults to ``False`` to keep
            responses small.

    Returns:
        A ``dict`` suitable to pass as the body / ``**kwargs`` of a client
        ``search`` call. When there are no terms or no fields, a
        ``match_none`` query is returned so callers get an empty result set
        rather than the whole index.
    """
    terms = split_terms(value)
    field_list = [f for f in fields if f]

    if not terms or not field_list:
        return {"size": 0, "_source": False, "query": {"match_none": {}}}

    must: list[dict] = []
    for term, is_phrase in terms:
        if is_phrase:
            clause = {
                "multi_match": {
                    "query": term,
                    "fields": field_list,
                    "type": "phrase",
                }
            }
        else:
            clause = {
                "multi_match": {
                    "query": term,
                    "fields": field_list,
                    "type": "best_fields",
                    "fuzziness": fuzziness,
                    "operator": "and",
                }
            }
        must.append(clause)

    return {
        "size": size,
        "_source": source,
        "query": {"bool": {"must": must}},
    }
