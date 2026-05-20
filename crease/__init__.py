"""Crease — declarative Excel-to-JSON extraction + validation."""

from __future__ import annotations

from crease.extractor import ExtractResult, extract, get, stream
from crease.session import Session, open
from crease.template_model import (
    Anchor,
    DataEnd,
    Enrich,
    Entity,
    FieldSpec,
    HeaderAnchor,
    Locate,
    Template,
    Unpivot,
)
from crease.validator import Issue, ValidationReport, check, validate

__all__ = [
    # template
    "Template",
    "Entity",
    "FieldSpec",
    "Locate",
    "Anchor",
    "HeaderAnchor",
    "DataEnd",
    "Enrich",
    "Unpivot",
    # extraction
    "ExtractResult",
    "extract",
    "get",
    "stream",
    # validation
    "ValidationReport",
    "Issue",
    "validate",
    "check",
    # session
    "Session",
    "open",
]

__version__ = "0.1.0"
