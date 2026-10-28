// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Minimal, no-backend client telemetry.
 *
 * The codebase has no analytics/track util and no client-event ingest
 * endpoint (the `/analytics` route is a server-side cost dashboard, not
 * an event sink). Inventing a backend endpoint is explicitly out of
 * scope, so this is a self-contained, privacy-safe event recorder:
 *
 *  • In-memory ring buffer (last `MAX_EVENTS`) — readable for QA/debug
 *    via `getTelemetryBuffer()`.
 *  • Mirrors to a localStorage ring so events survive a reload (useful
 *    for "did the user finish setup?" funnels without a server).
 *  • `console.debug` in dev only — silent in production.
 *
 * No PII: callers pass small primitive props (preset id, module name,
 * step number). Free-text (project name, address) must never be passed.
 */

export type TelemetryEvent =
  | 'wizard_started'
  | 'preset_selected'
  | 'module_toggled'
  | 'setup_completed'
  | 'setup_rerun';

export interface TelemetryRecord {
  event: TelemetryEvent;
  ts: number;
  props: Record<string, string | number | boolean>;
}

const MAX_EVENTS = 100;
const LS_KEY = 'oe_telemetry_buffer';

const buffer: TelemetryRecord[] = [];

function readLs(): TelemetryRecord[] {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as TelemetryRecord[]) : [];
  } catch {
    return [];
  }
}

function writeLs(records: TelemetryRecord[]) {
  try {
    localStorage.setItem(
      LS_KEY,
      JSON.stringify(records.slice(-MAX_EVENTS)),
    );
  } catch {
    /* storage full / unavailable — telemetry is best-effort */
  }
}

/** Record a single product-analytics event. Never throws. */
export function track(
  event: TelemetryEvent,
  props: Record<string, string | number | boolean> = {},
): void {
  const record: TelemetryRecord = { event, ts: Date.now(), props };
  buffer.push(record);
  if (buffer.length > MAX_EVENTS) buffer.shift();

  // Persist across reloads so the setup funnel is reconstructable
  // client-side without a backend.
  const ls = readLs();
  ls.push(record);
  writeLs(ls);

  if (import.meta.env.DEV) {
    // eslint-disable-next-line no-console
    console.debug('[telemetry]', event, props);
  }
}

/** In-memory event buffer (most recent last) — for QA / debug only. */
export function getTelemetryBuffer(): readonly TelemetryRecord[] {
  return buffer;
}

/** React-friendly accessor. Returns a stable `track` reference; the
 *  module-level function is already a singleton so no memoisation is
 *  needed and the hook stays dependency-free. */
export function useTelemetry(): {
  track: typeof track;
} {
  return { track };
}
