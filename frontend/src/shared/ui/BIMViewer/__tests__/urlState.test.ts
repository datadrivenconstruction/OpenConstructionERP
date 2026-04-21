import { describe, expect, it } from 'vitest';
import {
  parseBIMUrlState,
  serializeBIMUrlState,
  BIM_URL_STATE_KEYS,
  type BIMUrlState,
} from '../urlState';

describe('serializeBIMUrlState + parseBIMUrlState — round-trip', () => {
  it('round-trips a camera + multi-selection exactly (within 3-decimal precision)', () => {
    const original: BIMUrlState = {
      camera: {
        position: { x: 12.345, y: -6.789, z: 0.001 },
        target: { x: -1, y: 0, z: 7.5 },
      },
      selection: ['elem-1', 'elem-2', 'elem-3'],
    };
    const params = new URLSearchParams(serializeBIMUrlState(original));
    const parsed = parseBIMUrlState(params);
    expect(parsed.camera).not.toBeNull();
    expect(parsed.camera!.position.x).toBeCloseTo(12.345, 3);
    expect(parsed.camera!.position.y).toBeCloseTo(-6.789, 3);
    expect(parsed.camera!.position.z).toBeCloseTo(0.001, 3);
    expect(parsed.camera!.target.x).toBeCloseTo(-1, 3);
    expect(parsed.camera!.target.y).toBeCloseTo(0, 3);
    expect(parsed.camera!.target.z).toBeCloseTo(7.5, 3);
    expect(parsed.selection).toEqual(['elem-1', 'elem-2', 'elem-3']);
  });

  it('rounds camera coordinates to 3 decimals so URLs stay compact', () => {
    const payload = serializeBIMUrlState({
      camera: {
        position: { x: 1.234567, y: 0, z: 0 },
        target: { x: 0, y: 0, z: 0 },
      },
      selection: [],
    });
    expect(payload.cx).toBe('1.235');
  });

  it('omits selection key when empty — keeps URL short', () => {
    const payload = serializeBIMUrlState({
      camera: {
        position: { x: 1, y: 2, z: 3 },
        target: { x: 0, y: 0, z: 0 },
      },
      selection: [],
    });
    expect(payload).not.toHaveProperty('sel');
  });

  it('omits camera keys when camera is null', () => {
    const payload = serializeBIMUrlState({
      camera: null,
      selection: ['a', 'b'],
    });
    expect(payload).not.toHaveProperty('cx');
    expect(payload).not.toHaveProperty('tx');
    expect(payload.sel).toBe('a,b');
  });

  it('parses empty params → null camera + empty selection', () => {
    const parsed = parseBIMUrlState(new URLSearchParams());
    expect(parsed.camera).toBeNull();
    expect(parsed.selection).toEqual([]);
  });

  it('treats a partial camera (missing tz) as no camera — never apply a half-set view', () => {
    const parsed = parseBIMUrlState(
      new URLSearchParams('cx=1&cy=2&cz=3&tx=0&ty=0'),
    );
    expect(parsed.camera).toBeNull();
  });

  it('filters out blank selection ids from trailing commas', () => {
    const parsed = parseBIMUrlState(new URLSearchParams('sel=a,,b,'));
    expect(parsed.selection).toEqual(['a', 'b']);
  });

  it('ignores non-finite camera coords (NaN / Infinity) — empty string, letters', () => {
    const parsed = parseBIMUrlState(
      new URLSearchParams('cx=abc&cy=2&cz=3&tx=0&ty=0&tz=0'),
    );
    expect(parsed.camera).toBeNull();
  });

  it('round-trips a single-id selection', () => {
    const params = new URLSearchParams(
      serializeBIMUrlState({ camera: null, selection: ['only-one'] }),
    );
    expect(parseBIMUrlState(params).selection).toEqual(['only-one']);
  });

  it('exports a stable list of keys (contract for URL cleanup)', () => {
    // If this list ever changes, callers that merge params need updating.
    expect(BIM_URL_STATE_KEYS).toEqual(['cx', 'cy', 'cz', 'tx', 'ty', 'tz', 'sel']);
  });

  it('round-trip: parse(serialize(x)) === x for the concrete shape (coords close)', () => {
    const cases: BIMUrlState[] = [
      { camera: null, selection: [] },
      {
        camera: { position: { x: 0, y: 0, z: 0 }, target: { x: 0, y: 0, z: 0 } },
        selection: [],
      },
      {
        camera: {
          position: { x: -50.5, y: 22.25, z: 10 },
          target: { x: 1.111, y: 2.222, z: 3.333 },
        },
        selection: ['uuid-1', 'uuid-2'],
      },
    ];
    for (const original of cases) {
      const params = new URLSearchParams(serializeBIMUrlState(original));
      const parsed = parseBIMUrlState(params);
      if (original.camera === null) {
        expect(parsed.camera).toBeNull();
      } else {
        expect(parsed.camera).not.toBeNull();
        expect(parsed.camera!.position.x).toBeCloseTo(original.camera.position.x, 2);
        expect(parsed.camera!.target.z).toBeCloseTo(original.camera.target.z, 2);
      }
      expect(parsed.selection).toEqual(original.selection);
    }
  });
});
