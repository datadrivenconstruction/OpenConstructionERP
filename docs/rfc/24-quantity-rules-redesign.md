# RFC 24 — Quantity Rules redesign (BETA)

**Status:** draft
**Related items:** ROADMAP_v1.9.md #24 (R2 → v1.9.1). Depends on #23 (shipped in v1.9.0 — rule creation now works).
**Date:** 2026-04-17

## 1. Context

A **quantity rule** at `/bim/rules` maps BIM element properties (category, type, material, dims…) to BOQ quantity extraction (count / length / area / volume) and either links to an existing BOQ position or auto-creates one.

Data model — `backend/app/modules/bim_hub/models.py:173-199`:
- `element_type_filter: str(100)` — wildcard pattern
- `property_filter: JSON{k:v}` — arbitrary property matches
- `quantity_source: str(100)` — preset (`area_m2`, `volume_m3`, `length_m`, `weight_kg`, `count`) or `property:xxx`
- `multiplier`, `unit`, `waste_factor_pct`
- `boq_target: JSON` — `{position_id}` or `{auto_create, unit_rate}`

### UX pain points user reported
1. Fields are **dropdown-only** — user wants free-text too (they know their property names).
2. No **required/optional markers**.
3. No **project seeding** — can't pick a source RVT/IFC and see its categories / types / parameters.
4. Dialog feels dated.

And: **mark the module as BETA** across sidebar + page header.

## 2. Options considered

### Option A — Wizard (3 steps: source → target → condition)

Beginner-friendly, slower for power users.

### Option B — Builder canvas (drag categories, operators)

Powerful, visual, but overkill for 80% of rules.

### Option C — Hybrid (simple mode by default, advanced toggle)

Current single-screen form cleaned up + model-seeding + advanced mode for AND/OR logic and regex.

## 3. Decision

**Option C — hybrid.** Wizard adds friction; builder is scope creep. Hybrid keeps the happy path (one screen, smart defaults) and exposes complexity behind a toggle.

### Concrete changes

1. **Simple mode (default)** — unchanged layout, but:
   - Sections visually grouped: **Filter** / **Quantity** / **Target**
   - Red `*` marker on every required field (not just name)
   - New **"Seed from model"** button at top → pick a BIM model → populate every dropdown with real values from that model
   - `element_type_filter`, `property_filter` keys & values, `quantity_source` become **combobox** (searchable select with free-text fallback)
2. **Advanced mode toggle** at the top → reveals:
   - Property-filter operator: `AND` / `OR` / `NOT`
   - Regex syntax hint + pattern help
   - Raw JSON editor as last-resort escape hatch
3. **BETA badges** — sidebar (already done), page header new, modal header skipped.

## 4. Implementation sketch

### 4.1 Backend — model-seeding endpoint

New route `backend/app/modules/bim_hub/router.py`:
```python
@router.get(
    "/models/{model_id}/schema/",
    response_model=BIMModelSchemaResponse,
    tags=["bim-hub"],
)
async def get_model_schema(
    model_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
) -> BIMModelSchemaResponse:
    return await BIMHubService(session).get_model_schema(model_id)
```

`backend/app/modules/bim_hub/service.py`:
```python
async def get_model_schema(self, model_id: UUID) -> BIMModelSchemaResponse:
    elements = await self.repo.list_elements(model_id, limit=None)
    distinct_types: set[str] = set()
    property_keys: dict[str, set[str]] = {}
    for e in elements:
        if e.element_type:
            distinct_types.add(e.element_type)
        for k, v in (e.properties or {}).items():
            property_keys.setdefault(k, set()).add(str(v))
    return BIMModelSchemaResponse(
        distinct_types=sorted(distinct_types),
        property_keys={k: sorted(vs) for k, vs in property_keys.items()},
        available_quantities=["area_m2", "volume_m3", "length_m", "weight_kg", "count"],
        element_count=len(elements),
    )
```

Schema — `backend/app/modules/bim_hub/schemas.py`:
```python
class BIMModelSchemaResponse(BaseModel):
    distinct_types: list[str]
    property_keys: dict[str, list[str]]
    available_quantities: list[str]
    element_count: int
```

### 4.2 Frontend — combobox + seeding

In `RuleEditorModal` (inside `BIMQuantityRulesPage.tsx:236-806`):
- New local state `modelSchema: BIMModelSchema | null`
- New button `Seed from model` → opens a small picker → `fetchModelSchema(modelId)` populates `modelSchema`
- `element_type_filter` input becomes `<Combobox options={modelSchema?.distinct_types ?? []} allowCustom />`
- Property-filter rows use two comboboxes (key / value) driven by `modelSchema?.property_keys`
- `quantity_source` dropdown gets options from `modelSchema?.available_quantities` but still allows the `property:xxx` free-text option

### 4.3 Advanced mode

`<input type="checkbox">` "Advanced mode" at modal top sets `advancedMode: boolean`. When on:
- Row operator control (AND / OR / NOT)
- Regex hint block visible under `element_type_filter`
- Button "Edit raw JSON" opens a `<textarea>` with the serialised `property_filter` for power-user editing

### 4.4 BETA badge on page header

`BIMQuantityRulesPage.tsx` around line 2122 — add next to the title:
```tsx
<span className="ms-2 text-[10px] font-medium uppercase tracking-wide px-1.5 py-0.5 rounded text-content-quaternary bg-surface-tertiary/60">
  {t('common.beta', { defaultValue: 'beta' })}
</span>
```

Sidebar already has `badge: 'BETA'` (`Sidebar.tsx:111`).

## 5. Testing plan

**Backend unit** (`backend/tests/unit/v1_9/test_model_schema.py`):
- Returns empty collections for an empty model
- De-duplicates repeated types / values
- Excludes null property values
- 404 for missing model

**Frontend E2E** (`frontend/e2e/v1.9/24-quantity-rules.spec.ts`):
- Seed from a test model — dropdowns populate
- Free-text entry still works when no model is seeded
- Advanced mode toggle reveals AND/OR/NOT + regex hint
- Required-field asterisks visible on all required fields
- BETA badge visible in sidebar and page header
- Rule create with model-seeded values saves and appears in list (regression guard on v1.9.0 #23 fix)

**Visual regression:** modal with and without advanced mode open.

## 6. Risks / follow-ups

- **`property_keys` cardinality.** A model with 10 k elements and 50 properties can emit large responses. Cap each property's distinct values at 1 000 (server-side) and show a "show more…" hint client-side.
- **Schema cache.** Cache `getModelSchema` for 60 s in React Query — avoids a refetch every time the user opens a dialog.
- **Legacy rules.** Existing rules with free-text `element_type_filter` remain valid. Combobox respects `allowCustom`.
- **Advanced-mode parity.** Phase 1 only adds AND/OR/NOT. Full boolean-tree UI (nested groups) is R3+.
