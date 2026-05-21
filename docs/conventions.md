# Excel conventions in the wild

> A reference for the patterns customers actually send. Each section names a
> convention, shows a minimal example, and notes how crease's declarative YAML
> handles it (or where we explicitly defer).

The examples use plain HTML `<table>` blocks so the file renders on GitHub,
in MkDocs, and in any other markdown viewer. No build step required.

---

## 1. Title block above the header row

A few "decorative" rows precede the actual header row.

<table>
  <thead><tr><th></th><th>A</th><th>B</th><th>C</th></tr></thead>
  <tbody>
    <tr><td>1</td><td colspan="3">Acme Corporation — Order Export</td></tr>
    <tr><td>2</td><td colspan="3">Generated: 2025-04-15</td></tr>
    <tr><td>3</td><td></td><td></td><td></td></tr>
    <tr><td>4</td><td><b>order_id</b></td><td><b>order_date</b></td><td><b>customer_email</b></td></tr>
    <tr><td>5</td><td>ORD-1001</td><td>2025-01-15</td><td>a@acme.com</td></tr>
  </tbody>
</table>

> **How crease handles it.** `locate.header_row: 3` (zero-indexed) and
> `locate.data_starts_row: 4`. The LLM is expected to recognize that rows
> 0–2 are non-tabular and pick the correct header row from the samples.

**Fixture:** `flat_with_title_rows`

---

## 2. Footer / totals row below the data

A summary row at the bottom that *looks* like data but shouldn't be extracted.

<table>
  <thead><tr><th></th><th>A</th><th>B</th><th>C</th></tr></thead>
  <tbody>
    <tr><td>1</td><td><b>order_id</b></td><td><b>quantity</b></td><td><b>total</b></td></tr>
    <tr><td>2</td><td>ORD-1001</td><td>10</td><td>250.00</td></tr>
    <tr><td>3</td><td>ORD-1002</td><td>5</td><td>500.00</td></tr>
    <tr><td>4</td><td>ORD-1003</td><td>3</td><td>75.00</td></tr>
    <tr><td>5</td><td><b>TOTAL</b></td><td></td><td><b>825.00</b></td></tr>
  </tbody>
</table>

> **How crease handles it.** `locate.data_ends_at: {type: value_match, column: 0, value: "TOTAL"}`
> — stop reading at the first row whose column 0 contains "TOTAL".

**Fixture:** `flat_with_totals_row`

---

## 3. Multi-level (merged) headers

Excel merge cells produce visually-grouped headers across two rows.

<table>
  <thead><tr><th></th><th>A</th><th>B</th><th>C</th><th>D</th></tr></thead>
  <tbody>
    <tr><td>1</td><td>SKU</td><td colspan="3" align="center">Q1 2025</td></tr>
    <tr><td>2</td><td></td><td>Jan</td><td>Feb</td><td>Mar</td></tr>
    <tr><td>3</td><td>SKU-001</td><td>120</td><td>140</td><td>155</td></tr>
    <tr><td>4</td><td>SKU-002</td><td>30</td><td>45</td><td>50</td></tr>
  </tbody>
</table>

> **How crease handles it.** **Deferred to v2.** This requires either a
> crosstab-aware extractor or a pre-flatten step. v1 emits
> `column_count_mismatch` and routes to a structural-error reject queue.

---

## 4. Scattered metadata on a cover sheet

Properties sprinkled across a tab with gaps, notes, and arbitrary ordering.

<table>
  <thead><tr><th></th><th>A</th><th>B</th></tr></thead>
  <tbody>
    <tr><td>1</td><td colspan="2"><b>Acme Quarterly Sales Report</b></td></tr>
    <tr><td>2</td><td colspan="2"></td></tr>
    <tr><td>3</td><td colspan="2"></td></tr>
    <tr><td>4</td><td>Reporting Period:</td><td>Q1 2025</td></tr>
    <tr><td>5</td><td colspan="2"></td></tr>
    <tr><td>6</td><td>Submitted by:</td><td>Jane Smith</td></tr>
    <tr><td>7</td><td>Contact:</td><td>jane@acme.com</td></tr>
    <tr><td>8</td><td colspan="2"></td></tr>
    <tr><td>9</td><td>Notes:</td><td></td></tr>
    <tr><td>10</td><td colspan="2">First-time submission — please confirm</td></tr>
    <tr><td>11</td><td colspan="2"></td></tr>
    <tr><td>12</td><td>Date sent:</td><td>2025-04-15</td></tr>
  </tbody>
