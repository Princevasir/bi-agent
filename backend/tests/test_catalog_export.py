"""M29c: the full data catalog (schema, types, keys, relationships, descriptions) as one reference."""
import json
from pathlib import Path

import psycopg
import pytest

from app import catalog
from retail.export_catalog import GENERATED_JSON, HTML_PAGE, render_html, to_json
from retail.load import load

OWNER_URL = "postgresql://retail_owner:retail_owner_dev_pw@localhost:5433/retail_test"
ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.integration


def owner_run(sql, params=None):
    with psycopg.connect(OWNER_URL) as conn:
        return conn.execute(sql, params).fetchall()


@pytest.fixture(scope="module")
def full():
    load(OWNER_URL, seed=7, scale="tiny")
    return catalog.merged(catalog.load(), catalog.introspect(owner_run))


def test_every_table_and_column_is_in_the_merged_catalog(full):
    assert len(full) == 29
    assert sum(len(t["columns"]) for t in full.values()) == 168


def test_a_table_has_its_keys_relationships_and_descriptions(full):
    orders = full["orders"]
    assert orders["domain"] == "Sales" and orders["grain"] == "One row per order."
    assert orders["description"].startswith("Customer orders")
    assert orders["primary_key"] == ["order_id"]
    assert {"column": "customer_id", "table": "customers", "references": "customer_id"} in orders["foreign_keys"]
    assert {"table": "order_items", "column": "order_id"} in orders["referenced_by"]
    assert any("cancelled" in c.lower() for c in orders["caveats"])


def test_a_column_has_type_key_flags_and_description(full):
    columns = {c["name"]: c for c in full["orders"]["columns"]}
    assert columns["order_id"]["primary_key"] is True and columns["order_id"]["nullable"] is False
    assert columns["ordered_at"]["type"] == "timestamp without time zone"
    assert columns["status"]["values"] == ["completed", "cancelled"]
    assert columns["total_amount"]["unit"] == "USD"
    assert columns["customer_id"]["references"] == "customers.customer_id" and columns["customer_id"]["nullable"]
    email = next(c for c in full["customers"]["columns"] if c["name"] == "email")
    assert email["pii"] is True


def test_composite_primary_keys_are_kept(full):
    assert full["inventory_snapshots"]["primary_key"] == ["snapshot_date", "warehouse_id", "product_id"]


def test_columns_keep_database_order(full):
    assert [c["name"] for c in full["orders"]["columns"]][:3] == ["order_id", "customer_id", "channel"]


def test_the_committed_catalog_is_up_to_date(full):
    committed = json.loads(GENERATED_JSON.read_text())
    assert committed == json.loads(to_json(full)), "run: cd backend && .venv/bin/python -m retail.export_catalog"


def test_the_committed_page_is_up_to_date(full):
    assert HTML_PAGE.read_text() == render_html(full), "run: cd backend && .venv/bin/python -m retail.export_catalog"


def test_the_page_shows_every_table_and_marks_keys(full):
    page = render_html(full)
    for name in full:
        assert f'id="{name}"' in page
    assert "PK" in page and "FK" in page and "Personal data" in page
    assert "<title>Data catalog</title>" in page


def test_the_export_holds_no_row_counts_or_data(full):
    exported = json.loads(to_json(full))
    assert "rows" not in exported["tables"]["orders"]                 # counts differ between databases
    assert "@example.com" not in to_json(full) and "@example.com" not in render_html(full)
