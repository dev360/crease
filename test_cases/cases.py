"""
The Crease test corpus.

Each function returns a TestCase: an input .xlsx, a gold-standard Template,
the expected canonical JSON, and (for corrupted cases) the expected validation
issues. These are the ground truth — the extractor and validator must
reproduce them.

Faker is used for data, seeded for reproducibility. Every case is deterministic:
running this file twice produces byte-identical fixtures.
"""
from __future__ import annotations

from typing import Any
import random

from faker import Faker

from .types import TestCase, new_workbook, write_rows


# ---------- shared helpers ----------

def _seeded_faker(seed: int) -> Faker:
    Faker.seed(seed)
    random.seed(seed)
    return Faker()


def _mk_order_rows(fake: Faker, n: int, first_id: int = 1000) -> list[dict]:
    rows = []
    for i in range(n):
        rows.append({
            "order_id":       f"ORD-{first_id + i:04d}",
            "order_date":     fake.date_between(start_date="-180d", end_date="today").isoformat(),
            "customer_email": fake.email(),
            "quantity":       random.randint(1, 100),
            "unit_price":     round(random.uniform(10, 1000), 2),
        })
    return rows


def _envelope(template_id: str, source_file: str = "input.xlsx", **extras) -> dict:
    return {
        "template_id": template_id,
        "source_file": source_file,
        "errors": [],
        **extras,
    }


# =====================================================================
# CLEAN CASES (extraction tests)
# =====================================================================


def case_flat_simple() -> TestCase:
    """A clean flat order table with all common field types. The simplest case."""
    fake = _seeded_faker(42)
    rows = _mk_order_rows(fake, n=8)

    wb = new_workbook()
    ws = wb.create_sheet("Orders")
    ws.append(list(rows[0].keys()))
    for r in rows:
        ws.append(list(r.values()))

    template = {
        "template_id": "flat_simple",
        "version": 1,
        "description": "Flat order table.",
        "entities": [{
            "name": "order",
            "cardinality": "many",
            "locate": {
                "tab": "Orders",
                "orientation": "flat",
                "header_row": 0,
            },
            "fields": [
                {"name": "order_id",       "source_column": "order_id",       "type": "string",  "pattern": r"^ORD-\d{4}$"},
                {"name": "order_date",     "source_column": "order_date",     "type": "date"},
                {"name": "customer_email", "source_column": "customer_email", "type": "email"},
                {"name": "quantity",       "source_column": "quantity",       "type": "integer", "minimum": 1},
                {"name": "unit_price",     "source_column": "unit_price",     "type": "number",  "minimum": 0},
            ],
        }],
    }

    expected = _envelope("flat_simple", orders=rows)

    return TestCase(
        name="flat_simple",
        description="A flat table of order records — order ID, date, customer email, quantity, unit price.",
        workbook=wb,
        template=template,
        expected=expected,
        notes="Baseline. Tests flat extraction with header_row=0 and basic typed fields.",
    )


def case_flat_with_title_rows() -> TestCase:
    """Flat table with 3 title/metadata rows above the header row."""
    fake = _seeded_faker(43)
    rows = _mk_order_rows(fake, n=6)

    wb = new_workbook()
    ws = wb.create_sheet("Orders")
    ws.append(["Acme Corporation — Order Export"])
    ws.append(["Generated: 2025-04-15"])
    ws.append([])
    ws.append(list(rows[0].keys()))   # row 3 = header row
    for r in rows:
        ws.append(list(r.values()))

    template = {
        "template_id": "flat_with_title_rows",
        "version": 1,
        "description": "Flat order table preceded by title/metadata rows.",
        "entities": [{
            "name": "order",
            "cardinality": "many",
            "locate": {
                "tab": "Orders",
                "orientation": "flat",
                "header_row": 3,                  # headers on row 3
                "data_starts_row": 4,
            },
            "fields": [
                {"name": "order_id",       "source_column": "order_id",       "type": "string",  "pattern": r"^ORD-\d{4}$"},
                {"name": "order_date",     "source_column": "order_date",     "type": "date"},
                {"name": "customer_email", "source_column": "customer_email", "type": "email"},
                {"name": "quantity",       "source_column": "quantity",       "type": "integer", "minimum": 1},
                {"name": "unit_price",     "source_column": "unit_price",     "type": "number",  "minimum": 0},
            ],
        }],
    }

    expected = _envelope("flat_with_title_rows", orders=rows)

    return TestCase(
        name="flat_with_title_rows",
        description="Acme's order export — three title rows then a header row at row 4, then data.",
        workbook=wb,
        template=template,
        expected=expected,
        notes="Tests header_row > 0. Operators commonly have title + 'generated on' lines above data.",
    )


