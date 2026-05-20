"""Session context manager — multi-entity access on a single open file."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from crease.extractor import ExtractResult, extract
from crease.template_model import Template
from crease.validator import ValidationReport, validate


class Session:
    """Open once, get multiple entities, get a final report on exit.

    For v1 the implementation eagerly extracts everything on entry; streaming
    yields from the already-extracted result. Row-by-row streaming via openpyxl
    is a follow-on.
    """

    def __init__(self, path: str | Path, template: Template):
        self._path = Path(path)
        self._template = template
        self._result: ExtractResult | None = None

    def __enter__(self) -> Session:
        self._result = extract(self._path, self._template)
        return self

    def __exit__(self, *exc_info) -> None:
        self._result = None

    @property
    def result(self) -> ExtractResult:
        if self._result is None:
            raise RuntimeError("session is not open; use `with crease.open(...) as s:`")
        return self._result

    def get(self, entity: str) -> Any:
        """Return the canonical value for an entity (dict for `one`, list for `many`)."""
        value = self.result.canonical.get(entity)
        if value is not None:
            return value
        plural = entity if entity.endswith("s") else entity + "s"
        return self.result.canonical.get(plural)

    def stream(self, entity: str) -> Iterator[dict[str, Any]]:
        value = self.get(entity)
        if value is None:
            return
        if isinstance(value, list):
            yield from value
        else:
            yield value

    def report(self) -> ValidationReport:
        return validate(self.result, self._template)


def open(path: str | Path, template: Template) -> Session:  # noqa: A001 - shadowing builtin is intentional
    """Open a file for multi-entity extraction. Use as a context manager."""
    return Session(path, template)
