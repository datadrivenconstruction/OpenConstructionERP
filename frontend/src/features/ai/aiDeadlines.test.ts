// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { aiApi } from './api';
import { matchElementsApi } from '../match-elements/api';
import { intakeApi } from './intake/api';
import { apiGet, apiPost } from '@/shared/lib/api';
import { queueMutation } from '@/shared/lib/offlineStore';

vi.mock('@/shared/lib/errorLogger', () => ({ logError: vi.fn(), logApiError: vi.fn() }));
vi.mock('@/shared/lib/offlineStore', () => ({
  cacheResponse: vi.fn(), getCachedResponse: vi.fn().mockResolvedValue(null), queueMutation: vi.fn(),
}));
vi.mock('@/stores/useAuthStore', () => ({ useAuthStore: { getState: () => ({ accessToken: 'test-token' }) } }));
vi.mock('@/stores/useToastStore', () => ({ useToastStore: { getState: () => ({ addToast: vi.fn() }) } }));

const file = new File(['sample'], 'sample.png', { type: 'image/png' });
const quick = { description: 'A small building' };
type Operation = (signal?: AbortSignal) => Promise<unknown>;
const slowCalls: [string, Operation][] = [
  ['quick estimate', (signal) => aiApi.quickEstimate(quick, signal ? { signal } : undefined)],
  ['photo estimate', (signal) => aiApi.photoEstimate({ file, signal })],
  ['file estimate', (signal) => aiApi.fileEstimate({ file, signal })],
  ['match', (signal) => matchElementsApi.runMatch('session', { method: 'llm' }, { signal })],
  ['pipeline stage', () => matchElementsApi.runStage('session', 'schema')],
  ['match image', (signal) => matchElementsApi.createSessionFromImage({ project_id: 'project', file, signal })],
  ['match PDF', (signal) => matchElementsApi.createSessionFromPdf({ project_id: 'project', file, signal })],
  ['match Excel', (signal) => matchElementsApi.createSessionFromExcel({ project_id: 'project', file, signal })],
];

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

function stalledFetch() {
  let finish = () => {};
  const fetch = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((resolve, reject) => {
    finish = () => resolve(new Response('{}', { headers: { 'Content-Type': 'application/json' } }));
    if (init?.signal?.aborted) reject(init.signal.reason);
    else init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true });
  }));
  vi.stubGlobal('fetch', fetch);
  return { fetch, finish: () => finish() };
}

