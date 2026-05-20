"""
Streamlit frontend for cohort-based schema inference.

Workflow:
  1. Name the cohort and describe what the files contain
  2. Drop in 1-N Excel files
  3. Click "Infer schema" — Claude reads samples, returns a JSON Schema
  4. Review, optionally edit, save to disk
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import streamlit as st

from schema_inference import (
    FileSample,
    InferredSchema,
    infer_schema,
    sample_file,
    to_json_schema,
)


SCHEMAS_DIR = Path("artifacts/cohort_schemas")
SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)


st.set_page_config(page_title="Excel Schema Inferrer", layout="wide")
st.title("Excel Schema Inferrer")
st.caption("Drop files into a cohort. Claude infers a JSON Schema for the rows.")


with st.sidebar:
    st.subheader("Settings")
    api_key_present = bool(os.environ.get("ANTHROPIC_API_KEY"))
    st.write(("API key: detected" if api_key_present else "Set `ANTHROPIC_API_KEY` env var"))
    model = st.selectbox(
        "Model",
        ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"],
        index=0,
        help="Opus is most accurate; Sonnet is faster/cheaper.",
    )

# ---------- Cohort definition ----------

col1, col2 = st.columns([1, 2])
with col1:
    cohort_name = st.text_input(
        "Cohort name",
        placeholder="e.g. quarterly_orders",
        help="Lowercase, no spaces. Used as the filename.",
    )
with col2:
    description = st.text_area(
        "Describe what these files contain",
        placeholder=(
            "e.g. Each file is one customer's monthly order history. "
            "Rows are individual orders. Columns include order ID, date, "
            "customer info, product SKU, and pricing."
        ),
        height=100,
    )

uploaded_files = st.file_uploader(
    "Drop Excel files",
    type=["xlsx", "xls"],
    accept_multiple_files=True,
    help="All files should share the same schema (= one cohort).",
)

# ---------- Sample preview ----------

samples: list[FileSample] = []
if uploaded_files:
    with tempfile.TemporaryDirectory() as tmpdir:
        for up in uploaded_files:
            tmp_path = Path(tmpdir) / up.name
            tmp_path.write_bytes(up.getbuffer())
            samples.append(sample_file(tmp_path))

    with st.expander(f"Preview samples ({len(samples)} files)", expanded=False):
        for f in samples:
            st.markdown(f"**`{f.filename}`**")
            for tab in f.tabs:
                st.caption(
                    f"Tab `{tab.tab_name}` — {tab.total_rows} rows total, "
                    f"showing first {len(tab.rows)}"
                )
                preview = [tab.headers] + tab.rows[:5]
                st.dataframe(
                    {h: [r[i] if i < len(r) else None for r in tab.rows[:5]]
                     for i, h in enumerate(tab.headers)},
                    use_container_width=True,
                )

# ---------- Inference ----------

can_run = bool(samples and description.strip() and cohort_name.strip() and api_key_present)
if st.button("Infer schema", type="primary", disabled=not can_run):
    if not api_key_present:
        st.error("Set ANTHROPIC_API_KEY in your environment first.")
    else:
        with st.spinner(f"Asking {model}..."):
            try:
                import anthropic
                client = anthropic.Anthropic()
                inferred, meta = infer_schema(
                    samples, description, client=client, model=model,
                )
                st.session_state["inferred"] = inferred.model_dump()
                st.session_state["meta"] = meta
                st.session_state["cohort_name"] = cohort_name
            except Exception as e:
                st.error(f"Inference failed: {e}")
                st.exception(e)

# ---------- Show result ----------

if "inferred" in st.session_state:
    inferred_dict = st.session_state["inferred"]
    inferred = InferredSchema(**inferred_dict)
    meta = st.session_state.get("meta", {})

    st.success(f"Inferred schema: **{inferred.title}**")
    st.write(inferred.description)

    if meta:
        st.caption(
            f"Model: {meta.get('model')} · "
            f"input tokens: {meta.get('usage', {}).get('input_tokens')} · "
            f"output tokens: {meta.get('usage', {}).get('output_tokens')}"
        )

    tab_view, tab_json, tab_notes = st.tabs(["Fields", "JSON Schema", "Notes"])

    with tab_view:
        st.dataframe(
            [{
                "name": f.name,
                "type": f.json_type,
                "semantic": f.semantic_type,
                "nullable": f.nullable,
                "enum_values": ", ".join(f.enum_values) if f.enum_values else "",
                "description": f.description,
            } for f in inferred.fields],
            use_container_width=True,
        )

    with tab_json:
        json_schema = to_json_schema(inferred, st.session_state.get("cohort_name", "cohort"))
        st.code(json.dumps(json_schema, indent=2), language="json")

        cohort_name_to_save = st.session_state.get("cohort_name", "cohort")
        save_path = SCHEMAS_DIR / f"{cohort_name_to_save}.schema.json"
        if st.button(f"Save to `{save_path}`"):
            save_path.write_text(json.dumps(json_schema, indent=2))
            st.success(f"Saved to {save_path}")

    with tab_notes:
        if inferred.notes:
            for n in inferred.notes:
                st.write(f"- {n}")
        else:
            st.write("_(no notes)_")
