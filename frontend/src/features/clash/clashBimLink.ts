// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure helpers for the clash → BIM-viewer deep-link.
 *
 * A clash result's "3D" link must (a) isolate BOTH interfering elements,
 * (b) flag them clash-red, and (c) frame the camera on the clash. The
 * element ids alone are NOT a reliable camera target: showcase IFC/RVT
 * models export GLB nodes named with numeric Revit ids that never equal the
 * DB element UUIDs, so the viewer's per-element mesh resolution is only an
 * approximate positional fallback. The clash world centroid (`cx/cy/cz`,
 * canonical Z-up) IS exact, so we pass it as `focus=` and let the viewer
 * apply its own Z-up→Y-up rotation.
 *
 * Extracted so the URL contract is unit-tested independently of the page.
 */

export interface ClashLinkInput {
  projectId: string;
  modelId: string;
  aElementId: string;
  bElementId: string;
  /** Clash world centroid, canonical Z-up (same frame as element bboxes). */
  cx: number;
  cy: number;
  cz: number;
}

/** Build the `/projects/:pid/bim/:mid?...` deep-link for a clash result. */
export function buildClashBimLink(input: ClashLinkInput): string {
  const ids = [input.aElementId, input.bElementId].filter(Boolean).join(',');
  const base = `/projects/${input.projectId}/bim/${input.modelId}`;
  if (!ids) return base;
  const q = new URLSearchParams();
  q.set('isolate', ids);
  q.set('clash', '1');
  if (
    Number.isFinite(input.cx) &&
    Number.isFinite(input.cy) &&
    Number.isFinite(input.cz)
  ) {
    q.set('focus', `${input.cx},${input.cy},${input.cz}`);
  }
  return `${base}?${q.toString()}`;
}

export interface SelectionSetLinkInput {
  projectId: string;
  modelId: string;
  /** Every element id to isolate in the viewer (already de-duplicated). */
  elementIds: readonly string[];
  /** Optional camera focus target in canonical Z-up, or null to skip it. */
  focus?: { x: number; y: number; z: number } | null;
}

/**
 * Build the BIM-viewer deep-link for a selection set assembled from several
 * findings. Reuses the exact `isolate` / `clash` / `focus` query contract the
 * single-clash link uses (so the viewer / `parseClashDeepLink` handle both),
 * but isolates the WHOLE element union and flags `clash=1` so the unresolved-
 * element warning fires when a stale reference can't be located in the model.
 *
 * Returns a bare model link when no element id survives, so the user still
 * lands in the right model rather than on a dead URL.
 */
export function buildSelectionSetBimLink(input: SelectionSetLinkInput): string {
  const ids = input.elementIds.filter((id) => !!id && id.length > 0);
  const base = `/projects/${input.projectId}/bim/${input.modelId}`;
  if (ids.length === 0) return base;
  const q = new URLSearchParams();
  q.set('isolate', ids.join(','));
  q.set('clash', '1');
  const f = input.focus;
  if (
    f &&
    Number.isFinite(f.x) &&
    Number.isFinite(f.y) &&
    Number.isFinite(f.z)
  ) {
    q.set('focus', `${f.x},${f.y},${f.z}`);
  }
  return `${base}?${q.toString()}`;
}

export interface ParsedClashDeepLink {
  /** Element ids requested for isolation (order preserved). */
  ids: string[];
  /** True when this is a clash-review link (colour the ids clash-red). */
  isClash: boolean;
  /** Clash centroid in canonical Z-up, or null when absent/malformed. */
  focus: { x: number; y: number; z: number } | null;
}

/**
 * Parse the BIM deep-link query the viewer receives. Mirrors the BIMPage
 * effect exactly so the contract is regression-tested in isolation.
 */
export function parseClashDeepLink(
  params: URLSearchParams,
): ParsedClashDeepLink {
  const isolate = params.get('isolate') ?? '';
  const ids = isolate.split(',').filter((id) => id.length > 0);
  const isClash = params.get('clash') === '1';
  let focus: { x: number; y: number; z: number } | null = null;
  const focusParam = params.get('focus');
  if (focusParam) {
    const parts = focusParam.split(',').map((s) => Number.parseFloat(s));
    if (parts.length === 3 && parts.every((n) => Number.isFinite(n))) {
      focus = { x: parts[0]!, y: parts[1]!, z: parts[2]! };
    }
  }
  return { ids, isClash, focus };
}

/**
 * Transform a canonical Z-up clash centroid into the viewer's Y-up scene
 * space. The loaded geometry is rotated -90° about X (Z-up → Y-up); this is
 * the exact transform ElementManager applies to element bbox centres for
 * the positional fallback, so the camera target lands on the geometry.
 *
 *   viewerX =  x
 *   viewerY =  z
 *   viewerZ = -y
 */
export function clashCentroidToViewerSpace(focus: {
  x: number;
  y: number;
  z: number;
}): { x: number; y: number; z: number } {
  return { x: focus.x, y: focus.z, z: -focus.y };
}
