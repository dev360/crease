"""Crease error model.

Pydantic-shaped errors: every problem the library surfaces, whether structural
(template can't map the file) or cell-level (a value violated a constraint),
is represented as an `Error` with the same five fields. The shape mirrors
`pydantic.ValidationError.errors()` so anyone who has used Pydantic this year
already knows how to consume it.

`ValidationError` is the exception raised by halt-by-default projections
(`to_pydantic`, `to_pandas`, `iter`, `get`, and `stream` without
`allow_partial=True`). It carries the same `Error` list.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from dataclasses import field as _dc_field
from typing import Any, Literal

Severity = Literal["cell", "structural"]


# `error.type` values whose presence forces severity="structural".
# Anything not in this set defaults to "cell".
STRUCTURAL_TYPES: frozenset[str] = frozenset(
    {
        "missing_tab",
        "tab_pattern_no_match",
        "header_mapping_failed",
        "entity_missing",
        "multiple_rows_for_cardinality_one",
        "column_count_mismatch",
        "unsupported_orientation",
        # blocks v2
        "block_starts_not_found",
        "block_unterminated",
        "capture_no_match",
        "capture_multiple_matches",
        "block_ref_not_found",
        "unreadable_source",
    }
)


def severity_for(error_type: str) -> Severity:
    """Derive severity from the error type code."""
    return "structural" if error_type in STRUCTURAL_TYPES else "cell"


@dataclass
class Error:
    """A single problem surfaced by crease.

    Fields mirror `pydantic.ValidationError.errors()` entries, with one crease
    addition: `severity` distinguishes structural errors (the template can't
    map the file at all) from cell-level errors (an individual value
    violated a constraint).

    Attributes:
        type: Stable machine code for routing — e.g. ``"wrong_type"``,
            ``"missing_required"``, ``"pattern_mismatch"``. See the README
            for the full taxonomy.
        loc: ``(entity, row, field)`` tuple identifying where the problem
            was found. Any element may be ``None`` for errors that don't
            apply to a specific row or field (e.g. ``missing_tab``).
        msg: Human-readable description.
        input: The offending value, if applicable. ``None`` for structural
            errors with no specific cell.
        ctx: Extra context — for example ``{"likely_cause":
            "excel_autoconvert"}`` when a string field received what looks
            like an Excel-autoconverted date.
        severity: ``"cell"`` or ``"structural"``. Derived from ``type``.
    """

    type: str
    loc: tuple[str | int | None, ...]
    msg: str = ""
    input: Any = None
    ctx: dict[str, Any] = _dc_field(default_factory=dict)
    severity: Severity = "cell"

    def __post_init__(self) -> None:
        # Always derive severity from type so we can't drift.
        self.severity = severity_for(self.type)

    @property
    def is_structural(self) -> bool:
        return self.severity == "structural"

    @property
    def is_cell(self) -> bool:
        return self.severity == "cell"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for JSON output."""
        d = asdict(self)
        d["loc"] = list(self.loc)
        # Drop empty optional fields to keep the JSON compact.
        if not d["ctx"]:
            d.pop("ctx")
        if d["input"] is None:
            d.pop("input")
        if not d["msg"]:
            d.pop("msg")
        return d


class ValidationError(Exception):
    """Raised by halt-by-default projection methods when crease has errors to report.

    The exception carries the full `Error` list — same shape as
    `Report.errors()` would have produced. Pattern after Pydantic's
    `ValidationError`:

        try:
            orders = result.to_pydantic("order", model=Order)
        except crease.ValidationError as e:
            for err in e.errors():
                print(err.type, err.loc, err.msg)
    """

    def __init__(self, errors: list[Error], message: str | None = None):
        self._errors = list(errors)
        if message is None:
            message = self._default_message()
        super().__init__(message)

    def errors(self) -> list[Error]:
        """Return the full list of errors. Same shape as `Report.errors()`."""
        return list(self._errors)

    def error_count(self) -> int:
        return len(self._errors)

    def _default_message(self) -> str:
        if not self._errors:
            return "ValidationError with no errors attached"
        n = len(self._errors)
        first = self._errors[0]
        head = f"{n} error{'s' if n != 1 else ''}"
        loc = ".".join(str(p) for p in first.loc if p is not None)
        if loc:
            head += f" — first: {first.type} at {loc}"
        else:
            head += f" — first: {first.type}"
        if first.msg:
            head += f" ({first.msg})"
        return head
