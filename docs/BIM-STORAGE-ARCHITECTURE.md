# BIM Storage Architecture

**Status**: Design + initial implementation in v1.3.24
**Owner**: Core team
**Last updated**: 2026-04-11

## Goals

A construction-cost ERP has to handle BIM projects of every size:

| Project tier  | Element count   | Geometry size | Today's pain                              |
|---------------|-----------------|---------------|-------------------------------------------|
| Renovation    | 200 – 5 000     | 5 – 50 MB     | Already fast, no work needed              |
| Mid-rise      | 5 000 – 30 000  | 50 – 300 MB   | Per-mesh viewer hits 6 fps at 20 k        |
| Large-scale   | 30 000 – 100 k+ | 300 MB – 2 GB | Local FS bloat, no dedup, no streaming    |
| Megaproject   | 100 k+          | 2 GB+         | Currently impossible — single HTTP fetch  |

The architecture below is the plan to handle all four tiers cleanly.

## Three layers, one data flow

```
┌──────────────┐  bytes  ┌─────────────────┐  rows  ┌───────────────┐
│ Storage      │ ──────► │ Database        │ ─────► │ Cross-module  │
│ Backend      │         │ Tables          │        │ Links         │
│              │         │                 │        │               │
│ Local FS │ S3│         │ bim_model       │        │ bim_boq_link  │
│              │         │ bim_element     │        │ schedule.bim_ │
│ + dedup      │         │ bim_element_grp │        │  element_ids  │
│ + compress   │         │ bim_quantity_map│        │ validation… │
│ + presigned  │         │                 │        │               │
└──────────────┘         └─────────────────┘        └───────────────┘
```

### Layer 1 — Storage Backend (binary blobs)

The big files (`geometry.dae`, `original.rvt`, `original.xlsx`) live behind a
pluggable backend abstraction in `app/core/storage.py`:

```python
class StorageBackend(ABC):
    async def put(self, key: str, content: bytes) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def exists(self, key: str) -> bool: ...
    async def delete(self, key: str) -> None: ...
    async def delete_prefix(self, prefix: str) -> int: ...
    async def size(self, key: str) -> int: ...
    async def open_stream(self, key: str) -> AsyncIterator[bytes]: ...
    def url_for(self, key: str, *, expires_in: int = 3600) -> str | None: ...
```

Two implementations ship in v1.3.24:

- **`LocalStorageBackend(base_dir)`** — default. Writes to `data/bim/{project_id}/{model_id}/…`
  with the same path layout as today. `url_for()` returns `None` so the FastAPI
  route falls back to streaming.
- **`S3StorageBackend(endpoint, …)`** — opt-in. Uses `aioboto3` (an *optional*
  dependency under the `[s3]` extras). `url_for()` returns a presigned GET URL
  so clients fetch directly from the bucket — no proxying through FastAPI.

Selected via the new `STORAGE_BACKEND=local|s3` env var. The S3 fields
(`S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION`)
already exist in `app/config.py` and now actually get used.

A small helper script `backend/scripts/migrate_bim_to_s3.py` walks the local
`data/bim/` tree and uploads every file to the configured bucket — one-time
migration for existing deployments.

### Layer 2 — Database Tables

| Table                     | Purpose                                              | New?      |
|---------------------------|------------------------------------------------------|-----------|
| `oe_bim_model`            | One row per uploaded BIM model                       | existing  |
| `oe_bim_element`          | One row per element with JSON properties + quantities| existing  |
| `oe_bim_boq_link`         | Per-element link to a BOQ position                   | existing  |
| `oe_bim_quantity_map`     | Rule-based bulk linking definition                   | existing  |
| `oe_bim_model_diff`       | Per-version geometry diff                            | existing  |
| **`oe_bim_element_group`**| **Saved selections / named groups**                  | **v1.3.24**|

### Layer 3 — Cross-module links

Today every consuming module has its own column shape:

- BOQ Position has `cad_element_ids: list[str]` (JSON column on the position)
  AND a real link table `oe_bim_boq_link` (the canonical truth, kept in sync).
- Schedule Activity has `bim_element_ids: dict | None` (JSON column).
- Validation, Costs, Takeoff, Documents currently have nothing.

In the next iteration this gets unified behind `oe_bim_link` — a single thin
link table with `(target_module, target_id, bim_element_id | bim_group_id, link_type)`
that any module can use. v1.3.24 keeps the existing per-module shapes for
backwards compatibility; the unification is a follow-up.

