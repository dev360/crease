# Why crease exists

Excel parsing has well-documented failure modes that quietly cost money and
time. Crease is designed to make these *visible and structured* rather than
silent.

This page summarises the patterns that shaped the design. The full research
notes (with sources) live in [ANECDOTES.md](https://github.com/dev360/crease/blob/main/ANECDOTES.md)
in the repository.

---

## Excel autoconvert destroys gene names

Microsoft Excel silently converts strings that *look like* dates or numbers
into dates or scientific notation. In genomics:

| Original | What Excel turned it into |
|---|---|
| `SEPT2` (Septin-2 gene) | `2-Sep` |
| `MARCH1` | `1-Mar` |
| `2310009E13` (gene accession) | `2.31E+13` |

A 2016 study found **~20% of supplementary spreadsheets** in genomics
research contained these corruptions. In 2020, the gene nomenclature
committee renamed 30+ genes rather than fix Excel.

**How crease handles it.** The validator emits `wrong_type` with
`ctx.likely_cause: "excel_autoconvert"` when a string field receives what
looks like an autoconverted value. The template field can declare
`treat_as_text: true` to force the column out of the date path.

---

## Public Health England loses 15,706 COVID cases

During the early UK pandemic, daily case data was batched through Excel's
legacy `.xls` format — which has a **65,536-row limit per sheet**. When
case counts spiked, ~16,000 rows silently overflowed past the limit and
**never reached contact tracing**. The bug took **8 days to identify**.

**How crease handles it.** Silent truncation is the worst failure mode.
Crease never "rounds down" — `min_data_rows` on a template and
`column_count_mismatch` detection ensure structural problems surface as
`severity: structural` errors that route to a rejection queue, not into
the downstream pipeline.

---

## JPMorgan loses \$6B because a VaR model required manual copy-paste

JPMorgan's Value-at-Risk model spanned multiple Excel workbooks. Updating
it required *manually* copying values from one workbook into another,
sheet by sheet. A modeler used `divide by sum` instead of `divide by
average`, halving the apparent volatility. The desk took larger positions;
losses hit \$6 billion.

**How crease handles it.** Canonical JSON flows from xlsx into downstream
pipelines directly — the copy step disappears. Manual transcription is
the workflow crease replaces.

---

## Lehman Brothers' hidden-rows-resurrected-in-PDF

Barclays Capital bought 179 of Lehman's trading contracts that Barclays did
**not** intend to buy. Lehman had *hidden* the rows for excluded
contracts (rather than deleting them). When the spreadsheet was converted
to PDF for the legal record, **the hidden rows reappeared**.

**How crease handles it.** Hidden cells are still data. The template flag
`locate.skip_hidden_rows: true` excludes hidden rows from extraction,
giving operators a deterministic way to opt out of soft-deleted data.

---

## VLOOKUP fails because `"Acme Corp"` has a trailing space

A trailing space, a smart quote, an em dash that should have been a
hyphen — invisible character differences turn matches into `#N/A`. Hours
of debugging follow.

**How crease handles it.** Always-on header normalisation (case-fold +
trim + collapse internal whitespace) for column names. Per-field
`normalize: trim | lower | trim_lower` for cell values.

---

## `N/A`, `TBD`, `-` in cells trigger `wrong_type` everywhere

Half the columns in a spreadsheet include sentinel values that mean
"missing." Without a way to declare them, every one of them produces a
spurious `wrong_type` error and buries the real ones.

**How crease handles it.** Layered `null_tokens`: library defaults
(`N/A`, `TBD`, `-`, `—`, `(blank)`, `NaN`, …) → template-level overrides
→ per-field overrides. Override any layer, including `null_tokens: []`
to disable.

---

## Headers move down a row when the customer adds a title line

The customer pastes a title above the table. Every subsequent file fails
because `header_row: 3` is now `header_row: 4`.

**How crease handles it.** `locate.header_anchor: "Order ID"` finds the
header row by scanning for a known label, not by fixed offset. Adding
title rows above the table doesn't break the template.

---

## The design philosophy

Each of these failures shares one shape: **silent transformation between
the customer's intent and the downstream pipeline.** Crease's principle
is to make every transformation explicit:

- **Templates declare what the data is supposed to look like.** A
  divergence isn't a parse failure — it's a structured error with a row
  and field coordinate.
- **Errors carry coordinates.** `Error.loc = (entity, row, field)` is the
  load-bearing line.
- **The library never silently drops or coerces.** Cell-level problems
  route to a `needs_review` queue; structural problems route to a
  `reject` queue. Either way, they're visible.

> The full research notes (incidents, sources, test-fixture mappings) live
> in `ANECDOTES.md`. Each pattern that we ship coverage for is tagged with
> the test fixture under `test_cases/` that locks it down.
