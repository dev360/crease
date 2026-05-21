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
    resolve_null_patterns,
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
from crease._workbook import Engine, Sheet, Workbook, open_workbook, select_engine
from crease.template_model import (
    AnnotationRule,
    Block,
    Capture,
    DataEnd,
    Enrich,
    Entity,
    LocateSkipRule,
    SkipRowRule,
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
    reason: str  # "wrong_type" | "missing_required" | "anchor_not_found" | "anchor_value_blank"
    expected: str | None = None
    got: Any = None
    likely_cause: str | None = None
    label_was: str | None = None  # "present" | "absent" for anchored failures


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
    for offset, row in enumerate(ws.iter_rows(min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col)):
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

    if data_end.type == "value_pattern":
        col = data_end.column
        if data_end.value_pattern is None:
            return rows
        pat = re.compile(data_end.value_pattern)
        for i, r in enumerate(data):
            if col < len(r) and r[col] is not None and pat.fullmatch(str(r[col])):
                return rows[: header_idx + 1] + data[:i]
        return rows

    if data_end.type == "skip_trailing_rows":
        n = data_end.rows
        return rows[:-n] if n > 0 else rows

    return rows


@dataclass
class _ResolvedSkipRule:
    """Skip rule with referenced column names resolved to column indices."""

    all_blank_cols: list[int]
    non_blank_cols: list[int]
    column: int | None
    pattern: re.Pattern[str] | None


def _resolve_skip_row_if(rules: list[LocateSkipRule], headers: list[str]) -> list[_ResolvedSkipRule]:
    resolved: list[_ResolvedSkipRule] = []
    for rule in rules:
        all_blank_cols: list[int] = []
        if rule.all_blank:
            for col_name in rule.all_blank:
                wanted = normalize_header(col_name)
                if wanted in headers:
                    all_blank_cols.append(headers.index(wanted))
        non_blank_cols: list[int] = []
        if rule.non_blank:
            for col_name in rule.non_blank:
                wanted = normalize_header(col_name)
                if wanted in headers:
                    non_blank_cols.append(headers.index(wanted))
        col_idx: int | None = None
        pat: re.Pattern[str] | None = None
        if rule.column and rule.value_pattern:
            wanted = normalize_header(rule.column)
            if wanted in headers:
                col_idx = headers.index(wanted)
                pat = re.compile(rule.value_pattern)
        resolved.append(
            _ResolvedSkipRule(
                all_blank_cols=all_blank_cols,
                non_blank_cols=non_blank_cols,
                column=col_idx,
                pattern=pat,
            )
        )
    return resolved


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _row_matches_locate_skip(row: list[Any], rules: list[_ResolvedSkipRule]) -> bool:
    for rule in rules:
        if not _locate_skip_rule_applies(row, rule):
            continue
        return True
    return False


def _locate_skip_rule_applies(row: list[Any], rule: _ResolvedSkipRule) -> bool:
    matched_any = False
    for col in rule.all_blank_cols:
        if col >= len(row) or not _is_blank(row[col]):
            return False
        matched_any = True
    for col in rule.non_blank_cols:
        if col >= len(row) or _is_blank(row[col]):
            return False
        matched_any = True
    if rule.column is not None and rule.pattern is not None:
        if rule.column >= len(row):
            return False
        raw = row[rule.column]
        if raw is None or not rule.pattern.fullmatch(str(raw)):
            return False
        matched_any = True
    return matched_any


def _row_is_annotation(row: list[Any], rules: list[AnnotationRule]) -> bool:
    if not rules:
        return False
    populated = sum(1 for v in row if v is not None and not (isinstance(v, str) and v.strip() == ""))
    return any(populated <= rule.only_columns_populated for rule in rules)


def _extract_flat(
    ws: Sheet,
    entity: Entity,
    tab: TabMatch,
    template: Template,
    result: ExtractResult,
    *,
    cell_range_override: CellRange | None = None,
    separator_rows: list[SkipRowRule] | None = None,
    extra_fields: dict[str, Any] | None = None,
) -> list[dict[str, Any]] | dict[str, Any] | None:
    # `cell_range_override` is set when extracting inside a block instance — the
    # block's [start_row, end_row] window is synthesized into a CellRange so we
    # reuse the same row-window machinery as the user-facing `cell_range`.
    # `separator_rows` are applied BEFORE header detection so the entity's
    # header_anchor scan doesn't latch onto a separator. `extra_fields` are
    # block captures merged into every emitted row (B3 propagation).
    cell_range = cell_range_override
    if cell_range is None and entity.locate.cell_range:
        cell_range = parse_cell_range(entity.locate.cell_range)
    grid = _read_flat_grid(ws, entity.locate, cell_range)

    # When extracting inside a block instance, restrict the header_anchor
    # scan to the instance's row range so an outer header anchor can't
    # latch onto a row outside the block.
    if cell_range is not None:
        scope_min = cell_range.start_row
        scope_max = cell_range.end_row
    else:
        scope_min = 0
        scope_max = None
    header_idx = resolve_header_row(ws, entity.locate, min_row=scope_min, max_row=scope_max)
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

    # Interim multi-row-header drift detector: if the row directly above the
    # chosen header_row carries non-blank text in the same column as a real
    # header, the operator probably meant a two-row header but only pointed
    # at the bottom row. Surface the column geometry so the report shows
    # what the bind would have looked like with header_levels:2.
    #
    # Skip when the entity uses ``header_anchor`` (the row was dynamically
    # located by scanning a known label; content above is expected — title
    # blocks, block start anchors, etc.) or when extracting inside a block
    # instance (the surrounding tab routinely carries section-level metadata
    # above each block's header).
    skip_header_above_check = entity.locate.header_anchor is not None or cell_range_override is not None
    if not skip_header_above_check and header_idx > 0 and header_idx - 1 < len(grid):
        above = grid[header_idx - 1]
        suspicious: list[dict[str, Any]] = []
        for col_idx, header_text in enumerate(headers):
            if header_text == "":
                continue
            if col_idx >= len(above):
                continue
            raw_above = above[col_idx]
            if raw_above is None:
                continue
            above_text = str(raw_above).strip()
            if above_text == "":
                continue
            suspicious.append(
                {
                    "column": col_idx,
                    "header": header_text,
                    "above": above_text,
                }
            )
        if suspicious:
            result.errors.append(
                ExtractionError(
                    entity=entity.name,
                    reason="header_above_nonblank",
                    details={
                        "header_row": header_idx,
                        "columns": suspicious,
                    },
                )
            )

    data_starts_offset = (
        (entity.locate.data_starts_row - (cell_range.start_row if cell_range else 0))
        if entity.locate.data_starts_row is not None
        else header_idx + 1
    )
    data_rows = grid[data_starts_offset:]

    # Apply separator-row filtering AFTER the header is identified so the
    # filter can't shift the header position out from under us.
    if separator_rows:
        data_rows = _apply_separator_rows(data_rows, separator_rows, cell_range)

    # Map header → all column indices that carry it. Duplicates are kept
    # so we can either disambiguate with source_column_index or emit a
    # header_duplicated warning when a field binds without one.
    header_to_cols: dict[str, list[int]] = {}
    for col_idx, h in enumerate(headers):
        if h == "":
            continue
        header_to_cols.setdefault(h, []).append(col_idx)

    field_to_col: dict[str, int] = {}
    missing_columns: list[str] = []
    for f in entity.fields:
        if f.source_column is None:
            continue
        wanted = normalize_header(f.source_column)
        matches = header_to_cols.get(wanted, [])
        if not matches:
            missing_columns.append(f.source_column)
            continue
        if f.source_column_index is not None:
            if 0 <= f.source_column_index < len(matches):
                field_to_col[f.name] = matches[f.source_column_index]
            else:
                missing_columns.append(f.source_column)
            continue
        if len(matches) > 1:
            result.errors.append(
                ExtractionError(
                    entity=entity.name,
                    reason="header_duplicated",
                    details={
                        "field": f.name,
                        "source_column": f.source_column,
                        "columns": list(matches),
                    },
                )
            )
        field_to_col[f.name] = matches[0]

    if missing_columns:
        result.errors.append(
            ExtractionError(
                entity=entity.name,
                reason="header_mapping_failed",
                details={"missing": missing_columns, "got": list(raw_headers)},
            )
        )

    skip_rules = _resolve_skip_row_if(entity.locate.skip_row_if, headers)

    extracted: list[dict[str, Any]] = []
    null_token_cache = {f.name: resolve_null_tokens(f, template) for f in entity.fields}
    null_pattern_cache = {f.name: resolve_null_patterns(f, template) for f in entity.fields}
    annotation_rules = list(entity.locate.row_is_annotation_if)

    for r_idx, row in enumerate(data_rows):
        if all(v is None for v in row):
            continue  # skip fully blank rows mid-data; validator may flag
        if _row_matches_locate_skip(row, skip_rules):
            continue
        if _row_is_annotation(row, annotation_rules):
            continue

        record: dict[str, Any] = {}
        for f in entity.fields:
            col = field_to_col.get(f.name)
            raw = row[col] if (col is not None and col < len(row)) else None
            value = collapse_null(raw, null_token_cache[f.name], null_pattern_cache[f.name])
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
        if extra_fields:
            # Captures from the enclosing block instance merge onto every
            # emitted row. Child field names win over capture names — but
            # `field_shadow_collision` should have already caught that at
            # `Template.model_validate`, so in practice this is just a
            # belt-and-suspenders.
            record = {**extra_fields, **record}
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
        patterns = resolve_null_patterns(f, template)
        raw = collapse_null(raw, nulls, patterns)
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
                    label_was="absent",
                )
            )
            continue
        r, c = loc
        raw = _walk_from(grid, r, c, f.anchor)
        nulls = resolve_null_tokens(f, template)
        patterns = resolve_null_patterns(f, template)
        raw = collapse_null(raw, nulls, patterns)
        raw = normalize_value(raw, f.normalize)
        if raw is None:
            record[f.name] = None
            if f.nullable:
                # Label was there; the value just wasn't filled in. Surface
                # as an informational warning so the report still tells the
                # operator about the empty slot — distinct from the harder
                # "label entirely missing" failure mode.
                result.row_errors.append(
                    RowExtractError(
                        entity=entity.name,
                        row=0,
                        field=f.name,
                        reason="anchor_value_blank",
                        expected=f.type,
                        label_was="present",
                    )
                )
            else:
                result.row_errors.append(
                    RowExtractError(
                        entity=entity.name,
                        row=0,
                        field=f.name,
                        reason="missing_required",
                        expected=f.type,
                        label_was="present",
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
    pinned_col = anchor.column
    nth = max(1, anchor.nth)
    seen = 0
    for r, row in enumerate(grid):
        for c, val in enumerate(row):
            if pinned_col is not None and c != pinned_col:
                continue
            if val is None:
                continue
            s = str(val).strip()
            if mode == "exact" and s == target:
                pass
            elif mode == "contains" and target in s:
                pass
            elif mode == "regex" and re.search(target, s):
                pass
            else:
                continue
            seen += 1
            if seen == nth:
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


# ---- blocks: extraction --------------------------------------------------


@dataclass
class _BlockInstance:
    """One occurrence of a block in a tab (between consecutive starts_at hits,
    or terminated by ends_at per strategy)."""

    start_row: int  # 0-indexed, inclusive — row where starts_at matched
    end_row: int  # 0-indexed, inclusive — last row that belongs to this instance


def _cell_matches(value: Any, pattern: re.Pattern) -> tuple[bool, re.Match | None]:
    """Apply `cell_pattern` to a cell value. Per B6: re.fullmatch against the
    stripped string repr; None / empty cells never match.
    """
    if value is None:
        return False, None
    s = str(value).strip()
    if not s:
        return False, None
    m = pattern.fullmatch(s)
    return (m is not None), m


def _row_matches_skip(row: list[Any], rule: SkipRowRule, compiled: re.Pattern | None) -> bool:
    """`SkipRowRule` matches when its column-cell satisfies either
    `cell_pattern` or `match_blank: true`."""
    col = rule.column
    cell = row[col] if col < len(row) else None
    if rule.match_blank:
        if cell is None:
            return True
        if isinstance(cell, str) and cell.strip() == "":
            return True
        return False
    # cell_pattern path; compiled regex passed in to avoid re-compiling per row
    assert compiled is not None
    ok, _ = _cell_matches(cell, compiled)
    return ok


def _apply_separator_rows(
    grid: list[list[Any]],
    rules: list[SkipRowRule],
    cell_range: CellRange | None,
) -> list[list[Any]]:
    """Filter out rows in `grid` that match any of the block's separator rules.

    The grid is already row-windowed to the block instance (via cell_range);
    `column` indexes on each rule are 0-indexed against the SHEET, so we
    adjust to the windowed column offset before indexing.
    """
    col_offset = cell_range.start_col if cell_range else 0
    compiled: list[re.Pattern | None] = [re.compile(r.cell_pattern) if r.cell_pattern else None for r in rules]
    out: list[list[Any]] = []
    for row in grid:
        # Translate sheet-absolute column → grid-relative.
        if any(
            _row_matches_skip(
                row,
                SkipRowRule(
                    column=r.column - col_offset,
                    cell_pattern=r.cell_pattern,
                    match_blank=r.match_blank,
                ),
                compiled[i],
            )
            for i, r in enumerate(rules)
        ):
            continue
        out.append(row)
    return out


def _find_block_instances(
    ws: Sheet,
    block: Block,
    result: ExtractResult,
) -> list[_BlockInstance]:
    """Scan `block.starts_at.column` for every match. Pair with `ends_at` per
    strategy. Returns instances; pushes structural errors to `result.errors`
    for anchor failures.
    """
    starts_at_re = re.compile(block.starts_at.cell_pattern)
    ends_at_re = re.compile(block.ends_at.cell_pattern) if block.ends_at else None

    # First pass: collect all starts_at row indices and all ends_at row indices
    # in the worksheet (single linear scan).
    start_col = block.starts_at.column
    end_col = block.ends_at.column if block.ends_at else -1
    start_rows: list[int] = []
    end_rows: list[int] = []
    for r_idx, row in enumerate(ws.iter_rows()):
        cells = list(row)
        if start_col < len(cells):
            ok, _ = _cell_matches(cells[start_col], starts_at_re)
            if ok:
                start_rows.append(r_idx)
        if ends_at_re is not None and end_col != start_col and end_col < len(cells):
            ok, _ = _cell_matches(cells[end_col], ends_at_re)
            if ok:
                end_rows.append(r_idx)
        elif ends_at_re is not None and end_col == start_col and start_col < len(cells):
            # Same column for starts_at and ends_at — re-check against ends_at_re;
            # a row can be both a start AND an end, so we tally both.
            ok, _ = _cell_matches(cells[start_col], ends_at_re)
            if ok:
                end_rows.append(r_idx)

    if not start_rows:
        result.errors.append(
            ExtractionError(
                entity=None,
                reason="block_starts_not_found",
                details={"block": block.name, "tab": ws.name},
            )
        )
        return []

    # Pair starts with ends per strategy.
    instances: list[_BlockInstance] = []
    for i, start in enumerate(start_rows):
        next_start = start_rows[i + 1] if i + 1 < len(start_rows) else None
        # Closing-window upper bound: just before next start, or EOF.
        ceiling = (next_start - 1) if next_start is not None else None

        if ends_at_re is None:
            # No ends_at: instance ends just before next start, or at EOF.
            # We don't know EOF row from a streaming iter; use a sentinel that
            # _read_flat_grid + iter_rows will naturally clip to last data row.
            end_row = ceiling if ceiling is not None else 1_000_000
            instances.append(_BlockInstance(start_row=start, end_row=end_row))
            continue

        # ends_at: find candidates in (start, ceiling]
        candidates = [e for e in end_rows if e > start and (ceiling is None or e <= ceiling)]
        if not candidates:
            result.errors.append(
                ExtractionError(
                    entity=None,
                    reason="block_unterminated",
                    details={
                        "block": block.name,
                        "tab": ws.name,
                        "instance": i,
                        "starts_at_row": start,
                    },
                )
            )
            continue

        if block.ends_at.strategy == "first_in_block":
            end_row = candidates[0]
        else:  # last_in_block (default)
            end_row = candidates[-1]
        instances.append(_BlockInstance(start_row=start, end_row=end_row))
    return instances


def _resolve_captures(
    ws: Sheet,
    block: Block,
    instance: _BlockInstance,
    result: ExtractResult,
) -> dict[str, Any]:
    """For each capture, scan its `from.column` between [start_row, end_row]
    inclusive, pick per `on_multiple`, extract regex_group, coerce."""
    out: dict[str, Any] = {}
    if not block.captures:
        return out

    # Single pass through the window: collect per-capture matches.
    compiled: list[tuple[Capture, re.Pattern]] = [(c, re.compile(c.from_.cell_pattern)) for c in block.captures]
    matches_per_capture: dict[str, list[tuple[int, str]]] = {c.field: [] for c, _ in compiled}

    iter_min = instance.start_row + 1
    iter_max = instance.end_row + 1
    for offset, row in enumerate(ws.iter_rows(min_row=iter_min, max_row=iter_max)):
        r_idx = instance.start_row + offset
        cells = list(row)
        for cap, pat in compiled:
            col = cap.from_.column
            if col >= len(cells):
                continue
            ok, m = _cell_matches(cells[col], pat)
            if not ok:
                continue
            # Pull the requested regex group (0 = whole match)
            try:
                group_val = m.group(cap.from_.regex_group)
            except IndexError:
                # group index out of range; treat as no-match for this row
                continue
            matches_per_capture[cap.field].append((r_idx, group_val))

    for cap, _ in compiled:
        hits = matches_per_capture[cap.field]
        if len(hits) == 0:
            if cap.required:
                result.errors.append(
                    ExtractionError(
                        entity=None,
                        reason="capture_no_match",
                        details={
                            "block": block.name,
                            "tab": ws.name,
                            "instance_start_row": instance.start_row,
                            "field": cap.field,
                        },
                    )
                )
            out[cap.field] = None
            continue
        if len(hits) > 1 and cap.from_.on_multiple == "error":
            result.errors.append(
                ExtractionError(
                    entity=None,
                    reason="capture_multiple_matches",
                    details={
                        "block": block.name,
                        "tab": ws.name,
                        "instance_start_row": instance.start_row,
                        "field": cap.field,
                        "n_matches": len(hits),
                    },
                )
            )
            out[cap.field] = None
            continue
        if cap.from_.on_multiple == "last" and len(hits) > 1:
            row_idx, raw = hits[-1]
        else:
            # "first" (default), or "error" with exactly one hit, or "last" with exactly one
            row_idx, raw = hits[0]
        try:
            out[cap.field] = _coerce_capture(raw, cap)
        except CoercionError as exc:
            # Surface as a row-level `wrong_type` keyed to the capture so the
            # validator picks it up the same way it does field-level coercion
            # failures.
            result.row_errors.append(
                RowExtractError(
                    entity=cap.field,
                    row=row_idx,
                    field=cap.field,
                    reason="wrong_type",
                    expected=cap.type,
                    got=repr(raw),
                    likely_cause=getattr(exc, "likely_cause", None),
                )
            )
            out[cap.field] = raw
    return out


def _coerce_capture(raw: str, cap: Capture) -> Any:
    """Coerce a captured regex-group string to `cap.type`. Mirrors the
    existing field coercion convention — dates come back as ISO strings, not
    `date` objects, so block-scoped rows can be JSON-serialized the same way
    the rest of the corpus is. Raises `CoercionError` on failure so the
    caller can emit a `wrong_type` row error tied to the capture."""
    if cap.type == "date" and cap.date_formats:
        import datetime as _dt

        for fmt in cap.date_formats:
            try:
                return _dt.datetime.strptime(raw, fmt).date().isoformat()
            except ValueError:
                continue
        raise CoercionError(value=raw, expected="date")
    # For everything else, route through the standard field coercer with
    # a throwaway FieldSpec. Picks up the same ISO-string handling for
    # datetime, the same int/number coercion, etc.
    from crease.template_model import FieldSpec

    spec = FieldSpec(
        name=cap.field,
        type=cap.type,
        date_format=(cap.date_formats[0] if cap.date_formats else None),
    )
    return coerce(raw, spec)


def _extract_for_block(
    workbook: Workbook,
    entity: Entity,
    block: Block,
    template: Template,
    result: ExtractResult,
) -> list[dict[str, Any]]:
    """Top-level driver for entities scoped to a block. Iterates matching
    tabs, finds each block instance, resolves captures, runs the entity
    extraction per instance, merges captures, aggregates."""
    # The block owns tab scope. Build a stand-in Locate so we can reuse
    # `find_tabs` without mutating the entity's locate.
    from crease.template_model import Locate as _LocateClass  # local to avoid top-of-file churn

    block_locate = _LocateClass(
        tab=None,
        tab_pattern=block.tab_pattern,
        orientation=entity.locate.orientation,
    )
    tabs = find_tabs(workbook, block_locate, template.ignore_tabs)
    if not tabs:
        result.errors.append(
            ExtractionError(
                entity=entity.name,
                reason="tab_pattern_no_match" if block.tab_pattern else "missing_tab",
                details={"block": block.name, "tab_pattern": block.tab_pattern},
            )
        )
        return []

    all_rows: list[dict[str, Any]] = []
    for tab in tabs:
        ws = tab.worksheet
        instances = _find_block_instances(ws, block, result)
        for instance in instances:
            captures = _resolve_captures(ws, block, instance, result)
            # Only carry captures with propagate=True onto the row.
            propagating = {cap.field: captures.get(cap.field) for cap in block.captures if cap.propagate}
            cell_range_for_instance = CellRange(
                start_row=instance.start_row,
                end_row=instance.end_row,
                start_col=0,
                end_col=None,
            )
            rows = _extract_flat(
                ws,
                entity,
                tab,
                template,
                result,
                cell_range_override=cell_range_for_instance,
                separator_rows=block.separator_rows,
                extra_fields=propagating,
            )
            if isinstance(rows, list):
                all_rows.extend(rows)
            elif rows is not None:
                all_rows.append(rows)
    return all_rows


def _extract_entity(workbook: Workbook, entity: Entity, template: Template, result: ExtractResult) -> None:  # noqa: E501
    # Block-scoped entities take the block path entirely; the block owns
    # tab targeting and instance discovery. The template validator already
    # checked that the named block exists.
    if entity.block is not None:
        block = next((b for b in template.blocks if b.name == entity.block), None)
        if block is None:
            # Defense in depth — the template-load validator should have
            # caught this. If it didn't, surface it instead of silently
            # producing no rows.
            result.errors.append(
                ExtractionError(
                    entity=entity.name,
                    reason="block_ref_not_found",
                    details={"block": entity.block},
                )
            )
            result.canonical[_pluralize(entity.name) if entity.cardinality == "many" else entity.name] = (
                [] if entity.cardinality == "many" else None
            )
            return
        rows = _extract_for_block(workbook, entity, block, template, result)
        key = entity.name if entity.cardinality == "one" else _pluralize(entity.name)
        if entity.cardinality == "one":
            result.canonical[key] = rows[0] if rows else None
        else:
            result.canonical[key] = rows
        return

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


def extract(path: str | Path, template: Template, *, engine: Engine | None = None) -> ExtractResult:
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

    Raises:
        crease.SourceFileError: If the file is missing, corrupt, encrypted,
            or in a format the chosen backend cannot read.
    """
    p = Path(path)
    result = ExtractResult(
        template_id=template.template_id,
        source_file=p.name,
        template=template,
    )
    workbook = open_workbook(p, select_engine(template, engine))
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
    engine: Engine | None = None,
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
    engine: Engine | None = None,
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