## Element Groups — the saved-selection layer

The biggest workflow gap today: a user filters down to "all walls on Level 1"
in the viewer, gets the perfect subset, then has no way to **save it**. Next
time they open the model they have to redo every chip click.

`oe_bim_element_group` fixes this:

```sql
CREATE TABLE oe_bim_element_group (
    id              UUID PRIMARY KEY,
    project_id      UUID NOT NULL,                 -- always project-scoped
    model_id        UUID,                          -- nullable: null = all models
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    is_dynamic      BOOLEAN NOT NULL DEFAULT TRUE, -- recompute on read?
    filter_criteria JSON NOT NULL DEFAULT '{}',    -- predicate
    element_ids     JSON NOT NULL DEFAULT '[]',    -- materialised cache
    element_count   INTEGER NOT NULL DEFAULT 0,    -- cached count
    color           VARCHAR(20),                   -- UI accent
    created_by      UUID,
    metadata        JSON NOT NULL DEFAULT '{}',
    created_at      TIMESTAMP NOT NULL,
    updated_at      TIMESTAMP NOT NULL,
    UNIQUE (project_id, name)
);
```

### Two flavours per group

- **Dynamic** (`is_dynamic=true`, default) — `filter_criteria` is the source
  of truth; `element_ids` is a cache that gets refreshed whenever the group
  is read or whenever the underlying model changes. Best for rule-based
  selections like "every Wall on Level 1" — auto-updates when the model
  is re-imported with a new revision.
- **Static** (`is_dynamic=false`) — `element_ids` is the source of truth and
  the filter is just metadata. Best for hand-curated selections like
  "the 47 walls the architect flagged for thermal audit".

### `filter_criteria` shape

```json
{
  "element_type": ["Wall", "Slab"],                  // string OR list
  "category":     "Architectural Walls",             // string OR list
  "discipline":   "architecture",                    // string OR list
  "storey":       ["01 - Entry Level"],              // string OR list
  "name_contains": "fire-rated",                     // ILIKE
  "property_filter": {                               // JSON property match
    "material": "Concrete",
    "thickness_mm": "240"
  }
}
```

`resolve_element_group_members()` runs the predicate against
`oe_bim_element` rows and returns the resulting UUID list. On PostgreSQL
the property filter uses the JSON containment operator (`properties @> :json`);
on SQLite it falls back to a Python-side filter (load all elements, filter
in memory) since SQLite doesn't have JSONB.

## How the layers talk to each other

### Read path: render the viewer

```
Frontend     →  GET /api/v1/bim_hub/{model_id}/elements/?limit=50000
FastAPI      →  fetch rows from oe_bim_element + eager-load oe_bim_boq_link briefs
Storage      →  (not touched on the read path; element rows are in the DB)
Frontend     →  GET /api/v1/bim_hub/models/{id}/geometry
FastAPI      →  storage_backend.open_stream("bim/{p}/{m}/geometry.dae")
                OR redirect to storage_backend.url_for(...) on S3
```

### Write path: upload a model

```
Frontend     →  POST /api/v1/bim_hub/upload-cad/  (multipart, RVT)
FastAPI      →  storage.put("bim/{p}/{m}/original.rvt", content)
                INSERT oe_bim_model (status="processing")
Background   →  Convert RVT → canonical → COLLADA + parquet
                storage.put("bim/{p}/{m}/geometry.dae", dae)
                BULK INSERT oe_bim_element (...)
                UPDATE oe_bim_model SET status="ready", element_count=N
```

### Group save

```
Frontend     →  POST /api/v1/bim_hub/element-groups/?project_id=…
                  body: { name, model_id, filter_criteria, is_dynamic: true }
FastAPI      →  resolve_element_group_members(filter_criteria) → list of UUIDs
                INSERT oe_bim_element_group (element_ids=cache, element_count=N)
                return BIMElementGroupResponse
```

### Group → BOQ link (the bulk-takeoff path)

```
Frontend     →  POST /api/v1/bim_hub/element-groups/{group_id}/link-to-boq/
                  body: { boq_position_id }
FastAPI      →  resolve members (re-runs filter if dynamic)
                For each element_id:
                  INSERT oe_bim_boq_link (idempotent on (position, element))
                  Append to oe_boq_position.cad_element_ids
                Return { links_created: N }
```

