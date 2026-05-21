"""Pydantic models that define the Crease YAML template."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

# ---- enums ---------------------------------------------------------------

FieldType = Literal[
    "string",
    "integer",
    "number",
    "boolean",
    "date",
    "datetime",
    "email",
    "uuid",
    "url",
]
Orientation = Literal["flat", "property_sheet", "anchored"]
MatchMode = Literal["exact", "contains", "regex"]
Direction = Literal["right", "below", "left", "above"]
DataEndType = Literal["end_of_sheet", "blank_row", "value_match", "skip_trailing_rows"]
EnrichSource = Literal["tab_name", "tab_name_regex_group"]
Normalize = Literal["none", "trim", "lower", "trim_lower"]


# ---- core blocks ---------------------------------------------------------


class HeaderAnchor(BaseModel):
    """Locate the header row by scanning for a known label rather than a fixed index."""

    model_config = ConfigDict(extra="forbid")

    text: str
    match_mode: MatchMode = "contains"
    column: int | None = None  # restrict scan to one column; None = any column


class Anchor(BaseModel):
    """Locate one field's value in `anchored` orientation."""

    model_config = ConfigDict(extra="forbid")

    label_match: str
    match_mode: MatchMode = "contains"
    value_at: Direction = "right"
    offset: int = 1
    column: int | None = None  # restrict label search to a single column; None = any column
    nth: int = 1  # 1-indexed match to return when the label appears more than once


class DataEnd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: DataEndType = "end_of_sheet"
    n_consecutive: int = 1  # blank_row
    column: int = 0  # value_match
    value: str | None = None  # value_match
    rows: int = 0  # skip_trailing_rows


class Unpivot(BaseModel):
    """Reshape wide-format data into long-format during extraction."""

    model_config = ConfigDict(extra="forbid")

    id_columns: list[str]
    variable_column_pattern: str  # regex; columns matching go into variable_name
    variable_name: str
    value_name: str


class FilenameCapture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    group: int
    type: FieldType = "string"


class LocateSkipRule(BaseModel):
    """One predicate for ``Locate.skip_row_if``.

    Distinct from the block-scoped ``SkipRowRule`` (which filters rows
    inside a single block instance by single-column pattern). This
    rule operates on top-level Locate extraction and supports
    multi-column predicates:

    - ``all_blank``: every listed column must be blank on the row.
    - ``non_blank``: every listed column must carry a non-blank value.
    - ``column`` + ``value_pattern``: that column's stringified value
      must fully match the regex.

    Combine fields on the same rule for AND semantics (e.g. blank
    discriminator AND populated totals column). Use multiple rules in
    the list for OR semantics across distinct shapes.
    """

    model_config = ConfigDict(extra="forbid")

    all_blank: list[str] | None = None
    non_blank: list[str] | None = None
    column: str | None = None
    value_pattern: str | None = None  # regex; full-match


class Locate(BaseModel):
    """Where (and how) to find an entity's data."""

    model_config = ConfigDict(extra="forbid")

    # Tab targeting (exactly one of tab / tab_pattern must be set, except when cell_range is used in a single tab)
    tab: str | None = None
    tab_pattern: str | None = None  # regex

    orientation: Orientation

    # Optional sub-range to restrict the entity to part of the tab
    cell_range: str | None = None  # "A8:E*" or "A1:B6"

    # flat
    header_row: int = 0
    header_anchor: HeaderAnchor | None = None
    data_starts_row: int | None = None
    data_ends_at: DataEnd | None = None
    skip_row_if: list[LocateSkipRule] = []

    # property_sheet
    label_col: int = 0
    value_col: int = 1
    start_row: int = 0

    # filtering
    skip_hidden_rows: bool = False


class Enrich(BaseModel):
    """Inject a field into extracted rows derived from the tab name."""

    model_config = ConfigDict(extra="forbid")

    field: str
    source: EnrichSource = "tab_name"
    group: int = 1
    strip_prefix: str | None = None
    strip_suffix: str | None = None
    type: FieldType = "string"  # coerce the extracted value


