import { afterEach, describe, expect, it, vi } from 'vitest';
import { appendCaptureFields, captureDeviceEvidence, compassPoint, hasValidPin } from './photoEvidence';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('appendCaptureFields', () => {
  it('sends location only with both coordinates and keeps orientation', () => {
    const form = new FormData();
    appendCaptureFields(form, { capturedAt: '2026-10-25T09:00:00Z', lat: 48.1, lon: 11.5, accuracyM: 6, headingDeg: 90 });
    expect(form.get('capture_lat')).toBe('48.1');
    expect(form.get('capture_accuracy_m')).toBe('6');
    expect(form.get('capture_heading_deg')).toBe('90');
    expect(form.get('captured_at')).toBe('2026-10-25T09:00:00Z');
  });

  it('drops a half location and ignores a missing capture', () => {
    const form = new FormData();
    appendCaptureFields(form, { capturedAt: 'x', lat: 48.1, accuracyM: 6 });
    expect(form.get('capture_lat')).toBeNull();
    expect(form.get('capture_accuracy_m')).toBeNull();
    appendCaptureFields(form, null);
    expect([...form.keys()]).toEqual(['captured_at']);
  });
});

describe('pins and compass', () => {
  it('rejects null island, out of range and non numbers', () => {
    expect(hasValidPin(52.5, 13.4)).toBe(true);
    expect(hasValidPin(0, 0)).toBe(false);
    expect(hasValidPin(91, 0)).toBe(false);
    expect(hasValidPin(null, 13)).toBe(false);
  });

  it('maps headings to eight points', () => {
    expect(compassPoint(0)).toBe('N');
    expect(compassPoint(44)).toBe('NE');
    expect(compassPoint(180)).toBe('S');
    expect(compassPoint(-90)).toBe('W');
    expect(compassPoint(350)).toBe('N');
  });
});

describe('captureDeviceEvidence', () => {
  it('reports a refused location without failing', async () => {
    vi.stubGlobal('navigator', {
      geolocation: {
        getCurrentPosition: (_ok: unknown, err: (e: { code: number }) => void) => err({ code: 1 }),
      },
    });
    const capture = await captureDeviceEvidence();
    expect(capture.locationError).toBe('denied');
    expect(capture.lat).toBeUndefined();
    expect(capture.capturedAt).toMatch(/T/);
  });

  it('returns the fix with its accuracy', async () => {
    vi.stubGlobal('navigator', {
      geolocation: {
        getCurrentPosition: (ok: (p: unknown) => void) =>
          ok({ coords: { latitude: 1.5, longitude: 2.5, accuracy: 7, altitude: null, heading: null } }),
      },
    });
    const capture = await captureDeviceEvidence();
    expect(capture).toMatchObject({ lat: 1.5, lon: 2.5, accuracyM: 7 });
  });
});
