-- Trailhead Outfitters: fictional outdoor-gear retailer, sold online and in stores.
-- Tables and primary keys only; foreign keys and indexes are added after loading (constraints.sql).
DROP TABLE IF EXISTS
  employees, departments, support_tickets, web_sessions, campaigns,
  purchase_order_items, purchase_orders, inventory_snapshots,
  returns, shipments, payments, order_promotions, order_items, orders, promotions,
  loyalty_memberships, customer_addresses, customers, loyalty_tiers,
  product_suppliers, product_prices, products, suppliers, brands, categories,
  warehouses, stores, countries, regions
  CASCADE;

-- Geography
CREATE TABLE regions (
  region_id    integer PRIMARY KEY,
  name         text NOT NULL UNIQUE
);
CREATE TABLE countries (
  country_id   integer PRIMARY KEY,
  name         text NOT NULL UNIQUE,
  iso_code     char(2) NOT NULL UNIQUE,
  region_id    integer NOT NULL
);
CREATE TABLE stores (
  store_id      integer PRIMARY KEY,
  name          text NOT NULL UNIQUE,
  city          text NOT NULL,
  country_id    integer NOT NULL,
  store_type    text NOT NULL CHECK (store_type IN ('flagship', 'standard', 'outlet')),
  opened_on     date NOT NULL,
  square_meters integer NOT NULL CHECK (square_meters > 0)
);
CREATE TABLE warehouses (
  warehouse_id integer PRIMARY KEY,
  name         text NOT NULL UNIQUE,
  city         text NOT NULL,
  country_id   integer NOT NULL
);

-- Product
CREATE TABLE categories (
  category_id  integer PRIMARY KEY,
  name         text NOT NULL UNIQUE,
  parent_id    integer
);
CREATE TABLE brands (
  brand_id         integer PRIMARY KEY,
  name             text NOT NULL UNIQUE,
  is_private_label boolean NOT NULL
);
CREATE TABLE suppliers (
  supplier_id        integer PRIMARY KEY,
  name               text NOT NULL UNIQUE,
  country_id         integer NOT NULL,
  reliability_rating numeric(3,1) NOT NULL CHECK (reliability_rating BETWEEN 1 AND 5)
);
CREATE TABLE products (
  product_id      integer PRIMARY KEY,
  sku             text NOT NULL UNIQUE,
  name            text NOT NULL,
  category_id     integer NOT NULL,
  brand_id        integer NOT NULL,
  unit_cost       numeric(10,2) NOT NULL CHECK (unit_cost > 0),
  launched_on     date NOT NULL,
  discontinued_on date,
  CHECK (discontinued_on IS NULL OR discontinued_on > launched_on)
);
CREATE TABLE product_prices (
  product_price_id integer PRIMARY KEY,
  product_id       integer NOT NULL,
  list_price       numeric(10,2) NOT NULL CHECK (list_price > 0),
  valid_from       date NOT NULL,
  valid_to         date,
  CHECK (valid_to IS NULL OR valid_to > valid_from)
);
CREATE TABLE product_suppliers (
  product_id     integer NOT NULL,
  supplier_id    integer NOT NULL,
  unit_cost      numeric(10,2) NOT NULL CHECK (unit_cost > 0),
  lead_time_days integer NOT NULL CHECK (lead_time_days > 0),
  is_primary     boolean NOT NULL,
  PRIMARY KEY (product_id, supplier_id)
);