class FieldSpec(BaseModel):
    """A canonical field: name, type, source mapping, constraints."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    type: FieldType

    # source mapping (one of these is set, depending on orientation)
    source_column: str | None = None  # flat
    # Disambiguates when source_column matches multiple header cells in the
    # same row. 0-indexed across the matching occurrences (not raw column
    # index). Leave None to let crease raise header_duplicated when the
    # header is ambiguous.
    source_column_index: int | None = None  # flat
    source_label: str | None = None  # property_sheet
    anchor: Anchor | None = None  # anchored

    # constraints
    pattern: str | None = None
    enum: list[str] | None = None
    minimum: float | None = None
    maximum: float | None = None
    nullable: bool = False

    # extraction hints
    null_tokens: list[str] | None = None  # None = use template default; [] = no tokens
    normalize: Normalize = "none"
    treat_as_text: bool = False
    true_values: list[str] | None = None  # boolean only
    false_values: list[str] | None = None
    date_format: str | None = None  # strptime-compatible


class Entity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    cardinality: Literal["one", "many"]
    locate: Locate
    fields: list[FieldSpec]
    enrich: list[Enrich] = []
    unpivot: Unpivot | None = None

    # `blocks:` grammar (template version 2). When set, the entity is scoped
    # to each instance of the named block; the block's captures merge onto
    # every emitted row. None = run globally, today's behavior.
    block: str | None = None


# ---- blocks: grammar (template version 2) -------------------------------
#
# A `Block` declares a repeating region inside a tab: anchor patterns that
# delimit each instance, optional per-instance captures (metadata that
# applies to every row inside), and optional separator-row rules. Entities
# at the top level reference a block by name via `Entity.block`. There is
# no nested-blocks form in v2 — composition stays flat.


# Coerce an `int` (0-indexed column) or an Excel letter ("A" .. "Z") into a
# 0-indexed int. Anything else is a validation error. Single-letter only
# in v2 — multi-letter (e.g. "AA") is out of scope until a real fixture
# demands it.
def _coerce_column(v: Any) -> int:
    if isinstance(v, bool):
        # bool is a subclass of int in Python; reject explicitly.
        raise ValueError("column must be an int or single Excel letter, not a bool")
    if isinstance(v, int):
        if v < 0:
            raise ValueError(f"column must be >= 0, got {v}")
        return v
    if isinstance(v, str):
        s = v.strip().upper()
        if len(s) == 1 and "A" <= s <= "Z":
            return ord(s) - ord("A")
        raise ValueError(f"column letter must be A..Z (single letter), got {v!r}")
    raise ValueError(f"column must be an int or Excel letter, got {type(v).__name__}")


class CellAnchor(BaseModel):
    """Locate a cell by scanning one column for a regex match."""

    model_config = ConfigDict(extra="forbid")

    column: int
    cell_pattern: str
    regex_group: int = 0
    on_multiple: Literal["first", "last", "error"] = "first"

    @field_validator("column", mode="before")
    @classmethod
    def _column_letter(cls, v: Any) -> int:
        return _coerce_column(v)


class EndAnchor(CellAnchor):
    """Close-of-block anchor. Adds the search strategy."""

    strategy: Literal["first_in_block", "last_in_block"] = "last_in_block"


class SkipRowRule(BaseModel):
    """A row filter applied inside a block. Exactly one of cell_pattern or
    match_blank must be set."""

    model_config = ConfigDict(extra="forbid")

    column: int
    cell_pattern: str | None = None
    match_blank: bool = False

    @field_validator("column", mode="before")
    @classmethod
    def _column_letter(cls, v: Any) -> int:
        return _coerce_column(v)

    @model_validator(mode="after")
    def _exactly_one(self) -> SkipRowRule:
        has_pattern = self.cell_pattern is not None
        if has_pattern == self.match_blank:
            raise ValueError("SkipRowRule requires exactly one of `cell_pattern` or `match_blank: true`")
        return self


class Capture(BaseModel):
    """A piece of per-block-instance metadata. Scanned inside the block,
    coerced to a type, then merged onto every entity row in the instance."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    field: str
    from_: CellAnchor = Field(alias="from")
    type: FieldType
    date_formats: list[str] = []
    required: bool = True
    propagate: bool = True


class Block(BaseModel):
    """A repeating region within a tab."""

    model_config = ConfigDict(extra="forbid")

    name: str
    tab_pattern: str | None = None
    starts_at: CellAnchor
    ends_at: EndAnchor | None = None
    separator_rows: list[SkipRowRule] = []
    captures: list[Capture] = []


