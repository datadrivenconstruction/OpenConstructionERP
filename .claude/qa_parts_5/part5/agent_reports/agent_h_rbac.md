# Agent H — RBAC Matrix Audit Report

- Server: `http://127.0.0.1:8080`
- Endpoints probed (state-changing, non-multipart): **421**
- Skipped (multipart uploads): **25**
- Privilege-escalation findings: **4**  (by severity: {'high': 4})
- Unauth 2xx leaks: **1**
- Admin anomalies (401/403): **0**

## Role summary

| Role | allowed(2xx) | forbidden(403) | unauth(401) | validation(4xx) | not_found(404) | 5xx |
|------|--------------|----------------|-------------|-----------------|----------------|-----|
| none | 1 | 0 | 415 | 5 | 0 | 0 |
| estimator | 19 | 62 | 0 | 166 | 174 | 0 |
| manager | 23 | 15 | 0 | 170 | 213 | 0 |
| admin | 27 | 0 | 0 | 175 | 219 | 0 |

## Privilege escalation findings

| Method | Path | Estimator | Manager | Admin | Severity |
|--------|------|-----------|---------|-------|----------|
| DELETE | `/api/demo/clear-all` | 200/allowed | 200/allowed | 200/allowed | high |
| DELETE | `/api/v1/collaboration_locks/{lock_id}/` | 204/allowed | 204/allowed | 204/allowed | high |
| DELETE | `/api/v1/costs/actions/clear-database/` | 200/allowed | 200/allowed | 200/allowed | high |
| DELETE | `/api/v1/schedule/relationships/{relationship_id}` | 204/allowed | 204/allowed | 204/allowed | high |

## Unauth leaks (2xx without token)

| Method | Path | Status |
|--------|------|--------|
| POST | `/api/v1/feedback` | 200 |

## Admin anomalies (401 or 403 with admin token)

_None — admin authorised on all state-changing endpoints._

## Notes

- Status classes: `allowed`=2xx, `forbidden`=403, `unauth`=401, `passed_auth_validation_fail`=400/409/415/422, `not_found`=404.
- For severity scoring: `high` = estimator DELETE or POST/PATCH on `/users/`, `/admin/`, `/settings/`, or on `/audit/`/`baseline` paths.
- Validation failures (422/400) are treated as auth-passing for the purposes of privilege analysis — they mean the role was allowed through the auth layer.
- Full matrix JSON: `agent_h_rbac_matrix.json`.