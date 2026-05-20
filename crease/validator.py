"""Validate extracted canonical data against the template's constraints."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from dataclasses import field as _dc_field
from pathlib import Path
from typing import Any

from crease._coerce import check_constraints
from crease.extractor import ExtractResult, extract
from crease.template_model import Entity, FieldSpec, Template

_STRUCTURAL_REASONS: set[str] = {
    "missing_tab",
    "tab_pattern_no_match",
    "header_mapping_failed",
    "entity_missing",
    "multiple_rows_for_cardinality_one",
    "column_count_mismatch",
    "unsupported_orientation",
}


@dataclass
class Issue:
    entity: str
    reason: str
    row: int | None = None
    field: str | None = None
    expected: str | None = None
    got: Any = None
    details: dict[str, Any] = _dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {k: v for k, v in d.items() if v not in (None, {}, [])}


@dataclass
class ValidationReport:
    verdict: str  # "valid" | "needs_review" | "reject"
    issues: list[Issue] = _dc_field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "summary": self.summary,
            "issues": [i.to_dict() for i in self.issues],
        }


def _field_by_name(entity: Entity) -> dict[str, FieldSpec]:
    return {f.name: f for f in entity.fields}


def _check_record(
    record: dict[str, Any],
    entity: Entity,
    row_idx: int | None,
    issues: list[Issue],
) -> None:
    fields = _field_by_name(entity)
    for name, value in record.items():
        spec = fields.get(name)
        if spec is None:
            continue  # enriched / injected field; skip constraint check
        if value is None:
            if not spec.nullable:
                issues.append(
                    Issue(
                        entity=entity.name,
                        reason="missing_required",
                        row=row_idx,
                        field=name,
                        expected=spec.type,
                    )
                )
            continue
        reason = check_constraints(value, spec)
        if reason:
            issues.append(
                Issue(
                    entity=entity.name,
                    reason=reason,
                    row=row_idx,
                    field=name,
                    expected=spec.type,
                    got=value,
                )
            )


def _check_duplicates(
    records: list[dict[str, Any]],
    entity: Entity,
    issues: list[Issue],
) -> None:
    seen: dict[tuple, int] = {}
    keys = [f.name for f in entity.fields]
    for i, rec in enumerate(records):
        key = tuple(rec.get(k) for k in keys)
        if all(v is None for v in key):
            continue
        if key in seen:
            issues.append(
                Issue(
                    entity=entity.name,
                    reason="duplicate_row",
                    row=i,
                    details={"duplicate_of": seen[key]},
                )
            )
        else:
            seen[key] = i


def validate(result: ExtractResult, template: Template) -> ValidationReport:
    """Compare extracted data against the template's constraints."""
    issues: list[Issue] = []

    # Lift extraction-time errors into the report.
    for err in result.errors:
        issues.append(
            Issue(
                entity=err.entity or "",
                reason=err.reason,
                details=err.details,
            )
        )
    for re_err in result.row_errors:
        issues.append(
            Issue(
                entity=re_err.entity,
                reason=re_err.reason,
                row=re_err.row,
                field=re_err.field,
                expected=re_err.expected,
                got=re_err.got,
                details={"likely_cause": re_err.likely_cause} if re_err.likely_cause else {},
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
                _check_record(data, entity, row_idx=None, issues=issues)
        else:
            if isinstance(data, list):
                for i, rec in enumerate(data):
                    if not isinstance(rec, dict):
                        continue
                    _check_record(rec, entity, row_idx=i, issues=issues)
                _check_duplicates(data, entity, issues)

    # Aggregate verdict.
    if any(i.reason in _STRUCTURAL_REASONS for i in issues):
        verdict = "reject"
    elif issues:
        verdict = "needs_review"
    else:
        verdict = "valid"

    summary = _summarize(issues, verdict)
    return ValidationReport(verdict=verdict, issues=issues, summary=summary)


def _summarize(issues: list[Issue], verdict: str) -> str:
    if not issues:
        return "no issues"
    by_reason: dict[str, int] = {}
    for i in issues:
        by_reason[i.reason] = by_reason.get(i.reason, 0) + 1
    parts = [f"{n} {reason}" for reason, n in sorted(by_reason.items(), key=lambda kv: -kv[1])]
    return f"{verdict}: " + ", ".join(parts)


def check(path: str | Path, template: Template) -> tuple[ExtractResult, ValidationReport]:
    """Run extract + validate in one call."""
    result = extract(path, template)
    report = validate(result, template)
    return result, report
