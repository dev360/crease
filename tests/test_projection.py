"""Unit tests for the projection API: iter / get / to_pydantic / to_pandas / Template.model.

Uses test_cases/flat_simple as a clean baseline and test_cases/corrupted_wrong_type
to exercise halt-by-default vs allow_partial behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from crease import Template, ValidationError, extract

CORPUS_ROOT = Path(__file__).parent.parent / "test_cases"
CLEAN_CASE = CORPUS_ROOT / "flat_simple"
DIRTY_CASE = CORPUS_ROOT / "corrupted_wrong_type"


def _load_clean():
    template = Template.load(CLEAN_CASE / "template.yml")
    return extract(CLEAN_CASE / "input.xlsx", template), template


def _load_dirty():
    template = Template.load(DIRTY_CASE / "template.yml")
    return extract(DIRTY_CASE / "input.xlsx", template), template


# ---- Template.model() ----------------------------------------------------


class TestTemplateModel:
    def test_generates_class_with_entity_fields(self) -> None:
        _, template = _load_clean()
        entity_name = template.entities[0].name
        Model = template.model(entity_name)

        assert issubclass(Model, BaseModel)
        for f in template.entities[0].fields:
            assert f.name in Model.model_fields, f"missing field {f.name}"

    def test_unknown_entity_raises_keyerror(self) -> None:
        _, template = _load_clean()
        with pytest.raises(KeyError):
            template.model("nope_does_not_exist")

    def test_generated_model_ignores_extra_fields(self) -> None:
        """extra='ignore' so projecting records with extra keys doesn't break."""
        _, template = _load_clean()
        Model = template.model(template.entities[0].name)
        sample = {f.name: _sample_value(f.type) for f in template.entities[0].fields}
        sample["unexpected_extra_key"] = "should be silently dropped"
        instance = Model.model_validate(sample)
        assert not hasattr(instance, "unexpected_extra_key")


def _sample_value(field_type: str):
    import datetime as dt

    return {
        "string": "x",
        "integer": 1,
        "number": 1.0,
        "boolean": True,
        "email": "a@b.co",
        "uuid": "00000000-0000-0000-0000-000000000000",
        "url": "https://x",
        "date": dt.date(2025, 1, 1),
        "datetime": dt.datetime(2025, 1, 1, 0, 0, 0),
    }.get(field_type, "x")


# ---- iter / get / to_pydantic / to_pandas (happy path) -------------------


class TestProjectionHappyPath:
    def test_iter_yields_dicts(self) -> None:
        result, template = _load_clean()
        entity = _pick_many_entity(template)
        if entity is None:
            pytest.skip("no cardinality=many entity in flat_simple")

        rows = list(result.iter(entity))
        assert rows, "expected at least one row"
        assert all(isinstance(r, dict) for r in rows)

    def test_iter_with_model_yields_pydantic_instances(self) -> None:
        result, template = _load_clean()
        entity = _pick_many_entity(template)
        if entity is None:
            pytest.skip("no cardinality=many entity in flat_simple")

        Model = template.model(entity)
        rows = list(result.iter(entity, model=Model))
        assert rows
        assert all(isinstance(r, Model) for r in rows)

    def test_to_pydantic_with_auto_model(self) -> None:
        result, template = _load_clean()
        entity = _pick_many_entity(template)
        if entity is None:
            pytest.skip("no cardinality=many entity in flat_simple")

        rows = result.to_pydantic(entity)
        assert isinstance(rows, list)
        assert rows  # at least one
        assert all(isinstance(r, BaseModel) for r in rows)

    def test_to_pydantic_with_subset_model_drops_extra_fields(self) -> None:
        """A user-supplied model with fewer fields than the template should
        succeed — extra canonical keys are silently dropped."""
        result, template = _load_clean()
        entity = _pick_many_entity(template)
        if entity is None:
            pytest.skip("no cardinality=many entity in flat_simple")

        first_field = template.entities[0].fields[0]
        py_type = {"string": str, "integer": int, "number": float, "boolean": bool}.get(
            first_field.type, str
        )

        class MinimalSubset(BaseModel):
            pass

        # Build dynamically so we don't hardcode the entity name.
        from pydantic import ConfigDict, create_model

        Subset = create_model(
            "Subset",
            __config__=ConfigDict(extra="ignore", strict=True),
            **{first_field.name: (py_type, ...)},
        )
        rows = result.to_pydantic(entity, model=Subset)
        assert all(isinstance(r, Subset) for r in rows)

    def test_to_pandas(self) -> None:
        pd = pytest.importorskip("pandas")
        result, template = _load_clean()
        entity = _pick_many_entity(template)
        if entity is None:
            pytest.skip("no cardinality=many entity in flat_simple")

        df = result.to_pandas(entity)
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0


# ---- halt-by-default vs allow_partial -----------------------------------


class TestHaltByDefault:
    def test_to_pydantic_halts_by_default_when_errors_present(self) -> None:
        result, template = _load_dirty()
        entity = _pick_many_entity(template)
        if entity is None:
            pytest.skip("no cardinality=many entity in corrupted_wrong_type")

        assert not result.report.is_valid, "fixture should produce errors"
        with pytest.raises(ValidationError):
            result.to_pydantic(entity)

    def test_to_pydantic_allow_partial_returns_rows(self) -> None:
        result, template = _load_dirty()
        entity = _pick_many_entity(template)
        if entity is None:
            pytest.skip("no cardinality=many entity in corrupted_wrong_type")

        rows = result.to_pydantic(entity, allow_partial=True)
        assert isinstance(rows, list)
        # Errors are still discoverable on the report.
        assert not result.report.is_valid

    def test_iter_halts_by_default_when_errors_present(self) -> None:
        result, template = _load_dirty()
        entity = _pick_many_entity(template)
        if entity is None:
            pytest.skip("no cardinality=many entity in corrupted_wrong_type")

        with pytest.raises(ValidationError):
            list(result.iter(entity))

    def test_to_pandas_halts_by_default(self) -> None:
        pytest.importorskip("pandas")
        result, template = _load_dirty()
        entity = _pick_many_entity(template)
        if entity is None:
            pytest.skip("no cardinality=many entity in corrupted_wrong_type")

        with pytest.raises(ValidationError):
            result.to_pandas(entity)


# ---- cardinality enforcement --------------------------------------------


class TestCardinalityEnforcement:
    def test_iter_rejects_cardinality_one(self) -> None:
        """iter() on a cardinality=one entity is a category error."""
        case = CORPUS_ROOT / "property_sheet_cover"
        if not (case / "input.xlsx").exists():
            pytest.skip("property_sheet_cover fixture missing")

        template = Template.load(case / "template.yml")
        result = extract(case / "input.xlsx", template)
        one_entity = next((e.name for e in template.entities if e.cardinality == "one"), None)
        if one_entity is None:
            pytest.skip("no cardinality=one entity")

        with pytest.raises(ValueError, match="cardinality='one'"):
            list(result.iter(one_entity, allow_partial=True))

    def test_get_rejects_cardinality_many(self) -> None:
        result, template = _load_clean()
        many_entity = _pick_many_entity(template)
        if many_entity is None:
            pytest.skip("no cardinality=many entity")

        with pytest.raises(ValueError, match="cardinality='many'"):
            result.get(many_entity, allow_partial=True)


# ---- helpers -------------------------------------------------------------


def _pick_many_entity(template) -> str | None:
    for e in template.entities:
        if e.cardinality == "many":
            return e.name
    return None
