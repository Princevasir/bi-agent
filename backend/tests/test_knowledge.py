"""R1: the Trailhead Outfitters knowledge pack, checked for structure, consistency and truth."""
import shutil
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app import access
from app.bi import schema
from app.bi.sql_guard import validate_sql
from app.catalog import load as load_catalog
from app.db import run_readonly
from app.knowledge.documents import KNOWLEDGE_DIR, KnowledgeError, load
from retail import generate as gen
from retail.load import load as load_retail

OWNER_URL = "postgresql://retail_owner:retail_owner_dev_pw@localhost:5433/retail_test"
TYPES = {"metric", "rule", "sql_example", "dashboard", "data_quality", "document"}


@pytest.fixture(scope="module")
def docs():
    return load(KNOWLEDGE_DIR)


def by_id(docs):
    return {d.id: d for d in docs}


# ---- the pack ------------------------------------------------------------------------------------------------

def test_the_pack_covers_every_type(docs):
    assert len(docs) >= 35
    counts = defaultdict(int)
    for d in docs:
        counts[d.type] += 1
    assert set(counts) == TYPES
    assert counts["metric"] >= 10 and counts["sql_example"] >= 8 and counts["dashboard"] >= 3


def test_every_document_has_owner_version_date_and_source(docs):
    for d in docs:
        assert d.owner and d.source and d.version >= 1 and isinstance(d.effective_date, date), d.id
        assert d.body.strip(), d.id


def test_each_metric_has_exactly_one_authoritative_definition(docs):
    active = defaultdict(list)
    for d in docs:
        if d.type == "metric" and d.status == "active":
            active[d.metric].append(d)
    assert all(sum(x.authoritative for x in ds) == 1 for ds in active.values())
    revenue = [d for d in active["revenue"]]
    assert len(revenue) == 2, "the pack keeps a conflicting Finance view of revenue on purpose"


def test_a_superseded_rule_points_to_its_active_successor(docs):
    old = [d for d in docs if d.status == "superseded"]
    assert old
    index = by_id(docs)
    for d in old:
        new = index[d.superseded_by]
        assert new.status == "active" and new.type == d.type and new.version > d.version


def test_knowledge_access_matches_data_access(docs, monkeypatch):
    monkeypatch.setenv("DATA_SOURCE", "retail")
    for d in docs:
        for group in d.access_groups:
            assert set(d.tables) <= set(access.tables_for(group)), (d.id, group)
    assert any("limited" in d.access_groups for d in docs), "some knowledge is for limited users too"


def test_documents_only_name_described_tables(docs):
    described = set(load_catalog().tables)
    assert all(set(d.tables) <= described for d in docs)


# ---- facts in the documents agree with the generated data -----------------------------------------------------

def text_of(docs, doc_id):
    return by_id(docs)[doc_id].body


def long_date(d):
    return f"{d.day} {d.strftime('%B %Y')}"


def test_incident_report_matches_the_supply_data(docs):
    body = text_of(docs, "doc-incident-q1-2026-tent-supply")
    assert "Summit Tentworks" in body and gen.SUPPLIERS[0][0] == "Summit Tentworks"
    assert long_date(gen.STOCKOUT[0]) in body                      # 16 February 2026
    assert long_date(gen.LATE_DELIVERY) in body                     # 1 April 2026
    assert all(c in body for c in gen.STOCKOUT_CATEGORIES)


def test_recall_and_store_and_promotion_facts(docs):
    assert long_date(gen.RECALL_DAY) in text_of(docs, "doc-ridgeline-headlamp-recall-2025")
    spring = next(p for p in gen.PROMOTIONS if p[1] == "SPRINGTRAIL25")
    review = text_of(docs, "doc-spring-trail-sale-2025-review")
    assert "SPRINGTRAIL25" in review and f"{spring[2]}%" in review
    boulder = next(s for s in gen.STORES if s[0] == gen.BOULDER)
    assert long_date(boulder[4]) in text_of(docs, "dq-known-issues")


def test_data_cut_off_and_fiscal_calendar(docs):
    assert long_date(gen.LAST_DAY) in text_of(docs, "dq-known-issues")
    fiscal = text_of(docs, "rule-fiscal-calendar")
    assert "1 February" in fiscal and "FY2025" in fiscal and "31 January 2026" in fiscal


# ---- the validated SQL examples really are valid ----------------------------------------------------------------

@pytest.fixture(scope="module")
def tiny():
    load_retail(OWNER_URL, seed=7, scale="tiny")
    raw = gen.collect(seed=7, scale="tiny")
    return {t: [dict(zip(gen.COLUMNS[t], r)) for r in rows] for t, rows in raw.items()}


@pytest.fixture
def retail(monkeypatch):
    monkeypatch.setenv("DATA_SOURCE", "retail")
    schema.clear_cache()
    yield
    schema.clear_cache()


def run_example(d):
    sql = validate_sql(d.sql, access.tables_for("analyst"), access.denied_columns("analyst"), access.metric_rules())
    return run_readonly(sql, role="analyst", max_rows=200)


@pytest.mark.integration
def test_every_sql_example_passes_every_check_and_runs(docs, tiny, retail):
    examples = [d for d in docs if d.type == "sql_example"]
    for d in examples:
        out = run_example(d)
        assert out["columns"] == list(d.result_columns), d.id
        assert out["rows"], d.id


def completed_lines(data, start, end):
    orders = {o["order_id"]: o for o in data["orders"]}
    for i in data["order_items"]:
        o = orders[i["order_id"]]
        if o["status"] == "completed" and start <= o["ordered_at"].date() < end:
            yield o, i


