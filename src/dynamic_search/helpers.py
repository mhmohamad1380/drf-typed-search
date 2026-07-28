"""Optional, generic helpers for building annotations.

These utilities are *conveniences*, not requirements — they contain no
business logic. The most common need is a concatenated "full name" style
annotation, so a small generic builder is provided.
"""

from __future__ import annotations

from collections.abc import Sequence

from django.db.models import CharField, F, QuerySet, Value
from django.db.models.functions import Concat

__all__ = ["concat_annotation"]


def concat_annotation(
    alias: str,
    fields: Sequence[str],
    *,
    separator: str = " ",
    join: str | None = None,
):
    """Return an ``annotate`` callable that concatenates ``fields`` into ``alias``.

    Example::

        {
            "field": "full_name",
            "annotate": concat_annotation(
                "full_name", ["first_name", "last_name"], join="user"
            ),
            "lookup": "icontains",
        }


    The resulting callable has the signature ``(queryset, prefix) -> queryset``
    expected by the config's ``annotate`` key. ``join`` (and the runtime
    ``prefix``) are combined to resolve the relation path to the source fields.
    """
    if not fields:
        raise ValueError("concat_annotation requires at least one field.")

    def annotate(queryset: QuerySet, prefix: str | None = None) -> QuerySet:
        parts = [p for p in (prefix, join) if p]
        base = "__".join(parts)

        expressions = []
        for i, name in enumerate(fields):
            if i:
                expressions.append(Value(separator))
            path = f"{base}__{name}" if base else name
            expressions.append(F(path))

        return queryset.annotate(
            **{alias: Concat(*expressions, output_field=CharField())}
        )

    return annotate
