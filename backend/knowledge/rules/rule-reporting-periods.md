+++
id = "rule-reporting-periods"
type = "rule"
title = "Reporting periods"
domain = "Sales"
owner = "Sales Analytics"
source = "Sales Analytics handbook, section 4"
version = 1
effective_date = 2024-01-01
status = "active"
access_groups = ["analyst"]
tables = ["orders"]
+++

# Reporting periods

- Months are calendar months; weeks start on Monday (ISO weeks), matching the Monday stock snapshots.
- Date filters use half-open ranges: `>= first day AND < first day of the next period`.
- "Last month" and "this year" are relative to today's date; the data ends on 30 September 2026, so later periods are empty rather than zero.
- Compare a partial period only with the same part of the earlier period (for example January to September with January to September).
