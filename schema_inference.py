"""
Given a "cohort" of Excel files + a user description, ask Claude to infer
a JSON Schema describing one row of the data.

Approach:
  1. Read each file with openpyxl, extract a sample of rows per tab
  2. Render the samples as markdown tables (clearest format for the model)
  3. Pass them all in one prompt with the user's description
  4. Use structured outputs (output_config.format.json_schema) to constrain
     Claude's response to a known shape
  5. Convert the response into a standard JSON Schema and return both
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
import json

import openpyxl
from pydantic import BaseModel, Field

import anthropic


SAMPLE_ROWS = 25  # rows per tab to send to the model
MODEL = "claude-opus-4-7"


# ---------- structured output schema ----------

JsonType = Literal["string", "integer", "number", "boolean", "null"]
SemanticType = Literal[
    "none", "date", "datetime", "email", "uuid", "url", "phone",
    "currency", "percentage", "country", "country_code", "us_state",
    "postal_code", "enum",
]


class FieldSpec(BaseModel):
    name: str = Field(description="Field name as it appears in the file (header text).")
    description: str = Field(description="What this field contains; reasoned from the values.")
    json_type: JsonType = Field(description="The JSON primitive type.")
    semantic_type: SemanticType = Field(
        default="none",
        description="A more specific type when applicable (date, email, uuid, etc).",
    )
    nullable: bool = Field(
        description="True if any sampled value was blank/missing; "
                    "false if every sampled value was populated.",
    )
    enum_values: list[str] | None = Field(
        default=None,
        description="If semantic_type is 'enum', list the observed distinct values.",
    )


class InferredSchema(BaseModel):
    title: str = Field(description="Short title for this dataset, e.g. 'Quarterly Sales Orders'.")
    description: str = Field(description="One-paragraph description of what each row represents.")
    fields: list[FieldSpec]
    notes: list[str] = Field(
        default_factory=list,
        description="Observations: ambiguities, suspected data quality issues, layout quirks.",
    )


# ---------- file sampling ----------

@dataclass
class TabSample:
    tab_name: str
    headers: list[str]
    rows: list[list[Any]]
    total_rows: int


@dataclass
class FileSample:
    filename: str
    tabs: list[TabSample]


def sample_file(path: Path, max_rows: int = SAMPLE_ROWS) -> FileSample:
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    tabs = []
    for ws in wb.worksheets:
        all_rows = []
        for row in ws.iter_rows(values_only=True):
            all_rows.append(list(row))
        # trim trailing fully-empty rows that openpyxl pads
        while all_rows and all(v is None for v in all_rows[-1]):
            all_rows.pop()
        if not all_rows:
            continue
        headers = [str(h) if h is not None else "" for h in all_rows[0]]
        body = all_rows[1:]
        sampled = body[:max_rows]
        tabs.append(TabSample(
            tab_name=ws.title,
            headers=headers,
            rows=sampled,
            total_rows=len(body),
        ))
    return FileSample(filename=path.name, tabs=tabs)


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    def cell(v):
        if v is None:
            return ""
        s = str(v)
        return s.replace("|", "\\|").replace("\n", " ")
    head = "| " + " | ".join(cell(h) for h in headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = "\n".join("| " + " | ".join(cell(v) for v in row) + " |" for row in rows)
    return "\n".join([head, sep, body]) if body else head + "\n" + sep


def render_samples(samples: list[FileSample]) -> str:
    """Render the cohort's samples as markdown for the model."""
    parts: list[str] = []
    for f in samples:
        parts.append(f"## File: `{f.filename}`")
        for tab in f.tabs:
            parts.append(
                f"\n### Tab: `{tab.tab_name}`  "
                f"({tab.total_rows} data rows total, showing first {len(tab.rows)})"
            )
            parts.append(_markdown_table(tab.headers, tab.rows))
    return "\n\n".join(parts)


# ---------- LLM call ----------

SYSTEM_PROMPT = """You are a data-schema expert. The user will give you sample rows
from one or more Excel files that share a schema (a "cohort"), plus a description of
what the files contain. Your job is to infer the schema of ONE ROW.

Guidance:
- Use the user's description as the primary signal for what the data represents.
- Use the sample VALUES (not just headers) to infer types — a column called "amount"
  could be int, float, or currency string; the values tell you which.
- Pick the narrowest semantic_type that fits every observed value. If values are
  ISO dates, use "date". If they look like email addresses, use "email". Etc.
- Mark `nullable: true` if you see ANY blank/None value in that column.
- For categorical columns with few distinct values, use `semantic_type: "enum"`
  and list the observed values.
- In `notes`, call out anything ambiguous, suspected dirty data, or layout quirks
  (e.g. "Tab 'Cover' has metadata, not row data").
"""


def infer_schema(
    samples: list[FileSample],
    description: str,
    client: anthropic.Anthropic | None = None,
    model: str = MODEL,
) -> tuple[InferredSchema, dict]:
    """Call Claude to infer the schema. Returns (parsed_schema, raw_message_dict)."""
    client = client or anthropic.Anthropic()

    user_content = (
        f"## What the user says these files contain\n\n{description}\n\n"
        f"## Sample data\n\n{render_samples(samples)}\n\n"
        "Infer the schema of one row. Return your answer in the structured format."
    )

    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        output_format=InferredSchema,
    )

    parsed: InferredSchema = response.parsed_output
    return parsed, {"model": response.model, "usage": response.usage.model_dump()}


# ---------- conversion to standard JSON Schema ----------

_SEMANTIC_FORMAT = {
    "date": "date",
    "datetime": "date-time",
    "email": "email",
    "uuid": "uuid",
    "url": "uri",
}


def to_json_schema(inferred: InferredSchema, cohort_name: str) -> dict:
    """Convert our InferredSchema into a Draft-07 JSON Schema document."""
    properties: dict[str, dict] = {}
    required: list[str] = []
    for f in inferred.fields:
        prop: dict[str, Any] = {"description": f.description}
        if f.nullable:
            prop["type"] = [f.json_type, "null"]
        else:
            prop["type"] = f.json_type
            required.append(f.name)
        fmt = _SEMANTIC_FORMAT.get(f.semantic_type)
        if fmt:
            prop["format"] = fmt
        if f.semantic_type == "enum" and f.enum_values:
            prop["enum"] = f.enum_values
        # keep our extra semantic info under an x- prefix so it round-trips
        if f.semantic_type and f.semantic_type != "none":
            prop["x-semantic-type"] = f.semantic_type
        properties[f.name] = prop

    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": inferred.title,
        "description": inferred.description,
        "x-cohort": cohort_name,
        "x-notes": inferred.notes,
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }
