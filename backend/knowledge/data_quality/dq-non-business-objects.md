+++
id = "dq-non-business-objects"
type = "data_quality"
title = "Objects that are not company data"
domain = "Company"
owner = "Data Governance"
source = "Data governance register DG-03"
version = 1
effective_date = 2026-10-01
status = "active"
access_groups = ["analyst", "limited"]
+++

# Objects that are not company data

- The small **`analytics`** database (12 orders, 3 regions) is a test fixture for the BI agent's automated tests. It is not Trailhead Outfitters data and must never be used for business answers.
- The **`internal_notes`** table in that database exists only to prove access controls work; no login used for analysis can read it.
- Columns flagged as personal data (names, email, phone, street address, postal code, salary) are hidden from analysts and limited users by the database itself.