</table>

> **How crease handles it.** `orientation: anchored` with per-field
> `anchor.label_match`. Each field finds its label independently, walks
> one cell right, reads the value.

**Fixture:** `anchored_scattered`

---

## 5. Multiple tables on one tab

Two unrelated tables stacked vertically, separated by blank rows.

<table>
  <thead><tr><th></th><th>A</th><th>B</th><th>C</th></tr></thead>
  <tbody>
    <tr><td>1</td><td><b>Customer Info</b></td><td colspan="2"></td></tr>
    <tr><td>2</td><td>Name</td><td>Acme</td><td></td></tr>
    <tr><td>3</td><td>Tier</td><td>Enterprise</td><td></td></tr>
    <tr><td>4</td><td></td><td></td><td></td></tr>
    <tr><td>5</td><td><b>Orders</b></td><td colspan="2"></td></tr>
    <tr><td>6</td><td>order_id</td><td>customer</td><td>total</td></tr>
    <tr><td>7</td><td>ORD-1001</td><td>Acme</td><td>500</td></tr>
  </tbody>
</table>

> **How crease handles it.** **Deferred to v1.5.** v1 supports one entity
> per tab. To handle this reliably we'll use `locate.cell_range` so each
> entity can be bound to a rectangular sub-region of the tab.

---

## 6. Inline subtotals interspersed with data

A summary row appears after each grouping, mixed with regular data.

<table>
  <thead><tr><th></th><th>A</th><th>B</th><th>C</th></tr></thead>
  <tbody>
    <tr><td>1</td><td><b>region</b></td><td><b>customer</b></td><td><b>total</b></td></tr>
    <tr><td>2</td><td>North</td><td>Globex</td><td>500</td></tr>
    <tr><td>3</td><td>North</td><td>Initech</td><td>750</td></tr>
    <tr><td>4</td><td colspan="2"><b>North subtotal</b></td><td><b>1250</b></td></tr>
    <tr><td>5</td><td>South</td><td>Hooli</td><td>900</td></tr>
    <tr><td>6</td><td colspan="2"><b>South subtotal</b></td><td><b>900</b></td></tr>
  </tbody>
</table>

> **How crease handles it.** **Deferred to v1.5.** Would require a row-skip
> predicate (e.g. `skip_row_if: cell_at(column: 0) matches "/subtotal/i"`).
> For v1 we expect customers to remove subtotals, or for the validator
> to flag them as `wrong_type` since the subtotal cells often don't match
> the declared field types.

---

## 7. Date-format chaos

The same column may carry several date encodings.

<table>
  <thead><tr><th></th><th>A (date)</th></tr></thead>
  <tbody>
    <tr><td>1</td><td>2025-01-15</td></tr>
    <tr><td>2</td><td>01/15/2025</td></tr>
    <tr><td>3</td><td>15-Jan-2025</td></tr>
    <tr><td>4</td><td>45672</td></tr>
    <tr><td>5</td><td>Jan 15, 2025</td></tr>
  </tbody>
</table>

Row 4 is an Excel date serial number (days since 1900-01-01). Row 1 is the
"correct" ISO form. The other three are common operator-typed variations.

> **How crease handles it.** The extractor coerces the dominant format;
> outliers emit `wrong_type` per row. For columns with strongly mixed
> encodings, prefer `type: string` and parse downstream — or add `pattern:`
> to enforce one shape and route bad rows to human review.

---

## 8. Numbers stored as text (leading apostrophe)

Excel's classic gotcha — a leading `'` forces the cell to text, making
`'12345` display as `12345` but be a string under the hood.

<table>
  <thead><tr><th></th><th>A (sku)</th><th>B (quantity)</th></tr></thead>
  <tbody>
    <tr><td>1</td><td>'00123</td><td>10</td></tr>
    <tr><td>2</td><td>'00124</td><td>20</td></tr>
  </tbody>
</table>

> **How crease handles it.** openpyxl reads these as strings. If the field
> is `type: string`, no problem. If `type: integer`, coercion may succeed
> (it strips the leading apostrophe) or emit `wrong_type` if there are
> non-numeric chars.

---

## 9. Null sentinels

Operators encode "missing" with many tokens. None of these are the same as
a truly blank cell.

