+++
id = "dq-dataset-ownership"
type = "data_quality"
title = "Dataset ownership and refresh"
domain = "Company"
owner = "Data Governance"
source = "Data governance register DG-01"
version = 2
effective_date = 2025-01-01
status = "active"
access_groups = ["analyst", "limited"]
+++

# Dataset ownership and refresh

| Area | Owner | Refresh |
|---|---|---|
| Sales (orders, items, payments, shipments, returns, promotions) | Sales Analytics | Daily, overnight |
| Products, brands, categories, prices, suppliers | Merchandising | Daily |
| Customers and loyalty | Customer Insights | Daily |
| Stock and purchase orders | Supply Chain Planning | Weekly stock count on Monday; purchase orders daily |
| Web visits, campaigns, support tickets | Digital Marketing and Customer Service | Daily |
| Stores, warehouses, regions | Operations | When changed |
| Employees, departments | People team | Weekly |

Questions about a dataset go to its owner. The actual time of the last load is in the operational systems, not in this document.
