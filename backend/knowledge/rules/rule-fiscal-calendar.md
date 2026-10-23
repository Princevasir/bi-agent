+++
id = "rule-fiscal-calendar"
type = "rule"
title = "Fiscal calendar"
domain = "Finance"
owner = "Finance"
source = "Finance calendar policy FIN-01"
version = 1
effective_date = 2024-02-01
status = "active"
access_groups = ["analyst", "limited"]
tables = []
+++

# Fiscal calendar

**The fiscal year starts on 1 February and is named after the calendar year it starts in.**

- **FY2025 runs from 1 February 2025 to 31 January 2026.** FY2024 runs from 1 February 2024 to 31 January 2025.
- Fiscal quarters: FQ1 February to April, FQ2 May to July, FQ3 August to October, FQ4 November to January.
- "This year", "year to date" and "Q1" mean calendar periods unless the question says *fiscal*.
- In SQL: fiscal year = `EXTRACT(YEAR FROM date)` when the month is February or later, otherwise the year minus one.
