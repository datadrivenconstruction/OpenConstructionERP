// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * canonicalElementDetails — pure derivation of the geometry / spatial facts
 * the DDC canonical format carries for a BIM element.
 *
 * The element list the viewer loads (see `BIMElementData`) flattens the
 * canonical record: the `geometry` block's dimensions land in `quantities`
 * (area / volume / length) and `properties` (thickness, height, …); the
 * world extent is the `bounding_box`; the spatial structure (level / zone /
 * parent) lives in `storey`, `properties` and `metadata`. The properties
 * panel previously surfaced none of the *derived* bounding-box geometry,
 * so this module computes the width / depth / height / footprint / diagonal
 * the canonical format implies and the spatial relations, with zero Three.js
 * dependency so it is trivially unit-testable.
 */

export interface CanonicalBBox {
  min_x: number;
  min_y: number;
  min_z: number;
  max_x: number;
  max_y: number;
  max_z: number;
}

export interface CanonicalGeometry {
  /** X span in metres. */
  width: number;
  /** Y span in metres. */
  depth: number;
  /** Z span (height) in metres. */
  height: number;
  /** Plan footprint width × depth, m². */
  footprint: number;
  /** Axis-aligned bounding-box volume, m³. */
  bboxVolume: number;
  /** Space diagonal length, m. */
  diagonal: number;
  /** Centre point of the bounding box. */
  center: { x: number; y: number; z: number };
}

/** A flat label/value row for the relations section. */
export interface CanonicalRelation {
  key: string;
  value: string;
}

/** Translated base names (no unit) for the six derived geometry rows. The
 *  unit suffix is appended by {@link geometryDisplayRows} from the active
 *  measurement system so the label tracks the value (m -> ft, m2 -> ft2). */
export interface GeometryLabels {
  width: string;
  depth: string;
  height: string;
  footprint: string;
  bboxVolume: string;
  diagonal: string;
}

/** Minimal shape of the display-quantity converter (see
 *  `useDisplayQuantity`): scales a metric-canonical value into the user's
 *  system and returns the value paired with its display unit. */
type ConvertFn = (value: number, metricUnit: string) => { value: number; unit: string };

/**
 * Turn derived box geometry into the `{ "Label (unit)": value }` rows the
 * properties-panel QuantitiesTable renders, converting both the value and the
 * unit suffix into the user's measurement system.
 *
 * The bbox spans are metric-canonical (m / m² / m³). `convert` is the only
 * place the metric/imperial decision is made: for a metric user every value
 * passes through unchanged and the suffix stays "m"/"m²"/"m³" (byte-identical
 * to before this was unit-aware); for an imperial user the value is scaled and
 * the suffix becomes "ft"/"ft²"/"ft³". Pure so it is unit-tested without React.
 */
export function geometryDisplayRows(
  geom: CanonicalGeometry,
  labels: GeometryLabels,
  convert: ConvertFn,
): Record<string, number> {
  const row = (
    base: string,
    value: number,
    metricUnit: string,
  ): [string, number] => {
    const d = convert(value, metricUnit);
    return [`${base} (${d.unit})`, d.value];
  };
  return Object.fromEntries([
    row(labels.width, geom.width, 'm'),
    row(labels.depth, geom.depth, 'm'),
    row(labels.height, geom.height, 'm'),
    row(labels.footprint, geom.footprint, 'm²'),
    row(labels.bboxVolume, geom.bboxVolume, 'm³'),
    row(labels.diagonal, geom.diagonal, 'm'),
  ]);
}

const round = (v: number, dp = 3): number => {
  const f = 10 ** dp;
  return Math.round(v * f) / f;
};

/**
 * Derive box geometry from a canonical `bounding_box`. Returns null when the
 * box is missing or degenerate (zero/NaN extent) so callers can hide the
 * section instead of rendering all-zeros.
 */
export function deriveGeometry(
  bbox: CanonicalBBox | null | undefined,
): CanonicalGeometry | null {
  if (!bbox) return null;
  const w = bbox.max_x - bbox.min_x;
  const d = bbox.max_y - bbox.min_y;
  const h = bbox.max_z - bbox.min_z;
  if (
    !Number.isFinite(w) ||
    !Number.isFinite(d) ||
    !Number.isFinite(h) ||
    w < 0 ||
    d < 0 ||
    h < 0 ||
    (w === 0 && d === 0 && h === 0)
  ) {
    return null;
  }
  return {
    width: round(w),
    depth: round(d),
    height: round(h),
    footprint: round(w * d),
    bboxVolume: round(w * d * h),
    diagonal: round(Math.sqrt(w * w + d * d + h * h)),
    center: {
      x: round((bbox.min_x + bbox.max_x) / 2),
      y: round((bbox.min_y + bbox.max_y) / 2),
      z: round((bbox.min_z + bbox.max_z) / 2),
    },
  };
}

/** Canonical relation keys we look for inside the flattened bag. The DDC
 *  exporter is inconsistent across source CAD formats, so we accept a few
 *  spellings per concept. First non-empty hit wins. */
const RELATION_SOURCES: Array<{ label: string; keys: string[] }> = [
  { label: 'Level', keys: ['level', 'storey', 'story', 'floor', 'reference_level'] },
  { label: 'Zone', keys: ['zone', 'space', 'room', 'area'] },
  { label: 'System', keys: ['system', 'parent_system', 'mep_system'] },
  { label: 'Assembly', keys: ['assembly', 'parent', 'host', 'group'] },
  { label: 'Phase', keys: ['phase', 'phase_created', 'construction_phase'] },
  { label: 'Workset', keys: ['workset'] },
];

function pickString(
  bag: Record<string, unknown> | undefined,
  keys: string[],
): string | null {
  if (!bag) return null;
  // Case-insensitive lookup so "Level" / "level" / "LEVEL" all resolve.
  const lower = new Map<string, unknown>();
  for (const [k, v] of Object.entries(bag)) lower.set(k.toLowerCase(), v);
  for (const key of keys) {
    const v = lower.get(key.toLowerCase());
    if (v === null || v === undefined) continue;
    const s = String(v).trim();
    if (s && s !== 'None' && s !== 'null' && s !== 'N/A') return s;
  }
  return null;
}

/**
 * Resolve the canonical spatial relations for an element. `storey` is the
 * top-level shortcut the API already exposes; everything else is mined from
 * `properties` then `metadata` (in that priority order).
 */
export function deriveRelations(input: {
  storey?: string | null;
  properties?: Record<string, unknown>;
  metadata?: Record<string, unknown> | null;
}): CanonicalRelation[] {
  const out: CanonicalRelation[] = [];
  const meta = input.metadata ?? undefined;
  for (const src of RELATION_SOURCES) {
    let value: string | null = null;
    if (src.label === 'Level' && input.storey && input.storey.trim()) {
      value = input.storey.trim();
    }
    value =
      value ??
      pickString(input.properties, src.keys) ??
      pickString(meta, src.keys);
    if (value) out.push({ key: src.label, value });
  }
  return out;
}
