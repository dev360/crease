# Real-world Excel anecdotes

A research file. Each entry is a documented incident or well-known pattern that
shaped a design decision in Crease's template model, validator vocabulary, or
test corpus. Use as evidence when someone asks *"why does Crease bother to
handle X?"*

Each pattern is tagged with the test fixture (if we have one) or marked
"deferred" / "not in scope."

---

## A. Excel autocorrect destroys gene names (2016–present)

**The story.** Microsoft Excel auto-converts strings that *look like* dates or
numbers into dates or scientific notation, **silently**, on import. In
genomics:

| Original | What Excel turned it into |
|---|---|
| `SEPT2` (Septin-2 gene) | `2-Sep` |
| `MARCH1` (MARCH F-Box Protein 1) | `1-Mar` |
| `2310009E13` (gene accession) | `2.31E+13` |
| `OCT4` | `4-Oct` |

A 2016 study of 3,597 genomics papers found **~20% of supplementary
spreadsheets contained these corruptions**. In 2020, HGNC (the gene
nomenclature committee) renamed **30+ genes** to avoid the Excel trap —
because it was easier to rename the genes than to fix Excel.

**Why it matters for Crease.** This is the canonical case for "a cell's value
got silently transformed before it reached us." The customer's intent was a
string; Excel stored a date. Our extractor reads a date; our validator should
flag this as `wrong_type` (declared: string, got: date) — *and* point the
operator at the likely cause.

**Coverage:** test fixture `excel_autoconverted_to_date`. Validator emits
`wrong_type` with `details.likely_cause: "excel_autoconvert"`.