-- Customers
CREATE TABLE loyalty_tiers (
  tier_id          integer PRIMARY KEY,
  name             text NOT NULL UNIQUE,
  min_annual_spend numeric(10,2) NOT NULL CHECK (min_annual_spend >= 0),
  discount_pct     numeric(4,1) NOT NULL CHECK (discount_pct BETWEEN 0 AND 100)
);
CREATE TABLE customers (
  customer_id         integer PRIMARY KEY,
  first_name          text NOT NULL,
  last_name           text NOT NULL,
  email               text NOT NULL UNIQUE,
  phone               text NOT NULL,
  birth_year          integer CHECK (birth_year BETWEEN 1920 AND 2010),
  country_id          integer NOT NULL,
  signup_date         date NOT NULL,
  acquisition_channel text NOT NULL CHECK (acquisition_channel IN ('organic', 'search', 'social', 'email', 'referral', 'store')),
  marketing_opt_in    boolean NOT NULL
);
CREATE TABLE customer_addresses (
  address_id   integer PRIMARY KEY,
  customer_id  integer NOT NULL,
  address_type text NOT NULL CHECK (address_type IN ('shipping', 'billing')),
  street       text NOT NULL,
  city         text NOT NULL,
  postal_code  text NOT NULL,
  country_id   integer NOT NULL,
  is_default   boolean NOT NULL
);
CREATE TABLE loyalty_memberships (
  membership_id integer PRIMARY KEY,
  customer_id   integer NOT NULL,
  tier_id       integer NOT NULL,
  valid_from    date NOT NULL,
  valid_to      date,
  CHECK (valid_to IS NULL OR valid_to > valid_from)
);

-- Sales
CREATE TABLE promotions (
  promotion_id integer PRIMARY KEY,
  name         text NOT NULL,
  code         text NOT NULL UNIQUE,
  discount_pct numeric(4,1) NOT NULL CHECK (discount_pct > 0 AND discount_pct < 100),
  channel      text NOT NULL CHECK (channel IN ('online', 'store', 'all')),
  starts_on    date NOT NULL,
  ends_on      date NOT NULL,
  CHECK (ends_on >= starts_on)
);
CREATE TABLE orders (
  order_id            integer PRIMARY KEY,
  customer_id         integer,
  channel             text NOT NULL CHECK (channel IN ('online', 'store')),
  store_id            integer,
  shipping_address_id integer,
  ordered_at          timestamp NOT NULL,
  status              text NOT NULL CHECK (status IN ('completed', 'cancelled')),
  subtotal            numeric(12,2) NOT NULL CHECK (subtotal >= 0),
  discount_amount     numeric(12,2) NOT NULL CHECK (discount_amount >= 0),
  shipping_fee        numeric(12,2) NOT NULL CHECK (shipping_fee >= 0),
  total_amount        numeric(12,2) NOT NULL CHECK (total_amount >= 0),
  CHECK ((channel = 'store') = (store_id IS NOT NULL))
);
CREATE TABLE order_items (
  order_item_id   integer PRIMARY KEY,
  order_id        integer NOT NULL,
  product_id      integer NOT NULL,
  quantity        integer NOT NULL CHECK (quantity > 0),
  unit_price      numeric(10,2) NOT NULL CHECK (unit_price > 0),
  discount_amount numeric(10,2) NOT NULL CHECK (discount_amount >= 0),
  line_total      numeric(12,2) NOT NULL CHECK (line_total >= 0)
);
CREATE TABLE order_promotions (
  order_id     integer NOT NULL,
  promotion_id integer NOT NULL,
  PRIMARY KEY (order_id, promotion_id)
);
CREATE TABLE payments (
  payment_id integer PRIMARY KEY,
  order_id   integer NOT NULL,
  method     text NOT NULL CHECK (method IN ('card', 'paypal', 'gift_card', 'cash')),
  amount     numeric(12,2) NOT NULL CHECK (amount > 0),
  paid_at    timestamp NOT NULL,
  status     text NOT NULL CHECK (status IN ('captured', 'refunded'))
);
CREATE TABLE shipments (
  shipment_id   integer PRIMARY KEY,
  order_id      integer NOT NULL,
  warehouse_id  integer NOT NULL,
  carrier       text NOT NULL,
  shipped_at    timestamp NOT NULL,
  delivered_at  timestamp,
  shipping_cost numeric(10,2) NOT NULL CHECK (shipping_cost >= 0),
  CHECK (delivered_at IS NULL OR delivered_at >= shipped_at)
);
CREATE TABLE returns (
  return_id     integer PRIMARY KEY,
  order_item_id integer NOT NULL,
  quantity      integer NOT NULL CHECK (quantity > 0),
  reason        text NOT NULL CHECK (reason IN ('defective', 'wrong_size', 'changed_mind', 'damaged', 'recall')),
  returned_at   timestamp NOT NULL,
  refund_amount numeric(12,2) NOT NULL CHECK (refund_amount > 0)
);

