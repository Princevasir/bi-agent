-- Read access per login, applied after every load (the tables are recreated each time).
-- Column-level grants keep personal data and salaries away from analysts:
-- the database itself refuses those columns, whatever SQL is sent.

-- Manager: everything.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO retail_manager;

-- Analyst: every table, but only non-personal columns of customers, addresses and employees.
GRANT SELECT ON
  regions, countries, stores, warehouses,
  categories, brands, suppliers, products, product_prices, product_suppliers,
  loyalty_tiers, loyalty_memberships,
  promotions, orders, order_items, order_promotions, payments, shipments, returns,
  inventory_snapshots, purchase_orders, purchase_order_items,
  campaigns, web_sessions, support_tickets, departments
  TO retail_analyst;
GRANT SELECT (customer_id, birth_year, country_id, signup_date, acquisition_channel, marketing_opt_in)
  ON customers TO retail_analyst;
GRANT SELECT (address_id, customer_id, address_type, city, country_id, is_default)
  ON customer_addresses TO retail_analyst;
GRANT SELECT (employee_id, department_id, store_id, manager_id, job_title, hired_on)
  ON employees TO retail_analyst;

-- Limited: geography and the product catalogue, no sales or people.
GRANT SELECT ON
  regions, countries, stores, warehouses, categories, brands, products, product_prices
  TO retail_limited;
