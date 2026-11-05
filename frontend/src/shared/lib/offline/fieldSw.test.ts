import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';

describe('field-sw.js clear message', () => {
  it('drops the data cache on oe-field-clear', async () => {
    const handlers: Record<string, (e: unknown) => void> = {};
    const del = vi.fn().mockResolvedValue(true);
    const selfStub = { addEventListener: (t: string, h: (e: unknown) => void) => (handlers[t] = h), clients: {} };
    const src = readFileSync(resolve(__dirname, '../../../../public/field-sw.js'), 'utf8');
    new Function('self', 'caches', src)(selfStub, {
      keys: async () => ['oe-field-data-v1', 'oe-field-shell-v1'],
      delete: del,
    });
    let pending: Promise<unknown> = Promise.resolve();
    handlers.message!({ data: { type: 'oe-field-clear' }, waitUntil: (p: Promise<unknown>) => (pending = p) });
    await pending;
    expect(del).toHaveBeenCalledWith('oe-field-data-v1');
    expect(del).not.toHaveBeenCalledWith('oe-field-shell-v1');
  });
});
