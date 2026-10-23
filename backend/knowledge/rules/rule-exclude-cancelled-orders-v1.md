+++
id = "rule-exclude-cancelled-orders-v1"
type = "rule"
title = "Exclude cancelled and staff orders"
domain = "Sales"
owner = "Sales Analytics"
source = "Sales Analytics handbook, 2023 edition"
version = 1
effective_date = 2023-01-01
status = "superseded"
superseded_by = "rule-exclude-cancelled-orders"
access_groups = ["analyst"]
tables = ["orders"]
+++

# Exclude cancelled and staff orders (superseded)

Version 1 excluded cancelled orders **and** orders placed by staff accounts. Staff accounts were never flagged in the order data, so the second part could not be applied; version 2 keeps only the cancelled-order rule. Do not use this version.
