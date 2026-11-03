# Data feeds: connect Excel or Power BI

Data feeds are read-only flat tables over your projects, BOQ positions, invoices, purchase orders and schedule activities. You paste a URL into Excel, Power Query or any BI tool and refresh whenever you need new numbers. Nothing can be written back.

1. Open Settings, tab Data feeds.
2. Pick a project (or all your projects) and create a key with the `bi:read` scope. The key is shown once.
3. In Excel use Data > From Web and paste the CSV URL, or use the Power Query snippet on the page, which sends the key in the `X-API-Key` header.

Each feed is available as `.csv` (UTF-8 with BOM, opens correctly in Excel), `.parquet` and `.json`:

    /api/v1/bi-feed/feeds/<feed>.csv?project_id=<id>&updated_since=<ISO time>&limit=50000&offset=0

Feeds: `projects`, `boq_positions`, `invoices`, `purchase_orders`, `schedule_activities`. Money and quantities are exact decimals with a currency column; dates are ISO 8601 in UTC. Rows come in a stable order. For large feeds page with `limit` (at most 50000) and `offset`, or follow the `X-Next-After` header with `after=` to avoid repeats when rows are added meanwhile. A feed over 500000 rows must be paged.

You only ever see the projects you own or belong to. A key without `bi:read` is refused.

## SQL access (optional, PostgreSQL 15 or newer)

    openconstructionerp bi enable --single-tenant
    openconstructionerp bi status
    openconstructionerp bi disable

`bi enable` creates the schema `oe_bi` with one view per feed (same column names) and a read-only login role `oe_bi_reader`. The password is printed once and not stored. Use `--single-tenant` only when the instance serves one organisation. It is off by default.
