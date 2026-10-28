// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Coordinate input utilities for the Geo Hub coord picker.
 *
 * Handles:
 *   - Decimal degrees ↔ DMS conversion
 *   - Live lat/lon range validation
 *   - Tolerant parsing of common DMS notations:
 *
 *     ``52°31'12" N``  → 52.52
 *     ``52 31 12 N``   → 52.52
 *     ``52d31m12sN``   → 52.52
 *     ``-13.405``      → -13.405
 *     ``52.5200``      → 52.5200
 *
 * Pure functions only — no Cesium, no React; keeps the picker testable
 * without a JSDOM map mock.
 */

export type CoordAxis = 'lat' | 'lon';

export interface CoordRange {
  min: number;
  max: number;
}

export const COORD_RANGES: Record<CoordAxis, CoordRange> = {
  lat: { min: -90, max: 90 },
  lon: { min: -180, max: 180 },
};

export interface DmsParts {
  /** Whole degrees (unsigned). */
  degrees: number;
  /** Minutes 0..59. */
  minutes: number;
  /** Seconds 0..59.999... */
  seconds: number;
  /** Compass hemisphere — uppercased. */
  hemisphere: 'N' | 'S' | 'E' | 'W';
}

/** True when ``value`` is a finite number inside the axis range. */
export function isValidCoord(value: number, axis: CoordAxis): boolean {
  if (!Number.isFinite(value)) return false;
  const r = COORD_RANGES[axis];
  return value >= r.min && value <= r.max;
}

/**
 * Convert a signed decimal-degree value to its DMS breakdown.
 *
 * Returns ``null`` for non-finite inputs so callers can render "—".
 */
export function ddToDms(value: number, axis: CoordAxis): DmsParts | null {
  if (!Number.isFinite(value)) return null;
  const positive = axis === 'lat' ? 'N' : 'E';
  const negative = axis === 'lat' ? 'S' : 'W';
  const hemisphere = value >= 0 ? positive : negative;
  const abs = Math.abs(value);
  const degrees = Math.floor(abs);
  const minutesFloat = (abs - degrees) * 60;
  const minutes = Math.floor(minutesFloat);
  // Round to 4 decimals to avoid 59.99999... seconds artefacts that
  // would visually look like "60 seconds".
  let seconds = Math.round((minutesFloat - minutes) * 60 * 10000) / 10000;
  let adjMinutes = minutes;
  let adjDegrees = degrees;
  if (seconds >= 60) {
    seconds -= 60;
    adjMinutes += 1;
  }
  if (adjMinutes >= 60) {
    adjMinutes -= 60;
    adjDegrees += 1;
  }
  return {
    degrees: adjDegrees,
    minutes: adjMinutes,
    seconds,
    hemisphere,
  };
}

/** Format a DMS breakdown as the conventional ``DD° MM' SS.s" H`` string. */
export function formatDms(parts: DmsParts): string {
  const { degrees, minutes, seconds, hemisphere } = parts;
  const sec = seconds.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
  return `${degrees}° ${minutes}' ${sec || '0'}" ${hemisphere}`;
}

/** Convenience — value+axis → ``DD° MM' SS.s" H``. */
export function ddToDmsString(value: number, axis: CoordAxis): string {
  const parts = ddToDms(value, axis);
  return parts ? formatDms(parts) : '';
}

/**
 * Parse a DMS string back to signed decimal degrees.
 *
 * Returns ``null`` when the string can't be parsed or the resulting
 * value is out of range for ``axis``. Accepts the formats listed in
 * the module docstring above.
 */
export function parseDms(value: string, axis: CoordAxis): number | null {
  if (typeof value !== 'string') return null;
  const raw = value.trim();
  if (!raw) return null;
  // 1) Try plain decimal first — covers "52.52", "-13.405" etc.
  const plain = Number(raw.replace(/,/g, '.'));
  if (Number.isFinite(plain)) {
    return isValidCoord(plain, axis) ? plain : null;
  }
  // 2) DMS parser — extract degrees/minutes/seconds/hemisphere tokens.
  //
  // First, peel off a trailing hemisphere letter so 'S' (which is both
  // "south" AND "seconds") cannot collide with the seconds-marker
  // collapse below. Accepts:
  //
  //     "33° 51' 35" S"   → hemi=S, body="33° 51' 35""
  //     "52.5N"           → hemi=N, body="52.5"
  //     "-13.405"         → hemi=null, body="-13.405"
  let hemisphere: string | null = null;
  let body = raw;
  const trailingHemi = /([NSEWnsew])\s*$/.exec(body);
  if (trailingHemi) {
    // Ensure the hemisphere letter isn't part of a number / mid-token —
    // it must be preceded by whitespace, a digit, a quote, or one of
    // the unit markers we're about to collapse.
    const beforeIdx = trailingHemi.index - 1;
    const before = beforeIdx >= 0 ? body[beforeIdx] : '';
    if (
      beforeIdx < 0 ||
      /[\s0-9.°"'″′]/.test(before ?? '')
    ) {
      hemisphere = trailingHemi[1]!.toUpperCase();
      body = body.slice(0, trailingHemi.index);
    }
  }
  // Permissive about separators (°, d, m, s, ', ", spaces, tabs).
  const normalised = body
    .replace(/[°dD]/g, ' ')
    .replace(/[′']/g, ' ')
    .replace(/[″"]/g, ' ')
    .replace(/[mMsS]/g, ' ')
    .replace(/,/g, '.')
    .trim();
  const tokens = normalised.split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return null;
  const nums = tokens.map((t) => Number(t)).filter((n) => Number.isFinite(n));
  if (nums.length === 0) return null;
  const [deg = 0, min = 0, sec = 0] = nums;
  if (min < 0 || min >= 60) return null;
  if (sec < 0 || sec >= 60) return null;
  const absDeg = Math.abs(deg);
  let dd = absDeg + min / 60 + sec / 3600;
  // Apply hemisphere / sign. If both a hemisphere AND a negative leading
  // value were given we trust the hemisphere (DMS convention).
  if (hemisphere === 'S' || hemisphere === 'W') {
    dd = -dd;
  } else if (hemisphere === 'N' || hemisphere === 'E') {
    // explicit positive — no sign change
  } else if (deg < 0) {
    dd = -dd;
  }
  return isValidCoord(dd, axis) ? dd : null;
}

/**
 * Round a decimal-degree value to a stable precision suitable for the
 * Numeric(10, 7) backend column. Avoids handing a runaway 17-digit
 * float to the API which would 422 on schema validation.
 */
export function roundCoord(value: number, decimals = 7): number {
  if (!Number.isFinite(value)) return 0;
  const f = 10 ** decimals;
  return Math.round(value * f) / f;
}
