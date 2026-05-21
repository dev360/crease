"""Validate extracted canonical data against the template's constraints.

The validation step is a pure inspection — it produces a `Report` carrying
the same `Error` shape that extraction-time problems use. The report exposes
`is_valid`, `errors()`, and `error_count()` (mirroring Pydantic's
`ValidationError` API) so a Python developer can consume it without learning
crease-specific vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _dc_field
from pathlib import Path
from typing import Any

from crease._coerce import check_constraints
from crease._errors import Error, ValidationError
from crease._workbook import Engine
from crease.extractor import ExtractResult, extract
from crease.template_model import Entity, FieldSpec, Template


@dataclass
class Report:
    """Result of validating an `ExtractResult` against its template.

    Attributes:
        errors_list: The full list of `Error` records.

    The richer API surface (`is_valid`, `errors()`, `error_count()`) is
    accessed as methods/properties, matching the pydantic idiom.
    """

    errors_list: list[Error] = _dc_field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """``True`` iff zero errors. The 90% check."""
        return not self.errors_list

    def errors(self) -> list[Error]:
        """Return the full list of errors. Pydantic-shaped."""
        return list(self.errors_list)

    def error_count(self) -> int:
        return len(self.errors_list)

    @property
    def has_structural(self) -> bool:
        """``True`` if any error is structural (template can't map the file)."""
        return any(e.is_structural for e in self.errors_list)

    def raise_if_invalid(self) -> None:
        """If any errors are present, raise `ValidationError` with the full list."""
        if self.errors_list:
            raise ValidationError(self.errors_list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for JSON output."""
        return {
            "is_valid": self.is_valid,
            "error_count": self.error_count(),
            "errors": [e.to_dict() for e in self.errors_list],
        }


# ---- internals ----------------------------------------------------------


def _field_by_name(entity: Entity) -> dict[str, FieldSpec]:
    return {f.name: f for f in entity.fields}


def _check_record(
    record: dict[str, Any],
    entity: Entity,
    row_idx: int | None,
    errors: list[Error],
) -> None:
    fields = _field_by_name(entity)
    for name, value in record.items():
        spec = fields.get(name)
        if spec is None:
            # Enriched / injected fields are out-of-template — skip constraint checks.
            continue
        if value is None:
            if not spec.nullable:
                errors.append(
                    Error(
                        type="missing_required",
                        loc=(entity.name, row_idx, name),
                        msg=f"Field '{name}' is required and was blank",
                        input=None,
                    )
                )
            continue
        reason = check_constraints(value, spec)
        if reason:
            errors.append(
                Error(
                    type=reason,
                    loc=(entity.name, row_idx, name),
                    msg=f"Field '{name}' failed {reason}",
                    input=value,
                )
            )


def _check_duplicates(
    records: list[dict[str, Any]],
    entity: Entity,
    errors: list[Error],
) -> None:
    seen: dict[tuple, int] = {}
    keys = [f.name for f in entity.fields]
    for i, rec in enumerate(records):
        key = tuple(rec.get(k) for k in keys)
        if all(v is None for v in key):
            continue
        if key in seen:
            errors.append(
                Error(
                    type="duplicate_row",
                    loc=(entity.name, i, None),
                    msg=f"Row {i} is a duplicate of row {seen[key]}",
                    ctx={"duplicate_of": seen[key]},
                )
            )
        else:
            seen[key] = i


def validate(result: ExtractResult, template: Template) -> Report:
    """Validate an `ExtractResult` against a template's constraints.

    This is a pure inspection — it does not mutate `result`. The returned
    `Report` carries every error surfaced during extraction (structural and
    coercion problems) plus any constraint violations found in the canonical
    data.

    Args:
        result: The output of `crease.extract`.
        template: The same `Template` used to produce `result`.

    Returns:
        A `Report` describing every problem found.
    """
    errors: list[Error] = []

    # Lift extraction-time structural errors into the report.
    for err in result.errors:
        ctx = dict(err.details) if err.details else {}
        errors.append(
            Error(
                type=err.reason,
                loc=(err.entity or "", None, None),
                msg=_structural_msg(err.reason),
                ctx=ctx,
            )
        )

    # Lift extraction-time per-row coercion errors.
    for re_err in result.row_errors:
        ctx: dict[str, Any] = {}
        if re_err.likely_cause:
            ctx["likely_cause"] = re_err.likely_cause
        if re_err.expected:
            ctx["expected"] = re_err.expected
        if re_err.label_was:
            ctx["label_was"] = re_err.label_was
        errors.append(
            Error(
                type=re_err.reason,
                loc=(re_err.entity, re_err.row, re_err.field),
                msg=_row_msg(re_err.reason, re_err.field, re_err.expected),
                input=re_err.got,
                ctx=ctx,
            )
        )

    # Constraint checks across extracted records.
    for entity in template.entities:
        key_singular = entity.name
        key_plural = key_singular + "s" if not key_singular.endswith("s") else key_singular
        data = result.canonical.get(key_singular)
        if data is None:
            data = result.canonical.get(key_plural)
        if data is None:
            continue

        if entity.cardinality == "one":
            if isinstance(data, dict):
                _check_record(data, entity, row_idx=None, errors=errors)
        else:
            if isinstance(data, list):
                for i, rec in enumerate(data):
                    if not isinstance(rec, dict):
                        continue
                    _check_record(rec, entity, row_idx=i, errors=errors)
                if entity.locate.duplicate_policy == "error":
                    _check_duplicates(data, entity, errors)
                _check_data_density(data, entity, errors)

    return Report(errors_list=errors)


def _check_data_density(
    records: list[dict[str, Any]],
    entity: Entity,
    errors: list[Error],
) -> None:
    threshold = entity.locate.min_data_density
    if threshold is None or not records:
        return
    keys = [f.name for f in entity.fields]
    if not keys:
        return
    populated = 0
    for rec in records:
        if not isinstance(rec, dict):
            continue
        for k in keys:
            v = rec.get(k)
            if v is None:
                continue
            if isinstance(v, str) and v.strip() == "":
                continue
            populated += 1
    total = len(records) * len(keys)
    if total == 0:
        return
    density = populated / total
    if density < threshold:
        errors.append(
            Error(
                type="low_data_density",
                loc=(entity.name, None, None),
                msg=(f"Entity {entity.name!r} has data density {density:.2f}, " f"below threshold {threshold:.2f}"),
                ctx={"density": density, "threshold": threshold},
            )
        )


def _structural_msg(reason: str) -> str:
    return {
        "missing_tab": "Template's tab was not found in the workbook",
        "tab_pattern_no_match": "No tabs matched the template's tab_pattern",
        "header_mapping_failed": "Required header(s) not found in the worksheet",
        "header_duplicated": "source_column matched multiple header cells; set source_column_index to disambiguate",
        "header_above_nonblank": "Row above header_row has non-blank text; multi-row header likely",
        "entity_missing": "Entity could not be located in the workbook",
        "multiple_rows_for_cardinality_one": "Cardinality 'one' entity returned multiple rows",
        "column_count_mismatch": "Header row has the wrong number of columns",
        "unsupported_orientation": "Template specifies an unsupported orientation",
        "block_starts_not_found": "Block's starts_at anchor did not match any cell in the tab",
        "block_unterminated": "Block's ends_at anchor did not match before the next starts_at or EOF",
        "capture_no_match": "Capture's `from` pattern matched zero cells in the block instance",
        "capture_multiple_matches": "Capture's `from` pattern matched multiple cells in the block instance and on_multiple=error",
        "block_ref_not_found": "Entity references a block name that is not declared in the template",
    }.get(reason, f"Structural problem: {reason}")


def _row_msg(reason: str, field: str | None, expected: str | None) -> str:
    if reason == "missing_required":
        return f"Field '{field}' is required and was blank"
    if reason == "wrong_type":
        return f"Field '{field}' could not be coerced to {expected}"
    if reason == "anchor_not_found":
        return f"Field '{field}' could not be located by its anchor"
    if reason == "anchor_value_blank":
        return f"Field '{field}' has a label but its value cell is blank"
    if reason == "anchor_value_type_mismatch":
        return f"Field '{field}' anchor matched but the neighbor's shape didn't fit value_type={expected!r}"
    return f"Field '{field}': {reason}"


def check(
    path: str | Path,
    template: Template,
    *,
    engine: Engine | None = None,
) -> tuple[ExtractResult, Report]:
    """Run `extract` + `validate` in one call.

    Args:
        path: Path to the source file.
        template: A loaded `crease.Template`.
        engine: See `crease.extract`.

    Returns:
        A tuple ``(result, report)``. `result` always carries a populated
        canonical dict (even when there are errors — partial extraction is
        the whole point); `report` carries the full error list.
    """
    result = extract(path, template, engine=engine)
    report = validate(result, template)
    # Cache the report on the result so projection methods can consult it.
    result._cached_report = report
    return result, report