def case_flat_with_totals_row() -> TestCase:
    """Flat table that ends with a TOTAL row that must NOT be extracted as data."""
    fake = _seeded_faker(44)
    rows = _mk_order_rows(fake, n=5)
    total = sum(r["unit_price"] * r["quantity"] for r in rows)

    wb = new_workbook()
    ws = wb.create_sheet("Orders")
    ws.append(list(rows[0].keys()))
    for r in rows:
        ws.append(list(r.values()))
    # The totals row: only first cell + last cell populated
    ws.append(["TOTAL", None, None, None, round(total, 2)])

    template = {
        "template_id": "flat_with_totals_row",
        "version": 1,
        "description": "Flat order table ending with a TOTAL summary row that should be ignored.",
        "entities": [{
            "name": "order",
            "cardinality": "many",
            "locate": {
                "tab": "Orders",
                "orientation": "flat",
                "header_row": 0,
                "data_ends_at": {
                    "type": "value_match",
                    "column": 0,
                    "value": "TOTAL",
                },
            },
            "fields": [
                {"name": "order_id",       "source_column": "order_id",       "type": "string",  "pattern": r"^ORD-\d{4}$"},
                {"name": "order_date",     "source_column": "order_date",     "type": "date"},
                {"name": "customer_email", "source_column": "customer_email", "type": "email"},
                {"name": "quantity",       "source_column": "quantity",       "type": "integer", "minimum": 1},
                {"name": "unit_price",     "source_column": "unit_price",     "type": "number",  "minimum": 0},
            ],
        }],
    }

    expected = _envelope("flat_with_totals_row", orders=rows)

    return TestCase(
        name="flat_with_totals_row",
        description="Order table that ends with a TOTAL row summarizing the orders above.",
        workbook=wb,
        template=template,
        expected=expected,
        notes="Tests data_ends_at: value_match. The TOTAL row should not appear in the extracted orders list.",
    )


def case_property_sheet_cover() -> TestCase:
    """A clean property_sheet — labels in col A, values in col B, no scattering."""
    fake = _seeded_faker(45)
    record = {
        "company_name":      fake.company(),
        "tax_id":            fake.bothify("##-#######"),
        "primary_contact":   fake.name(),
        "contact_email":     fake.email(),
        "submitted_on":      fake.date_between(start_date="-30d", end_date="today").isoformat(),
    }

    wb = new_workbook()
    ws = wb.create_sheet("Profile")
    ws.append(["Company Name",    record["company_name"]])
    ws.append(["Tax ID",          record["tax_id"]])
    ws.append(["Primary Contact", record["primary_contact"]])
    ws.append(["Contact Email",   record["contact_email"]])
    ws.append(["Submitted On",    record["submitted_on"]])

    template = {
        "template_id": "property_sheet_cover",
        "version": 1,
        "description": "Company profile as a property sheet (labels in column A, values in column B).",
        "entities": [{
            "name": "company",
            "cardinality": "one",
            "locate": {
                "tab": "Profile",
                "orientation": "property_sheet",
                "label_col": 0,
                "value_col": 1,
            },
            "fields": [
                {"name": "company_name",    "source_label": "Company Name",    "type": "string"},
                {"name": "tax_id",          "source_label": "Tax ID",          "type": "string", "pattern": r"^\d{2}-\d{7}$"},
                {"name": "primary_contact", "source_label": "Primary Contact", "type": "string"},
                {"name": "contact_email",   "source_label": "Contact Email",   "type": "email"},
                {"name": "submitted_on",    "source_label": "Submitted On",    "type": "date"},
            ],
        }],
    }

    expected = _envelope("property_sheet_cover", company=record)

    return TestCase(
        name="property_sheet_cover",
        description="A company profile sheet — each row has a field name in column A and its value in column B.",
        workbook=wb,
        template=template,
        expected=expected,
        notes="Tests property_sheet extraction with cardinality=one.",
    )


