"""Data-quality and story checks for the generated retail dataset (no database needed)."""
import hashlib
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal

import pytest

from retail.generate import COLUMNS, collect

SEED = 7

TABLES = {
    "regions", "countries", "stores", "warehouses",
    "categories", "brands", "suppliers", "products", "product_prices", "product_suppliers",
    "loyalty_tiers", "customers", "customer_addresses", "loyalty_memberships",
    "promotions", "orders", "order_items", "order_promotions", "payments", "shipments", "returns",
    "inventory_snapshots", "purchase_orders", "purchase_order_items",
    "campaigns", "web_sessions", "support_tickets",
    "departments", "employees",
}

PRIMARY_KEYS = {
    "regions": ("region_id",), "countries": ("country_id",), "stores": ("store_id",),
    "warehouses": ("warehouse_id",), "categories": ("category_id",), "brands": ("brand_id",),
    "suppliers": ("supplier_id",), "products": ("product_id",), "product_prices": ("product_price_id",),
    "product_suppliers": ("product_id", "supplier_id"), "loyalty_tiers": ("tier_id",),
    "customers": ("customer_id",), "customer_addresses": ("address_id",),
    "loyalty_memberships": ("membership_id",), "promotions": ("promotion_id",),
    "orders": ("order_id",), "order_items": ("order_item_id",),
    "order_promotions": ("order_id", "promotion_id"), "payments": ("payment_id",),
    "shipments": ("shipment_id",), "returns": ("return_id",),
    "inventory_snapshots": ("snapshot_date", "warehouse_id", "product_id"),
    "purchase_orders": ("purchase_order_id",), "purchase_order_items": ("po_item_id",),
    "campaigns": ("campaign_id",), "web_sessions": ("session_id",), "support_tickets": ("ticket_id",),
    "departments": ("department_id",), "employees": ("employee_id",),
}

# (table, column, referenced table, referenced column); NULL means "no reference".
FOREIGN_KEYS = [
    ("countries", "region_id", "regions", "region_id"),
    ("stores", "country_id", "countries", "country_id"),
    ("warehouses", "country_id", "countries", "country_id"),
    ("categories", "parent_id", "categories", "category_id"),
    ("suppliers", "country_id", "countries", "country_id"),
    ("products", "category_id", "categories", "category_id"),
    ("products", "brand_id", "brands", "brand_id"),
    ("product_prices", "product_id", "products", "product_id"),
    ("product_suppliers", "product_id", "products", "product_id"),
    ("product_suppliers", "supplier_id", "suppliers", "supplier_id"),
    ("customers", "country_id", "countries", "country_id"),
    ("customer_addresses", "customer_id", "customers", "customer_id"),
    ("customer_addresses", "country_id", "countries", "country_id"),
    ("loyalty_memberships", "customer_id", "customers", "customer_id"),
    ("loyalty_memberships", "tier_id", "loyalty_tiers", "tier_id"),
    ("orders", "customer_id", "customers", "customer_id"),
    ("orders", "store_id", "stores", "store_id"),
    ("orders", "shipping_address_id", "customer_addresses", "address_id"),
    ("order_items", "order_id", "orders", "order_id"),
    ("order_items", "product_id", "products", "product_id"),
    ("order_promotions", "order_id", "orders", "order_id"),
    ("order_promotions", "promotion_id", "promotions", "promotion_id"),
    ("payments", "order_id", "orders", "order_id"),
    ("shipments", "order_id", "orders", "order_id"),
    ("shipments", "warehouse_id", "warehouses", "warehouse_id"),
    ("returns", "order_item_id", "order_items", "order_item_id"),
    ("inventory_snapshots", "warehouse_id", "warehouses", "warehouse_id"),
    ("inventory_snapshots", "product_id", "products", "product_id"),
    ("purchase_orders", "supplier_id", "suppliers", "supplier_id"),
    ("purchase_orders", "warehouse_id", "warehouses", "warehouse_id"),
    ("purchase_order_items", "purchase_order_id", "purchase_orders", "purchase_order_id"),
    ("purchase_order_items", "product_id", "products", "product_id"),
    ("web_sessions", "customer_id", "customers", "customer_id"),
    ("web_sessions", "campaign_id", "campaigns", "campaign_id"),
    ("web_sessions", "order_id", "orders", "order_id"),
    ("support_tickets", "customer_id", "customers", "customer_id"),
    ("support_tickets", "order_id", "orders", "order_id"),
    ("employees", "department_id", "departments", "department_id"),
    ("employees", "store_id", "stores", "store_id"),
    ("employees", "manager_id", "employees", "employee_id"),
]