<table>
  <thead><tr><th></th><th>A (email)</th></tr></thead>
  <tbody>
    <tr><td>1</td><td>a@example.com</td></tr>
    <tr><td>2</td><td>N/A</td></tr>
    <tr><td>3</td><td>TBD</td></tr>
    <tr><td>4</td><td>-</td></tr>
    <tr><td>5</td><td>—</td></tr>
    <tr><td>6</td><td>(blank)</td></tr>
    <tr><td>7</td><td></td></tr>
  </tbody>
</table>

> **How crease handles it.** Library-default `null_tokens` collapses
> `N/A`, `TBD`, `-`, `—`, `(blank)`, `NaN`, and a handful of other common
> sentinels to `null` during extraction. Override at template or field
> level — `null_tokens: []` disables, `null_tokens: ["UNKNOWN"]` extends.

---

## 10. Negative numbers as parentheses

A finance convention: `(1,234.56)` means `-1234.56`.

<table>
  <thead><tr><th></th><th>A (amount)</th></tr></thead>
  <tbody>
    <tr><td>1</td><td align="right">1,234.56</td></tr>
    <tr><td>2</td><td align="right">(842.10)</td></tr>
    <tr><td>3</td><td align="right">500.00</td></tr>
  </tbody>
</table>

> **How crease handles it.** Excel's number formatting hides the sign, but
> the underlying value is numeric. openpyxl reads the actual stored value,
> not the display. Only an issue when the cell is *text-stored* as
> `"(842.10)"` — then `wrong_type` fires.

---

## 11. Currency-formatted numbers

`$1,234.56` may be a number with currency formatting (fine) or a string (not fine).

<table>
  <thead><tr><th></th><th>A (price)</th></tr></thead>
  <tbody>
    <tr><td>1</td><td align="right">$1,234.56</td></tr>
    <tr><td>2</td><td align="right">€90.00</td></tr>
    <tr><td>3</td><td align="right">£75.50</td></tr>
  </tbody>
</table>

> **How crease handles it.** Same as #10 — depends on whether Excel stored
> a number or a string. Customers who mix currencies in one column are
> flagging a real semantic problem; consider a `currency` field alongside
> `amount`.

---

## 12. Boolean variations

Same concept, multiple encodings.

<table>
  <thead><tr><th></th><th>A (active)</th><th>B (active)</th><th>C (active)</th></tr></thead>
  <tbody>
    <tr><td>1</td><td>Yes</td><td>True</td><td>Y</td></tr>
    <tr><td>2</td><td>No</td><td>False</td><td>N</td></tr>
    <tr><td>3</td><td>yes</td><td>true</td><td>1</td></tr>
    <tr><td>4</td><td>NO</td><td>FALSE</td><td>0</td></tr>
  </tbody>
</table>

> **How crease handles it.** Library-default `true_values` / `false_values`
> covers the common cases (`Yes/No`, `True/False`, `Y/N`, `1/0`, with
> casing variants). Override per field for unusual encodings.

---

## 13. Headers with whitespace / mixed case / smart-quote drift

Same column, three operators, three different headers.

<table>
  <thead><tr><th></th><th>operator A</th><th>operator B</th><th>operator C</th></tr></thead>
  <tbody>
    <tr><td>header text</td><td>Order ID</td><td>order_id</td><td>Order&nbsp;ID&nbsp;</td></tr>
  </tbody>
</table>

Operator A: title case. Operator B: snake_case. Operator C: title case
with a trailing space and a non-breaking space between words.

> **How crease handles it.** The extractor normalises headers
> (NBSP→space, collapse internal whitespace runs, trim, lower-case)
> before matching `source_column`. The template's `source_column: "Order
> ID"` matches all three — and also matches headers that wrap mid-label
> (`"Order \nID"`, common when an operator widens a column after Excel
> auto-wrapped the text) or contain a stray double-space typo
> (`"Order  ID"`).

---

## 14. Cells with embedded line breaks

A single cell carrying multiple values separated by `\n`.

<table>
  <thead><tr><th></th><th>A (address)</th></tr></thead>
  <tbody>
    <tr><td>1</td><td>123 Main St<br>Suite 400<br>Boston, MA 02101</td></tr>
  </tbody>
</table>

> **How crease handles it.** Stays as a single string with `\n`
> separators. If the consumer wants it split, that's a downstream concern.

---

## 15. Hidden columns / rows

Excel allows hiding rows/columns; visually invisible but still in the file.

