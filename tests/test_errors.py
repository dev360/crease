"""Unit tests for the pydantic-shaped error model."""

from __future__ import annotations

import pytest

from crease import Error, ValidationError
from crease._errors import STRUCTURAL_TYPES, severity_for


class TestErrorShape:
    """The Error type matches the pydantic .errors() shape."""

    def test_loc_is_tuple(self) -> None:
        e = Error(type="wrong_type", loc=("order", 47, "quantity"))
        assert e.loc == ("order", 47, "quantity")
        assert isinstance(e.loc, tuple)

    def test_severity_derived_from_type(self) -> None:
        cell = Error(type="missing_required", loc=("o", 0, "x"))
        assert cell.severity == "cell"
        assert cell.is_cell
        assert not cell.is_structural

        structural = Error(type="missing_tab", loc=("o", None, None))
        assert structural.severity == "structural"
        assert structural.is_structural
        assert not structural.is_cell

    def test_severity_helper_matches_table(self) -> None:
        for t in STRUCTURAL_TYPES:
            assert severity_for(t) == "structural", f"{t} should be structural"
        for t in ("missing_required", "wrong_type", "pattern_mismatch", "enum_violation"):
            assert severity_for(t) == "cell", f"{t} should be cell"

    def test_to_dict_omits_empties(self) -> None:
        e = Error(type="missing_tab", loc=("order", None, None))
        d = e.to_dict()
        assert d["type"] == "missing_tab"
        assert d["loc"] == ["order", None, None]
        assert "input" not in d
        assert "ctx" not in d

    def test_to_dict_preserves_filled_fields(self) -> None:
        e = Error(
            type="wrong_type",
            loc=("order", 0, "qty"),
            msg="not an int",
            input="abc",
            ctx={"likely_cause": "excel_autoconvert"},
        )
        d = e.to_dict()
        assert d["msg"] == "not an int"
        assert d["input"] == "abc"
        assert d["ctx"] == {"likely_cause": "excel_autoconvert"}


class TestValidationError:
    """The exception carries errors() like pydantic's ValidationError."""

    def test_errors_returns_a_copy(self) -> None:
        errs = [Error(type="missing_required", loc=("o", 0, "x"))]
        ve = ValidationError(errs)
        out = ve.errors()
        out.append(Error(type="wrong_type", loc=("o", 1, "y")))
        # internal list unaffected
        assert ve.error_count() == 1

    def test_error_count(self) -> None:
        errs = [
            Error(type="missing_required", loc=("o", 0, "x")),
            Error(type="wrong_type", loc=("o", 1, "y")),
        ]
        ve = ValidationError(errs)
        assert ve.error_count() == 2

    def test_default_message_includes_first_error(self) -> None:
        errs = [Error(type="missing_required", loc=("order", 47, "email"))]
        ve = ValidationError(errs)
        assert "missing_required" in str(ve)
        assert "order" in str(ve)
        assert "email" in str(ve)

    def test_message_handles_empty_locs(self) -> None:
        errs = [Error(type="missing_tab", loc=("order", None, None))]
        ve = ValidationError(errs)
        # should not crash on None elements in loc
        assert "missing_tab" in str(ve)

    def test_empty_errors_message(self) -> None:
        ve = ValidationError([])
        assert "no errors" in str(ve)

    def test_raisable(self) -> None:
        errs = [Error(type="missing_required", loc=("o", 0, "x"))]
        with pytest.raises(ValidationError) as exc_info:
            raise ValidationError(errs)
        assert exc_info.value.error_count() == 1