START, END = datetime(2024, 1, 1), datetime(2026, 10, 1)


@pytest.fixture(scope="module")
def data():
    raw = collect(seed=SEED, scale="small")
    return {t: [dict(zip(COLUMNS[t], r)) for r in rows] for t, rows in raw.items()}


def digest(raw):
    h = hashlib.sha256()
    for table in sorted(raw):
        for row in raw[table]:
            h.update(repr(row).encode())
    return h.hexdigest()


def by_id(rows, key):
    return {r[key]: r for r in rows}


def month(dt):
    return dt.strftime("%Y-%m")


@pytest.fixture(scope="module")
def sales(data):
    """Completed order items joined to their order, product and category name."""
    orders = by_id(data["orders"], "order_id")
    products = by_id(data["products"], "product_id")
    categories = by_id(data["categories"], "category_id")
    out = []
    for item in data["order_items"]:
        o = orders[item["order_id"]]
        if o["status"] != "completed":
            continue
        p = products[item["product_id"]]
        out.append({**item, "order": o, "product": p, "category": categories[p["category_id"]]["name"]})
    return out


def revenue(rows, pred=lambda s: True):
    return sum((s["line_total"] for s in rows if pred(s)), Decimal(0))


# ---- shape and determinism ------------------------------------------------

def test_every_table_is_generated(data):
    assert set(data) == TABLES
    assert all(data[t] for t in TABLES), [t for t in TABLES if not data[t]]


def test_same_seed_gives_identical_data():
    assert digest(collect(seed=SEED, scale="tiny")) == digest(collect(seed=SEED, scale="tiny"))


def test_different_seed_gives_different_data():
    assert digest(collect(seed=SEED, scale="tiny")) != digest(collect(seed=SEED + 1, scale="tiny"))


def test_small_scale_has_a_useful_amount_of_data(data):
    assert 3_000 <= len(data["orders"]) <= 12_000
    assert len(data["order_items"]) > len(data["orders"])
    assert len(data["customers"]) >= 500


@pytest.mark.parametrize("table", sorted(PRIMARY_KEYS))
def test_primary_keys_are_unique(data, table):
    keys = [tuple(r[c] for c in PRIMARY_KEYS[table]) for r in data[table]]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("table,col,ref_table,ref_col", FOREIGN_KEYS)
def test_foreign_keys_resolve(data, table, col, ref_table, ref_col):
    known = {r[ref_col] for r in data[ref_table]}
    missing = {r[col] for r in data[table] if r[col] is not None} - known
    assert not missing, f"{table}.{col} has {len(missing)} unknown values"


# ---- business rules -------------------------------------------------------

def test_orders_fall_inside_the_data_window(data):
    assert all(START <= o["ordered_at"] < END for o in data["orders"])


def test_line_totals_and_order_totals_add_up(data):
    items = defaultdict(list)
    for i in data["order_items"]:
        assert i["line_total"] == i["quantity"] * i["unit_price"] - i["discount_amount"]
        assert i["quantity"] >= 1 and i["discount_amount"] >= 0
        items[i["order_id"]].append(i)
    for o in data["orders"]:
        lines = items[o["order_id"]]
        assert lines, f"order {o['order_id']} has no items"
        assert o["subtotal"] == sum(i["quantity"] * i["unit_price"] for i in lines)
        assert o["discount_amount"] == sum(i["discount_amount"] for i in lines)
        assert o["total_amount"] == o["subtotal"] - o["discount_amount"] + o["shipping_fee"]


def test_unit_price_is_the_list_price_valid_on_the_order_date(data):
    prices = defaultdict(list)
    for p in data["product_prices"]:
        prices[p["product_id"]].append(p)
    orders = by_id(data["orders"], "order_id")
    for i in data["order_items"]:
        d = orders[i["order_id"]]["ordered_at"].date()
        valid = [p for p in prices[i["product_id"]]
                 if p["valid_from"] <= d and (p["valid_to"] is None or d < p["valid_to"])]
        assert len(valid) == 1, (i, d)
        assert i["unit_price"] == valid[0]["list_price"]


def test_price_history_periods_do_not_overlap(data):
    prices = defaultdict(list)
    for p in data["product_prices"]:
        prices[p["product_id"]].append(p)
    assert any(len(v) > 1 for v in prices.values()), "no product ever changed price"
    for rows in prices.values():
        rows.sort(key=lambda p: p["valid_from"])
        for a, b in zip(rows, rows[1:]):
            assert a["valid_to"] == b["valid_from"]
        assert rows[-1]["valid_to"] is None