def case_anchored_scattered() -> TestCase:
    """Cover sheet with scattered properties — not a clean rectangle."""
    fake = _seeded_faker(46)
    record = {
        "company_name":  fake.company(),
        "period":        "Q1 2025",
        "submitted_by":  fake.name(),
        "contact_email": fake.email(),
        "submitted_on":  fake.date_between(start_date="-30d", end_date="today").isoformat(),
    }

    wb = new_workbook()
    ws = wb.create_sheet("Cover")
    # Title block
    ws.append([f"{record['company_name']} Quarterly Sales Report"])     # row 0
    ws.append([])
    ws.append([])
    ws.append(["Reporting Period:", record["period"]])                  # row 3
    ws.append([])
    ws.append(["Submitted by:",     record["submitted_by"]])            # row 5
    ws.append(["Contact:",          record["contact_email"]])           # row 6
    ws.append([])
    ws.append([])
    ws.append(["Notes:"])
    ws.append(["First-time submission — please confirm receipt"])
    ws.append([])
    ws.append(["Date sent:",        record["submitted_on"]])            # row 12

    template = {
        "template_id": "anchored_scattered",
        "version": 1,
        "description": "Cover sheet with scattered properties (gaps and arbitrary positions).",
        "entities": [{
            "name": "report",
            "cardinality": "one",
            "locate": {
                "tab": "Cover",
                "orientation": "anchored",
            },
            "fields": [
                {"name": "period",
                 "anchor": {"label_match": "Reporting Period", "match_mode": "contains", "value_at": "right", "offset": 1},
                 "type": "string", "pattern": r"^Q[1-4] \d{4}$"},
                {"name": "submitted_by",
                 "anchor": {"label_match": "Submitted by",     "match_mode": "contains", "value_at": "right", "offset": 1},
                 "type": "string"},
                {"name": "contact_email",
                 "anchor": {"label_match": "Contact",          "match_mode": "contains", "value_at": "right", "offset": 1},
                 "type": "email"},
                {"name": "submitted_on",
                 "anchor": {"label_match": "Date sent",        "match_mode": "contains", "value_at": "right", "offset": 1},
                 "type": "date"},
            ],
        }],
    }

    # Note: company_name is in the title but we don't extract it (operator chose not to)
    expected = _envelope("anchored_scattered", report={
        "period":        record["period"],
        "submitted_by":  record["submitted_by"],
        "contact_email": record["contact_email"],
        "submitted_on":  record["submitted_on"],
    })

    return TestCase(
        name="anchored_scattered",
        description="A cover sheet where properties are scattered with gaps — period, submitter, contact, date sent.",
        workbook=wb,
        template=template,
        expected=expected,
        notes="Tests anchored orientation. The data fields live at A4/B4, A6/B6, A7/B7, A13/B13 with notes interleaved.",
    )


