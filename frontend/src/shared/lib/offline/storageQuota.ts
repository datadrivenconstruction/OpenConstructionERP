// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Storage guard for the offline queue.
 *
 * Photos taken with no signal pile up in IndexedDB until the next sync. On a
 * phone that can mean a full disk and a browser that evicts the lot, so the
 * field shell does three things with this module: shrinks a photo before it is
 * stored, refuses to store one when the device is nearly full, and tells the
 * person how much is waiting and for how long.
 *
 * Everything that decides is pure and takes its inputs as arguments, so it is
 * tested without a browser. The browser calls are thin wrappers that degrade to
 * "unknown" (and therefore "allow") when the platform does not offer them.
 */

import type { QueuedOp } from './mutationQueue';
import { fmtFixed } from '../formatters';

/** Longest edge of a stored photo, in pixels. */
export const PHOTO_MAX_EDGE = 1600;
/** JPEG quality of a stored photo. */
export const PHOTO_QUALITY = 0.8;
/** Share of the quota at which the person is warned. */
export const QUOTA_WARN_RATIO = 0.8;
/** Share of the quota at which new photos are refused. */
export const QUOTA_FULL_RATIO = 0.95;

export type QuotaLevel = 'ok' | 'warn' | 'full';

export interface StorageEstimateLike {
  usage?: number;
  quota?: number;
}

/** Size after scaling the longest edge down to `maxEdge`; never scales up. */
export function downscaleDimensions(
  width: number,
  height: number,
  maxEdge: number = PHOTO_MAX_EDGE,
): { width: number; height: number } {
  if (!(width > 0) || !(height > 0)) return { width: 0, height: 0 };
  const longest = Math.max(width, height);
  if (longest <= maxEdge) return { width: Math.round(width), height: Math.round(height) };
  const scale = maxEdge / longest;
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

/** How full the device is. Unknown figures count as fine: never block on a guess. */
export function quotaLevel(estimate: StorageEstimateLike | null | undefined): QuotaLevel {
  const usage = estimate?.usage;
  const quota = estimate?.quota;
  if (typeof usage !== 'number' || typeof quota !== 'number' || quota <= 0) return 'ok';
  const ratio = usage / quota;
  if (ratio >= QUOTA_FULL_RATIO) return 'full';
  if (ratio >= QUOTA_WARN_RATIO) return 'warn';
  return 'ok';
}

/** True when `bytes` more can be stored without crossing the "full" line. */
export function canStore(bytes: number, estimate: StorageEstimateLike | null | undefined): boolean {
  const usage = estimate?.usage;
  const quota = estimate?.quota;
  if (typeof usage !== 'number' || typeof quota !== 'number' || quota <= 0) return true;
  return (usage + Math.max(0, bytes)) / quota < QUOTA_FULL_RATIO;
}

export interface BacklogSummary {
  count: number;
  bytes: number;
  /** Whole days since the oldest waiting op was captured; 0 when nothing waits. */
  oldestDays: number;
}

const DAY_MS = 86_400_000;

function bodyBytes(op: QueuedOp): number {
  if (op.body === undefined || op.body === null) return 0;
  try {
    return new TextEncoder().encode(JSON.stringify(op.body)).length;
  } catch {
    return 0;
  }
}

/**
 * What is waiting to sync: how many, how large and how old. `photoBytes` is the
 * total of photo blobs held beside the ops, which the queue itself does not see.
 */
export function summariseBacklog(ops: readonly QueuedOp[], now: number, photoBytes = 0): BacklogSummary {
  if (ops.length === 0) return { count: 0, bytes: Math.max(0, photoBytes), oldestDays: 0 };
  let bytes = Math.max(0, photoBytes);
  let oldest = now;
  for (const op of ops) {
    bytes += bodyBytes(op);
    if (op.queuedAt < oldest) oldest = op.queuedAt;
  }
  return { count: ops.length, bytes, oldestDays: Math.max(0, Math.floor((now - oldest) / DAY_MS)) };
}

/** "512 B", "18.4 KB", "18 MB": short enough for a pill. */
export function formatBytes(bytes: number): string {
  if (!(bytes > 0)) return '0 B';
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb < 10 ? fmtFixed(kb, 1) : Math.round(kb)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb < 10 ? fmtFixed(mb, 1) : Math.round(mb)} MB`;
  return `${fmtFixed(mb / 1024, 1)} GB`;
}

/* ── Browser wrappers ──────────────────────────────────────────────────── */

/** `navigator.storage.estimate()`, or null where the platform has none. */
export async function readStorageEstimate(): Promise<StorageEstimateLike | null> {
  try {
    if (typeof navigator === 'undefined' || !navigator.storage?.estimate) return null;
    return await navigator.storage.estimate();
  } catch {
    return null;
  }
}

/**
 * Ask the browser not to evict our data (iOS Safari and Chrome both may under
 * pressure). Returns whether storage is now persistent; false is a warning
 * signal for the caller, not an error.
 */
export async function requestPersistentStorage(): Promise<boolean> {
  try {
    if (typeof navigator === 'undefined' || !navigator.storage?.persist) return false;
    if (navigator.storage.persisted && (await navigator.storage.persisted())) return true;
    return await navigator.storage.persist();
  } catch {
    return false;
  }
}

/**
 * Shrink a photo before it is stored: longest edge 1600 px, JPEG at 0.8. Returns
 * the original blob when the platform cannot decode or encode it, or when the
 * result would not be smaller, so a capture is never lost to the optimisation.
 */
export async function downscalePhoto(blob: Blob): Promise<Blob> {
  try {
    if (typeof createImageBitmap !== 'function' || typeof document === 'undefined') return blob;
    const bitmap = await createImageBitmap(blob);
    const { width, height } = downscaleDimensions(bitmap.width, bitmap.height);
    if (width === bitmap.width && height === bitmap.height && blob.type === 'image/jpeg') {
      bitmap.close?.();
      return blob;
    }
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      bitmap.close?.();
      return blob;
    }
    ctx.drawImage(bitmap, 0, 0, width, height);
    bitmap.close?.();
    const out: Blob | null = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', PHOTO_QUALITY));
    return out && out.size > 0 && out.size < blob.size ? out : blob;
  } catch {
    return blob;
  }
}
