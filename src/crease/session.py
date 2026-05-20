"""Session context manager — multi-entity access on a single open file.

A session opens a file once, lets you fetch ``cardinality: one`` entities
eagerly and stream ``cardinality: many`` entities in the same context, and
exposes the running error report. For v1 the implementation eagerly
extracts everything on entry; row-by-row streaming via openpyxl's
read-only mode is a follow-on.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from crease.extractor import ExtractResult, extract
from crease.template_model import Template
from crease.validator import Report, validate


class Session:
    """Open once; access multiple entities; consult the final report on exit.

    Use as a context manager via `crease.open`:

        with crease.open("incoming.xlsx", template) as session:
            company = session.get("company")
            for order in session.stream("order", model=Order):
                ...
            if not session.report().is_valid:
                log.warning(session.report().errors())
    """

    def __init__(self, path: str | Path, template: Template, *, engine: str | None = None):
        self._path = Path(path)
        self._template = template
        self._engine = engine
        self._result: ExtractResult | None = None

    def __enter__(self) -> Session:
        self._result = extract(self._path, self._template, engine=self._engine)
        return self

    def __exit__(self, *exc_info) -> None:
        self._result = None

    @property
    def result(self) -> ExtractResult:
        if self._result is None:
            raise RuntimeError("Session is not open; use `with crease.open(...) as s:`")
        return self._result

    def get(
        self,
        entity: str,
        *,
        model: Any | None = None,
        allow_partial: bool = False,
    ) -> Any:
        """Return the single record for a ``cardinality: one`` entity."""
        return self.result.get(entity, model=model, allow_partial=allow_partial)

    def stream(
        self,
        entity: str,
        *,
        model: Any | None = None,
        allow_partial: bool = False,
    ) -> Iterator[Any]:
        """Yield records of one entity. Symmetric with `crease.stream`."""
        yield from self.result.iter(entity, model=model, allow_partial=allow_partial)

    def report(self) -> Report:
        """Return the validation report for everything extracted in this session."""
        return validate(self.result, self._template)


def open(  # noqa: A001 - shadowing builtin is intentional
    path: str | Path,
    template: Template,
    *,
    engine: str | None = None,
) -> Session:
    """Open a file for multi-entity extraction. Use as a context manager.

    Args:
        path: Path to the source file.
        template: A loaded `crease.Template`.
        engine: ``"calamine"`` or ``"openpyxl"`` to force a specific
            backend. See `crease.extract` for the default behavior.

    Returns:
        An unentered `Session`. Use it inside a ``with`` block.
    """
    return Session(path, template, engine=engine)
