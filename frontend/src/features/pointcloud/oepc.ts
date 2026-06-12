/**
 * Parser for the OEPC binary point buffer the backend streams from
 * GET /api/v1/pointcloud/scans/{scan_id}/points.
 *
 * Mirrors backend/app/modules/pointcloud/wire.py exactly. One little-endian
 * buffer, read in a single pass:
 *
 *     offset  type        field
 *     0       char[4]     magic "OEPC"
 *     4       uint32      version (1)
 *     8       uint32      point_count N
 *     12      uint32      flags  bit0 = has RGB, bit1 = has intensity
 *     16      float64[3]  center (world origin subtracted from positions)
 *     40      float32[6]  bbox in world frame: minx,miny,minz,maxx,maxy,maxz
 *     64      float32[3N] positions, centre-relative, XYZ interleaved
 *     ...     uint8[3N]   RGB interleaved          (only if flags bit0)
 *     ...     float32[N]  intensity 0-1            (only if flags bit1)
 *
 * Positions are centre-relative so they stay float32-precision-safe even for
 * georeferenced scans with multi-million-metre coordinates; the world origin
 * lives in ``center`` as float64.
 */

export const OEPC_MAGIC = 'OEPC';
export const OEPC_VERSION = 1;
export const OEPC_HEADER_BYTES = 64;

const FLAG_RGB = 1 << 0;
const FLAG_INTENSITY = 1 << 1;

/** Machine-checkable reason for a parse failure. */
export type OepcParseErrorCode =
  | 'truncated_header'
  | 'bad_magic'
  | 'unsupported_version'
  | 'truncated_body';

/** Thrown when the buffer is not a valid OEPC payload. */
export class OepcParseError extends Error {
  readonly code: OepcParseErrorCode;

  constructor(code: OepcParseErrorCode, message: string) {
    super(message);
    this.name = 'OepcParseError';
    this.code = code;
  }
}

/** A fully parsed OEPC point cloud, ready for THREE.BufferGeometry. */
export interface OepcCloud {
  version: number;
  pointCount: number;
  /** World origin already subtracted from ``positions`` (float64 precision). */
  center: [number, number, number];
  /** Axis-aligned bounds in the WORLD frame (add to nothing; subtract center
   *  to get the local frame the positions live in). */
  bboxMin: [number, number, number];
  bboxMax: [number, number, number];
  /** Centre-relative XYZ triples, length 3N. Zero-copy view when aligned. */
  positions: Float32Array;
  /** Interleaved RGB triples 0-255, length 3N, or null when absent. */
  rgb: Uint8Array | null;
  /** Per-point intensity 0-1, length N, or null when absent. */
  intensity: Float32Array | null;
}

/** Read a Float32Array of ``length`` elements at ``byteOffset``; uses a
 *  zero-copy view when the offset is 4-byte aligned, otherwise copies. */
function readF32(buffer: ArrayBuffer, byteOffset: number, length: number): Float32Array {
  if (byteOffset % 4 === 0) {
    return new Float32Array(buffer, byteOffset, length);
  }
  // Unaligned (possible for the intensity block when 15N is not a multiple
  // of 4): copy through a sliced buffer so the typed view is valid.
  return new Float32Array(buffer.slice(byteOffset, byteOffset + length * 4));
}

/**
 * Parse an OEPC binary buffer into typed arrays.
 *
 * Throws {@link OepcParseError} when the magic, version or length do not
 * match; never returns partially valid data.
 */
export function parseOepc(buffer: ArrayBuffer): OepcCloud {
  if (buffer.byteLength < OEPC_HEADER_BYTES) {
    throw new OepcParseError(
      'truncated_header',
      `OEPC buffer too small: ${buffer.byteLength} bytes, need at least ${OEPC_HEADER_BYTES}`,
    );
  }

  const view = new DataView(buffer);
  const magic = String.fromCharCode(
    view.getUint8(0),
    view.getUint8(1),
    view.getUint8(2),
    view.getUint8(3),
  );
  if (magic !== OEPC_MAGIC) {
    throw new OepcParseError('bad_magic', `Not an OEPC buffer (magic ${JSON.stringify(magic)})`);
  }

  const version = view.getUint32(4, true);
  if (version !== OEPC_VERSION) {
    throw new OepcParseError(
      'unsupported_version',
      `Unsupported OEPC version ${version}, expected ${OEPC_VERSION}`,
    );
  }

  const pointCount = view.getUint32(8, true);
  const flags = view.getUint32(12, true);
  const hasRgb = (flags & FLAG_RGB) !== 0;
  const hasIntensity = (flags & FLAG_INTENSITY) !== 0;

  const center: [number, number, number] = [
    view.getFloat64(16, true),
    view.getFloat64(24, true),
    view.getFloat64(32, true),
  ];
  const bboxMin: [number, number, number] = [
    view.getFloat32(40, true),
    view.getFloat32(44, true),
    view.getFloat32(48, true),
  ];
  const bboxMax: [number, number, number] = [
    view.getFloat32(52, true),
    view.getFloat32(56, true),
    view.getFloat32(60, true),
  ];

  const expected =
    OEPC_HEADER_BYTES +
    pointCount * 12 +
    (hasRgb ? pointCount * 3 : 0) +
    (hasIntensity ? pointCount * 4 : 0);
  if (buffer.byteLength < expected) {
    throw new OepcParseError(
      'truncated_body',
      `OEPC buffer truncated: ${buffer.byteLength} bytes, expected ${expected} for ${pointCount} points`,
    );
  }

  let offset = OEPC_HEADER_BYTES;
  const positions = readF32(buffer, offset, pointCount * 3);
  offset += pointCount * 12;

  let rgb: Uint8Array | null = null;
  if (hasRgb) {
    rgb = new Uint8Array(buffer, offset, pointCount * 3);
    offset += pointCount * 3;
  }

  let intensity: Float32Array | null = null;
  if (hasIntensity) {
    intensity = readF32(buffer, offset, pointCount);
  }

  return { version, pointCount, center, bboxMin, bboxMax, positions, rgb, intensity };
}