> **How crease handles it.** By default, crease reads hidden cells as if
> they were visible. If a customer intentionally hides "draft" rows,
> those will appear in extraction — set `locate.skip_hidden_rows: true`
> to exclude them.

---

## 16. "Notes" / "Instructions" tabs

Operator-facing tabs that aren't data.

> **How crease handles it.** List them in `ignore_tabs:`. The LLM is
> expected to spot common names (`Notes`, `Instructions`, `Cover Page`,
> empty `Sheet1`) during inference and add them automatically.

**Fixture:** `multi_tab_acme` includes a `Notes` tab in `ignore_tabs`.

---

## 17. Cover sheet that lists the rest of the workbook

A meta-tab that says "see Region: North, Region: South for data."

<table>
  <thead><tr><th></th><th>A</th><th>B</th></tr></thead>
  <tbody>
    <tr><td>1</td><td colspan="2"><b>Tabs in this report</b></td></tr>
    <tr><td>2</td><td>Region - North</td><td>30 rows</td></tr>
    <tr><td>3</td><td>Region - South</td><td>22 rows</td></tr>
    <tr><td>4</td><td>Region - West</td><td>15 rows</td></tr>
  </tbody>
</table>

> **How crease handles it.** **Deferred to v2.** This is a meta-template
> that crease could in principle parse first to learn which tabs to look
> at. For v1, the operator declares the pattern in `tab_pattern` directly.

---

## 18. Repeated header rows

For "print-friendly" reports, headers repeat every N rows.

<table>
  <thead><tr><th></th><th>A</th><th>B</th></tr></thead>
  <tbody>
    <tr><td>1</td><td><b>order_id</b></td><td><b>total</b></td></tr>
    <tr><td>2</td><td>ORD-1001</td><td>500</td></tr>
    <tr><td>3</td><td>ORD-1002</td><td>750</td></tr>
    <tr><td>4</td><td><b>order_id</b></td><td><b>total</b></td></tr>
    <tr><td>5</td><td>ORD-1003</td><td>900</td></tr>
  </tbody>
</table>

> **How crease handles it.** **Deferred to v1.5.** Adds `skip_row_if:
> matches_header` to drop rows whose values equal the header text.

---

## 19. Cells with formulas instead of values

`=SUM(B2:B10)` instead of `825`.

> **How crease handles it.** `openpyxl.load_workbook(path, data_only=True)`
> reads the cached value Excel computed, not the formula text. Crease uses
> `data_only=True` throughout. If a customer sends a file that was never
> opened in Excel (cache is stale), the cell may come back as `None` or
> the formula string — emit `extraction_failed` with a message suggesting
> they open + save the file in Excel.
>
> **Backend divergence.** `python-calamine` (the default backend) does not
> expose a cached-value mode and returns an empty string for formula cells
> that haven't been pre-evaluated; crease normalizes those to `None`. If a
> file relies on Excel-computed formula values, pass `engine="openpyxl"`
> so crease can read the cached results, or open + save the file in Excel
> before extracting.

---

## 19a. Excel error cells (`#REF!`, `#N/A`, `#DIV/0!`)

A formula that didn't resolve produces a visible error code in the cell.

> **How crease handles it.** Both backends surface error cells as `None`
> rather than the literal error text. `python-calamine` does not expose
> the cell error type at all in its Python API; openpyxl with
> ``data_only=True`` also returns `None` for these. The downstream
> coercion layer therefore reports the field as missing rather than
> mistyped. If you need to distinguish "formula broke" from "operator
> left blank", treat any unexpected `None` in a numeric column as a
> signal to inspect the source workbook.

---

## 20. Tabs named with version suffixes

`Orders_FINAL_v3_revised`, `Orders_FINAL_v3_revised_REAL_FINAL`, etc.

> **How crease handles it.** Tab patterns can be loose: `tab_pattern:
> ^Orders` matches any of those. Better: a v1.5 fuzzy-match mode that the
> LLM picks based on examples.

---

## What this catalog is for

- **Operators** — recognize whether their files fit one of these patterns
  before submitting; if not, expect re-onboarding.
- **Engineers** — understand the scope of weirdness the system commits to.
- **The LLM (via the inference prompt)** — examples in this doc inform the
  system prompt for `infer_template`.
- **The roadmap** — each "Deferred" tag is a tracked item; we ship them as
  customers actually hit them, not speculatively.
