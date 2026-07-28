"""Tests for view-level config compilation and validation."""

from __future__ import annotations

import pytest

from dynamic_search.config import SearchField, compile_search_fields
from dynamic_search.exceptions import (
    InvalidConfigurationError,
    InvalidJoinError,
    InvalidLookupError,
    MissingFieldError,
)
from dynamic_search.helpers import concat_annotation

pytestmark = pytest.mark.django_db


def _model():
    from tests.models import Account

    return Account


def test_compile_simple_field():
    fields = compile_search_fields([{"field": "username"}], _model())
    assert len(fields) == 1
    sf = fields[0]
    assert isinstance(sf, SearchField)
    assert sf.field == "username"
    assert sf.matcher == "username"  # defaults to field name


def test_compile_related_field():
    fields = compile_search_fields(
        [{"field": "national_code", "join": "user"}], _model()
    )
    assert fields[0].orm_path("exact") == "user__national_code__exact"


def test_compile_lookup_override():
    fields = compile_search_fields(
        [{"field": "username", "lookup": "icontains"}], _model()
    )
    assert fields[0].lookup == "icontains"
    assert fields[0].is_text_searchable is True


def test_missing_field_key_raises():
    with pytest.raises(MissingFieldError):
        compile_search_fields([{"join": "user"}], _model())


def test_missing_model_field_raises():
    with pytest.raises(MissingFieldError):
        compile_search_fields([{"field": "does_not_exist"}], _model())


def test_invalid_join_raises():
    with pytest.raises(InvalidJoinError):
        compile_search_fields(
            [{"field": "national_code", "join": "not_a_relation"}], _model()
        )


def test_invalid_lookup_raises():
    with pytest.raises(InvalidLookupError):
        compile_search_fields([{"field": "username", "lookup": "regex"}], _model())


def test_unknown_key_raises():
    with pytest.raises(InvalidConfigurationError):
        compile_search_fields([{"field": "username", "bogus": 1}], _model())


def test_entry_not_dict_raises():
    with pytest.raises(InvalidConfigurationError):
        compile_search_fields(["username"], _model())  # type: ignore[list-item]


def test_config_not_list_raises():
    with pytest.raises(InvalidConfigurationError):
        compile_search_fields({"field": "username"}, _model())  # type: ignore[arg-type]


def test_duplicate_field_raises():
    with pytest.raises(InvalidConfigurationError):
        compile_search_fields([{"field": "username"}, {"field": "username"}], _model())


def test_bad_join_type_raises():
    with pytest.raises(InvalidJoinError):
        compile_search_fields([{"field": "username", "join": 5}], _model())


def test_bad_matcher_type_raises():
    with pytest.raises(InvalidConfigurationError):
        compile_search_fields([{"field": "username", "matcher": 5}], _model())


def test_bad_annotate_raises():
    with pytest.raises(InvalidConfigurationError):
        compile_search_fields([{"field": "full_name", "annotate": "nope"}], _model())


def test_annotation_field_skips_model_validation():
    fields = compile_search_fields(
        [
            {
                "field": "full_name",
                "annotate": concat_annotation(
                    "full_name", ["first_name", "last_name"], join="user"
                ),
                "lookup": "icontains",
            }
        ],
        _model(),
    )
    sf = fields[0]
    # Annotation aliases must not be prefixed by join.
    assert sf.orm_path("icontains") == "full_name__icontains"


def test_matcher_none_disables_routing():
    fields = compile_search_fields(
        [{"field": "username", "matcher": None, "lookup": "icontains"}], _model()
    )
    assert fields[0].matcher is None


def test_queryset_builder_field_not_text_searchable():
    fields = compile_search_fields(
        [{"field": "username", "queryset_builder": lambda qs, v: qs}], _model()
    )
    assert fields[0].is_text_searchable is False


def test_bad_queryset_builder_type_raises():
    with pytest.raises(InvalidConfigurationError):
        compile_search_fields(
            [{"field": "username", "queryset_builder": "nope"}], _model()
        )


def test_text_flag_forces_text_searchable_with_exact_lookup():
    fields = compile_search_fields(
        [{"field": "username", "lookup": "exact", "text": True, "matcher": None}],
        _model(),
    )
    assert fields[0].is_text_searchable is True


def test_deep_join_through_non_relation_raises():
    # ``username`` is a CharField, so walking through it as a relation must fail.
    with pytest.raises(InvalidJoinError):
        compile_search_fields([{"field": "x", "join": "username__deeper"}], _model())


def test_empty_join_string_raises():
    with pytest.raises(InvalidJoinError):
        compile_search_fields([{"field": "username", "join": ""}], _model())
