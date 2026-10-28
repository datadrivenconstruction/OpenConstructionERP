// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Evidence-grade photo capture for field items (punch items, defects).
 *
 * At the moment a photo is attached the browser can tell us where the device
 * is (with an accuracy radius), what its clock says, and which way it points.
 * `captureDeviceEvidence` collects what the device will give without ever
 * blocking the upload: a refused permission or a desktop without sensors
 * simply yields fewer fields. The server reads EXIF from the file itself and
 * hashes the stored bytes, so the record the API returns (`PhotoEvidence`)
 * carries both sources side by side.
 */

export interface DeviceCapture {
  lat?: number;
  lon?: number;
  accuracyM?: number;
  altitudeM?: number;
  capturedAt: string;
  headingDeg?: number;
  pitchDeg?: number;
  rollDeg?: number;
  /** Why no location was captured, when it was not. */
  locationError?: 'denied' | 'unavailable' | 'timeout' | 'unsupported';
}

export interface EvidenceLocation {
  lat: number;
  lon: number;
  accuracy_m: number | null;
  source: 'device' | 'exif';
}

/** The record the API stores per photo (see backend app/core/photo_evidence.py). */
export interface PhotoEvidence {
  path: string;
  sha256: string;
  original_sha256?: string;
  size_bytes: number;
  received_at: string;
  uploaded_by?: string | null;
  exif: Record<string, unknown>;
  device: Record<string, unknown> | null;
  location: EvidenceLocation | null;
  captured_at: { value: string; source: 'device' | 'exif' | 'server' } | null;
  orientation: { heading_deg?: number; pitch_deg?: number; roll_deg?: number; exif_orientation?: number } | null;
  grade: 'full' | 'basic' | 'none';
  imported_from?: string;
}

const GEO_TIMEOUT_MS = 8000;
const ORIENTATION_WAIT_MS = 600;

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function readPosition(): Promise<Partial<DeviceCapture>> {
  if (typeof navigator === 'undefined' || !navigator.geolocation) {
    return Promise.resolve({ locationError: 'unsupported' });
  }
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const c = pos.coords;
        resolve({
          lat: c.latitude,
          lon: c.longitude,
          accuracyM: finite(c.accuracy) ? c.accuracy : undefined,
          altitudeM: finite(c.altitude) ? c.altitude : undefined,
          headingDeg: finite(c.heading) ? c.heading : undefined,
        });
      },
      (err) => {
        const code = err?.code;
        resolve({ locationError: code === 1 ? 'denied' : code === 3 ? 'timeout' : 'unavailable' });
      },
      { enableHighAccuracy: true, timeout: GEO_TIMEOUT_MS, maximumAge: 30_000 },
    );
  });
}

type OrientationEventCtor = typeof DeviceOrientationEvent & { requestPermission?: () => Promise<string> };

async function readOrientation(): Promise<Partial<DeviceCapture>> {
  if (typeof window === 'undefined' || typeof DeviceOrientationEvent === 'undefined') return {};
  const ctor = DeviceOrientationEvent as OrientationEventCtor;
  try {
    // iOS asks for permission; it must be requested inside the user gesture that opened the picker.
    if (typeof ctor.requestPermission === 'function') {
      const state = await ctor.requestPermission();
      if (state !== 'granted') return {};
    }
  } catch {
    return {};
  }
  return new Promise((resolve) => {
    const done = (value: Partial<DeviceCapture>) => {
      window.removeEventListener('deviceorientation', onEvent);
      clearTimeout(timer);
      resolve(value);
    };
    const onEvent = (ev: DeviceOrientationEvent) => {
      const webkit = (ev as DeviceOrientationEvent & { webkitCompassHeading?: number }).webkitCompassHeading;
      const heading = finite(webkit) ? webkit : finite(ev.alpha) ? (360 - ev.alpha) % 360 : undefined;
      done({
        headingDeg: heading,
        pitchDeg: finite(ev.beta) ? ev.beta : undefined,
        rollDeg: finite(ev.gamma) ? ev.gamma : undefined,
      });
    };
    const timer = setTimeout(() => done({}), ORIENTATION_WAIT_MS);
    window.addEventListener('deviceorientation', onEvent);
  });
}

/** Collect location, clock and orientation; never rejects. */
export async function captureDeviceEvidence(): Promise<DeviceCapture> {
  const capturedAt = new Date().toISOString();
  const [position, orientation] = await Promise.all([readPosition(), readOrientation()]);
  return {
    capturedAt,
    ...orientation,
    ...position,
    // A compass heading from the orientation sensor beats the GPS course.
    headingDeg: orientation.headingDeg ?? position.headingDeg,
  };
}

/** Append the capture as the `capture_*` form fields the photo endpoints accept. */
export function appendCaptureFields(form: FormData, capture: DeviceCapture | null | undefined): void {
  if (!capture) return;
  const put = (key: string, value: number | string | undefined) => {
    if (value === undefined || value === null || value === '') return;
    form.append(key, String(value));
  };
  put('captured_at', capture.capturedAt);
  if (finite(capture.lat) && finite(capture.lon)) {
    put('capture_lat', capture.lat);
    put('capture_lon', capture.lon);
    put('capture_accuracy_m', capture.accuracyM);
    put('capture_altitude_m', capture.altitudeM);
  }
  put('capture_heading_deg', capture.headingDeg);
  put('capture_pitch_deg', capture.pitchDeg);
  put('capture_roll_deg', capture.rollDeg);
}

/** Map pins from items that carry a WGS84 position. */
export interface MapPin {
  id: string;
  lat: number;
  lon: number;
  label: string;
  tone?: 'open' | 'progress' | 'done' | 'critical';
}

export function hasValidPin(lat: unknown, lon: unknown): boolean {
  return (
    finite(lat) &&
    finite(lon) &&
    Math.abs(lat) <= 90 &&
    Math.abs(lon) <= 180 &&
    !(Math.abs(lat) < 1e-9 && Math.abs(lon) < 1e-9)
  );
}

/** Short compass label (N, NE, ...) for a heading in degrees. */
export function compassPoint(deg: number): string {
  const points = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
  const idx = Math.round((((deg % 360) + 360) % 360) / 45) % 8;
  return points[idx]!;
}