class Template(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str
    # version: 1 = legacy (no `blocks:`); version: 2 = supports `blocks:` and
    # `Entity.block`. Bump explicitly when authoring a template that uses
    # the v2 grammar so older loaders can fail loudly instead of silently
    # ignoring unknown fields.
    version: Literal[1, 2] = 1
    description: str
    entities: list[Entity]
    blocks: list[Block] = []
    ignore_tabs: list[str] = []
    notes: list[str] = []

    # template-level extraction defaults (applied to all fields unless overridden)
    null_tokens: list[str] | None = None  # None = library defaults

    # filename-as-metadata
    filename_pattern: str | None = None
    filename_capture: list[FilenameCapture] = []

    @model_validator(mode="after")
    def _check_blocks_grammar(self) -> Template:
        # `blocks:` is a v2 feature.
        if self.blocks and self.version == 1:
            raise ValueError(
                "`blocks:` requires `version: 2`; bump the template version " "or remove the blocks declaration"
            )

        if not self.blocks:
            return self

        block_by_name = {b.name: b for b in self.blocks}
        if len(block_by_name) != len(self.blocks):
            seen: set[str] = set()
            dupes = [b.name for b in self.blocks if b.name in seen or seen.add(b.name)]  # type: ignore[func-returns-value]
            raise ValueError(f"duplicate block name(s): {sorted(set(dupes))}")

        for ent in self.entities:
            if ent.block is None:
                continue

            block = block_by_name.get(ent.block)
            if block is None:
                # `block_ref_not_found` — entity points at a name that's not declared.
                raise ValueError(
                    f"entity {ent.name!r}: block reference {ent.block!r} not found in "
                    f"template.blocks ({sorted(block_by_name)})"
                )

            # `entity_tab_with_block` — the block owns tab scope.
            if ent.locate.tab is not None or ent.locate.tab_pattern is not None:
                raise ValueError(
                    f"entity {ent.name!r}: `locate.tab`/`tab_pattern` is not allowed "
                    f"when `block: {ent.block!r}` is set; the block owns tab scope"
                )

            # `field_shadow_collision` — capture name collides with an entity field name.
            capture_names = {c.field for c in block.captures}
            field_names = {f.name for f in ent.fields}
            collisions = capture_names & field_names
            if collisions:
                raise ValueError(
                    f"entity {ent.name!r}: field name(s) {sorted(collisions)} collide "
                    f"with captures on block {block.name!r}; rename one side"
                )

        return self

    @classmethod
    def load(cls, path: str | Path) -> Template:
        """Load a template from a .crease.yml file.

        Args:
            path: Path to the YAML file.

        Returns:
            A validated `Template` instance.
        """
        import yaml

        return cls.model_validate(yaml.safe_load(Path(path).read_text()))

    def save(self, path: str | Path) -> None:
        """Write the template to a .crease.yml file."""
        import yaml

        Path(path).write_text(
            yaml.safe_dump(
                self.model_dump(exclude_none=True),
                sort_keys=False,
                default_flow_style=False,
                allow_unicode=True,
            )
        )

    def model(self, entity: str) -> type[BaseModel]:
        """Build a Pydantic model from an entity's field declarations.

        Field types map as: ``string``/``email``/``uuid``/``url`` → str,
        ``integer`` → int, ``number`` → float, ``boolean`` → bool, ``date``
        → ``datetime.date``, ``datetime`` → ``datetime.datetime``. Nullable
        fields are ``T | None`` with default ``None``.

        The generated model uses ``extra="ignore"`` so enriched / extra
        keys don't error. Pydantic's default coercion is permitted (e.g.
        an ISO-format date string projects into ``datetime.date``) — truly
        incompatible inputs still raise, which is what callers want from
        "throw if the type is wrong."

        Args:
            entity: Name of the entity (must match `Entity.name`).

        Returns:
            A new Pydantic ``BaseModel`` subclass.

        Raises:
            KeyError: If no entity with that name exists.
        """
        return _build_entity_model(self, entity)


# ---- library-level defaults ---------------------------------------------

DEFAULT_NULL_TOKENS: list[str] = [
    "N/A",
    "n/a",
    "NA",
    "na",
    "TBD",
    "tbd",
    "-",
    "—",
    "–",
    "(blank)",
    "(empty)",
    "(none)",
    "NaN",
    "nan",
    "null",
    "NULL",
    "None",
    "#N/A",
    "#NULL",
]

DEFAULT_TRUE_VALUES: list[str] = ["true", "True", "TRUE", "yes", "Yes", "YES", "y", "Y", "1"]
DEFAULT_FALSE_VALUES: list[str] = ["false", "False", "FALSE", "no", "No", "NO", "n", "N", "0"]


# ---- entity-model generation --------------------------------------------

_PY_TYPE: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "date": _dt.date,
    "datetime": _dt.datetime,
    "email": str,
    "uuid": str,
    "url": str,
}


def _build_entity_model(template: Template, entity_name: str) -> type[BaseModel]:
    """Generate a Pydantic model class for a template entity."""
    entity = next((e for e in template.entities if e.name == entity_name), None)
    if entity is None:
        raise KeyError(
            f"No entity named {entity_name!r} in template {template.template_id!r}; "
            f"known entities: {[e.name for e in template.entities]}"
        )

    fields: dict[str, tuple[Any, Any]] = {}
    for f in entity.fields:
        py_type = _PY_TYPE.get(f.type, str)
        if f.nullable:
            fields[f.name] = (py_type | None, None)
        else:
            fields[f.name] = (py_type, ...)

    class_name = "".join(part.capitalize() for part in entity_name.split("_")) or "Entity"

    Model = create_model(  # type: ignore[call-overload]
        class_name,
        # extra="ignore" — silently drop canonical fields the model doesn't declare,
        # so a subset model can project a richer canonical record.
        # strict=False — accept Pydantic's safe coercions (ISO date strings → date,
        # "5" → 5). Truly incompatible types still raise, which is what callers
        # want from "throw if the type is wrong."
        __config__=ConfigDict(extra="ignore", strict=False, arbitrary_types_allowed=True),
        **fields,
    )
    Model.__doc__ = f"Auto-generated from crease template '{template.template_id}', entity '{entity_name}'."
    return Model
