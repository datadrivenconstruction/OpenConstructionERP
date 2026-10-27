// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Site sensor​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ data helpers: grouping, online state and strength progress.
 * Pure functions with no React, so they are easy to test.
 */
import type { SensorKind } from './api';

/** Display order of the sensor groups. */
export const KIND_ORDER: readonly SensorKind[] = [
  'concrete_maturity',
  'noise',
  'dust_pm10',
  'vibration',
  'weather',
  'water_level',
];

/** English fallbacks for `site_sensors.kind.<kind>`. */
export const KIND_LABELS: Record<SensorKind, string> = {
  concrete_maturity: 'Concrete maturity',
  noise: 'Noise',
  dust_pm10: 'Dust PM10',
  vibration: 'Vibration',
  weather: 'Weather',
  water_level: 'Water level',
};

export function isSensorKind(value: string): value is SensorKind {
  return (KIND_ORDER as readonly string[]).includes(value);
}

/** Devices bucketed by kind in display order; empty kinds are left out. */
export function groupByKind<T extends { kind: string }>(devices: readonly T[]): { kind: SensorKind; devices: T[] }[] {
  const buckets = new Map<SensorKind, T[]>();
  for (const d of devices) {
    if (!isSensorKind(d.kind)) continue;
    const list = buckets.get(d.kind) ?? [];
    list.push(d);
    buckets.set(d.kind, list);
  }
  return KIND_ORDER.filter((k) => buckets.has(k)).map((kind) => ({ kind, devices: buckets.get(kind) ?? [] }));
}

/** A sensor is online when it is active and reported inside its offline window. */
export function isOnline(
  device: { active: boolean; last_seen_at: string | null; offline_after_minutes: number },
  now: number = Date.now(),
): boolean {
  if (!device.active || !device.last_seen_at) return false;
  const seen = Date.parse(device.last_seen_at);
  if (Number.isNaN(seen)) return false;
  return now - seen <= device.offline_after_minutes * 60_000;
}

export function countOnline(
  devices: readonly { active: boolean; last_seen_at: string | null; offline_after_minutes: number }[],
  now: number = Date.now(),
): number {
  return devices.filter((d) => isOnline(d, now)).length;
}

/** Estimated strength as a share (0-100) of the target; null when either is unknown. */
export function strengthProgressPct(strength: number | null | undefined, target: number | null | undefined): number | null {
  if (strength === null || strength === undefined || target === null || target === undefined) return null;
  if (!Number.isFinite(strength) || !Number.isFinite(target) || target <= 0) return null;
  return Math.min(100, Math.max(0, (strength / target) * 100));
}

/** True when a reading is above a set limit. */
export function overLimit(value: number | null | undefined, limit: string | number | null | undefined): boolean {
  if (value === null || value === undefined || limit === null || limit === undefined || limit === '') return false;
  const l = Number(limit);
  return Number.isFinite(l) && value > l;
}

/** True when a struck strip reached less strength than its target. */
export function struckBelowTarget(strip: {
  struck_at: string | null;
  strength_at_strike_mpa: string | null;
  target_strength_mpa: string;
}): boolean {
  if (!strip.struck_at || strip.strength_at_strike_mpa === null) return false;
  return Number(strip.strength_at_strike_mpa) < Number(strip.target_strength_mpa);
}

/** `datetime-local` value for "now", in local time. */
export function localDateTimeValue(d: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** ISO instant from a `datetime-local` value, or null when it is empty or invalid. */
export function isoFromLocal(value: string): string | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}
