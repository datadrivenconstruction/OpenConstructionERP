# Migration guide - OpenConstructionERP v4.5 -> v4.6

> **This is a historical note for one version pair, not the current deployment
> procedure.** It describes the product as it stood at v4.6.0 and it is kept
> because that upgrade path is still a fair record of what those two releases
> needed. Three things it says were true then and are not true now, and each of
> them will break an installation if carried forward:
>
> - It installs a wheel over the deployment with `pip install --upgrade`. A
>   deployment that runs from a git checkout, which is how ours runs, is
>   overwritten by that command.
> - It runs `alembic -c backend/alembic.ini upgrade head`. The schema moves at
>   boot now, through the automatic migration pass plus `create_all`, and
>   running alembic by hand against a populated database sets a revision the
>   boot path does not expect.
> - It assumes SQLite at `data/openestimate.db`. Production has been
>   PostgreSQL since August 2026, so the backup command here backs up nothing.
>
> `alembic_head_matches: false` in `/api/health` is also not a fault on the
> boot-heal path, and the checklist at the end of this file reads it as one.
> Do not roll back a healthy deployment on the strength of that line.

Covers v4.5.0 -> v4.6.0. No breaking API changes; two new alembic revisions; one new
required-default column on `accommodation_bookings`; one new optional `UserPreference`
key (dashboard layout) that auto-migrates from `localStorage`.

If you are on v4.4.x or earlier, run the v4.4->v4.5 migration first, then this one.

---

## Pre-flight

1. **Pin the release**

   ```
   v4.6.0  →  tag v4.6.0   →  commit 3429414a
   alembic head: v3121_geo_raster_overlay
   ```

2. **Back up the database**

   ```bash
   # VPS / SQLite production layout
   sqlite3 /root/OpenConstructionERP/data/openestimate.db ".backup '/root/backups/oe-pre-v4.6.0.db'"
   ```

   For PostgreSQL deployments use `pg_dump --format=c` to a clock-stamped path.

3. **Confirm prior head**

   ```bash
   DATABASE_SYNC_URL=sqlite:////root/OpenConstructionERP/data/openestimate.db \
     alembic -c backend/alembic.ini current
   # expect: v3119_propdev_complete_clickflow  (the v4.5.0 head)
   ```

   If `alembic current` reports anything other than `v3119_*`, finish the older
   migration chain first; v3120 stacks on top of v3119.

4. **Snapshot the frontend bundle** (only needed if you intend to revert)

   ```bash
   cp -r backend/app/_frontend_dist /root/backups/_frontend_dist.v4.5.0
   ```

---

## Upgrade steps

### 1. Stop the API

```bash
systemctl stop openconstructionerp
```

(Or `docker compose down api` for Compose deployments.)

### 2. Fetch and install the new wheel

```bash
# Pip-from-PyPI path (when published)
/root/OpenConstructionERP/venv/bin/pip install --upgrade openconstructionerp==4.6.0

# Or — if PyPI lag — scp the prebuilt wheel and install locally
scp dist/openconstructionerp-4.6.0-py3-none-any.whl root@<host>:/tmp/
ssh root@<host> '/root/OpenConstructionERP/venv/bin/pip install --upgrade /tmp/openconstructionerp-4.6.0-py3-none-any.whl'
```

### 3. Sync the frontend bundle

Backend source shadows the wheel-shipped bundle (see
`feedback_vps_wheel_shadowed`). Copy the wheel's bundle into the source tree:

```bash
SITE=$(/root/OpenConstructionERP/venv/bin/python -c 'import openconstructionerp, os; print(os.path.dirname(openconstructionerp.__file__))')
rm -rf /root/OpenConstructionERP/backend/app/_frontend_dist
cp -r "$SITE/_frontend_dist" /root/OpenConstructionERP/backend/app/_frontend_dist
```

### 4. Run alembic

```bash
DATABASE_SYNC_URL=sqlite:////root/OpenConstructionERP/data/openestimate.db \
  alembic -c backend/alembic.ini upgrade head
# applies:  v3120_accommodation_init
#           v3121_geo_raster_overlay
```

What each revision does:

