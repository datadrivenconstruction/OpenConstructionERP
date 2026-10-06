import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchBIMDataframeColumnValues } from '../api';

afterEach(() => vi.unstubAllGlobals());

describe('column values pagination', () => {
  it('loads only the requested page, preserving total, slash column and cancellation', async () => {
    const values = Array.from({ length: 205 }, (_, i) => ({ value: `v${i}`, count: 205 - i }));
    const ctrl = new AbortController();
    const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
      const params = new URL(url, 'http://test').searchParams;
      expect(params.get('column')).toBe('Width/Height');
      expect(init.signal).toBe(ctrl.signal);
      const offset = Number(params.get('offset'));
      const limit = Number(params.get('limit'));
      return new Response(JSON.stringify({ items: values.slice(offset, offset + limit), total: 205, offset, limit }), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);
    const first = await fetchBIMDataframeColumnValues('model', 'Width/Height', 100, ctrl.signal);
    expect(first.items).toHaveLength(100);
    expect(first.total).toBe(205);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const next = await fetchBIMDataframeColumnValues('model', 'Width/Height', 100, ctrl.signal, 100);
    expect(next.items[0]?.value).toBe('v100');
    expect(next.offset).toBe(100);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('rejects incorrect paging metadata instead of presenting it as a complete set', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [], total: 3, offset: -1, limit: 100 }))));
    await expect(fetchBIMDataframeColumnValues('model', 'Width/Height', 100)).rejects.toThrow('Invalid');
  });

  it('propagates invalid paging rejection from the server', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 422 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(fetchBIMDataframeColumnValues('model', 'Width/Height', 0)).rejects.toThrow();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
