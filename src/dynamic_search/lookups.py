"""Supported ORM lookups.

The library deliberately supports a curated, index-friendly subset of Django
field lookups. Lookups are split into two families:

* :data:`EXACT_LOOKUPS` — whole-value lookups used for *typed routing*.
* :data:`TEXT_LOOKUPS` — partial/substring lookups used for the *free-text*
  fallback search.
"""

from __future__ import annotations

from typing import FrozenSet

__all__ = [
    "EXACT_LOOKUPS",
    "TEXT_LOOKUPS",
    "VALID_LOOKUPS",
    "is_text_lookup",
    "is_valid_lookup",
]

EXACT_LOOKUPS: FrozenSet[str] = frozenset({"exact", "iexact"})

TEXT_LOOKUPS: FrozenSet[str] = frozenset(
    {
        "contains",
        "icontains",
        "startswith",
        "istartswith",
        "endswith",
        "iendswith",
    }
)

VALID_LOOKUPS: FrozenSet[str] = EXACT_LOOKUPS | TEXT_LOOKUPS


def is_text_lookup(lookup: str) -> bool:
    """Return ``True`` if ``lookup`` participates in the free-text fallback."""
    return lookup in TEXT_LOOKUPS


def is_valid_lookup(lookup: str) -> bool:
    """Return ``True`` if ``lookup`` is a supported lookup."""
    return lookup in VALID_LOOKUPS