def case_multi_tab_acme() -> TestCase:
    """The full Acme example: Cover (property_sheet) + 3 region tabs (flat with title) + Notes (ignored)."""
    fake = _seeded_faker(47)
    company_record = {
        "company":      "Acme Corp",
        "period":       "Q1 2025",
        "contact":      "jane.smith@acme.com",
        "submitted_on": "2025-04-15",
    }

    wb = new_workbook()
    cover = wb.create_sheet("Cover")
    cover.append(["Company",       company_record["company"]])
    cover.append(["Period",        company_record["period"]])
    cover.append(["Contact",       company_record["contact"]])
    cover.append(["Submitted On",  company_record["submitted_on"]])

    all_orders = []
    for region in ["North", "South", "West"]:
        ws = wb.create_sheet(f"Region - {region}")
        # Two title rows before headers
        ws.append([f"{region} Region — Q1 2025"])
        ws.append([f"Manager: {fake.name()}"])
        ws.append([])
        ws.append(["Order ID", "Customer", "Date", "Total"])
        region_rows = []
        for _ in range(5):
            row = {
                "order_id": f"ORD-{random.randint(1000, 9999)}",
                "customer": fake.company(),
                "date":     fake.date_between(start_date="-90d", end_date="today").isoformat(),
                "total":    round(random.uniform(100, 50000), 2),
            }
            ws.append([row["order_id"], row["customer"], row["date"], row["total"]])
            region_rows.append({**row, "region": region})
        all_orders.extend(region_rows)

    notes_ws = wb.create_sheet("Notes")
    notes_ws.append(["Internal notes — ignored by Crease"])
    notes_ws.append(["This file was generated for testing"])

    template = {
        "template_id": "multi_tab_acme",
        "version": 1,
        "description": "Acme quarterly sales — cover sheet with company info, one tab per region with orders.",
        "entities": [
            {
                "name": "company",
                "cardinality": "one",
                "locate": {
                    "tab": "Cover",
                    "orientation": "property_sheet",
                    "label_col": 0,
                    "value_col": 1,
                },
                "fields": [
                    {"name": "company",      "source_label": "Company",      "type": "string"},
                    {"name": "period",       "source_label": "Period",       "type": "string", "pattern": r"^Q[1-4] \d{4}$"},
                    {"name": "contact",      "source_label": "Contact",      "type": "email"},
                    {"name": "submitted_on", "source_label": "Submitted On", "type": "date"},
                ],
            },
            {
                "name": "order",
                "cardinality": "many",
                "locate": {
                    "tab_pattern": r"^Region - (.+)$",
                    "orientation": "flat",
                    "header_row": 3,
                    "data_starts_row": 4,
                },
                "fields": [
                    {"name": "order_id", "source_column": "Order ID", "type": "string",  "pattern": r"^ORD-\d{4}$"},
                    {"name": "customer", "source_column": "Customer", "type": "string"},
                    {"name": "date",     "source_column": "Date",     "type": "date"},
                    {"name": "total",    "source_column": "Total",    "type": "number",  "minimum": 0},
                ],
                "enrich": [
                    {"field": "region", "source": "tab_name_regex_group", "group": 1},
                ],
            },
        ],
        "ignore_tabs": ["Notes"],
    }

    expected = _envelope("multi_tab_acme", company=company_record, orders=all_orders)

    return TestCase(
        name="multi_tab_acme",
        description=(
            "Acme's quarterly sales report. The Cover tab has company info (name, period, contact, "
            "submission date) as label-value pairs. Then one tab per region named like "
            "'Region - North' — each has two title rows, a header row, then order rows. "
            "There's also a Notes tab that should be ignored."
        ),
        workbook=wb,
        template=template,
        expected=expected,
        notes="Tests multi-entity templates, tab_pattern with capture group + enrich, ignore_tabs.",
    )


def case_dialect_acme() -> TestCase:
    """Acme's vocabulary for orders — uses descriptive column names."""
    fake = _seeded_faker(48)
    base_rows = [{
        "order_id":       f"ORD-{1000 + i:04d}",
        "customer_email": fake.email(),
        "order_date":     fake.date_between(start_date="-90d", end_date="today").isoformat(),
        "total":          round(random.uniform(100, 5000), 2),
    } for i in range(6)]

    wb = new_workbook()
    ws = wb.create_sheet("Orders")
    ws.append(["Order ID", "Customer Email", "Order Date", "Total Amount"])
    for r in base_rows:
        ws.append([r["order_id"], r["customer_email"], r["order_date"], r["total"]])

    template = {
        "template_id": "dialect_acme",
        "version": 1,
        "description": "Acme's order export — verbose column headers map to canonical fields.",
        "entities": [{
            "name": "order",
            "cardinality": "many",
            "locate": {
                "tab": "Orders",
                "orientation": "flat",
                "header_row": 0,
            },
            "fields": [
                {"name": "order_id",       "source_column": "Order ID",       "type": "string",  "pattern": r"^ORD-\d{4}$"},
                {"name": "customer_email", "source_column": "Customer Email", "type": "email"},
                {"name": "order_date",     "source_column": "Order Date",     "type": "date"},
                {"name": "total",          "source_column": "Total Amount",   "type": "number",  "minimum": 0},
            ],
        }],
    }

    expected = _envelope("dialect_acme", orders=base_rows)

    return TestCase(
        name="dialect_acme",
        description="Order export from Acme — column headers are verbose (Order ID, Customer Email, Order Date, Total Amount).",
        workbook=wb,
        template=template,
        expected=expected,
        notes="Pair with case_dialect_globex — both map to the same canonical fields (order_id, customer_email, order_date, total).",
    )


