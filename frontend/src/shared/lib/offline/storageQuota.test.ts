import { describe, expect, it } from 'vitest';
import {
  canStore,
  downscaleDimensions,
  formatBytes,
  quotaLevel,
  summariseBacklog,
  PHOTO_MAX_EDGE,
} from './storageQuota';
import type { QueuedOp } from './mutationQueue';

const op = (queuedAt: number, body: unknown = {}): QueuedOp =>
  ({ clientOpId: `op-${queuedAt}`, method: 'POST', path: '/x', body, kind: 'k', queuedAt, retries: 0 }) as QueuedOp;

describe('downscaleDimensions', () => {
  it('shrinks the longest edge to 1600 and keeps the ratio', () => {
    expect(downscaleDimensions(4000, 3000)).toEqual({ width: 1600, height: 1200 });
    expect(downscaleDimensions(3000, 4000)).toEqual({ width: 1200, height: 1600 });
  });
  it('never scales up', () => {
    expect(downscaleDimensions(800, 600)).toEqual({ width: 800, height: 600 });
    expect(downscaleDimensions(PHOTO_MAX_EDGE, 10)).toEqual({ width: PHOTO_MAX_EDGE, height: 10 });
  });
  it('returns zero for a broken size', () => {
    expect(downscaleDimensions(0, 100)).toEqual({ width: 0, height: 0 });
  });
});

describe('quota guard', () => {
  it('warns at 80% and is full at 95%', () => {
    expect(quotaLevel({ usage: 50, quota: 100 })).toBe('ok');
    expect(quotaLevel({ usage: 80, quota: 100 })).toBe('warn');
    expect(quotaLevel({ usage: 95, quota: 100 })).toBe('full');
  });
  it('treats an unknown estimate as fine', () => {
    expect(quotaLevel(null)).toBe('ok');
    expect(quotaLevel({})).toBe('ok');
    expect(canStore(10_000_000, null)).toBe(true);
  });
  it('refuses a photo that would cross the full line', () => {
    expect(canStore(4, { usage: 90, quota: 100 })).toBe(true);
    expect(canStore(6, { usage: 90, quota: 100 })).toBe(false);
  });
});

describe('summariseBacklog', () => {
  it('is empty with nothing waiting', () => {
    expect(summariseBacklog([], 1000)).toEqual({ count: 0, bytes: 0, oldestDays: 0 });
  });
  it('counts ops, sizes and the age of the oldest in whole days', () => {
    const now = 10 * 86_400_000;
    const s = summariseBacklog([op(now - 3 * 86_400_000 - 5, { a: 'xx' }), op(now - 1000)], now, 1000);
    expect(s.count).toBe(2);
    expect(s.oldestDays).toBe(3);
    expect(s.bytes).toBeGreaterThan(1000);
  });
});

describe('formatBytes', () => {
  it('stays short', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(900)).toBe('900 B');
    expect(formatBytes(2048)).toBe('2.0 KB');
    expect(formatBytes(18 * 1024 * 1024)).toBe('18 MB');
  });
});

describe('summariseBacklog bytes', () => {
  it('counts UTF-8 bytes, not string length', () => {
    const body = { t: 'Штукатурка' }; // 10 Cyrillic chars, 2 bytes each
    const expected = new TextEncoder().encode(JSON.stringify(body)).length;
    const s = summariseBacklog([op(1000, body)], 2000);
    expect(s.bytes).toBe(expected);
    expect(s.bytes).toBeGreaterThan(JSON.stringify(body).length);
  });
});
