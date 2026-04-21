/**
 * urlState — serialize/deserialize BIM viewer deep-link state.
 *
 * The BIM viewer supports deep-linking a specific camera position, target,
 * and element selection via URL query params so teams can share a view of
 * the model with a colleague: copy URL, paste URL, see the same angle and
 * the same highlighted elements.
 *
 * URL schema:
 *   ?cx=<cam.x>&cy=<cam.y>&cz=<cam.z>
 *   &tx=<target.x>&ty=<target.y>&tz=<target.z>
 *   &sel=id1,id2,id3
 *
 * All coordinates are serialized with 3 decimal places — BIM models are
 * usually in metres so millimetre precision in the URL is plenty (10x the
 * typical level-of-detail at which a user parks the camera) while keeping
 * URLs short enough to paste into chat messages without wrapping.
 *
 * Selection ids are comma-separated; commas inside ids are not supported
 * (backend ids are UUIDs or Revit element strings — neither contains `,`).
 */

export interface CameraState {
  position: { x: number; y: number; z: number };
  target: { x: number; y: number; z: number };
}

export interface BIMUrlState {
  camera: CameraState | null;
  selection: string[];
}

/** Round a float to N decimals — keeps URLs compact without losing BIM precision. */
function roundTo(v: number, decimals: number): number {
  const p = 10 ** decimals;
  return Math.round(v * p) / p;
}

/** Safely parse a string as a finite float. Returns null for NaN / Infinity / undefined. */
function parseFiniteFloat(raw: string | null | undefined): number | null {
  if (raw == null || raw === '') return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

/**
 * Serialize camera + selection to a flat { key: value } param map suitable
 * for `new URLSearchParams(obj)`.
 *
 * Returns only the keys that are actually set — callers merge the result
 * into an existing URLSearchParams without blowing away unrelated params
 * (e.g. `?group=xxx` from the lazy-load flow).
 *
 * Precision: 3 decimals (≈ 1 mm at metre scale) — see module header.
 */
export function serializeBIMUrlState(state: BIMUrlState): Record<string, string> {
  const out: Record<string, string> = {};
  if (state.camera) {
    const { position, target } = state.camera;
    out.cx = String(roundTo(position.x, 3));
    out.cy = String(roundTo(position.y, 3));
    out.cz = String(roundTo(position.z, 3));
    out.tx = String(roundTo(target.x, 3));
    out.ty = String(roundTo(target.y, 3));
    out.tz = String(roundTo(target.z, 3));
  }
  if (state.selection.length > 0) {
    out.sel = state.selection.join(',');
  }
  return out;
}

/**
 * Parse camera + selection from a URLSearchParams instance.
 *
 * A camera is only returned when ALL six coordinates (cx/cy/cz/tx/ty/tz) are
 * present and parse as finite floats — a partial camera can't be applied
 * safely.  Selection is an empty array when `sel` is missing.
 */
export function parseBIMUrlState(params: URLSearchParams): BIMUrlState {
  const cx = parseFiniteFloat(params.get('cx'));
  const cy = parseFiniteFloat(params.get('cy'));
  const cz = parseFiniteFloat(params.get('cz'));
  const tx = parseFiniteFloat(params.get('tx'));
  const ty = parseFiniteFloat(params.get('ty'));
  const tz = parseFiniteFloat(params.get('tz'));
  const allCamParamsPresent =
    cx !== null && cy !== null && cz !== null &&
    tx !== null && ty !== null && tz !== null;
  const camera = allCamParamsPresent
    ? {
        position: { x: cx, y: cy, z: cz },
        target: { x: tx, y: ty, z: tz },
      }
    : null;

  const selRaw = params.get('sel');
  const selection = selRaw
    ? selRaw.split(',').map((s) => s.trim()).filter(Boolean)
    : [];

  return { camera, selection };
}

/** All param keys this module reads / writes — used to clear stale state. */
export const BIM_URL_STATE_KEYS = ['cx', 'cy', 'cz', 'tx', 'ty', 'tz', 'sel'] as const;
