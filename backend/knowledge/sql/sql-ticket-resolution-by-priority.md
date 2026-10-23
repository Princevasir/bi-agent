+++
id = "sql-ticket-resolution-by-priority"
type = "sql_example"
title = "Ticket resolution time by priority"
domain = "Marketing and service"
owner = "Customer Service"
source = "Validated by Sales Analytics, Oct 2026"
version = 1
effective_date = 2026-10-01
status = "active"
access_groups = ["analyst"]
tables = ["support_tickets"]
question = "How quickly were support tickets closed in 2025, by priority?"
result_columns = ["priority", "avg_hours_to_close", "tickets"]
assumptions = ["Closed tickets only"]
sql = '''
SELECT t.priority, ROUND((AVG(EXTRACT(EPOCH FROM (t.closed_at - t.opened_at))) / 3600)::numeric, 1) AS avg_hours_to_close,
       COUNT(*) AS tickets
FROM support_tickets t
WHERE t.closed_at IS NOT NULL AND t.opened_at >= '2025-01-01' AND t.opened_at < '2026-01-01'
GROUP BY t.priority ORDER BY avg_hours_to_close
'''
+++

Compare the averages with the targets in *Customer service standards* (24 hours, 3 days, 5 days).
