// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { withLongRunningDeadline } from './longRunningDeadline';

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

it('does not start an already-cancelled operation', async () => {
  const controller = new AbortController();
  controller.abort();
  const operation = vi.fn();
  await expect(withLongRunningDeadline(operation, controller.signal)).rejects.toBe(controller.signal.reason);
  expect(operation).not.toHaveBeenCalled();
  expect(vi.getTimerCount()).toBe(0);
});

it.each(['success', 'error'])('cleans the listener and timer after %s', async (mode) => {
  const controller = new AbortController();
  const remove = vi.spyOn(controller.signal, 'removeEventListener');
  const failure = new Error('network failed');
  const result = await withLongRunningDeadline(async () => {
    if (mode === 'error') throw failure;
    return 'done';
  }, controller.signal).catch((error: unknown) => error);
  expect(result).toBe(mode === 'error' ? failure : 'done');
  expect(remove).toHaveBeenCalledWith('abort', expect.any(Function));
  expect(vi.getTimerCount()).toBe(0);
});

it('keeps the deadline until the response body has been consumed', async () => {
  let bodyStarted = false;
  const result = withLongRunningDeadline(async (signal) => {
    // Headers arrived, but reading the streamed body is still pending.
    bodyStarted = true;
    return new Promise((_, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true }));
  }).catch((error: unknown) => error);
  expect(bodyStarted).toBe(true);
  await vi.advanceTimersByTimeAsync(300_000);
  expect(await result).toMatchObject({ name: 'TimeoutError', message: expect.any(String) });
  expect(vi.getTimerCount()).toBe(0);
});
