// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Map a device GPS reading to a point in the model, relative to the project's
 * geo anchor (its WGS84 location). This powers a "locate me" pin so a site
 * engineer can see roughly where they are standing inside the 3D model.
 *
 * This is a site-scale approximation, not survey-grade positioning: it assumes
 * the model origin sits at the project anchor, reads the model's linear units,
 * and takes an optional north rotation. Consumer GPS is typically accurate to
 * 5-15 m, so callers should always show an accuracy ring and never imply
 * millimetre precision.
 */

export interface Vec3Like {
  x: number;
  y: number;
  z: number;
}

/** Metres per degree at the equator, used for the small-angle projection. */
const METRES_PER_DEG_LAT = 110540;
const METRES_PER_DEG_LON = 111320;

/**
 * Local East/North offset (metres) of a point from an anchor, via an
 * equirectangular small-angle projection. Accurate to well under a metre over
 * a construction site (a few km at most), which is finer than consumer GPS.
 */
export function enuFromLatLon(
  anchorLat: number,
  anchorLon: number,
  lat: number,
  lon: number,
): { east: number; north: number } {
  const latRad = (anchorLat * Math.PI) / 180;
  const east = (lon - anchorLon) * Math.cos(latRad) * METRES_PER_DEG_LON;
  const north = (lat - anchorLat) * METRES_PER_DEG_LAT;
  return { east, north };
}

export interface GeoLocateOptions {
  /** Model linear units per metre (1 for metres, 1000 for mm, 3.28084 ft). */
  metresToModelUnits?: number;
  /** Rotation (radians) aligning model +X/-Z to true East/North. Default 0. */
  northRotationRad?: number;
  /** Y (up) coordinate to drop the point at - usually the model floor. */
  groundY?: number;
}

/**
 * Map a device WGS84 position to a scene point given the project anchor.
 *
 * Scene convention is three.js Y-up as trimesh/COLLADA export it: +X = East,
 * -Z = North, +Y = up. An optional north rotation turns the East/North frame
 * into the model frame before scaling to model units.
 */
export function modelPointFromGeo(
  anchor: { lat: number; lon: number },
  device: { lat: number; lon: number },
  opts: GeoLocateOptions = {},
): Vec3Like {
  const scale = opts.metresToModelUnits ?? 1;
  const rot = opts.northRotationRad ?? 0;
  const { east, north } = enuFromLatLon(anchor.lat, anchor.lon, device.lat, device.lon);
  const cos = Math.cos(rot);
  const sin = Math.sin(rot);
  const e = east * cos - north * sin;
  const n = east * sin + north * cos;
  return { x: e * scale, y: opts.groundY ?? 0, z: -n * scale };
}

/**
 * True when a scene point falls inside a box footprint (+ optional margin).
 * Only the horizontal X/Z footprint is checked - GPS carries no reliable
 * altitude, so the vertical axis is ignored.
 */
export function isWithinBounds(
  point: Vec3Like,
  box: { min: Vec3Like; max: Vec3Like },
  margin = 0,
): boolean {
  return (
    point.x >= box.min.x - margin &&
    point.x <= box.max.x + margin &&
    point.z >= box.min.z - margin &&
    point.z <= box.max.z + margin
  );
}

/**
 * Best-effort model-units-per-metre from a model's declared units. Falls back
 * to 1 (metres) for anything unrecognised, since most canonical exports are
 * metric metres.
 */
export function metresToModelUnits(units: unknown): number {
  const u = String(units ?? '')
    .trim()
    .toLowerCase();
  if (u === 'mm' || u === 'millimeter' || u === 'millimetre') return 1000;
  if (u === 'cm' || u === 'centimeter' || u === 'centimetre') return 100;
  if (u === 'ft' || u === 'feet' || u === 'foot' || u === 'imperial') return 3.28084;
  if (u === 'in' || u === 'inch' || u === 'inches') return 39.3701;
  return 1; // m / metric / metre / unknown
}