-- Supply chain
CREATE TABLE inventory_snapshots (
  snapshot_date     date NOT NULL,
  warehouse_id      integer NOT NULL,
  product_id        integer NOT NULL,
  quantity_on_hand  integer NOT NULL CHECK (quantity_on_hand >= 0),
  quantity_on_order integer NOT NULL CHECK (quantity_on_order >= 0),
  PRIMARY KEY (snapshot_date, warehouse_id, product_id)
);
CREATE TABLE purchase_orders (
  purchase_order_id integer PRIMARY KEY,
  supplier_id       integer NOT NULL,
  warehouse_id      integer NOT NULL,
  ordered_on        date NOT NULL,
  expected_on       date NOT NULL,
  received_on       date,
  status            text NOT NULL CHECK (status IN ('open', 'received')),
  CHECK (expected_on >= ordered_on),
  CHECK ((status = 'received') = (received_on IS NOT NULL))
);
CREATE TABLE purchase_order_items (
  po_item_id        integer PRIMARY KEY,
  purchase_order_id integer NOT NULL,
  product_id        integer NOT NULL,
  quantity          integer NOT NULL CHECK (quantity > 0),
  unit_cost         numeric(10,2) NOT NULL CHECK (unit_cost > 0)
);

-- Marketing and service
CREATE TABLE campaigns (
  campaign_id integer PRIMARY KEY,
  name        text NOT NULL,
  channel     text NOT NULL CHECK (channel IN ('email', 'social', 'search', 'display')),
  starts_on   date NOT NULL,
  ends_on     date NOT NULL,
  budget      numeric(12,2) NOT NULL CHECK (budget > 0),
  CHECK (ends_on >= starts_on)
);
CREATE TABLE web_sessions (
  session_id    integer PRIMARY KEY,
  customer_id   integer,
  campaign_id   integer,
  started_at    timestamp NOT NULL,
  device        text NOT NULL CHECK (device IN ('desktop', 'mobile', 'tablet')),
  pages_viewed  integer NOT NULL CHECK (pages_viewed > 0),
  order_id      integer
);
CREATE TABLE support_tickets (
  ticket_id          integer PRIMARY KEY,
  customer_id        integer NOT NULL,
  order_id           integer,
  category           text NOT NULL CHECK (category IN ('delivery', 'product_issue', 'return', 'billing', 'account')),
  priority           text NOT NULL CHECK (priority IN ('low', 'medium', 'high')),
  opened_at          timestamp NOT NULL,
  closed_at          timestamp,
  satisfaction_score integer CHECK (satisfaction_score BETWEEN 1 AND 5),
  CHECK (closed_at IS NULL OR closed_at >= opened_at)
);

-- People
CREATE TABLE departments (
  department_id integer PRIMARY KEY,
  name          text NOT NULL UNIQUE
);
CREATE TABLE employees (
  employee_id   integer PRIMARY KEY,
  first_name    text NOT NULL,
  last_name     text NOT NULL,
  email         text NOT NULL UNIQUE,
  department_id integer NOT NULL,
  store_id      integer,
  manager_id    integer,
  job_title     text NOT NULL,
  hired_on      date NOT NULL,
  salary        numeric(10,2) NOT NULL CHECK (salary > 0)
);
