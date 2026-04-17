# RFC 13 — DWG scale + annotation text

**Status:** draft
**Related items:** ROADMAP_v1.9.md #13 (R2 → v1.9.1, moved from R1)
**Date:** 2026-04-17

## 1. Context

Two user reports at `/dwg-takeoff` that the agent initially bundled under one item but are actually independent:

### Sub-issue A — drawing scale is wrong

User: "Неправильно выбирается масштаб — нужна возможность задать масштаб чертежа вручную."

Concrete failure: a DXF with `$INSUNITS = 4` (millimetres) containing a 5 000 mm line renders a measurement label of `5000.00 m` instead of `5.00 m`. The bug is a **unit-scaling bug masquerading as a scale bug**:

- Backend parses the `$INSUNITS` header correctly (`backend/app/modules/dwg_takeoff/dxf_processor.py:268`) and attaches `units` to the converted entities.
- Frontend `formatMeasurement()` in `frontend/src/features/dwg-takeoff/lib/measurement.ts:31-39` hard-codes the output label as metres and does not consume the `units` value.

Beyond the unit bug, a DWG is often drawn at a nominal scale (e.g. 1 : 50) — a user looking at a façade detail needs the ability to override "1 unit = N metres" even when units are unknown.

### Sub-issue B — annotation text not visible

User: "Не работает функция добавления текста — ничего не видно в annotation."

The text-pin pipeline **looks correct on a code read:**

- `ToolPalette.tsx:24` registers `text_pin` with shortcut T
- `DxfViewer.tsx:547` fires `setTextPinPopup` on single click
- `TextPinPopup` component renders at `DxfViewer.tsx:645`, collects text + colour + font size
- `handleTextPinConfirm` (L613-626) calls `onAnnotationCreated` with `{ type: 'text_pin', points, text, color, fontSize }`
- `DwgTakeoffPage.tsx:539-563` maps `fontSize` → `metadata.font_size` before mutating
- Backend `service.py:602-635` persists `metadata_` verbatim
- `AnnotationOverlay.tsx:45-115` renders with `ann.metadata?.font_size ?? 11`, uses `ann.color`, draws a dark pill background for contrast

All three code paths match. The bug is either (1) environmental — the `createAnnotation` mutation does not invalidate the annotations query, so the new pin never reaches the render loop; or (2) a timing race — the render fires before the refetch completes. Neither is visible from static analysis; requires live Playwright repro.

## 2. Options considered — sub-issue A (scale)

### Option 1 — drawing-scale multiplier, stored on the drawing record

- Add `scale_factor: float | null` to `DwgDrawingVersion.metadata_`
- UI: numeric input "1 unit = ___ metres" plus preset buttons (1:50, 1:100, 1:500) on the drawing toolbar
- `formatMeasurement(raw, units, scaleFactor)` applies unit conversion **then** multiplies by `scaleFactor`
- Default `scale_factor = 1.0`

**Pros:** persistent per drawing; handles both unit conversion and blueprint scaling. **Cons:** manual — user has to remember. Good default behaviour mitigates this.

### Option 2 — reference-line calibration

"Calibrate" tool: user clicks two points they know the real distance of, types the distance, backend computes `scale_factor = typedDistance / pixelDistance`.

**Pros:** zero typing of ratios; works even when headers are missing or lying. **Cons:** requires the drawing to have a known reference (scale bar, dimension, wall thickness); a separate flow.

### Option 3 — units override only

A "Display as: m / cm / mm / ft" dropdown applied at render time.

**Pros:** tiny change. **Cons:** doesn't handle non-1:1 blueprints — it's a cosmetic patch, not a fix.

## 3. Options considered — sub-issue B (text annotation)

### B.1 — Playwright repro first, patch second

Write a spec that (a) creates a drawing via the API, (b) selects `text_pin`, (c) clicks the canvas, (d) types text, (e) asserts the text is rendered (OCR on canvas screenshot or a DOM attribute the renderer sets). Use the spec output to identify which step is broken before changing production code.

### B.2 — Defensive fixes without repro

Apply common-case hardening blindly:
- Optimistic cache update in `createAnnotationMutation.onSuccess` (add the new annotation to `['dwg-annotations', drawingId]` before refetch)
- White stroke outline on rendered text for contrast on any background
- Minimum `customFontSize` floor of 11 px

This might fix the symptom without pinpointing the cause.

## 4. Decision

### Scale: Option 1 + Option 3 as a unified control

Store `scale_factor` on the drawing (Option 1). Expose a small dropdown chooser for the target display unit (Option 3) — it is free UX on top of a proper `formatMeasurement(raw, sourceUnits, displayUnits, scaleFactor)`. Option 2 (reference-line calibration) is deferred to R3/R4 — solid but not the minimum viable fix.

### Text annotation: Option B.1 → B.2

Repro first. The code read did not find a bug; patching blindly is more likely to mask the real cause than fix it. Once we have a failing Playwright spec, the actual fix (optimistic cache write vs. query invalidation vs. something in `AnnotationOverlay`) is obvious. The spec also serves as the permanent regression test.

