+++
id = "metric-ticket-resolution-time"
type = "metric"
title = "Ticket resolution time"
domain = "Marketing and service"
owner = "Customer Service"
source = "Customer Service metric guide"
version = 1
effective_date = 2025-01-01
status = "active"
access_groups = ["analyst"]
tables = ["support_tickets"]
metric = "ticket_resolution_time"
authoritative = true
+++

# Ticket resolution time

**Resolution time is the hours from opening a support ticket to closing it**: `closed_at - opened_at`, for closed tickets only. Report it per priority and compare with the targets in *Customer service standards*. Open tickets are counted separately, never as zero.