@pytest.mark.integration
def test_monthly_trend_and_average_order_value_match_a_independent_count(docs, tiny, retail):
    index = by_id(docs)
    lines = list(completed_lines(tiny, date(2025, 1, 1), date(2026, 1, 1)))
    revenue = sum((i["line_total"] for _, i in lines), Decimal(0))
    trend = run_example(index["sql-monthly-revenue-trend"])
    assert round(sum(r[1] for r in trend["rows"]), 2) == round(float(revenue), 2)
    aov = run_example(index["sql-average-order-value"])["rows"][0][0]
    assert round(aov, 2) == round(float(revenue / len({o["order_id"] for o, _ in lines})), 2)


@pytest.mark.integration
def test_fiscal_year_example_uses_february_to_january(docs, tiny, retail):
    out = run_example(by_id(docs)["sql-fiscal-year-revenue"])
    fy2024 = sum((i["line_total"] for _, i in completed_lines(tiny, date(2024, 2, 1), date(2025, 2, 1))), Decimal(0))
    assert round(dict(out["rows"])[2024], 2) == round(float(fy2024), 2)


# ---- malformed documents are refused --------------------------------------------------------------------------

def _copy(tmp_path):
    target = tmp_path / "knowledge"
    shutil.copytree(KNOWLEDGE_DIR, target)
    return target


def _edit(target, doc_id, old, new):
    f = next(target.rglob(f"{doc_id}.md"))
    text = f.read_text()
    assert old in text, (doc_id, old)
    f.write_text(text.replace(old, new, 1))


@pytest.mark.parametrize("doc_id,old,new,mentions", [
    ("metric-revenue", 'owner = "', 'ownr = "x"\nowner = "', "ownr"),
    ("metric-revenue", 'owner = "Sales Analytics"\n', "", "owner"),
    ("metric-revenue", 'id = "metric-revenue"', 'id = "metric-revenues"', "file name"),
    ("metric-revenue", 'status = "active"', 'status = "draft"', "status"),
    ("metric-revenue", "version = ", "version = 0 #", "version"),
    ("metric-revenue", 'access_groups = ["analyst"]', 'access_groups = ["admins"]', "admins"),
    ("metric-revenue", 'tables = ["orders", "order_items"]', 'tables = ["orders", "made_up"]', "made_up"),
    ("metric-revenue", "authoritative = true", "authoritative = false", "authoritative"),
    ("metric-revenue-finance-view", "authoritative = false", "authoritative = true", "authoritative"),
    ("rule-exclude-cancelled-orders-v1", 'superseded_by = "rule-exclude-cancelled-orders"', 'superseded_by = "nope"', "nope"),
    ("dq-dataset-ownership", 'access_groups = ["analyst", "limited"]', 'access_groups = ["analyst", "limited"]\ntables = ["orders"]', "limited"),
    ("metric-revenue", "+++\n", "+++ \n", "header"),
])
def test_malformed_documents_are_refused(tmp_path, doc_id, old, new, mentions):
    target = _copy(tmp_path)
    _edit(target, doc_id, old, new)
    with pytest.raises(KnowledgeError) as e:
        load(target)
    assert mentions in str(e.value)


def test_duplicate_ids_and_duplicate_content_are_refused(tmp_path):
    target = _copy(tmp_path)
    original = next(target.rglob("metric-revenue.md"))
    (original.parent / "copy.md").write_text(original.read_text().replace('id = "metric-revenue"', 'id = "copy"'))
    with pytest.raises(KnowledgeError, match="same content"):
        load(target)


# ---- the long handbooks agree with the generated data too (added with the second batch) -----------------

def test_company_overview_lists_every_store_warehouse_country_and_brand(docs):
    body = text_of(docs, "doc-company-overview")
    assert f"run {len(gen.STORES)} stores" in body
    for name, city, *_ in gen.STORES:
        assert name in body and city in body
    assert all(w[0] in body for w in gen.WAREHOUSES)
    assert all(c[0] in body for c in gen.COUNTRIES)
    assert all(b[0] in body for b in gen.BRANDS)


def test_loyalty_guide_matches_the_tiers(docs):
    body = text_of(docs, "doc-loyalty-programme-guide")
    for name, spend, discount, *_ in gen.TIERS:
        assert f"| {name} | from {spend:,} USD | {discount}% |" in body


def test_shipping_policy_matches_how_orders_are_charged(docs, tiny):
    body = text_of(docs, "doc-shipping-and-fulfilment-policy")
    assert "$100" in body and "$7.95" in body and all(c in body for c in gen.CARRIERS)
    online = [o for o in tiny["orders"] if o["channel"] == "online"]
    assert {o["shipping_fee"] for o in online} == {Decimal("0.00"), Decimal("7.95")}
    assert all(o["shipping_fee"] == 0 for o in online if o["subtotal"] - o["discount_amount"] >= 100)


def test_promotions_policy_lists_every_code_with_its_discount(docs):
    body = text_of(docs, "doc-pricing-and-promotions-policy")
    for _, code, pct, channel, *_ in gen.PROMOTIONS:
        assert f"| {code} |" in body and f"| {pct}% | {channel} |" in body


def test_supplier_handbook_names_every_supplier(docs):
    body = text_of(docs, "doc-supplier-handbook")
    assert all(s[0] in body for s in gen.SUPPLIERS)


def test_departments_and_store_floor_areas(docs):
    assert all(d in text_of(docs, "doc-people-and-departments") for d in gen.DEPARTMENTS)
    areas = [s[5] for s in gen.STORES]
    handbook = text_of(docs, "doc-store-operations-handbook")
    assert f"from {min(areas)} to {max(areas):,} square metres" in handbook
