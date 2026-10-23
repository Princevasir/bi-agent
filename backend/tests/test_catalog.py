"""M29a: the data catalog, checked against itself, the database and the access grants."""
import shutil
from pathlib import Path

import psycopg
import pytest
import sqlglot

from app import catalog
from retail.generate import collect
from retail.load import load

CATALOG_DIR = Path(__file__).resolve().parents[1] / "catalog"
OWNER_URL = "postgresql://retail_owner:retail_owner_dev_pw@localhost:5433/retail_test"
DOMAINS = {"Geography", "Product", "Customers", "Sales", "Supply chain", "Marketing and service", "People"}
PERSONAL = {
    ("customers", "first_name"), ("customers", "last_name"), ("customers", "email"), ("customers", "phone"),
    ("customer_addresses", "street"), ("customer_addresses", "postal_code"),
    ("employees", "first_name"), ("employees", "last_name"), ("employees", "email"), ("employees", "salary"),
}


@pytest.fixture(scope="module")
def cat():
    return catalog.load(CATALOG_DIR)


def owner_run(sql, params=None):
    with psycopg.connect(OWNER_URL) as conn:
        return conn.execute(sql, params).fetchall()


@pytest.fixture(scope="module")
def loaded():
    load(OWNER_URL, seed=7, scale="tiny")


@pytest.fixture(scope="module")
def db(loaded):
    return catalog.introspect(owner_run)


# ---- the files ---------------------------------------------------------------------------------

def test_every_table_is_described(cat):
    assert len(cat.tables) == 29
    assert {t.domain for t in cat.tables.values()} == DOMAINS
    for t in cat.tables.values():
        assert t.description and t.grain, t.name
        assert t.columns and all(c.description for c in t.columns.values()), t.name


def test_personal_columns_are_flagged(cat):
    flagged = {(t.name, c.name) for t in cat.tables.values() for c in t.columns.values() if c.pii}
    assert flagged == PERSONAL


def test_status_columns_list_their_values(cat):
    assert cat.tables["orders"].columns["status"].values == ("completed", "cancelled")
    assert cat.tables["orders"].columns["channel"].values == ("online", "store")
    assert set(cat.tables["returns"].columns["reason"].values) == {
        "defective", "wrong_size", "changed_mind", "damaged", "recall"}


def test_known_traps_are_written_down(cat):
    orders = " ".join(cat.tables["orders"].caveats).lower()
    assert "cancelled" in orders and "order_items" in orders          # revenue filter and double counting
    assert any("guest" in c.lower() for c in cat.tables["orders"].caveats)
    assert any("list price" in c.lower() or "price paid" in c.lower() for c in cat.tables["order_items"].caveats)


def test_metrics_are_defined_on_known_tables(cat):
    assert {"revenue", "order_count", "units_sold", "average_order_value", "return_rate"} <= set(cat.metrics)
    for m in cat.metrics.values():
        assert m.description and set(m.tables) <= set(cat.tables), m.name
        sqlglot.parse_one(f"SELECT {m.expression}", read="postgres")
        for f in m.filters:
            sqlglot.parse_one(f"SELECT 1 WHERE {f}", read="postgres")
    revenue = cat.metrics["revenue"]
    assert "line_total" in revenue.expression and "orders.status = 'completed'" in revenue.filters


# ---- malformed files are refused --------------------------------------------------------------

def _broken(tmp_path, name, old, new):
    target = tmp_path / "catalog"
    shutil.copytree(CATALOG_DIR, target)
    f = target / name
    text = f.read_text()
    assert old in text, old
    f.write_text(text.replace(old, new, 1))
    return target


@pytest.mark.parametrize("name,old,new,mentions", [
    ("sales.toml", 'grain = "One row per order."', 'grain = "One row per order."\ngrian = "typo"', "grian"),
    ("sales.toml", 'domain = "Sales"', 'domain = "Saless"', "Saless"),
    ("customers.toml", "pii = true", 'pii = "yes"', "pii"),
    ("customers.toml", "pii = true", "pii = true, secret = 1", "secret"),
    ("sales.toml", 'domain = "Sales"', 'domain = "Sales"\n[[[', "could not be read"),
])
def test_malformed_catalogs_are_refused(tmp_path, name, old, new, mentions):
    with pytest.raises(catalog.CatalogError) as e:
        catalog.load(_broken(tmp_path, name, old, new))
    assert mentions in str(e.value)


def test_a_table_described_twice_is_refused(tmp_path):
    target = tmp_path / "catalog"
    shutil.copytree(CATALOG_DIR, target)
    (target / "extra.toml").write_text(
        'domain = "Sales"\n[tables.orders]\ndescription = "x"\ngrain = "x"\n[tables.orders.columns]\nid = "x"\n')
    with pytest.raises(catalog.CatalogError, match="orders"):
        catalog.load(target)


def test_a_column_without_a_description_is_refused(tmp_path):
    with pytest.raises(catalog.CatalogError, match="region_id"):
        catalog.load(_broken(tmp_path, "geography.toml", 'region_id = "', 'region_id = { values = ["x"] }\nzz = "'))


# ---- the database ----------------------------------------------------------------------------------

@pytest.mark.integration
def test_catalog_and_database_agree(cat, db):
    assert catalog.drift(cat, db) == []


@pytest.mark.integration
def test_drift_reports_a_missing_and_an_extra_column(cat, db):
    del cat.tables["orders"].columns["status"]
    try:
        problems = catalog.drift(cat, {**db, "made_up": {"columns": {"x": "text"}, "primary_key": [],
                                                         "foreign_keys": [], "rows": 0}})
    finally:
        cat.tables["orders"].columns.clear()
        cat.tables["orders"].columns.update(catalog.load(CATALOG_DIR).tables["orders"].columns)
    assert any("orders.status" in p for p in problems)
    assert any("made_up" in p for p in problems)


@pytest.mark.integration
def test_types_keys_and_relationships_come_from_the_database(db):
    orders = db["orders"]
    assert orders["columns"]["ordered_at"] == "timestamp without time zone"
    assert orders["primary_key"] == ["order_id"]
    assert ("customer_id", "customers", "customer_id") in orders["foreign_keys"]
    assert db["order_items"]["rows"] > 0


@pytest.mark.integration
def test_personal_flags_match_the_analyst_grants(cat, loaded):
    granted = set(owner_run("""
        SELECT table_name, column_name FROM information_schema.column_privileges
        WHERE grantee = 'retail_analyst' AND privilege_type = 'SELECT'"""))
    every = {(t.name, c) for t in cat.tables.values() for c in t.columns}
    assert every - granted == PERSONAL


def test_documented_values_cover_the_data(cat):
    data = collect(seed=7, scale="tiny")
    from retail.generate import COLUMNS
    for t in cat.tables.values():
        for c in t.columns.values():
            if c.values:
                i = COLUMNS[t.name].index(c.name)
                seen = {r[i] for r in data[t.name] if r[i] is not None}
                assert seen <= set(c.values), (t.name, c.name, seen - set(c.values))


def test_sql_hints_cover_dates_and_shared_column_names(cat):
    hints = " ".join(cat.hints)
    for needle in ("EXTRACT(QUARTER FROM", "date_trunc('month'", "GROUP BY", ">= '2025-01-01'", "table alias"):
        assert needle in hints, needle


def test_hints_must_be_a_list_of_text(tmp_path):
    with pytest.raises(catalog.CatalogError, match="hints"):
        catalog.load(_broken(tmp_path, "hints.toml", "hints = [", "hints = 5\nold = ["))