| Revision | Adds | Notes |
|----------|------|-------|
| `v3120_accommodation_init` | `accommodations`, `accommodation_rooms`, `accommodation_bookings`, `accommodation_charges` | All money columns are `NUMERIC(18,4)` with `server_default='0'` — fresh-install safe (per `v4.4.1` lesson). FKs use `ON DELETE CASCADE` to `projects`. |
| `v3121_geo_raster_overlay` | `geo_overlays` | Stores PDF/image refs, four corner lat/lon, crop polygon (JSON), `z_order`, `opacity`. FK to `projects` with `ON DELETE CASCADE`. |

### 5. Start the API

```bash
systemctl start openconstructionerp
# boot is ~3 min on a 2 GB VPS (111 modules + validation rules + demo-seed gate + Qdrant probe)
```

### 6. Verify

```bash
curl -s https://<host>/api/health | python -m json.tool
# expect:
#   "version": "4.6.0"
#   "modules_loaded": 111
#   "alembic_head_matches": true
#   "frontend_dist_present": true
```

Spot-check the four new surfaces (any authenticated session token works):

```bash
TOKEN=...   # acquire via /api/v1/users/auth/demo-login/  body {"email":"demo@openconstructionerp.com"}

# 1. Accommodation (list mine)
curl -s -H "Authorization: Bearer $TOKEN" https://<host>/api/v1/accommodation/

# 2. Geo raster overlays (422 expected on bare list — needs project_id)
curl -s -H "Authorization: Bearer $TOKEN" "https://<host>/api/v1/geo-hub/raster-overlays/?project_id=00000000-0000-0000-0000-000000000000"

# 3. Floating chat (chat list — confirms erp_chat router mounted)
curl -s -H "Authorization: Bearer $TOKEN" https://<host>/api/v1/erp-chat/sessions/

# 4. Dashboard layout (per-user preference)
curl -s -H "Authorization: Bearer $TOKEN" https://<host>/api/v1/users/me/dashboard-layout/
```

Open the SPA, sign in as the demo user, and:

- Confirm the **floating chat pill** appears bottom-right on the dashboard (it
  is hidden on `/chat`, `/login`, `/onboarding`).
- If no LLM provider key is configured the pill shows a **"Configure AI"**
  banner that deep-links to `/settings/ai`. Either supply
  `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` in the environment or add a key in
  the UI.
- Sidebar shows **Accommodation** under the Field Ops group.
- Dashboard customizer (gear icon) lists **10 new widgets** under "Add widget".
- Geo Hub now has a **"Drape overlay"** action in the project context menu.

---

## New surface — what changed for integrators

### `/api/v1/accommodation/` (new)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` / `POST` | `/` | List / create accommodations |
| `GET` / `PATCH` / `DELETE` | `/{id}` | Retrieve / update / delete |
| `POST` | `/{id}/rooms/` | Add a room |
| `POST` | `/{id}/rooms/bulk/` | Add rooms in bulk |
| `PATCH` / `DELETE` | `/rooms/{id}` | Update / delete a room |
| `POST` | `/rooms/{id}/bookings/` | Reserve a room |
| `GET` | `/bookings/?status[]=&from=&to=&project_id=` | Booking search with date-overlap filter |
| `PATCH` | `/bookings/{id}` | Update / transition booking state |
| `POST` | `/bookings/{id}/check-in` / `/check-out` / `/cancel` | State-machine shortcuts |
| `POST` | `/bookings/{id}/charges/` | Add a charge to a booking |
| `POST` | `/from-propdev/{plot_id}` | Bootstrap rooms from a PropDev block |
| `POST` | `/hr-autobook/suggest` | Suggest a worker-camp room for an employee |

All money fields are Decimal-as-string in JSON. IDOR returns **404, never 403**
(no info leak). State machine: `reserved → checked_in → checked_out`; any
non-final state can transition to `cancelled`; final states are locked.

### `/api/v1/geo-hub/raster-overlays/` (new)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/?project_id=…` | List overlays for a project |
| `POST` | `/?project_id=…` | Create an overlay (multipart: image + corners JSON) |
| `GET` | `/{id}` | Retrieve |
| `GET` | `/{id}/image` | Raster bytes |
| `PATCH` | `/{id}` | Update corners / crop polygon / opacity / z_order |
| `DELETE` | `/{id}` | Delete |
| `POST` | `/from-pdf/{document_id}?page=1` | Rasterise a PDF page into an overlay |

