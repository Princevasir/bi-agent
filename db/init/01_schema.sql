CREATE TABLE regions (id INT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE orders (
  id INT PRIMARY KEY,
  order_date DATE NOT NULL,
  region_id INT NOT NULL REFERENCES regions(id),
  status TEXT NOT NULL,
  amount NUMERIC(12,2) NOT NULL
);
CREATE TABLE internal_notes (id INT PRIMARY KEY, note TEXT NOT NULL);