This is the rule-based bulk takeoff workflow — the same shape as
`apply_quantity_maps` but driven by an **explicit named group** instead of an
abstract pattern.

## Performance for big models

### What works today (per-mesh path)

The viewer renders one `THREE.Mesh` per BIM element. Empirical numbers from
the headless test (`frontend/debug-bim.cjs` TEST 9) on real GPU:

| Mesh count | FPS | Status                             |
|------------|-----|------------------------------------|
| 5 440      | 60  | Demo model — smooth                |
| 21 760     | 6   | 4× cloned demo — drops below usable|

### What v1.3.23 added (gated)

`ElementManager.batchMeshesByMaterial()` collapses same-material meshes into
one `THREE.BatchedMesh` per material — typically dropping draw calls from
5 440 → ~30 (98 % reduction). It's gated behind a 50 000-mesh threshold
because `BatchedMesh.setVisibleAt` has GPU-sync issues that cause partial
renders during rapid filter changes.

### What v1.3.24 will add

The proper fix is to **pre-bake** the BatchedMesh on the **backend side** as
part of the canonical-format conversion pipeline:

1. Backend conversion (`services/cad-converter`) groups elements by material
   and writes a `geometry.batched.glb` alongside the per-element `geometry.dae`.
2. Frontend prefers the batched glb when available, falls back to the dae.
3. Per-instance visibility comes from the element_id ↔ instance_id table
   shipped alongside the glb (`geometry.batched.json`).

This avoids the runtime visibility-sync problem entirely because the
mapping is computed once at convert time, not on every filter change.

### What v1.3.24 also adds — async element fetch + virtualisation

The current `fetchBIMElements(modelId, limit=50000)` returns the entire
element list in one HTTP request. For 100 k+ element models this is a
50 MB JSON parse. v1.3.24 will:

1. Add `GET /elements/?limit=…&offset=…&fields=id,storey,element_type,category`
   so the viewer can fetch a **lightweight projection** (no properties / quantities)
   for the initial filter pass — typically 5 MB instead of 50 MB.
2. Add `POST /elements/lookup` for batch property lookups when the user
   actually clicks an element (returns full properties just for the clicked id).
3. The frontend's element explorer in `BIMFilterPanel` already caps render
   at 200 items per group; the lookup-on-click fetch fills in details
   only when needed.

## Storage scaling cheatsheet

| Backend       | Best for                   | Scaling cap                         |
|---------------|----------------------------|-------------------------------------|
| Local FS      | dev, single-tenant, < 50 GB| disk size                            |
| MinIO         | self-hosted, cloud-portable| infinite (cluster)                  |
| AWS S3        | managed, multi-region      | infinite                            |
| Backblaze B2  | cheap cold storage         | infinite, slower                    |
| DO Spaces     | mid-tier, integrated billing| infinite                           |

All four S3-compatible backends use the same `S3StorageBackend` — only the
`S3_ENDPOINT` env var changes.

## Migration path for existing deployments

```bash
# 1. Install the s3 extras
pip install "openconstructionerp[s3]"

# 2. Set storage backend in .env
STORAGE_BACKEND=s3
S3_ENDPOINT=https://s3.eu-central-1.amazonaws.com
S3_BUCKET=my-erp-bim-files
S3_ACCESS_KEY=AKIA…
S3_SECRET_KEY=…
S3_REGION=eu-central-1

# 3. Run the one-time migration
python -m backend.scripts.migrate_bim_to_s3

# 4. Restart the backend
systemctl restart openconstructionerp
```

After step 4, every existing model continues to load — the file paths in the
DB stay the same, only the storage backend changes underneath.

## Open questions / future work

- **Geometry deduplication** — many BIM models reuse identical wall/door/window
  geometries. Hashing the BufferGeometry vertex data and storing each unique
  geometry once would cut typical project storage by 30–70 %. Not in v1.3.24.
- **Differential storage** — when a model is re-uploaded with a new revision,
  store only the diff against the prior version. The `oe_bim_model_diff` table
  already tracks the deltas; storage layer could use that to dedup blobs.
- **`oe_bim_link` unification** — collapse the per-module link columns
  (`cad_element_ids`, `bim_element_ids`) into one table that any module
  references via `(target_module, target_id, bim_element_id)`. Backwards
  compatibility means keeping the old columns synced for at least one
  major version.
- **Cold-tier offload** — automatically move BIM files for archived projects
  to a cheaper S3 storage class after 90 days, with on-demand restore.