def test_channels_follow_their_rules(data):
    shipped = Counter(s["order_id"] for s in data["shipments"])
    for o in data["orders"]:
        assert o["channel"] in ("online", "store")
        assert o["status"] in ("completed", "cancelled")
        if o["channel"] == "store":
            assert o["store_id"] is not None and o["shipping_fee"] == 0
            assert o["shipping_address_id"] is None and shipped[o["order_id"]] == 0
        else:
            assert o["store_id"] is None
            assert shipped[o["order_id"]] == (1 if o["status"] == "completed" else 0)


def test_shipping_address_belongs_to_the_customer(data):
    addresses = by_id(data["customer_addresses"], "address_id")
    for o in data["orders"]:
        if o["shipping_address_id"] is not None:
            assert addresses[o["shipping_address_id"]]["customer_id"] == o["customer_id"]


def test_store_orders_only_after_the_store_opened(data):
    stores = by_id(data["stores"], "store_id")
    for o in data["orders"]:
        if o["store_id"] is not None:
            assert o["ordered_at"].date() >= stores[o["store_id"]]["opened_on"]


def test_shipments_happen_after_the_order(data):
    orders = by_id(data["orders"], "order_id")
    for s in data["shipments"]:
        assert s["shipped_at"] >= orders[s["order_id"]]["ordered_at"]
        assert s["delivered_at"] is None or s["delivered_at"] >= s["shipped_at"]


def test_returns_are_valid(data):
    items = by_id(data["order_items"], "order_item_id")
    orders = by_id(data["orders"], "order_id")
    returned = Counter()
    for r in data["returns"]:
        item = items[r["order_item_id"]]
        order = orders[item["order_id"]]
        returned[r["order_item_id"]] += r["quantity"]
        assert order["status"] == "completed"
        assert r["returned_at"] > order["ordered_at"]
        assert 0 < r["refund_amount"] <= item["line_total"]
    assert all(returned[k] <= items[k]["quantity"] for k in returned)


def test_payments_match_order_totals(data):
    paid = defaultdict(Decimal)
    for p in data["payments"]:
        if p["status"] == "captured":
            paid[p["order_id"]] += p["amount"]
    for o in data["orders"]:
        expected = o["total_amount"] if o["status"] == "completed" else 0
        assert paid[o["order_id"]] == expected, o["order_id"]


def test_some_orders_are_from_guests(data):
    share = sum(o["customer_id"] is None for o in data["orders"]) / len(data["orders"])
    assert 0.05 <= share <= 0.35


def test_customers_order_only_after_signing_up(data):
    customers = by_id(data["customers"], "customer_id")
    for o in data["orders"]:
        if o["customer_id"] is not None:
            assert o["ordered_at"].date() >= customers[o["customer_id"]]["signup_date"]


@pytest.mark.parametrize("table,key,parent", [
    ("categories", "category_id", "parent_id"),
    ("employees", "employee_id", "manager_id"),
])
def test_hierarchies_have_one_root_and_no_cycles(data, table, key, parent):
    rows = by_id(data[table], key)
    roots = [r for r in rows.values() if r[parent] is None]
    if table == "employees":
        assert len(roots) == 1
    else:
        assert len(roots) >= 3
    depth = 0
    for r in rows.values():
        seen, cur = set(), r
        while cur[parent] is not None:
            assert cur[key] not in seen, f"cycle at {cur[key]}"
            seen.add(cur[key])
            cur = rows[cur[parent]]
        depth = max(depth, len(seen))
    assert depth >= 2


def test_contact_details_are_fictional(data):
    for c in data["customers"]:
        assert c["email"].endswith("@example.com")
        assert "555" in c["phone"]
    for e in data["employees"]:
        assert e["email"].endswith("@example.com")


# ---- planted stories ------------------------------------------------------

def test_december_is_the_peak_month_each_full_year(sales):
    for year in (2024, 2025):
        by_month = defaultdict(Decimal)
        for s in sales:
            if s["order"]["ordered_at"].year == year:
                by_month[s["order"]["ordered_at"].month] += s["line_total"]
        assert max(by_month, key=by_month.get) == 12, (year, dict(by_month))


def test_revenue_grows_year_on_year(sales):
    y24 = revenue(sales, lambda s: s["order"]["ordered_at"].year == 2024)
    y25 = revenue(sales, lambda s: s["order"]["ordered_at"].year == 2025)
    assert y25 >= y24 * Decimal("1.08")


def test_tents_sell_most_in_summer(sales):
    summer = revenue(sales, lambda s: s["category"] == "Tents" and s["order"]["ordered_at"].month in (6, 7, 8))
    winter = revenue(sales, lambda s: s["category"] == "Tents" and s["order"]["ordered_at"].month in (12, 1, 2))
    assert summer > 2 * winter


