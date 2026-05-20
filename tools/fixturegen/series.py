"""
Data sources for the generator.

A Series produces "records" — flat dicts of {field: value}.
A CrosstabSeries produces a (row_labels, col_labels, matrix) triple.

The layout module decides how to render either into a Sheet.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from faker import Faker

fake = Faker()


# ---------- Series: flat records ----------


@dataclass
class Series:
    name: str
    columns: list[str]
    row_factory: Callable[[], dict]

    def make_record(self) -> dict:
        return self.row_factory()

    def make_records(self, n: int) -> list[dict]:
        return [self.row_factory() for _ in range(n)]


def _orders_row() -> dict:
    return {
        "order_id": fake.uuid4(),
        "order_date": fake.date_between(start_date="-2y", end_date="today").isoformat(),
        "customer_name": fake.name(),
        "customer_email": fake.email(),
        "product_sku": f"SKU-{random.randint(1000, 9999)}",
        "quantity": random.randint(1, 50),
        "unit_price": round(random.uniform(5.0, 500.0), 2),
    }


def _employees_row() -> dict:
    return {
        "employee_id": f"E{random.randint(10000, 99999)}",
        "full_name": fake.name(),
        "department": random.choice(["Eng", "Sales", "Ops", "HR", "Finance"]),
        "hire_date": fake.date_between(start_date="-10y", end_date="today").isoformat(),
        "salary": random.randint(40_000, 220_000),
        "manager_email": fake.email(),
    }


def _inventory_row() -> dict:
    return {
        "sku": f"SKU-{random.randint(1000, 9999)}",
        "product_name": fake.catch_phrase(),
        "warehouse": random.choice(["WH-A", "WH-B", "WH-C"]),
        "on_hand": random.randint(0, 5000),
        "reorder_point": random.randint(10, 500),
        "last_counted": fake.date_between(start_date="-1y", end_date="today").isoformat(),
    }


def _company_profile_row() -> dict:
    # one record per file; works well as a property-sheet / transposed layout
    return {
        "company_name": fake.company(),
        "tax_id": fake.bothify("##-#######"),
        "primary_contact": fake.name(),
        "contact_email": fake.email(),
        "phone": fake.phone_number(),
        "address": fake.street_address(),
        "city": fake.city(),
        "country": fake.country(),
        "founded_year": random.randint(1900, 2025),
        "employee_count": random.randint(1, 50_000),
    }


SERIES: dict[str, Series] = {
    "orders": Series(
        name="orders",
        columns=["order_id", "order_date", "customer_name", "customer_email", "product_sku", "quantity", "unit_price"],
        row_factory=_orders_row,
    ),
    "employees": Series(
        name="employees",
        columns=["employee_id", "full_name", "department", "hire_date", "salary", "manager_email"],
        row_factory=_employees_row,
    ),
    "inventory": Series(
        name="inventory",
        columns=["sku", "product_name", "warehouse", "on_hand", "reorder_point", "last_counted"],
        row_factory=_inventory_row,
    ),
    "company_profile": Series(
        name="company_profile",
        columns=[
            "company_name",
            "tax_id",
            "primary_contact",
            "contact_email",
            "phone",
            "address",
            "city",
            "country",
            "founded_year",
            "employee_count",
        ],
        row_factory=_company_profile_row,
    ),
}


# ---------- CrosstabSeries: matrix data ----------


@dataclass
class CrosstabSeries:
    name: str
    row_label_factory: Callable[[], str]
    col_labels: list[str]
    value_factory: Callable[[], Any]
    n_row_labels: int
    corner_label: str = ""  # text for the top-left cell (often blank or "Region", etc.)


CROSSTABS: dict[str, CrosstabSeries] = {
    "sales_by_region_quarter": CrosstabSeries(
        name="sales_by_region_quarter",
        row_label_factory=lambda: random.choice(["North", "South", "East", "West", "Central", "EMEA", "APAC", "LATAM"]),
        col_labels=["Q1_2025", "Q2_2025", "Q3_2025", "Q4_2025"],
        value_factory=lambda: random.randint(10_000, 500_000),
        n_row_labels=6,
        corner_label="region",
    ),
    "inventory_by_warehouse_product": CrosstabSeries(
        name="inventory_by_warehouse_product",
        row_label_factory=lambda: f"SKU-{random.randint(1000, 9999)}",
        col_labels=["WH-A", "WH-B", "WH-C", "WH-D"],
        value_factory=lambda: random.randint(0, 2000),
        n_row_labels=10,
        corner_label="sku",
    ),
    "headcount_by_dept_year": CrosstabSeries(
        name="headcount_by_dept_year",
        row_label_factory=lambda: random.choice(["Eng", "Sales", "Ops", "HR", "Finance", "Marketing", "Legal"]),
        col_labels=["2021", "2022", "2023", "2024", "2025"],
        value_factory=lambda: random.randint(5, 500),
        n_row_labels=5,
        corner_label="department",
    ),
}
