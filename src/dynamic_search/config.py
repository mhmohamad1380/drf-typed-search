"""View-level search configuration.

A view declares *what* is searchable via ``search_fields_config`` — a list of
plain dicts. Each dict is compiled (once per view class, cached) into an
immutable :class:`SearchField`, validated against the model.

Config keys
-----------

``field`` (required)
    The model field name, related field name, or annotation alias to filter.

``join`` (optional)
    A relation path prefix (e.g. ``"user"`` or ``"loan__user"``) prepended to
    ``field`` when building the ORM lookup.

``lookup`` (optional)
    Overrides the lookup used for this field. When a *matcher* wins routing,
    the matcher's lookup is used unless this key overrides it. When this field
    participates in the free-text fallback, this lookup (if a text lookup) is
    used instead of the global default.

``matcher`` (optional)
    Explicit matcher name to bind this field to. Defaults to ``field`` — so a
    field named ``national_code`` is automatically routed by a matcher named
    ``national_code`` if one is registered. Set to ``None`` to disable typed
    routing for this field (free-text only).

``annotate`` (optional)
    A callable ``(queryset, prefix) -> queryset`` applied before filtering,
    used for computed fields (e.g. a ``Concat`` full-name annotation).

``queryset_builder`` (optional)
    A callable ``(queryset, value) -> queryset`` that fully owns filtering for
    this field, bypassing the default ``Q`` construction. Enables arbitrary
    custom SQL / trigram / full-text strategies.

``text`` (optional, bool)
    Force this field into the free-text fallback even when its ``lookup`` is an
    exact lookup (the global ``DEFAULT_TEXT_LOOKUP`` is then used for text).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, cast

from django.core.exceptions import FieldDoesNotExist
from django.db.models import Model, Q, QuerySet


from .exceptions import (
    InvalidConfigurationError,
    InvalidJoinError,
    InvalidLookupError,
    MissingFieldError,
)
from .lookups import VALID_LOOKUPS, is_text_lookup

__all__ = [
    "SearchField",
    "compile_search_fields",
]

AnnotateFunc = Callable[[QuerySet, Optional[str]], QuerySet]
QuerysetBuilder = Callable[[QuerySet, str], QuerySet]

_ALLOWED_KEYS = {
    "field",
    "join",
    "lookup",
    "matcher",
    "annotate",
    "queryset_builder",
    "text",
}

# Sentinel to distinguish "matcher not provided" from "matcher explicitly None".
_UNSET = object()


@dataclass(frozen=True)
class SearchField:
    """A compiled, validated searchable field."""

    field: str
    join: Optional[str] = None
    lookup: Optional[str] = None
    matcher: Optional[str] = None
    annotate: Optional[AnnotateFunc] = None
    queryset_builder: Optional[QuerysetBuilder] = None
    text: bool = False

    # --- lookup construction ------------------------------------------------

    def orm_path(self, lookup: Optional[str] = None) -> str:
        """Build the ORM lookup path, e.g. ``user__national_code__exact``.

        Annotation aliases are *not* prefixed with ``join`` — the relation is
        assumed to be baked into the annotation itself.
        """
        if self.annotate is not None:
            segments = [self.field, lookup]
        else:
            segments = [self.join, self.field, lookup]
        return "__".join(s for s in segments if s)

    def build_q(self, value: str, lookup: str) -> Q:
        """Build a ``Q`` object for ``value`` using ``lookup``."""
        return Q(**{self.orm_path(lookup): value})

    @property
    def is_text_searchable(self) -> bool:
        """Whether this field participates in the free-text fallback."""
        if self.queryset_builder is not None:
            return False
        if self.text:
            return True
        return self.lookup is not None and is_text_lookup(self.lookup)


def _validate_keys(index: int, entry: Mapping[str, Any]) -> None:
    unknown = set(entry) - _ALLOWED_KEYS
    if unknown:
        raise InvalidConfigurationError(
            f"search_fields_config[{index}] has unknown keys {sorted(unknown)}. "
            f"Allowed keys: {sorted(_ALLOWED_KEYS)}."
        )


def _resolve_model_field(model: type[Model], path: str, *, index: int) -> None:
    """Walk a ``a__b__c`` relation path and validate each hop exists."""
    parts = path.split("__")
    current: Optional[type[Model]] = model
    for i, part in enumerate(parts):
        if current is None:
            raise InvalidJoinError(
                f"search_fields_config[{index}]: cannot resolve {path!r}; "
                f"{'__'.join(parts[:i])!r} is not a relation."
            )
        try:
            field = current._meta.get_field(part)
        except FieldDoesNotExist as exc:
            # Distinguish a bad join hop from a bad final field.
            is_last = i == len(parts) - 1
            error = MissingFieldError if is_last else InvalidJoinError
            raise error(
                f"search_fields_config[{index}]: "
                f"{'field' if is_last else 'join relation'} {part!r} "
                f"does not exist on {current.__name__}."
            ) from exc
        related = getattr(field, "related_model", None)
        current = related


def compile_entry(
    index: int, entry: Mapping[str, Any], model: type[Model]
) -> SearchField:
    """Validate and compile a single config dict into a :class:`SearchField`."""
    if not isinstance(entry, Mapping):
        raise InvalidConfigurationError(
            f"search_fields_config[{index}] must be a dict; got {type(entry).__name__!r}."
        )
    _validate_keys(index, entry)

    field = entry.get("field")
    if not field or not isinstance(field, str):
        raise MissingFieldError(
            f"search_fields_config[{index}] must define a non-empty string 'field'."
        )

    join = entry.get("join")
    if join is not None and (not isinstance(join, str) or not join):
        raise InvalidJoinError(
            f"search_fields_config[{index}] 'join' must be a non-empty string or omitted."
        )

    lookup = entry.get("lookup")
    if lookup is not None and lookup not in VALID_LOOKUPS:
        raise InvalidLookupError(
            f"search_fields_config[{index}] uses invalid lookup {lookup!r}. "
            f"Valid lookups: {sorted(VALID_LOOKUPS)}."
        )

    annotate = entry.get("annotate")
    if annotate is not None and not callable(annotate):
        raise InvalidConfigurationError(
            f"search_fields_config[{index}] 'annotate' must be callable."
        )

    queryset_builder = entry.get("queryset_builder")
    if queryset_builder is not None and not callable(queryset_builder):
        raise InvalidConfigurationError(
            f"search_fields_config[{index}] 'queryset_builder' must be callable."
        )

    matcher_spec = entry.get("matcher", _UNSET)
    if matcher_spec is _UNSET:
        matcher_name: Optional[str] = field
    else:
        if matcher_spec is not None and not isinstance(matcher_spec, str):
            raise InvalidConfigurationError(
                f"search_fields_config[{index}] 'matcher' must be a string or None."
            )
        matcher_name = matcher_spec

    # Validate the field path against the model unless the field is a computed
    # annotation or fully custom builder (those own their own resolution).
    if annotate is None and queryset_builder is None:
        path = "__".join(p for p in [join, field] if p)
        _resolve_model_field(model, path, index=index)

    return SearchField(
        field=field,
        join=join,
        lookup=lookup,
        matcher=matcher_name,
        annotate=cast("Optional[AnnotateFunc]", annotate),
        queryset_builder=cast("Optional[QuerysetBuilder]", queryset_builder),
        text=bool(entry.get("text", False)),
    )


def compile_search_fields(
    config: Sequence[Mapping[str, Any]], model: type[Model]
) -> List[SearchField]:
    """Compile and validate a view's whole ``search_fields_config``."""
    if not isinstance(config, (list, tuple)):
        raise InvalidConfigurationError(
            "search_fields_config must be a list of dicts; "
            f"got {type(config).__name__!r}."
        )
    compiled = [compile_entry(i, entry, model) for i, entry in enumerate(config)]

    # Duplicate field detection (same field+join declared twice is a mistake).
    seen: Dict[str, int] = {}
    for i, sf in enumerate(compiled):
        key = sf.orm_path()
        if key in seen:
            raise InvalidConfigurationError(
                f"search_fields_config[{i}] duplicates the field path {key!r} "
                f"already declared at index {seen[key]}."
            )
        seen[key] = i
    return compiled