it.each(slowCalls)('%s survives 90 seconds and stops at five minutes without replay', async (_name, operation) => {
  const server = stalledFetch();
  const outcome = operation().catch((error: unknown) => error);
  try {
    await vi.advanceTimersByTimeAsync(90_001);
    expect(server.fetch.mock.calls[0]?.[1]?.signal?.aborted).not.toBe(true);
    await vi.advanceTimersByTimeAsync(209_999);
    expect(server.fetch.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
    expect(await outcome).toBeInstanceOf(Error);
    expect(server.fetch).toHaveBeenCalledTimes(1);
  } finally {
    server.finish();
    await outcome;
  }
});

it.each(slowCalls.filter(([name]) => name !== 'pipeline stage'))('%s keeps a deadline with a caller signal', async (_name, operation) => {
  const server = stalledFetch();
  const caller = new AbortController();
  const outcome = operation(caller.signal).catch((error: unknown) => error);
  try {
    await vi.advanceTimersByTimeAsync(300_000);
    expect(server.fetch.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
    expect(caller.signal.aborted).toBe(false);
    expect(await outcome).toBeInstanceOf(Error);
  } finally {
    server.finish();
    await outcome;
  }
});

it.each(slowCalls.filter(([name]) => name !== 'pipeline stage'))('%s still honours immediate user cancellation', async (_name, operation) => {
  const server = stalledFetch();
  const caller = new AbortController();
  const outcome = operation(caller.signal).catch((error: unknown) => error);
  caller.abort();
  expect(await outcome).toBeInstanceOf(Error);
  expect(server.fetch.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
  expect(server.fetch).toHaveBeenCalledTimes(1);
  expect(vi.getTimerCount()).toBe(0);
});

it('does not queue a cancelled request for replay when the browser goes offline', async () => {
  const server = stalledFetch();
  const caller = new AbortController();
  const outcome = aiApi.quickEstimate(quick, { signal: caller.signal }).catch((error: unknown) => error);
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
  caller.abort();
  expect(await outcome).toMatchObject({ name: 'AbortError' });
  expect(queueMutation).not.toHaveBeenCalled();
  expect(server.fetch).toHaveBeenCalledTimes(1);
});

it.each(['read', 'mutation'])('does not raise the ordinary %s budget', async (kind) => {
  const server = stalledFetch();
  const outcome = (kind === 'read' ? apiGet('/v1/sample') : apiPost('/v1/sample', {})).catch((error: unknown) => error);
  await vi.advanceTimersByTimeAsync(90_000);
  expect(await outcome).toMatchObject({ isTimeout: true });
  expect(server.fetch).toHaveBeenCalledTimes(1);
});

it('keeps already-long-running intake extraction at five minutes', async () => {
  const server = stalledFetch();
  const outcome = intakeApi.start({ text: 'A building' } as Parameters<typeof intakeApi.start>[0]).catch((error: unknown) => error);
  await vi.advanceTimersByTimeAsync(90_001);
  expect(server.fetch.mock.calls[0]?.[1]?.signal?.aborted).toBe(false);
  await vi.advanceTimersByTimeAsync(209_999);
  expect(await outcome).toMatchObject({ isTimeout: true });
  expect(server.fetch).toHaveBeenCalledTimes(1);
});

it.each(slowCalls)('%s releases its timer after a successful response', async (_name, operation) => {
  const fetch = vi.fn().mockResolvedValue(new Response('{"ok":true}', {
    headers: { 'Content-Type': 'application/json' },
  }));
  vi.stubGlobal('fetch', fetch);
  expect(await operation()).toEqual({ ok: true });
  expect(vi.getTimerCount()).toBe(0);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it.each(slowCalls)('%s preserves a server refusal and never repeats the request', async (_name, operation) => {
  const fetch = vi.fn().mockResolvedValue(new Response('{"detail":"Readable refusal"}', {
    status: 422, headers: { 'Content-Type': 'application/json' },
  }));
  vi.stubGlobal('fetch', fetch);
  await expect(operation()).rejects.toThrow('Readable refusal');
  expect(vi.getTimerCount()).toBe(0);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it.each(['photoEstimate', 'fileEstimate'] as const)('%s keeps multipart boundaries and authentication', async (method) => {
  const fetch = vi.fn().mockResolvedValue(new Response('{}', {
    headers: { 'Content-Type': 'application/json' },
  }));
  vi.stubGlobal('fetch', fetch);
  await aiApi[method]({ file, currency: 'EUR', location: 'Berlin' });
  const request = fetch.mock.calls[0]?.[1] as RequestInit;
  const headers = new Headers(request.headers);
  expect(headers.get('Authorization')).toBe('Bearer test-token');
  expect(headers.has('Content-Type')).toBe(false);
  expect(request.body).toBeInstanceOf(FormData);
  expect((request.body as FormData).get('file')).toBe(file);
  expect((request.body as FormData).get('currency')).toBe('EUR');
});

it.each([
  ['createSessionFromImage', 'image'], ['createSessionFromPdf', 'file'], ['createSessionFromExcel', 'file'],
] as const)('%s preserves the multipart contract', async (method, fileField) => {
  const fetch = vi.fn().mockResolvedValue(new Response('{}', { headers: { 'Content-Type': 'application/json' } }));
  vi.stubGlobal('fetch', fetch);
  await matchElementsApi[method]({ project_id: 'project', file, name: 'Import', catalogue_id: 'catalog', construction_stage: '04_Foundations' });
  const request = fetch.mock.calls[0]?.[1] as RequestInit;
  const headers = new Headers(request.headers);
  expect(headers.get('Authorization')).toBe('Bearer test-token');
  expect(headers.has('Content-Type')).toBe(false);
  const form = request.body as FormData;
  expect(form.get(fileField)).toBe(file);
  expect(form.get('project_id')).toBe('project');
  expect(form.get('name')).toBe('Import');
  expect(form.get('catalogue_id')).toBe('catalog');
  expect(form.get('construction_stage')).toBe('04_Foundations');
});


it.each([false, true])('quick estimate bounds a stalled response body (caller signal: %s)', async (withCaller) => {
  let signal: AbortSignal | undefined;
  let finish = () => {};
  const response = new Response('{}', { headers: { 'Content-Type': 'application/json' } });
  vi.spyOn(response, 'json').mockImplementation(() => new Promise((resolve, reject) => {
    finish = () => resolve({ ok: true });
    signal?.addEventListener('abort', () => reject(signal?.reason), { once: true });
  }));
  const fetch = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => {
    signal = init?.signal ?? undefined;
    return Promise.resolve(response);
  });
  vi.stubGlobal('fetch', fetch);
  const caller = new AbortController();
  const outcome = aiApi.quickEstimate(quick, withCaller ? { signal: caller.signal } : undefined)
    .catch((error: unknown) => error);
  try {
    await vi.advanceTimersByTimeAsync(90_001);
    expect(response.json).toHaveBeenCalledOnce();
    expect(signal?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(209_999);
    expect(signal?.aborted).toBe(true);
    expect(await outcome).toBeInstanceOf(Error);
    expect(caller.signal.aborted).toBe(false);
    expect(fetch).toHaveBeenCalledOnce();
    expect(queueMutation).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  } finally {
    finish();
    await outcome;
  }
});