def case_dialect_globex() -> TestCase:
    """Globex's vocabulary for the same canonical orders — terse column names."""
    fake = _seeded_faker(49)
    base_rows = [{
        "order_id":       f"ORD-{2000 + i:04d}",
        "customer_email": fake.email(),
        "order_date":     fake.date_between(start_date="-90d", end_date="today").isoformat(),
        "total":          round(random.uniform(100, 5000), 2),
    } for i in range(6)]

    wb = new_workbook()
    ws = wb.create_sheet("Sheet1")
    ws.append(["OrderNum", "Email", "Day", "Amt"])
    for r in base_rows:
        ws.append([r["order_id"], r["customer_email"], r["order_date"], r["total"]])

    template = {
        "template_id": "dialect_globex",
        "version": 1,
        "description": "Globex's order export — terse headers, same canonical fields as Acme.",
        "entities": [{
            "name": "order",
            "cardinality": "many",
            "locate": {
                "tab": "Sheet1",
                "orientation": "flat",
                "header_row": 0,
            },
            "fields": [
                {"name": "order_id",       "source_column": "OrderNum", "type": "string",  "pattern": r"^ORD-\d{4}$"},
                {"name": "customer_email", "source_column": "Email",    "type": "email"},
                {"name": "order_date",     "source_column": "Day",      "type": "date"},
                {"name": "total",          "source_column": "Amt",      "type": "number",  "minimum": 0},
            ],
        }],
    }

    expected = _envelope("dialect_globex", orders=base_rows)

    return TestCase(
        name="dialect_globex",
        description="Order export from Globex — column headers are terse (OrderNum, Email, Day, Amt).",
        workbook=wb,
        template=template,
        expected=expected,
        notes="Pair with case_dialect_acme. Same canonical output despite different headers.",
    )


# =====================================================================
# CORRUPTED CASES (validation tests)
# =====================================================================
# Each builds on the flat_simple shape but mutates one cell/header and
# specifies which issues the validator should emit.


def _flat_simple_base_rows(seed: int = 50) -> tuple[list[dict], dict]:
    fake = _seeded_faker(seed)
    rows = _mk_order_rows(fake, n=6)
    template = {
        "template_id": "TBD",
        "version": 1,
        "description": "Flat order table.",
        "entities": [{
            "name": "order",
            "cardinality": "many",
            "locate": {"tab": "Orders", "orientation": "flat", "header_row": 0},
            "fields": [
                {"name": "order_id",       "source_column": "order_id",       "type": "string",  "pattern": r"^ORD-\d{4}$"},
                {"name": "order_date",     "source_column": "order_date",     "type": "date"},
                {"name": "customer_email", "source_column": "customer_email", "type": "email"},
                {"name": "quantity",       "source_column": "quantity",       "type": "integer", "minimum": 1},
                {"name": "unit_price",     "source_column": "unit_price",     "type": "number",  "minimum": 0},
            ],
        }],
    }
    return rows, template


def case_corrupted_missing_value() -> TestCase:
    """Drop one cell in the data — should produce a 'missing_required' issue."""
    rows, template = _flat_simple_base_rows(seed=50)
    template["template_id"] = "corrupted_missing_value"

    # Blank out customer_email on row 3 (4th data row, 0-indexed)
    bad_row_idx = 3
    rows[bad_row_idx] = {**rows[bad_row_idx], "customer_email": None}

    wb = new_workbook()
    ws = wb.create_sheet("Orders")
    ws.append(list(rows[0].keys()))
    for r in rows:
        ws.append([r[k] for k in rows[0].keys()])

    expected = _envelope("corrupted_missing_value", orders=rows)

    expected_issues = [{
        "entity": "order",
        "row": bad_row_idx,
        "field": "customer_email",
        "reason": "missing_required",
    }]

    return TestCase(
        name="corrupted_missing_value",
        description="Flat order table — one row has a blank customer_email.",
        workbook=wb,
        template=template,
        expected=expected,
        expected_verdict="needs_review",
        expected_issues=expected_issues,
        notes="The extractor should still extract all rows; the validator should flag the missing email.",
    )


