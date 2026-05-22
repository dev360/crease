"""Crease — declarative Excel-to-JSON extraction + validation.

Public surface, in three layers:

Top-level functions (most users):
    extract(path, template) -> ExtractResult
    validate(result, template) -> Report
    check(path, template) -> tuple[ExtractResult, Report]
    stream(path, template, entity=..., model=..., allow_partial=...)
    open(path, template) -> Session  (context manager)

Methods on ExtractResult (the projection surface):
    .canonical                                  # plain dict
    .get(entity, model=..., allow_partial=...)
    .iter(entity, model=..., allow_partial=...)
    .to_pydantic(entity, model=..., allow_partial=...)
    .to_pandas(entity, allow_partial=...)       # requires pip install crease[pandas]
    .report                                     # lazy validation report

Methods on Report:
    .is_valid                                   # bool
    .errors()                                   # list[Error]  (pydantic-shaped)
    .error_count()                              # int
    .has_structural                             # bool

Exceptions:
    crease.ValidationError                      # raised by halt-by-default projections
    crease.SourceFileError                      # backend could not open the input file
"""

from __future__ import annotations

from crease._errors import Error, ValidationError
from crease._workbook import SourceFileError
from crease.extractor import ExtractResult, extract, get, inspect_headers, stream
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
from crease.validator import Report, check, validate

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
    "inspect_headers",
    "stream",
    # validation
    "Report",
    "Error",
    "ValidationError",
    "SourceFileError",
    "validate",
    "check",
    # session
    "Session",
    "open",
]

__version__ = "0.1.0"