**Sources:**
- [Excel autocorrect errors still plague genetic research — The Conversation](https://theconversation.com/excel-autocorrect-errors-still-plague-genetic-research-raising-concerns-over-scientific-rigour-166554)
- [Gene Name Auto-Correct Leads to Errors in 1 in 5 Genetics Research Articles — ASH Clinical News](https://ashpublications.org/ashclinicalnews/news/2669/Gene-Name-Auto-Correct-in-Microsoft-Excel-Leads-to)

---

## B. Public Health England loses 15,706 COVID cases (Oct 2020)

**The story.** During the early UK pandemic response, Public Health England
batched daily case data through Excel. The pipeline used the legacy `.xls`
format, which has a **65,536-row limit per sheet**. When daily case counts
spiked, ~16,000 rows silently overflowed past the limit and **never reached
contact tracing**. The bug took **8 days to identify** — during which infected
individuals weren't being contacted.

**Why it matters for Crease.** Two design implications:
1. **Row count is part of the contract.** A template can encode `min_data_rows`
   and (eventually) a "warn if row count is suspiciously below baseline."
2. **Silent truncation is the worst failure mode.** Crease should never
   "round down" silently — if extraction loses rows (e.g. encountering an
   unexpected blank row mid-data), it must emit `row_count_anomaly` not just
   stop reading.

**Coverage:** validator vocabulary includes `row_count_anomaly` (future). For
v1 we surface `empty_row` mid-data as `needs_review`, which would have caught
the early symptoms of an overflow.

**Sources:**
- [PHE Excel error blog write-ups](https://en.wikipedia.org/wiki/Public_Health_England) (multiple secondary sources)

---

## C. JPMorgan London Whale: $6B from manual copy-paste between sheets (2012)

**The story.** JPMorgan's Value-at-Risk model lived across multiple Excel
workbooks. Updating it required *manually* copying values from one workbook
into another, sheet by sheet. A modeler implemented a formula that "divided
by the sum" instead of "divided by the average" — halving the apparent
volatility — and the manual workflow had no second pair of eyes. The model
understated risk; the desk took larger positions; losses hit $6B.

**Why it matters for Crease.** Reinforces the **whole point of the system**:
manual copy-paste between Excel files is the workflow Crease replaces. Every
hand-copied number is a JPMorgan-shaped risk. A canonical JSON output that
flows directly into downstream systems eliminates the copy step.

**Sources:**
- [JPMorgan London Whale: How an Excel Error Triggered a $6 Billion Loss](https://paretoinvestor.substack.com/p/jpmorgan-london-whale-excel-error)
- [Case Study 18: JP Morgan Chase London Whale — Henrico Dolfing](https://www.henricodolfing.com/2024/07/case-study-jp-morgan-chase-london-whale.html)

---

## D. Lehman Brothers' hidden-rows-resurrected-in-PDF (2008)

**The story.** Barclays Capital bought 179 of Lehman's trading contracts that
Barclays did **not** intend to buy. Lehman's deal-tracking spreadsheet had
~24,000 cells; Lehman *hid* the rows for contracts excluded from the sale
(rather than deleting them). When the spreadsheet was converted to PDF for
the legal record, **the hidden rows reappeared** — and the PDF was the
contract of record. Barclays inherited the contracts.

**Why it matters for Crease.** Hidden cells are still data. openpyxl reads
them; pandas reads them. Operators who use hidden rows for "soft delete" will
have those rows in their extracted JSON unless we explicitly opt them out.

**Coverage:** `locate.skip_hidden_rows: true` (v1.5).

**Sources:**
- [Excel Horror Stories — Caspio](https://www.caspio.com/blog/5-of-the-most-terrifying-excel-spreadsheet-horror-stories-weve-ever-heard/)

---

## E. Wickham's tidy-data canonical examples

**The story.** Hadley Wickham's *Tidy Data* paper formalized three rules that
explain why most spreadsheets resist analysis:

1. Every column is one variable.
2. Every row is one observation.
3. Every table is one observational unit.

Common violations Wickham documents:

- **Column headings are values, not variables.** `<region> 2023 | 2024 | 2025`
  — the years are values of a `year` variable, not three columns.
- **Multiple variables stored in one column.** `male_15_24, female_15_24, ...`
  — two variables (sex, age-band) packed into one column name.
- **Variables stored in both rows and columns.** Crosstabs.
- **Multiple types in one table.** Customer-row mixed with order-row.

**Why it matters for Crease.** These are the "wide-format" cases. Crease's
output is canonical/long-format JSON. Customers who send wide-format data
need either:
- A template that **unpivots** (deferred to v1.5)
- A manual reshape step downstream

For v1 we extract as-found and flag wide-format as a known limitation in the
inferred template's `notes`.

**Coverage:** test fixture `wide_format_year_columns` documents the pattern;
extraction is in-scope (we get N columns named `2023`, `2024`, `2025`), but
the canonical shape will mirror the file. The LLM inference adds a note to
the template flagging the wide-format issue.

**Sources:**
- [Tidy Data paper (PDF) — Hadley Wickham](https://vita.had.co.nz/papers/tidy-data.pdf)
- [Tidy Data — R for Data Science (2e)](https://r4ds.hadley.nz/data-tidy.html)
- [Five Common Problems with Messy Data — Michael Chimenti](https://www.michaelchimenti.com/2014/07/five-common-problems-with-messy-data/)

---

## F. The 50-files-a-day warehouse operator

**The story.** Documented at Leeds Institute for Data Analytics: an operations
manager received 50+ individual Excel files from different warehouse managers
*every day*, and spent **the first 3 hours of every morning** manually opening,
copying, and pasting them into one master spreadsheet. Each warehouse had
slightly different headers, ordering, and conventions.

**Why it matters for Crease.** This is the user we're building for. The fix:
one template per warehouse → drop the day's files into a batch run → canonical
JSONL flows downstream. 50 files × 250ms = 12 seconds, not 3 hours.

**Sources:**
- [Wrangling Chaos: 6 Things I Wish I Knew — Leeds Institute for Data Analytics](https://lida.leeds.ac.uk/news/wrangling-chaos-6-things-i-wish-i-knew-before-tackling-messy-data/)

---

## G. Numbers stored as text — the silent-SUM bug

**The story.** When a column contains a mix of true numbers and "numbers
stored as text" (typically caused by leading apostrophes, import settings, or
trailing spaces), Excel's SUM **silently skips the text cells without warning**.
A column of 100 sales totals can be off by 30% and pass every visual check.

The flip side: if a "numeric" column contains a single text entry like
`"N/A"`, the whole column gets typed as text on import, and downstream
arithmetic fails.

**Why it matters for Crease.** Type validation has to happen on the **inferred
canonical type**, not on the raw cell type, because Excel's storage is
unreliable. We coerce per the template's `type:` declaration and emit
`wrong_type` on rows that fail coercion. The operator gets:
*"row 47: quantity is `'12'` (text-stored) — likely needs cell formatting fix."*

**Coverage:** test fixture `numbers_stored_as_text`.

**Sources:**
- [Number and text format mismatches — MakeUseOf](https://www.makeuseof.com/excel-finally-fixed-its-biggest-data-entry-problem-and-its-a-lifesaver/)
- [Numbers That Don't Act Like Numbers — Via Evaluation](https://www.viaevaluation.com/data-cleaning-in-excel-101-part-5-numbers-that-dont-act-like-numbers-and-leading-zeros/)

---

## H. Whitespace drift: `"100 "` ≠ `"100"`

**The story.** Trailing spaces, leading spaces, and non-breaking spaces (NBSP,
` `) are the most common reason VLOOKUPs return `#N/A`. To the human
eye, `"Acme Corp"` and `"Acme Corp "` look identical; to Excel they're
different strings, and they hash to different buckets.

Operators paste from PDF (which introduces NBSP), from email (which
introduces trailing spaces), from web tables (which introduce both). This is
the most common reason customer files fail downstream joins.

**Why it matters for Crease.** Header normalization is **non-negotiable**.
Our extractor must trim/normalize headers before matching `source_column:`,
or every other validation flag is wrong (the right cell will be in the
wrong column). Value normalization is more nuanced — we shouldn't silently
mutate value strings, but we should expose `trim_strings: true` per field for
columns where it matters.

**Coverage:** test fixtures `header_trailing_whitespace` and
`value_trailing_whitespace`.

**Sources:**
- [Excel Data Type Issues — MoldStud](https://moldstud.com/articles/p-troubleshooting-common-issues-with-excel-data-types-a-comprehensive-developer-guide)

---

## I. Multi-level headers (merged cells)

**The story.** Finance and operations reports routinely use merged cells for
multi-level headers. Example: a quarterly report with `Q1 2025` merged across
columns B, C, D and then sub-headers `Jan, Feb, Mar` underneath. pandas
handles this with `header=[0,1]` (a list of row indices) but **only the top-left
cell of a merged range holds a value** — the others are blank. Without
explicit handling, you get headers like `('Q1 2025', 'Jan')`, `(NaN, 'Feb')`,
`(NaN, 'Mar')`.

**Why it matters for Crease.** This is the crosstab/multi-header case from
the conventions doc. v1 doesn't handle it. v2 needs a `header_levels: 2`
option on `locate:` plus a `forward_fill: true` for merged top-row values.

**Sources:**
- [Read Excel Sheet with Multiple Header Using Pandas — Saturn Cloud](https://saturncloud.io/blog/how-to-read-excel-sheet-with-multiple-header-using-pandas/)
- [Pandas: How to Read Excel File with Merged Cells — Statology](https://www.statology.org/pandas-read-excel-merged-cells/)

---

## J. Color as data

**The story.** Financial-model conventions encode information through color:

- **Blue numbers** = hardcoded inputs (operator-entered)
- **Black numbers** = formulas
- **Green** = links to other sheets / workbooks
- **Red** = errors, negatives, or warnings

Operators expect the color to *be* metadata. A reviewer who sees a green
number knows to trace it across sheets; a blue number gets scrutinized
because it was hand-entered.

**Why it matters for Crease.** Color is genuinely meaningful in some templates.
v1 ignores formatting entirely. v2 could add `format_check:` to surface
"cells with unexpected color" (e.g. *"this row's total is colored red,
suggesting it's flagged"*).

**Status:** Out of scope for v1. Flagged here so we don't dismiss it as
"just formatting" later.

**Sources:**
- [Financial Model Formatting — Financial Edge](https://www.fe.training/free-resources/financial-modeling/financial-model-formatting/)
- [How To Format Your Excel Spreadsheet — Vena](https://www.venasolutions.com/blog/how-to-format-your-excel-spreadsheet-10-tips)

---

## K. Standard financial workbook structure: Raw / Categories / Summary / Reconciliation

**The story.** Bookkeeping templates converge on a canonical 4-tab structure:

| Tab | Role |
|---|---|
| `Raw Data` | Direct import of transactions, untouched |
| `Categories` | Lookup table mapping vendor names → categories |
| `Summary` | Pivot-style aggregations |
| `Reconciliation` | Side-by-side: internal vs external (bank statement) |

The `Categories` tab is a **lookup table** that other tabs reference via
VLOOKUP. The `Reconciliation` tab uses **conditional formatting** to highlight
rows where the difference isn't zero.

**Why it matters for Crease.** Three patterns this surfaces:

1. **Lookup tabs** — Crease v1 doesn't model cross-tab references. The
   Categories tab would just be ignored. v2 could introduce a `lookup:` block
   that auto-resolves codes.
2. **Reconciliation pattern** — two columns of paired values + a difference.
   A real entity in v2: an `assertion:` block on a row that says "col B - col A
   must equal col C, else emit `reconciliation_mismatch`."
3. **Multi-purpose tabs in one workbook** — same workbook serves
   data + lookups + summaries. Crease must `ignore_tabs:` the summary
   and lookups; only Raw Data is extracted.

**Sources:**
- [Microsoft Office: Tips for Excel-based financial reports — Journal of Accountancy](https://www.journalofaccountancy.com/issues/2019/feb/excel-based-financial-reports/)
- [Bank Statement Template Excel — invio.app](https://invio.app/blog/bank-statement-template-excel-create-professional-financial-reports-in-minutes)

---

## L. File-naming convention as metadata

**The story.** Industry-standard naming for financial models:
`YYYY-MM_Project_v01.xlsx`, e.g. `2025-03_Acme_FinModel_v07.xlsx`.

The date prefix sorts files chronologically in the filesystem. The version
suffix prevents the `_FINAL`/`_FINAL_v2`/`_FINAL_REAL` cascade.

**Why it matters for Crease.** Filename is metadata. The CLI's
`crease check incoming.xlsx` should be able to extract the reporting period
from the filename if a `filename_pattern:` is declared in the template:

```yaml
filename_pattern: ^(\d{4}-\d{2})_.+\.xlsx$
filename_capture:
  - {group: 1, field: report_period}
```

**Status:** Defer to v1.5. Documented here so we don't forget that "the
filename is data too."

**Sources:**
- [Guide to File Naming Conventions in Financial Analysis — CFI](https://corporatefinanceinstitute.com/resources/financial-modeling/financial-analysis-naming-conventions-best-practices/)

---

## M. The Kodak severance overpayment ($11M typo, 2005)

**The story.** A single cell in a severance-pay model carried an extra zero,
producing an $11M overstatement of severance liability that affected the
filing of Kodak's quarterly report. The error wasn't structural — the
spreadsheet was "valid" by any rule-based check. It was a value error
within range.

**Why it matters for Crease.** A reminder that **schema validation has limits**.
A `total: 11000000` is type-correct, regex-pass, range-pass (`minimum: 0`)
— but unreasonable. v2's distribution-drift detection (comparing this file
against historical baselines) would have caught it: "this column's median
jumped 10x from last quarter." Rules can't.

**Sources:**
- [Ten Memorable Excel Disasters — SheetCast](https://sheetcast.com/articles/ten-memorable-excel-disasters)

---

## N. The Emerson Construction missing-cell bid ($3.7M underbid, 2003)

**The story.** Emerson Construction won a 2003 Army Corps contract because
their Excel-based bid totaled $3.7M less than competitors. They later realized
the formula `SUM(B2:B47)` should have been `SUM(B2:B48)` — one row, electrical
work, missed. Emerson had to either eat the loss or walk away.

**Why it matters for Crease.** Off-by-one errors at the **edges of data
ranges** are the most common Excel bug. Crease's `data_ends_at:` spec must
be exact. If we read 47 rows when there are 48, the downstream impact is
the same as Emerson's bid.

**Coverage:** test fixture `flat_with_totals_row` exercises the
`data_ends_at: value_match` boundary precisely. We need to add coverage for
*missed last row* and *extra phantom row*.

**Sources:**
- [Ten Memorable Excel Disasters — SheetCast](https://sheetcast.com/articles/ten-memorable-excel-disasters)

---

## Patterns to add as test fixtures (this round)

From the anecdotes above, the following pressure the *runtime* (not just the
schema model) enough to deserve coverage in `test_cases/`:

| Pattern | Source | Fixture name |
|---|---|---|
| Excel date autoconvert | A | `excel_autoconverted_to_date` |
| Numbers stored as text | G | `numbers_stored_as_text` |
| Header whitespace drift | H | `header_trailing_whitespace` |
| Value whitespace drift | H | `value_trailing_whitespace` |
| Null sentinels (N/A, TBD, -) | (multiple) | `null_sentinels` |
| Wide-format year columns | E | `wide_format_year_columns` (LLM should flag, not extract) |
| Comma-thousands in numbers | (general) | `currency_formatted_text` |

These get added to `test_cases/cases.py` in this commit, with `expected.json`
and `expected_issues.json` reflecting how we want Crease to behave.

## Patterns documented but deferred (no fixture yet)

| Pattern | Source | Why deferred |
|---|---|---|
| Hidden rows | D | Needs `locate.skip_hidden_rows` (v1.5) |
| Multi-level headers | I | Needs `header_levels` (v2) |
| Color as data | J | Out of scope; flagged for awareness |
| Lookup-tab cross-references | K | Needs `lookup:` block (v2) |
| Reconciliation assertions | K | Needs `assertion:` block (v2) |
| Filename-as-metadata | L | Needs `filename_pattern:` (v1.5) |
| Distribution drift | M | Needs baselining (Phase 2 of broader system) |
| Row-count anomalies | B | Needs `min_data_rows` + baseline (v1.5) |

---

## Sources

This file synthesizes from:

- [Wrangling Chaos: 6 Things I Wish I Knew — Leeds Institute for Data Analytics](https://lida.leeds.ac.uk/news/wrangling-chaos-6-things-i-wish-i-knew-before-tackling-messy-data/)
- [Got Messy Excel Data? — fromexceltopython.com](https://fromexceltopython.com/blog/messy-excel-data/)
- [5 of the Most Terrifying Excel Spreadsheet Horror Stories — Caspio](https://www.caspio.com/blog/5-of-the-most-terrifying-excel-spreadsheet-horror-stories-weve-ever-heard/)
- [Ten Memorable Excel Disasters — SheetCast](https://sheetcast.com/articles/ten-memorable-excel-disasters)
- [Tidy Data — Hadley Wickham (PDF)](https://vita.had.co.nz/papers/tidy-data.pdf)
- [Five Common Problems with Messy Data — Michael Chimenti](https://www.michaelchimenti.com/2014/07/five-common-problems-with-messy-data/)
- [Excel autocorrect errors still plague genetic research — The Conversation](https://theconversation.com/excel-autocorrect-errors-still-plague-genetic-research-raising-concerns-over-scientific-rigour-166554)
- [Gene Name Auto-Correct Leads to Errors in 1 in 5 Genetics Research Articles — ASH Clinical News](https://ashpublications.org/ashclinicalnews/news/2669/Gene-Name-Auto-Correct-in-Microsoft-Excel-Leads-to)
- [Numbers That Don't Act Like Numbers — Via Evaluation](https://www.viaevaluation.com/data-cleaning-in-excel-101-part-5-numbers-that-dont-act-like-numbers-and-leading-zeros/)
- [Excel Data Type Issues — MoldStud](https://moldstud.com/articles/p-troubleshooting-common-issues-with-excel-data-types-a-comprehensive-developer-guide)
- [Read Excel Sheet with Multiple Header Using Pandas — Saturn Cloud](https://saturncloud.io/blog/how-to-read-excel-sheet-with-multiple-header-using-pandas/)
- [Pandas: How to Read Excel File with Merged Cells — Statology](https://www.statology.org/pandas-read-excel-merged-cells/)
- [JPMorgan London Whale: How an Excel Error Triggered a $6 Billion Loss — Pareto Investor](https://paretoinvestor.substack.com/p/jpmorgan-london-whale-excel-error)
- [Case Study 18: JP Morgan Chase London Whale — Henrico Dolfing](https://www.henricodolfing.com/2024/07/case-study-jp-morgan-chase-london-whale.html)
- [Microsoft Office: Tips for Excel-based financial reports — Journal of Accountancy](https://www.journalofaccountancy.com/issues/2019/feb/excel-based-financial-reports/)
- [Financial Model Formatting — Financial Edge](https://www.fe.training/free-resources/financial-modeling/financial-model-formatting/)
- [Guide to File Naming Conventions in Financial Analysis — CFI](https://corporatefinanceinstitute.com/resources/financial-modeling/financial-analysis-naming-conventions-best-practices/)