def case_corrupted_wrong_type() -> TestCase:
    """Put text in the quantity column — should produce a 'wrong_type' issue."""
    rows, template = _flat_simple_base_rows(seed=51)
    template["template_id"] = "corrupted_wrong_type"

    bad_row_idx = 2
    # Use a non-null-sentinel string so it triggers wrong_type, not missing_required
    rows[bad_row_idx] = {**rows[bad_row_idx], "quantity": "twelve"}

    wb = new_workbook()
    ws = wb.create_sheet("Orders")
    ws.append(list(rows[0].keys()))
    for r in rows:
        ws.append([r[k] for k in rows[0].keys()])

    expected = _envelope("corrupted_wrong_type", orders=rows)

    expected_issues = [{
        "entity": "order",
        "row": bad_row_idx,
        "field": "quantity",
        "reason": "wrong_type",
    }]

    return TestCase(
        name="corrupted_wrong_type",
        description="Flat order table — one quantity cell contains 'twelve' instead of a number.",
        workbook=wb,
        template=template,
        expected=expected,
        expected_verdict="needs_review",
        expected_issues=expected_issues,
        notes="Tests type-coercion failure detection.",
    )


def case_corrupted_renamed_header() -> TestCase:
    """Rename a header so the source_column mapping fails."""
    rows, template = _flat_simple_base_rows(seed=52)
    template["template_id"] = "corrupted_renamed_header"

    wb = new_workbook()
    ws = wb.create_sheet("Orders")
    # Headers: rename 'customer_email' → 'cust_email'
    headers = ["order_id", "order_date", "cust_email", "quantity", "unit_price"]
    ws.append(headers)
    for r in rows:
        ws.append([r[k] for k in ["order_id", "order_date", "customer_email", "quantity", "unit_price"]])

    # Expected: customer_email won't be found → every row missing it
    extracted_rows = [{**r, "customer_email": None} for r in rows]
    expected = _envelope("corrupted_renamed_header", orders=extracted_rows)

    expected_issues = [
        {"entity": "order", "row": i, "field": "customer_email", "reason": "missing_required"}
        for i in range(len(rows))
    ]

    return TestCase(
        name="corrupted_renamed_header",
        description="Flat order table — the 'customer_email' header was renamed to 'cust_email'.",
        workbook=wb,
        template=template,
        expected=expected,
        expected_verdict="reject",
        expected_issues=expected_issues,
        notes="Tests the failure mode where the template's source_column doesn't match. "
              "Every row is missing the mapped field — should escalate to 'reject' verdict.",
    )


def case_corrupted_below_minimum() -> TestCase:
    """Put a negative number in unit_price — violates minimum=0."""
    rows, template = _flat_simple_base_rows(seed=53)
    template["template_id"] = "corrupted_below_minimum"

    bad_row_idx = 1
    rows[bad_row_idx] = {**rows[bad_row_idx], "unit_price": -42.50}

    wb = new_workbook()
    ws = wb.create_sheet("Orders")
    ws.append(list(rows[0].keys()))
    for r in rows:
        ws.append([r[k] for k in rows[0].keys()])

    expected = _envelope("corrupted_below_minimum", orders=rows)

    expected_issues = [{
        "entity": "order",
        "row": bad_row_idx,
        "field": "unit_price",
        "reason": "below_minimum",
    }]

    return TestCase(
        name="corrupted_below_minimum",
        description="Flat order table — one row has a negative unit_price.",
        workbook=wb,
        template=template,
        expected=expected,
        expected_verdict="needs_review",
        expected_issues=expected_issues,
        notes="Tests numeric range constraint (minimum).",
    )


# =====================================================================
# Registry
# =====================================================================


ALL_CASES = [
    # clean (parsing tests)
    case_flat_simple,
    case_flat_with_title_rows,
    case_flat_with_totals_row,
    case_property_sheet_cover,
    case_anchored_scattered,
    case_multi_tab_acme,
    case_dialect_acme,
    case_dialect_globex,
    # corrupted (validation tests)
    case_corrupted_missing_value,
    case_corrupted_wrong_type,
    case_corrupted_renamed_header,
    case_corrupted_below_minimum,
]
