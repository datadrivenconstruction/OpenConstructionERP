import { beforeEach, describe, expect, it, vi } from 'vitest';

const http = vi.hoisted(() => ({ apiGet: vi.fn(), apiPut: vi.fn(), apiPost: vi.fn() }));
vi.mock('@/shared/lib/api', async () => {
  class ApiError extends Error {
    constructor(public status: number, message: string, public body?: unknown) {
      super(message);
    }
  }
  return { ...http, ApiError };
});

import { confirmBrief, fetchBrief, saveBrief } from './api';
import type { BriefDoc } from './data/briefModel';

const doc = { schema: 'ddc-brief/1' } as BriefDoc;

beforeEach(() => Object.values(http).forEach((f) => f.mockReset().mockResolvedValue(doc)));

describe('brief API client announces the link version', () => {
  it('sends X-DDC-Link on read, save and confirm', async () => {
    await fetchBrief('p1');
    await saveBrief('p1', doc, 0);
    await confirmBrief('p1', ['/name'], 2);
    expect(http.apiGet.mock.calls[0]![1].headers).toEqual({ 'X-DDC-Link': '1' });
    expect(http.apiPut.mock.calls[0]![2].headers).toEqual({ 'X-DDC-Link': '1' });
    expect(http.apiPost.mock.calls[0]![2].headers).toEqual({ 'X-DDC-Link': '1', 'If-Match': '"2"' });
  });

  it('adds If-Match once a version exists, and ?draft=true only for a draft', async () => {
    await saveBrief('p1', doc, 3);
    await saveBrief('p1', doc, 0, true);
    expect(http.apiPut.mock.calls[0]![0]).toBe('/v1/design/projects/p1/brief');
    expect(http.apiPut.mock.calls[0]![2].headers['If-Match']).toBe('"3"');
    expect(http.apiPut.mock.calls[1]![0]).toBe('/v1/design/projects/p1/brief?draft=true');
    expect(http.apiPut.mock.calls[1]![2].headers['If-Match']).toBeUndefined();
  });
});
