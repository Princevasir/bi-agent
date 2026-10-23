+++
id = "sql-fiscal-year-revenue"
type = "sql_example"
title = "Revenue by fiscal year"
domain = "Finance"
owner = "Finance"
source = "Validated by Sales Analytics, Oct 2026"
version = 1
effective_date = 2026-10-01
status = "active"
access_groups = ["analyst"]
tables = ["orders", "order_items"]
question = "What was revenue in FY2024 and FY2025?"
result_columns = ["fiscal_year", "revenue"]
assumptions = ["Fiscal year starts 1 February, named by its start year"]
sql = '''
SELECT CASE WHEN EXTRACT(MONTH FROM o.ordered_at) >= 2 THEN EXTRACT(YEAR FROM o.ordered_at)
            ELSE EXTRACT(YEAR FROM o.ordered_at) - 1 END AS fiscal_year,
       SUM(oi.line_total) AS revenue
FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'completed' AND o.ordered_at >= '2024-02-01' AND o.ordered_at < '2026-02-01'
GROUP BY 1 ORDER BY 1
'''
+++

Implements the *Fiscal calendar* rule. FY2025 is 1 February 2025 to 31 January 2026.
