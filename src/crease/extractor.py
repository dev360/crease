"""Apply a Template to an xlsx file, produce canonical JSON."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import field as _dc_field
from pathlib import Path
from typing import Any

from crease._coerce import (
    CoercionError,
    coerce,
    collapse_null,
    normalize_header,
    normalize_value,
    resolve_null_tokens,
)
from crease._locate import (
    CellRange,
    TabMatch,
    find_tabs,
    hidden_row_indices,
    normalize_headers,
    parse_cell_range,
    resolve_header_row,
)
from crease._workbook import Sheet, Workbook, open_workbook, select_engine
from crease.template_model import (
    DataEnd,
    Enrich,
    Entity,
    Template,
)

# ---- result types --------------------------------------------------------


@dataclass
class ExtractionError:
    entity: str | None
    reason: str
    details: dict[str, Any] = _dc_field(default_factory=dict)


@dataclass
class RowExtractError:
    """A failure to coerce a single cell. Lifted into a validation Issue downstream."""

    entity: str
    row: int
    field: str
    reason: str  # "wrong_type" | "missing_required" | "anchor_not_found"
    expected: str | None = None
    got: Any = None
    likely_cause: str | None = None


@dataclass
class ExtractResult:
    """The output of `crease.extract`.

    Holds the canonical JSON plus any structural / row-level problems
    encountered while applying the template. Use the projection methods
    (`iter`, `get`, `to_pydantic`, `to_pandas`) to consume the data in a
    typed shape — they halt by default if errors are present, opt-in to
    partial recovery with `allow_partial=True`.

    Attributes:
        template_id: The id of the template used to produce this result.
        source_file: Filename of the source xlsx (without path).
        canonical: ``{entity_name: list_or_dict}`` — the raw extracted data.
        errors: Structural extraction errors (missing tab, header mapping
            failed, etc.). Internal — lifted into ``self.report.errors()``
            on access.
        row_errors: Per-row coercion errors. Internal — lifted into
            ``self.report.errors()`` on access.
        template: The `Template` used to produce this result. Set by
            `crease.extract`; projection methods rely on it.
    """

    template_id: str
    source_file: str
    canonical: dict[str, Any] = _dc_field(default_factory=dict)
    errors: list[ExtractionError] = _dc_field(default_factory=list)
    row_errors: list[RowExtractError] = _dc_field(default_factory=list)
    template: Any = None  # set to a Template by `extract()`; typed loosely to avoid cycles
    _cached_report: Any = None  # populated by `check()` or first `self.report` access

    # ---- report access ---------------------------------------------------

    @property
    def report(self):
        """Lazily compute (and cache) the `Report` for this result."""
        if self._cached_report is None:
            # Local import to avoid a module-level cycle.
            from crease.validator import validate

            if self.template is None:
                raise RuntimeError(
                    "ExtractResult has no template attached; cannot compute report. "
                    "Did you build this result manually instead of via crease.extract()?"
                )
            self._cached_report = validate(self, self.template)
        return self._cached_report

    # ---- canonical lookup ------------------------------------------------

    def _entity_value(self, entity: str) -> Any:
        """Look up canonical data for an entity by singular or pluralized key."""
        if entity in self.canonical:
            return self.canonical[entity]
        plural = _pluralize(entity)
        return self.canonical.get(plural)

    def _entity_spec(self, entity: str):
        if self.template is None:
            return None
        for e in self.template.entities:
            if e.name == entity:
                return e
        return None

    # ---- projection API --------------------------------------------------

    def get(self, entity: str, *, model: Any | None = None, allow_partial: bool = False) -> Any:
        """Return a single record for a ``cardinality: one`` entity.

        Args:
            entity: The entity name (matches `Entity.name` in the template).
            model: Optional Pydantic model to project into. If ``None`` and
                pydantic is available, the canonical dict is returned as-is.
            allow_partial: If ``False`` (default), raises
                ``crease.ValidationError`` when the report has any errors
                for this entity. If ``True``, returns whatever was extracted
                regardless.

        Returns:
            A dict (or a `model` instance if `model` was passed), or
            ``None`` if the entity wasn't found in canonical.

        Raises:
            ValueError: If the entity is declared with ``cardinality:
                many`` — use `iter` or `to_pandas` instead.
            crease.ValidationError: If errors are present and
                ``allow_partial`` is ``False``.
        """
        spec = self._entity_spec(entity)
        if spec is not None and spec.cardinality == "many":
            raise ValueError(
                f"Entity '{entity}' has cardinality='many'; use iter() / to_pandas() / "
                f"to_pydantic() instead of get()."
            )
        if not allow_partial:
            self.report.raise_if_invalid()
        value = self._entity_value(entity)
        if value is None or model is None:
            return value
        return _coerce_to_model(value, model, loc=(entity, None))

    def iter(self, entity: str, *, model: Any | None = None, allow_partial: bool = False) -> Iterator[Any]:
        """Iterate over records of a ``cardinality: many`` entity.

        Args:
            entity: The entity name.
            model: Optional Pydantic model to project each record into.
            allow_partial: If ``False`` (default), raises
                ``crease.ValidationError`` if the report has any errors
                **before** yielding. If ``True``, yields rows that
                successfully project; rows that fail are skipped and
                surfaced via ``self.report.errors()``.

        Yields:
            Dicts, or `model` instances if `model` was passed.

        Raises:
            ValueError: If the entity has ``cardinality: one``.
            crease.ValidationError: If errors are present and
                ``allow_partial`` is ``False``.
        """
        spec = self._entity_spec(entity)
        if spec is not None and spec.cardinality == "one":
            raise ValueError(f"Entity '{entity}' has cardinality='one'; use get() instead of iter().")
        if not allow_partial:
            self.report.raise_if_invalid()

        value = self._entity_value(entity)
        if value is None:
            return
        rows = value if isinstance(value, list) else [value]
        for i, row in enumerate(rows):
            if model is None:
                yield row
                continue
            try:
                yield _coerce_to_model(row, model, loc=(entity, i))
            except Exception:
                if not allow_partial:
                    raise
                # In partial mode, skip rows that can't project. The
                # underlying problem is already in self.report.errors().

    def to_pydantic(
        self,
        entity: str,
        *,
        model: Any | None = None,
        allow_partial: bool = False,
    ) -> Any:
        """Project canonical records into Pydantic model instances.

        Field matching is opportunistic by attribute name: fields the model
        doesn't declare are silently dropped (``extra="ignore"``); type
        mismatches raise.

        Args:
            entity: The entity name.
            model: Pydantic ``BaseModel`` subclass to project into. If
                ``None``, a model is auto-generated from the template's
                field declarations via `Template.model(entity)`.
            allow_partial: See `iter`.

        Returns:
            For ``cardinality: many`` entities, ``list[model]``.
            For ``cardinality: one``, a single ``model`` instance (or
            ``None`` if the entity wasn't found).

        Raises:
            crease.ValidationError: If errors are present and
                ``allow_partial`` is ``False``, or if a row can't project
                into the model.
        """
        if model is None:
            if self.template is None:
                raise RuntimeError("Cannot auto-generate a model without a Template attached.")
            model = self.template.model(entity)

        spec = self._entity_spec(entity)
        if spec is not None and spec.cardinality == "one":
            return self.get(entity, model=model, allow_partial=allow_partial)
        return list(self.iter(entity, model=model, allow_partial=allow_partial))

    def to_pandas(self, entity: str, *, allow_partial: bool = False) -> Any:
        """Project canonical records into a pandas DataFrame.

        Requires the ``pandas`` extra (``pip install crease[pandas]``).
        Pandas is imported lazily inside this method, so callers who never
        use it don't pay the import cost.

        Args:
            entity: The entity name.
            allow_partial: If ``False`` (default), raises
                ``crease.ValidationError`` when the report has any errors.

        Returns:
            A pandas DataFrame. For ``cardinality: one`` entities, a
            single-row DataFrame.
        """
        try:
            import pandas as pd  # local import — pandas is an optional extra
        except ImportError as e:
            raise ImportError("to_pandas() requires the 'pandas' extra: pip install crease[pandas]") from e

        if not allow_partial:
            self.report.raise_if_invalid()

        value = self._entity_value(entity)
        if value is None:
            return pd.DataFrame()
        if isinstance(value, dict):
            return pd.DataFrame([value])
        return pd.DataFrame(value)


def _coerce_to_model(record: dict[str, Any], model: Any, *, loc: tuple) -> Any:
    """Project a single canonical dict into a Pydantic model instance.

    Opportunistic field matching — fields the model doesn't declare are
    dropped silently; type mismatches surface as `crease.ValidationError`
    wrapping the underlying Pydantic error with crease-flavoured `loc`.
    """
    from pydantic import ValidationError as _PydanticValidationError

    from crease._errors import Error, ValidationError

    try:
        return model.model_validate(record)
    except _PydanticValidationError as e:
        crease_errors: list[Error] = []
        entity_name = loc[0] if loc else None
        row_idx = loc[1] if len(loc) > 1 else None
        for err in e.errors():
            field_name = ".".join(str(p) for p in err.get("loc", ()))
            crease_errors.append(
                Error(
                    type="model_type_mismatch",
                    loc=(entity_name, row_idx, field_name or None),
                    msg=err.get("msg", ""),
                    input=err.get("input"),
                    ctx={"pydantic_type": err.get("type", "")},
                )
            )
        raise ValidationError(crease_errors) from e


# ---- helpers -------------------------------------------------------------


def _pluralize(name: str) -> str:
    if name.endswith("s"):
        return name
    if name.endswith("y") and not name.endswith(("ay", "ey", "oy", "uy")):
        return name[:-1] + "ies"
    return name + "s"


def _open_workbook(path: Path, template: Template, engine: str | None) -> Workbook:
    chosen = select_engine(template, engine)
    return open_workbook(path, chosen)


def _filename_inject(record: dict[str, Any], template: Template, source_file: str) -> dict[str, Any]:
    if not template.filename_pattern or not template.filename_capture:
        return record
    m = re.match(template.filename_pattern, source_file)
    if not m:
        return record
    for cap in template.filename_capture:
        try:
            raw = m.group(cap.group)
            record[cap.field] = raw  # type coercion deferred for now
        except IndexError:
            continue
    return record


def _apply_enrich(record: dict[str, Any], enrich_list: list[Enrich], tab: TabMatch) -> dict[str, Any]:
    for enrich in enrich_list:
        if enrich.source == "tab_name":
            raw = tab.name
        elif enrich.source == "tab_name_regex_group":
            if tab.regex_match is None:
                raw = None
            else:
                try:
                    raw = tab.regex_match.group(enrich.group)
                except IndexError:
                    raw = None
        else:
            raw = None
        if raw is not None and isinstance(raw, str):
            if enrich.strip_prefix:
                raw = raw.removeprefix(enrich.strip_prefix)
            if enrich.strip_suffix:
                raw = raw.removesuffix(enrich.strip_suffix)
        record[enrich.field] = raw
    return record


# ---- flat orientation ----------------------------------------------------


def _read_flat_grid(ws: Sheet, locate, cell_range: CellRange | None) -> list[list[Any]]:
    """Pull rows into a 2D list."""
    grid: list[list[Any]] = []
    hidden = hidden_row_indices(ws) if locate.skip_hidden_rows else set()

    min_row = (cell_range.start_row + 1) if cell_range else 1
    max_row = (cell_range.end_row + 1) if (cell_range and cell_range.end_row is not None) else None
    min_col = (cell_range.start_col + 1) if cell_range else 1
    max_col = (cell_range.end_col + 1) if (cell_range and cell_range.end_col is not None) else None

    base = min_row - 1
    for offset, row in enumerate(
        ws.iter_rows(min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col)
    ):
        if (base + offset) in hidden:
            continue
        grid.append(list(row))

    while grid and all(v is None for v in grid[-1]):
        grid.pop()
    return grid


def _apply_data_end(rows: list[list[Any]], header_idx: int, data_end: DataEnd | None) -> list[list[Any]]:
    """Trim trailing rows based on data_ends_at."""
    if data_end is None or data_end.type == "end_of_sheet":
        return rows

    data = rows[header_idx + 1 :]

    if data_end.type == "blank_row":
        n = data_end.n_consecutive
        run = 0
        cutoff = len(data)
        for i, r in enumerate(data):
            if all(v is None for v in r):
                run += 1
                if run >= n:
                    cutoff = i - n + 1
                    break
            else:
                run = 0
        return rows[: header_idx + 1] + data[:cutoff]

    if data_end.type == "value_match":
        col = data_end.column
        value = data_end.value or ""
        for i, r in enumerate(data):
            if col < len(r) and r[col] is not None and value in str(r[col]):
                return rows[: header_idx + 1] + data[:i]
        return rows

    if data_end.type == "skip_trailing_rows":
        n = data_end.rows
        return rows[:-n] if n > 0 else rows

    return rows


def _extract_flat(
    ws: Sheet,
    entity: Entity,
    tab: TabMatch,
    template: Template,
    result: ExtractResult,
) -> list[dict[str, Any]] | dict[str, Any] | None:
    cell_range = parse_cell_range(entity.locate.cell_range) if entity.locate.cell_range else None
    grid = _read_flat_grid(ws, entity.locate, cell_range)

    header_idx = resolve_header_row(ws, entity.locate)
    if cell_range:
        header_idx = max(0, header_idx - cell_range.start_row)

    if header_idx >= len(grid):
        result.errors.append(
            ExtractionError(
                entity=entity.name,
                reason="entity_missing",
                details={"hint": "header_row beyond available rows"},
            )
        )
        return None

    grid = _apply_data_end(grid, header_idx, entity.locate.data_ends_at)
    raw_headers = grid[header_idx] if grid else []
    headers = normalize_headers(raw_headers)

    data_starts_offset = (
        (entity.locate.data_starts_row - (cell_range.start_row if cell_range else 0))
        if entity.locate.data_starts_row is not None
        else header_idx + 1
    )
    data_rows = grid[data_starts_offset:]

    # Map field → header column index
    field_to_col: dict[str, int] = {}
    missing_columns: list[str] = []
    for f in entity.fields:
        if f.source_column is None:
            continue
        wanted = normalize_header(f.source_column)
        try:
            field_to_col[f.name] = headers.index(wanted)
        except ValueError:
            missing_columns.append(f.source_column)

    if missing_columns:
        result.errors.append(
            ExtractionError(
                entity=entity.name,
                reason="header_mapping_failed",
                details={"missing": missing_columns, "got": list(raw_headers)},
            )
        )

    extracted: list[dict[str, Any]] = []
    null_token_cache = {f.name: resolve_null_tokens(f, template) for f in entity.fields}

    for r_idx, row in enumerate(data_rows):
        if all(v is None for v in row):
            continue  # skip fully blank rows mid-data; validator may flag

        record: dict[str, Any] = {}
        for f in entity.fields:
            col = field_to_col.get(f.name)
            raw = row[col] if (col is not None and col < len(row)) else None
            value = collapse_null(raw, null_token_cache[f.name])
            value = normalize_value(value, f.normalize)

            if value is None:
                record[f.name] = None
                if not f.nullable and col is not None:
                    result.row_errors.append(
                        RowExtractError(
                            entity=entity.name,
                            row=r_idx,
                            field=f.name,
                            reason="missing_required",
                            expected=f.type,
                            got=None,
                        )
                    )
                continue

            try:
                record[f.name] = coerce(value, f)
            except CoercionError as e:
                record[f.name] = value
                result.row_errors.append(
                    RowExtractError(
                        entity=entity.name,
                        row=r_idx,
                        field=f.name,
                        reason="wrong_type",
                        expected=e.expected,
                        got=repr(value),
                        likely_cause=e.likely_cause,
                    )
                )

        record = _apply_enrich(record, entity.enrich, tab)
        record = _filename_inject(record, template, result.source_file)
        extracted.append(record)

    return extracted


# ---- property_sheet orientation ------------------------------------------


def _extract_property_sheet(
    ws: Sheet,
    entity: Entity,
    tab: TabMatch,
    template: Template,
    result: ExtractResult,
) -> dict[str, Any]:
    """Read [label, value] pairs from two adjacent columns."""
    locate = entity.locate
    cell_range = parse_cell_range(locate.cell_range) if locate.cell_range else None

    label_col = locate.label_col
    value_col = locate.value_col
    start_row = locate.start_row

    if cell_range:
        label_col = cell_range.start_col
        value_col = cell_range.start_col + 1
        start_row = cell_range.start_row

    label_to_value: dict[str, Any] = {}
    end_row = (cell_range.end_row + 1) if (cell_range and cell_range.end_row is not None) else None

    for row in ws.iter_rows(min_row=start_row + 1, max_row=end_row):
        if label_col >= len(row):
            continue
        label = row[label_col]
        if label is None:
            continue
        value = row[value_col] if value_col < len(row) else None
        label_to_value[normalize_header(label).rstrip(":")] = value

    record: dict[str, Any] = {}
    for f in entity.fields:
        if f.source_label is None:
            continue
        key = normalize_header(f.source_label).rstrip(":")
        raw = label_to_value.get(key)
        nulls = resolve_null_tokens(f, template)
        raw = collapse_null(raw, nulls)
        raw = normalize_value(raw, f.normalize)
        if raw is None:
            record[f.name] = None
            if not f.nullable:
                result.row_errors.append(
                    RowExtractError(
                        entity=entity.name,
                        row=0,
                        field=f.name,
                        reason="missing_required",
                        expected=f.type,
                        got=None,
                    )
                )
            continue
        try:
            record[f.name] = coerce(raw, f)
        except CoercionError as e:
            record[f.name] = raw
            result.row_errors.append(
                RowExtractError(
                    entity=entity.name,
                    row=0,
                    field=f.name,
                    reason="wrong_type",
                    expected=e.expected,
                    got=repr(raw),
                    likely_cause=e.likely_cause,
                )
            )

    record = _apply_enrich(record, entity.enrich, tab)
    record = _filename_inject(record, template, result.source_file)
    return record


# ---- anchored orientation ------------------------------------------------


def _extract_anchored(
    ws: Sheet,
    entity: Entity,
    tab: TabMatch,
    template: Template,
    result: ExtractResult,
) -> dict[str, Any]:
    """Locate each field independently via its `anchor` spec."""
    grid: list[list[Any]] = []
    for row in ws.iter_rows():
        grid.append(list(row))

    record: dict[str, Any] = {}
    for f in entity.fields:
        if f.anchor is None:
            continue
        loc = _find_anchor(grid, f.anchor)
        if loc is None:
            record[f.name] = None
            result.row_errors.append(
                RowExtractError(
                    entity=entity.name,
                    row=0,
                    field=f.name,
                    reason="anchor_not_found",
                    expected=f.anchor.label_match,
                )
            )
            continue
        r, c = loc
        raw = _walk_from(grid, r, c, f.anchor)
        nulls = resolve_null_tokens(f, template)
        raw = collapse_null(raw, nulls)
        raw = normalize_value(raw, f.normalize)
        if raw is None:
            record[f.name] = None
            if not f.nullable:
                result.row_errors.append(
                    RowExtractError(
                        entity=entity.name,
                        row=0,
                        field=f.name,
                        reason="missing_required",
                        expected=f.type,
                    )
                )
            continue
        try:
            record[f.name] = coerce(raw, f)
        except CoercionError as e:
            record[f.name] = raw
            result.row_errors.append(
                RowExtractError(
                    entity=entity.name,
                    row=0,
                    field=f.name,
                    reason="wrong_type",
                    expected=e.expected,
                    got=repr(raw),
                    likely_cause=e.likely_cause,
                )
            )

    record = _apply_enrich(record, entity.enrich, tab)
    record = _filename_inject(record, template, result.source_file)
    return record


def _find_anchor(grid: list[list[Any]], anchor) -> tuple[int, int] | None:
    target = anchor.label_match
    mode = anchor.match_mode
    for r, row in enumerate(grid):
        for c, val in enumerate(row):
            if val is None:
                continue
            s = str(val).strip()
            if mode == "exact" and s == target:
                return (r, c)
            if mode == "contains" and target in s:
                return (r, c)
            if mode == "regex" and re.search(target, s):
                return (r, c)
    return None


def _walk_from(grid: list[list[Any]], r: int, c: int, anchor) -> Any:
    direction = anchor.value_at
    offset = anchor.offset
    if direction == "right":
        c += offset
    elif direction == "left":
        c -= offset
    elif direction == "below":
        r += offset
    elif direction == "above":
        r -= offset
    if 0 <= r < len(grid) and 0 <= c < len(grid[r]):
        return grid[r][c]
    return None


# ---- unpivot -------------------------------------------------------------


def _apply_unpivot(records: list[dict[str, Any]], entity: Entity) -> list[dict[str, Any]]:
    if entity.unpivot is None:
        return records
    up = entity.unpivot
    id_cols = set(up.id_columns)
    var_re = re.compile(up.variable_column_pattern)

    out: list[dict[str, Any]] = []
    for rec in records:
        for key, val in rec.items():
            if key in id_cols:
                continue
            if not var_re.match(str(key)):
                continue
            row = {k: rec[k] for k in id_cols if k in rec}
            row[up.variable_name] = key
            row[up.value_name] = val
            out.append(row)
    return out


# ---- entity dispatch -----------------------------------------------------


def _extract_entity(workbook: Workbook, entity: Entity, template: Template, result: ExtractResult) -> None:  # noqa: E501
    tabs = find_tabs(workbook, entity.locate, template.ignore_tabs)
    if not tabs:
        result.errors.append(
            ExtractionError(
                entity=entity.name,
                reason="tab_pattern_no_match" if entity.locate.tab_pattern else "missing_tab",
                details={
                    "tab": entity.locate.tab,
                    "tab_pattern": entity.locate.tab_pattern,
                },
            )
        )
        return

    orientation = entity.locate.orientation
    key = entity.name if entity.cardinality == "one" else _pluralize(entity.name)

    if entity.cardinality == "one":
        ws = tabs[0].worksheet
        tab = tabs[0]
        if orientation == "property_sheet":
            record = _extract_property_sheet(ws, entity, tab, template, result)
        elif orientation == "anchored":
            record = _extract_anchored(ws, entity, tab, template, result)
        elif orientation == "flat":
            rows = _extract_flat(ws, entity, tab, template, result)
            if isinstance(rows, list) and rows:
                if len(rows) > 1:
                    result.errors.append(
                        ExtractionError(
                            entity=entity.name,
                            reason="multiple_rows_for_cardinality_one",
                            details={"n_rows": len(rows)},
                        )
                    )
                record = rows[0]
            else:
                record = None
        else:
            result.errors.append(
                ExtractionError(
                    entity=entity.name,
                    reason="unsupported_orientation",
                    details={"orientation": orientation},
                )
            )
            return
        result.canonical[key] = record
        return

    # cardinality == "many" — aggregate across matching tabs
    all_rows: list[dict[str, Any]] = []
    for tab in tabs:
        ws = tab.worksheet
        if orientation == "flat":
            rows = _extract_flat(ws, entity, tab, template, result) or []
            all_rows.extend(rows)
        elif orientation == "property_sheet":
            all_rows.append(_extract_property_sheet(ws, entity, tab, template, result))
        elif orientation == "anchored":
            all_rows.append(_extract_anchored(ws, entity, tab, template, result))
        else:
            result.errors.append(
                ExtractionError(
                    entity=entity.name,
                    reason="unsupported_orientation",
                    details={"orientation": orientation},
                )
            )

    all_rows = _apply_unpivot(all_rows, entity)
    result.canonical[key] = all_rows


# ---- public API ----------------------------------------------------------


def extract(path: str | Path, template: Template, *, engine: str | None = None) -> ExtractResult:
    """Apply a template to a spreadsheet file and return canonical JSON.

    The returned `ExtractResult` carries the canonical data and any
    structural / row-level extraction problems. It also carries a reference
    to the template, so projection methods (`to_pydantic`, `to_pandas`,
    `iter`, `get`) can find it.

    Args:
        path: Path to the source file. Calamine (the default backend)
            reads ``.xls``, ``.xlsx``, ``.xlsb``, and ``.ods``; openpyxl
            (the fallback for templates that need cell-hidden metadata)
            reads ``.xlsx`` only.
        template: A loaded `crease.Template`.
        engine: ``"calamine"`` or ``"openpyxl"`` to force a specific
            backend. Default (``None``) auto-selects: openpyxl if the
            template uses ``locate.skip_hidden_rows``, calamine otherwise.

    Returns:
        An `ExtractResult` holding the canonical dict and any errors.
    """
    p = Path(path)
    result = ExtractResult(
        template_id=template.template_id,
        source_file=p.name,
        template=template,
    )
    workbook = _open_workbook(p, template, engine)
    try:
        for entity in template.entities:
            _extract_entity(workbook, entity, template, result)
    finally:
        workbook.close()
    return result


def get(
    path: str | Path,
    template: Template,
    entity: str,
    *,
    model: Any | None = None,
    allow_partial: bool = False,
    engine: str | None = None,
) -> Any:
    """Extract a single entity in one call. Convenience wrapper over `extract`.

    Args:
        path: Path to the source file.
        template: A loaded `crease.Template`.
        entity: The entity name (must have ``cardinality: one``).
        model: Optional Pydantic model to project into.
        allow_partial: If ``False`` (default), raises
            ``crease.ValidationError`` when extraction produced errors.
        engine: See `extract`.

    Returns:
        A dict (or a `model` instance), or ``None`` if the entity wasn't found.
    """
    result = extract(path, template, engine=engine)
    return result.get(entity, model=model, allow_partial=allow_partial)


def stream(
    path: str | Path,
    template: Template,
    *,
    entity: str,
    model: Any | None = None,
    allow_partial: bool = False,
    engine: str | None = None,
) -> Iterator[Any]:
    """Stream records of one entity from a spreadsheet file.

    For v1, this delegates to `extract` and iterates the materialized
    result.

    Args:
        path: Path to the source file.
        template: A loaded `crease.Template`.
        entity: The entity to stream.
        model: Optional Pydantic model to project each record into. When
            set, yields `model` instances instead of dicts.
        allow_partial: If ``False`` (default), raises
            ``crease.ValidationError`` when extraction produced errors.
        engine: See `extract`.

    Yields:
        Dicts, or `model` instances if `model` was passed.
    """
    result = extract(path, template, engine=engine)
    spec = result._entity_spec(entity)
    if spec is not None and spec.cardinality == "one":
        # Mirror the materialized API: cardinality=one yields once (or not at all).
        value = result.get(entity, model=model, allow_partial=allow_partial)
        if value is not None:
            yield value
        return
    yield from result.iter(entity, model=model, allow_partial=allow_partial)
