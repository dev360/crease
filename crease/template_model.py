"""Pydantic models that define the Crease YAML template."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

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


class Template(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str
    version: int = 1
    description: str
    entities: list[Entity]
    ignore_tabs: list[str] = []
    notes: list[str] = []

    # template-level extraction defaults (applied to all fields unless overridden)
    null_tokens: list[str] | None = None  # None = library defaults

    # filename-as-metadata
    filename_pattern: str | None = None
    filename_capture: list[FilenameCapture] = []

    @classmethod
    def load(cls, path: str | Path) -> Template:
        """Load a template from a .crease.yml file."""
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