Magic-byte validated; PDF goes through PyMuPDF. Frontend cuts a polygon crop
mask in Cesium via `ClippingPolygonCollection`.

### `/api/v1/users/me/dashboard-layout/` (new)

Mirrors the existing `/me/sidebar-preferences/` shape. Body:

```json
{ "widgets": ["boq_summary", "validation_score", ...], "columns": 12 }
```

The first time a user opens the dashboard after the upgrade, the existing
`localStorage` layout is read and immediately `PUT` to the server, then
removed locally. Subsequent loads come from the server only.

### `/api/v1/erp-chat/sessions/` (unchanged) + new tool surface

The floating chat reuses the existing `erp_chat` SSE backend. v4.6.0 expands
the registered tool set to **17 tools** (`backend/app/modules/erp_chat/tools.py`).
No client changes required — the tool registry is server-driven.

---

## Configuration

No new mandatory environment variables. Optional knobs:

| Variable | Default | Purpose |
|----------|---------|---------|
| `ACCOMMODATION_DEFAULT_CHECKIN_TIME` | `15:00` | Used by HR autobook when caller omits explicit times. |
| `GEO_RASTER_MAX_BYTES` | `25 * 1024 * 1024` | Per-overlay upload cap. |
| `CHAT_FLOATING_HIDDEN_ROUTES` | `/chat,/login,/onboarding` | CSV of route prefixes where the FAB is hidden. |

If you previously hid the floating chat by editing `AppLayout`, remove that
patch — the FAB is now feature-gated on the routes above.

---

## Rollback

The two new revisions are **forward-only-safe but not auto-reversible** in
SQLite (no native `DROP CONSTRAINT`). To roll back to v4.5.0:

1. Stop the API.
2. Restore the database backup from step 0 of "Pre-flight".
3. Reinstall v4.5.0:

   ```bash
   /root/OpenConstructionERP/venv/bin/pip install --upgrade openconstructionerp==4.5.0
   ```

4. Restore the previous frontend bundle:

   ```bash
   rm -rf /root/OpenConstructionERP/backend/app/_frontend_dist
   cp -r /root/backups/_frontend_dist.v4.5.0 /root/OpenConstructionERP/backend/app/_frontend_dist
   ```

5. Start the API and confirm `/api/health` reports `4.5.0`.

Do **not** attempt to `alembic downgrade` past `v3120` on SQLite — drop the
DB and restore from backup instead. PostgreSQL deployments may
`alembic downgrade v3119` cleanly.

---

## Known traps

- **VPS DB path needs four slashes**: `sqlite:////root/...` — see
  `feedback_alembic_wrong_db`. The CLI silently writes to `./openestimate.db`
  in the current working directory otherwise, and you will get a confusing
  "alembic head mismatch" on next boot.
- **`_frontend_dist` shadow**: if `/api/health` reports `frontend_dist_present: true`
  but the SPA still loads the old chunks, you skipped step 3. The wheel ships
  the bundle inside the installed package; the source tree wins at runtime.
- **Boot time**: 111 modules + Qdrant ping + demo-seed gate makes startup take
  2–3 minutes before `:9090` binds. Give systemd at least 4 minutes before
  declaring failure.
- **Tag rejection on `git push --tags`**: older `v2.9.x` tags on this repo
  conflict with newer history. Push the v4.6.0 tag explicitly:
  `git push origin v4.6.0`.

---

## Verification checklist

- [ ] `/api/health` → `version: "4.6.0"`, `modules_loaded: 111`, `alembic_head_matches: true`
- [ ] `alembic current` → `v3121_geo_raster_overlay`
- [ ] Sidebar lists **Accommodation** under Field Ops
- [ ] Floating chat pill visible on `/` dashboard
- [ ] Dashboard customizer offers the 10 new widgets
- [ ] Geo Hub project menu has "Drape overlay"
- [ ] Pre-existing v4.5 surface still passes regression (BIM walk, PropDev clickflow, BOQ section add)

Reach us at `info@datadrivenconstruction.io` if a step blocks the upgrade.