## 5. Implementation sketch

### 5.1 `formatMeasurement` overhaul

```ts
// frontend/src/features/dwg-takeoff/lib/measurement.ts

export type DxfUnit = 'mm' | 'cm' | 'm' | 'in' | 'ft' | 'unitless';

const TO_METRES: Record<Exclude<DxfUnit, 'unitless'>, number> = {
  mm: 0.001, cm: 0.01, m: 1, in: 0.0254, ft: 0.3048,
};

export function formatMeasurement(
  rawValue: number,
  sourceUnits: DxfUnit,
  displayUnits: DxfUnit = 'm',
  scaleFactor = 1,
): { value: number; label: string } {
  const metres =
    sourceUnits === 'unitless'
      ? rawValue * scaleFactor
      : rawValue * TO_METRES[sourceUnits] * scaleFactor;
  const out =
    displayUnits === 'unitless'
      ? metres
      : metres / TO_METRES[displayUnits];
  return { value: out, label: `${out.toFixed(2)} ${displayUnits}` };
}
```

### 5.2 Drawing-scale UI

Replace the read-only "XX %" badge at `DxfViewer.tsx:671` with a two-part control:
- Zoom % (existing, read-only) — keep
- "Scale 1 :" numeric input + units dropdown — new, persisted on change

State lives in `DwgTakeoffPage.tsx` (not `DxfViewer`) and is pushed down as props. The viewer becomes a dumb renderer.

Backend:
- Migration: add `scale_factor` and `display_units` columns to `oe_dwg_takeoff_drawing` (or store in `metadata_` JSON column if one exists — check first, prefer column for queryability).
- Endpoint: `PATCH /v1/dwg_takeoff/drawings/{id}` already exists for filename edits — extend with `scale_factor` and `display_units` fields.

### 5.3 Playwright repro for text annotation

```ts
// frontend/e2e/v1.9/13-dwg-text-annotation.spec.ts
test('text_pin annotation persists and is visible after creation', async ({ page }) => {
  await loginV19(page);

  // 1. Create a minimal DXF via API
  const projectId = await ensureProject(page);
  const drawingId = await uploadMinimalDxf(page, projectId); // helper to be added

  await page.goto(`/dwg-takeoff?drawing=${drawingId}`);
  await page.waitForLoadState('networkidle');

  // 2. Activate text_pin tool
  await page.keyboard.press('t');

  // 3. Click in the middle of the canvas
  const canvas = page.locator('canvas').first();
  const box = await canvas.boundingBox();
  await canvas.click({
    position: { x: (box!.width) / 2, y: (box!.height) / 2 },
  });

  // 4. Fill the popup and confirm
  const popup = page.locator('[role="dialog"]:has(input[type="text"])');
  await expect(popup).toBeVisible();
  await popup.locator('input[type="text"]').fill('V19-TEST-LABEL');
  await popup.locator('button:has-text(/confirm|add|ok/i)').click();

  // 5. Hit the DB directly — is the annotation persisted?
  const listRes = await page.request.get(
    `http://localhost:8000/api/v1/dwg_takeoff/drawings/${drawingId}/annotations/`,
    { headers: authHeaders() },
  );
  const annotations = await listRes.json();
  expect(annotations.some((a: { text?: string }) => a.text === 'V19-TEST-LABEL')).toBe(true);

  // 6. The annotation must also be rendered — take a screenshot and OCR or
  //    check the annotation count indicator in the sidebar.
  const sidebarCount = page.locator('[data-testid="annotations-count"]');
  await expect(sidebarCount).toHaveText(/\d+/, { timeout: 5_000 });
});
```

Run this spec. The first thing it fails on reveals the real bug. Fix it; the spec stays as a regression guard.

## 6. Testing plan

**Unit** (`__tests__/measurement.test.ts`): all `TO_METRES` conversions, `scaleFactor` multiplication, `unitless` behaviour (bypass unit conversion), rounding.

**E2E** (`e2e/v1.9/`):
- `13-dwg-scale.spec.ts` — set scale 1 : 50 on a test drawing, click two points with known real-world distance, assert label matches.
- `13-dwg-text-annotation.spec.ts` — as above (Section 5.3).

**Visual regression:** label rendered with correct units before and after scale change.

## 7. Risks / follow-ups

- **Historic drawings.** Existing records get `scale_factor = 1` by default (migration default). Users who had mm drawings displayed as metres (1 000× wrong) see their labels change after the fix — that is the intended behaviour, but warn in CHANGELOG.
- **Unit detection confidence.** `$INSUNITS` can be missing or wrong. Show a subtle "units: inferred / unset" hint in the UI so the user knows whether to override.
- **Reference-line calibration (Option 2)** remains a future feature — pull it from R3/R4 if users still miss-set the manual scale regularly.
- **Text-annotation fix scope depends on the repro outcome** — if the spec reveals an invalidation bug, the fix is 2 lines in `DwgTakeoffPage.tsx:createAnnotationMutation`; if it reveals a renderer bug, the fix lands in `AnnotationOverlay.tsx`. Budget flex accordingly.
