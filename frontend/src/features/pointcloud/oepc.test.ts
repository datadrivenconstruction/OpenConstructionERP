/**
 * Unit tests for the OEPC binary parser. Builds the buffer byte by byte with a
 * DataView (little-endian), exactly mirroring the packer in
 * backend/app/modules/pointcloud/wire.py, then asserts the parsed values.
 */
import { describe, expect, it } from 'vitest';
import { OEPC_HEADER_BYTES, OepcParseError, parseOepc } from './oepc';

interface BuildOptions {
  magic?: string;
  version?: number;
  /** Override the point count written in the header (for truncation tests). */
  headerCount?: number;
  center?: [number, number, number];
  bboxMin?: [number, number, number];
  bboxMax?: [number, number, number];
  positions: number[];
  rgb?: number[] | null;
  intensity?: number[] | null;
}

function buildBuffer(opts: BuildOptions): ArrayBuffer {
  const n = opts.positions.length / 3;
  const hasRgb = opts.rgb != null;
  const hasIntensity = opts.intensity != null;
  const total =
    OEPC_HEADER_BYTES + n * 12 + (hasRgb ? n * 3 : 0) + (hasIntensity ? n * 4 : 0);

  const buffer = new ArrayBuffer(total);
  const view = new DataView(buffer);

  const magic = opts.magic ?? 'OEPC';
  for (let i = 0; i < 4; i++) view.setUint8(i, magic.charCodeAt(i));
  view.setUint32(4, opts.version ?? 1, true);
  view.setUint32(8, opts.headerCount ?? n, true);
  view.setUint32(12, (hasRgb ? 1 : 0) | (hasIntensity ? 2 : 0), true);

  const center = opts.center ?? [0, 0, 0];
  view.setFloat64(16, center[0], true);
  view.setFloat64(24, center[1], true);
  view.setFloat64(32, center[2], true);

  const bboxMin = opts.bboxMin ?? [0, 0, 0];
  const bboxMax = opts.bboxMax ?? [0, 0, 0];
  for (let i = 0; i < 3; i++) {
    view.setFloat32(40 + i * 4, bboxMin[i] ?? 0, true);
    view.setFloat32(52 + i * 4, bboxMax[i] ?? 0, true);
  }

  let offset = OEPC_HEADER_BYTES;
  for (const v of opts.positions) {
    view.setFloat32(offset, v, true);
    offset += 4;
  }
  if (opts.rgb) {
    for (const v of opts.rgb) {
      view.setUint8(offset, v);
      offset += 1;
    }
  }
  if (opts.intensity) {
    for (const v of opts.intensity) {
      view.setFloat32(offset, v, true);
      offset += 4;
    }
  }
  return buffer;
}

describe('parseOepc', () => {
  it('parses a full buffer with rgb and intensity', () => {
    const buffer = buildBuffer({
      center: [4_500_000.25, 5_600_000.5, 312.75],
      bboxMin: [-1.5, -2.5, 0],
      bboxMax: [1.5, 2.5, 3],
      positions: [0.5, -1.25, 2.0, -0.5, 1.25, 0.0, 1.5, 2.5, 3.0],
      rgb: [255, 0, 0, 0, 255, 0, 0, 0, 255],
      intensity: [0.0, 0.5, 1.0],
    });

    const cloud = parseOepc(buffer);
    expect(cloud.version).toBe(1);
    expect(cloud.pointCount).toBe(3);
    // Center keeps float64 precision for georeferenced clouds.
    expect(cloud.center).toEqual([4_500_000.25, 5_600_000.5, 312.75]);
    expect(cloud.bboxMin).toEqual([-1.5, -2.5, 0]);
    expect(cloud.bboxMax).toEqual([1.5, 2.5, 3]);
    expect(Array.from(cloud.positions)).toEqual([0.5, -1.25, 2.0, -0.5, 1.25, 0.0, 1.5, 2.5, 3.0]);
    expect(cloud.rgb).not.toBeNull();
    expect(Array.from(cloud.rgb!)).toEqual([255, 0, 0, 0, 255, 0, 0, 0, 255]);
    expect(cloud.intensity).not.toBeNull();
    expect(Array.from(cloud.intensity!)).toEqual([0.0, 0.5, 1.0]);
  });

  it('parses positions only when both optional channels are absent', () => {
    const buffer = buildBuffer({ positions: [1, 2, 3, 4, 5, 6] });
    const cloud = parseOepc(buffer);
    expect(cloud.pointCount).toBe(2);
    expect(cloud.rgb).toBeNull();
    expect(cloud.intensity).toBeNull();
    expect(Array.from(cloud.positions)).toEqual([1, 2, 3, 4, 5, 6]);
  });

  it('parses intensity at an unaligned byte offset (odd point count, rgb present)', () => {
    // With rgb present the intensity block starts at 64 + 15N; for N=1 that is
    // byte 79, which is not 4-aligned, so the parser must copy instead of view.
    const buffer = buildBuffer({
      positions: [7, 8, 9],
      rgb: [10, 20, 30],
      intensity: [0.25],
    });
    const cloud = parseOepc(buffer);
    expect(cloud.pointCount).toBe(1);
    expect(Array.from(cloud.rgb!)).toEqual([10, 20, 30]);
    expect(Array.from(cloud.intensity!)).toEqual([0.25]);
  });

  it('parses an rgb-only buffer', () => {
    const buffer = buildBuffer({ positions: [1, 1, 1], rgb: [9, 9, 9] });
    const cloud = parseOepc(buffer);
    expect(Array.from(cloud.rgb!)).toEqual([9, 9, 9]);
    expect(cloud.intensity).toBeNull();
  });

  it('parses an intensity-only buffer', () => {
    const buffer = buildBuffer({ positions: [1, 1, 1], intensity: [0.75] });
    const cloud = parseOepc(buffer);
    expect(cloud.rgb).toBeNull();
    expect(Array.from(cloud.intensity!)).toEqual([0.75]);
  });

  it('parses an empty cloud (zero points)', () => {
    const buffer = buildBuffer({ positions: [] });
    const cloud = parseOepc(buffer);
    expect(cloud.pointCount).toBe(0);
    expect(cloud.positions.length).toBe(0);
  });

  it('rejects a buffer smaller than the header', () => {
    expect(() => parseOepc(new ArrayBuffer(10))).toThrowError(OepcParseError);
    try {
      parseOepc(new ArrayBuffer(10));
    } catch (e) {
      expect((e as OepcParseError).code).toBe('truncated_header');
    }
  });

  it('rejects a wrong magic', () => {
    const buffer = buildBuffer({ magic: 'NOPE', positions: [1, 2, 3] });
    try {
      parseOepc(buffer);
      expect.unreachable('should have thrown');
    } catch (e) {
      expect(e).toBeInstanceOf(OepcParseError);
      expect((e as OepcParseError).code).toBe('bad_magic');
    }
  });

  it('rejects an unsupported version', () => {
    const buffer = buildBuffer({ version: 2, positions: [1, 2, 3] });
    try {
      parseOepc(buffer);
      expect.unreachable('should have thrown');
    } catch (e) {
      expect((e as OepcParseError).code).toBe('unsupported_version');
    }
  });

  it('rejects a body shorter than the declared point count', () => {
    // Header claims 5 points but only one xyz triple follows.
    const buffer = buildBuffer({ headerCount: 5, positions: [1, 2, 3] });
    try {
      parseOepc(buffer);
      expect.unreachable('should have thrown');
    } catch (e) {
      expect((e as OepcParseError).code).toBe('truncated_body');
    }
  });
});
