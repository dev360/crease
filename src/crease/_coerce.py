"""Value normalization and type coercion shared across orientations."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from crease.template_model import (
    DEFAULT_FALSE_VALUES,
    DEFAULT_NULL_TOKENS,
    DEFAULT_TRUE_VALUES,
    FieldSpec,
    Normalize,
    Template,
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_URL_RE = re.compile(r"^https?://\S+$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NBSP = " "


def normalize_header(s: Any) -> str:
    """Header normalization is always-on. Trim, drop NBSP, lower-case."""
    if s is None:
        return ""
    return str(s).replace(_NBSP, " ").strip().lower()


def normalize_value(value: Any, mode: Normalize) -> Any:
    if mode == "none" or not isinstance(value, str):
        return value
    cleaned = value.replace(_NBSP, " ")
    match mode:
        case "trim":
            return cleaned.strip()
        case "lower":
            return cleaned.lower()
        case "trim_lower":
            return cleaned.strip().lower()
    return value


def resolve_null_tokens(field: FieldSpec, template: Template) -> list[str]:
    """Layered: field → template → library defaults."""
    if field.null_tokens is not None:
        return field.null_tokens
    if template.null_tokens is not None:
        return template.null_tokens
    return DEFAULT_NULL_TOKENS


def collapse_null(value: Any, null_tokens: list[str]) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed == "":
            return None
        for token in null_tokens:
            if trimmed.casefold() == token.casefold():
                return None
    return value


class CoercionError(Exception):
    """Raised when a value cannot be coerced to the declared type."""

    def __init__(self, value: Any, expected: str, likely_cause: str | None = None):
        super().__init__(f"could not coerce {value!r} to {expected}")
        self.value = value
        self.expected = expected
        self.likely_cause = likely_cause


def coerce(value: Any, field: FieldSpec) -> Any:
    """Coerce a value to field.type. Returns None for nullish input."""
    if value is None:
        return None

    t = field.type

    # Strings (and stringish semantic types) — accept any scalar as string
    if t in ("string", "email", "uuid", "url"):
        if isinstance(value, dt.datetime | dt.date) and not field.treat_as_text:
            # Excel autoconvert: the operator wanted text, Excel made it a date.
            raise CoercionError(
                value=value,
                expected=t,
                likely_cause="excel_autoconvert",
            )
        return str(value)

    if t == "integer":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if value.is_integer():
                return int(value)
            raise CoercionError(value, "integer")
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                try:
                    f = float(value.strip())
                    if f.is_integer():
                        return int(f)
                except ValueError:
                    pass
        raise CoercionError(value, "integer")

    if t == "number":
        if isinstance(value, bool):
            raise CoercionError(value, "number")
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                pass
        raise CoercionError(value, "number")

    if t == "boolean":
        true_vals = field.true_values or DEFAULT_TRUE_VALUES
        false_vals = field.false_values or DEFAULT_FALSE_VALUES
        if isinstance(value, bool):
            return value
        s = str(value).strip()
        if s in true_vals or s.lower() in (v.lower() for v in true_vals):
            return True
        if s in false_vals or s.lower() in (v.lower() for v in false_vals):
            return False
        raise CoercionError(value, "boolean")

    if t in ("date", "datetime"):
        if isinstance(value, dt.datetime):
            return value.date().isoformat() if t == "date" else value.isoformat()
        if isinstance(value, dt.date):
            return value.isoformat()
        if isinstance(value, str):
            s = value.strip()
            if field.date_format:
                try:
                    parsed = dt.datetime.strptime(s, field.date_format)
                    return parsed.date().isoformat() if t == "date" else parsed.isoformat()
                except ValueError as e:
                    raise CoercionError(value, t) from e
            # Default: accept ISO date for type=date
            if t == "date" and _ISO_DATE_RE.match(s):
                return s
            # Try datetime parsing as a fallback
            try:
                parsed = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
                return parsed.date().isoformat() if t == "date" else parsed.isoformat()
            except ValueError as e:
                raise CoercionError(value, t) from e
        raise CoercionError(value, t)

    return value


def check_constraints(value: Any, field: FieldSpec) -> str | None:
    """Returns a reason code if a constraint fails, else None. Assumes coerced value."""
    if value is None:
        return None
    t = field.type
    if field.pattern is not None and t in ("string", "email", "uuid", "url"):
        if not re.match(field.pattern, str(value)):
            return "pattern_mismatch"
    if field.enum is not None and value not in field.enum:
        return "enum_violation"
    if field.minimum is not None and isinstance(value, int | float) and value < field.minimum:
        return "below_minimum"
    if field.maximum is not None and isinstance(value, int | float) and value > field.maximum:
        return "above_maximum"
    # Built-in semantic regex checks (only if no custom pattern was supplied)
    if field.pattern is None and isinstance(value, str):
        if t == "email" and not _EMAIL_RE.match(value):
            return "pattern_mismatch"
        if t == "uuid" and not _UUID_RE.match(value):
            return "pattern_mismatch"
        if t == "url" and not _URL_RE.match(value):
            return "pattern_mismatch"
    return None
