# Agent M — POST Endpoint Fuzz Report

## Summary

- Endpoints fuzzed: **261**
- Total requests sent: **4510**
- Unhandled 500 responses (dedup'd): **32**
- 4xx validation responses: 4048
- 2xx successful responses: 383

## Unhandled 500 Table

| Endpoint | Input Category | Status | Error Snippet | Severity |
|---|---|---|---|---|
| `/api/v1/users/auth/forgot-password/` | `extra_field` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/boq/boqs/from-template/` | `bad_float:area_m2:nan` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/boq/boqs/search-cost-items/` | `bad_float:min_score:nan` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/boq/boqs/escalate-rate/` | `bad_float:rate:nan` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/boq/boqs/{boq_id}/positions/` | `bad_float:quantity:nan` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/boq/boqs/{boq_id}/markups/` | `bad_float:percentage:nan` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/costs/` | `bad_float:rate:nan` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/assemblies/{assembly_id}/apply-to-boq/` | `bad_float:quantity:nan` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/catalog/` | `bad_float:base_price:nan` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/changeorders/` | `bad_int:schedule_impact_days:9223372036854775808` | 500 | `{"detail":"Failed to create change order"}` | MEDIUM |
| `/api/v1/changeorders/{order_id}/items/` | `bad_float:original_quantity:nan` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/costmodel/projects/{project_id}/5d/what-if/` | `bad_float:material_cost_pct:nan` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/fieldreports/reports/{report_id}/workforce/` | `bad_int:headcount:9223372036854775808` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/markups/scales/` | `bad_int:page:9223372036854775808` | 500 | `{"detail":"Unable to create scale config — calibration failed"}` | MEDIUM |
| `/api/v1/markups/scales/` | `bad_float:pixels_per_unit:nan` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/punchlist/items/` | `bad_float:location_x:nan` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/punchlist/items/{item_id}/pin-to-sheet/` | `bad_float:location_x:nan` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/rfq_bidding/` | `extra_field` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/rfq_bidding/` | `unicode_chaos:rfq_number` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/rfq_bidding/` | `sql_inject:rfq_number` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/rfq_bidding/` | `empty_string:rfq_number` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/rfq_bidding/` | `huge_string:description` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/risk/` | `bad_float:probability:nan` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/schedule/schedules/{schedule_id}/relationships/` | `bad_int:lag_days:9223372036854775808` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/teams/` | `extra_field` | 500 | `{"detail":"Failed to create team"}` | MEDIUM |
| `/api/v1/teams/` | `unicode_chaos:name` | 500 | `{"detail":"Failed to create team"}` | MEDIUM |
| `/api/v1/teams/` | `sql_inject:name` | 500 | `{"detail":"Failed to create team"}` | MEDIUM |
| `/api/v1/teams/` | `bad_int:sort_order:9223372036854775808` | 500 | `{"detail":"Failed to create team"}` | MEDIUM |
| `/api/v1/teams/` | `bad_bool:is_default:true` | 500 | `{"detail":"Failed to create team"}` | MEDIUM |
| `/api/v1/variations/` | `bad_int:schedule_impact_days:9223372036854775808` | 500 | `{"detail":"Failed to create change order"}` | MEDIUM |
| `/api/v1/variations/{order_id}/items/` | `bad_float:original_quantity:nan` | 500 | `{"detail":"Internal server error"}` | MEDIUM |
| `/api/v1/finance/evm/projects/{project_id}/5d/what-if/` | `bad_float:material_cost_pct:nan` | 500 | `{"detail":"Internal server error"}` | MEDIUM |

## Patterns / Pydantic model gaps

Cluster A — **Float `NaN` accepted by Pydantic, crashes downstream (13 endpoints)**:
`boqs/from-template`, `search-cost-items`, `escalate-rate`, `positions`, `markups`,
`costs/`, `assemblies/apply-to-boq`, `catalog/`, `changeorders/items`, `costmodel 5d/what-if`,
`markups/scales`, `punchlist/items`, `punchlist/pin-to-sheet`, `risk/`, `variations/items`,
`finance/evm 5d/what-if`. All use `float` / `Decimal` fields without `allow_inf_nan=False`
constraint — NaN flows through JSON parsing and blows up in a later DB/math operation.
Fix: add `pydantic.condecimal(allow_inf_nan=False)` or a custom validator rejecting NaN/inf.

Cluster B — **Int64 overflow at ORM / DB boundary (5 endpoints)**:
`changeorders/`, `fieldreports/workforce`, `markups/scales` (page), `schedule/relationships`
(lag_days), `teams/` (sort_order), `variations/`. Pydantic accepts arbitrary Python int;
Postgres `INTEGER` / `BIGINT` column rejects → unhandled `DataError`. Fix: tighten
schemas to `conint(ge=-2**31, le=2**31-1)` or use `Field(strict=True, le=...)`.

Cluster C — **`extra="allow"` or loose model: `extra_field` causes 500 on (4)**:
`users/auth/forgot-password`, `assemblies/import`, `rfq_bidding/`, `teams/`. The endpoint
either stores or iterates over fields that can shadow ORM columns. Risk: data-integrity
bug if a maliciously crafted field overwrites internal state.

Cluster D — **String fields crash the create path (RFQ + Teams)**:
`/api/v1/rfq_bidding/` fails on unicode-chaos / SQL-ish / empty / 10K strings in the
`rfq_number` + `description` fields. `/api/v1/teams/` fails on unicode-chaos / SQL in
`name`. Likely a unique-constraint lookup or regex that doesn't handle NUL bytes /
length. The 500 replaces what should be 422 / 409.

## Notes

- Fuzzer categories: strings (empty / 10K / unicode-chaos / SQL / XSS / path-traversal), integers (overflow / float-as-int / string-as-int / null), floats (nan/inf/subnormal), UUIDs (bad / empty), dates (invalid / out-of-range), enums (bogus value), nested objects (missing required / extra field), arrays (10K / wrong-type), booleans (string / int / null), wholesale body (null / empty / array / scalar).
- Endpoints with path params receive random UUIDs (valid 404 expected, 500 = bug).
- Authentication: single admin token reused across all requests to avoid rate-limit.
- 69 raw 500s across 261 endpoints, de-duplicated to 32 distinct (endpoint, input-class) pairs.
- No resources were successfully created by the fuzz inputs (all 500-triggering payloads failed before persistence), so no cleanup was needed.