def test_late_tent_deliveries_cause_a_march_2026_dip(data, sales):
    suppliers = by_id(data["suppliers"], "supplier_id")
    late = [po for po in data["purchase_orders"]
            if suppliers[po["supplier_id"]]["name"] == "Summit Tentworks"
            and date(2026, 2, 1) <= po["expected_on"] < date(2026, 3, 1)]
    assert late and all(po["received_on"] is not None
                        and (po["received_on"] - po["expected_on"]).days >= 30 for po in late)

    def tents(m):
        return revenue(sales, lambda s: s["category"] == "Tents" and month(s["order"]["ordered_at"]) == m)

    def online(m):
        return revenue(sales, lambda s: s["order"]["channel"] == "online" and month(s["order"]["ordered_at"]) == m)

    assert tents("2026-03") < tents("2025-03") * Decimal("0.4")
    assert online("2026-03") < online("2025-03")
    assert online("2026-05") > online("2025-05"), "sales recover once tents are back (April 2025 had a promotion)"


def test_tent_stock_runs_out_in_march_2026(data):
    products = by_id(data["products"], "product_id")
    categories = by_id(data["categories"], "category_id")

    def tent_stock(d0, d1):
        rows = [s for s in data["inventory_snapshots"]
                if d0 <= s["snapshot_date"] < d1
                and categories[products[s["product_id"]]["category_id"]]["name"] == "Tents"]
        assert rows
        return sum(s["quantity_on_hand"] for s in rows) / len(rows)

    assert tent_stock(date(2026, 3, 1), date(2026, 3, 29)) < 0.1 * tent_stock(date(2025, 3, 1), date(2025, 3, 29))


def test_spring_promotion_lifts_april_2025(data, sales):
    promos = by_id(data["promotions"], "promotion_id")
    spring = {p["promotion_id"] for p in promos.values() if p["code"] == "SPRINGTRAIL25"}
    assert spring
    april = {o["order_id"] for o in data["orders"]
             if o["status"] == "completed" and month(o["ordered_at"]) == "2025-04"}
    used = {op["order_id"] for op in data["order_promotions"] if op["promotion_id"] in spring}
    assert len(april & used) >= 0.25 * len(april)
    assert not used - april, "the spring code was used outside April 2025"
    a25 = revenue(sales, lambda s: month(s["order"]["ordered_at"]) == "2025-04")
    a24 = revenue(sales, lambda s: month(s["order"]["ordered_at"]) == "2024-04")
    assert a25 > a24 * Decimal("1.2")


def test_recalled_headlamp_has_many_returns(data, sales):
    headlamp = next(p for p in data["products"] if p["name"] == "Ridgeline 300 Headlamp")
    assert headlamp["discontinued_on"] == date(2025, 6, 10)
    returned = {r["order_item_id"]: r for r in data["returns"]}
    lamp = [s for s in sales if s["product_id"] == headlamp["product_id"]]
    assert lamp and all(s["order"]["ordered_at"].date() < date(2025, 6, 10) for s in lamp)
    recent = [s for s in lamp if s["order"]["ordered_at"].date() >= date(2025, 1, 1)]
    rate = sum(s["order_item_id"] in returned for s in recent) / len(recent)
    assert rate >= 0.3
    assert any(returned[s["order_item_id"]]["reason"] == "recall" for s in recent if s["order_item_id"] in returned)
    others = [s for s in sales if s["product_id"] != headlamp["product_id"]]
    assert sum(s["order_item_id"] in returned for s in others) / len(others) < 0.12


def test_new_store_opened_in_july_2025(data):
    store = next(s for s in data["stores"] if s["name"] == "Boulder Basecamp")
    assert store["opened_on"] == date(2025, 7, 1)
    assert any(o["store_id"] == store["store_id"] for o in data["orders"])


def test_gold_members_spend_about_twice_as_much_as_bronze(data, sales):
    tiers = by_id(data["loyalty_tiers"], "tier_id")
    current = {m["customer_id"]: tiers[m["tier_id"]]["name"]
               for m in data["loyalty_memberships"] if m["valid_to"] is None}
    assert len(current) == len(data["customers"]), "every customer has exactly one current tier"
    spend = defaultdict(Decimal)
    for s in sales:
        if s["order"]["customer_id"] is not None:
            spend[s["order"]["customer_id"]] += s["line_total"]

    def avg(tier):
        ids = [c for c, t in current.items() if t == tier]
        return sum((spend[c] for c in ids), Decimal(0)) / len(ids)

    assert Decimal("1.6") <= avg("Gold") / avg("Bronze") <= Decimal("2.6")
