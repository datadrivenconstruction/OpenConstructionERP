// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Data Setup step's "Load Database" button must end with what happened to
// the load. It used to wait on a direct request and abort it after five
// minutes, so a large region read "Connection error" while the import went on
// and finished on the server. The load now runs as an onboarding job that the
// wizard follows to its end. The wizard-level check is in
// OnboardingWizard.flow.test.tsx; these hold the job follower and its messages.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

// Initialises i18next with the English resources the messages are read from.
import '@/app/i18n';
import { costDbLoadReport, followCostDbLoad } from '../costDbLoad';
import type { OnboardingJobState } from '../onboardingApi';

function job(over: Partial<OnboardingJobState>): OnboardingJobState {
  return {
    id: 'job-cwicr',
    kind: 'onboarding.load_cwicr',
    arg: 'ENG_TORONTO',
    state: 'pending',
    outcome: null,
    pct: 0,
    message: null,
    error: null,
    imported: null,
    total: null,
    failed_items: 0,
    ...over,
  };
}

const MINUTE = 60_000;

/** Provision answers with a pending job; the job list with `states(now)`. */
function serve(states: (elapsedMs: number) => OnboardingJobState[] | Error): void {
  const startedAt = Date.now();
  api.apiPost.mockImplementation((path: string) => {
    if (path === '/v1/onboarding/provision') return Promise.resolve({ jobs: [job({})] });
    return Promise.reject(new Error(`no fake for POST ${path}`));
  });
  api.apiGet.mockImplementation((path: string) => {
    if (path !== '/v1/onboarding/jobs/') return Promise.reject(new Error(`no fake for GET ${path}`));
    const answer = states(Date.now() - startedAt);
    return answer instanceof Error ? Promise.reject(answer) : Promise.resolve({ jobs: answer });
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  api.apiGet.mockReset();
  api.apiPost.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('a manual cost base load is followed to its end', () => {
  it('a load that runs longer than five minutes ends loaded, not as a connection error', async () => {
    serve((elapsed) =>
      elapsed < 7 * MINUTE
        ? [job({ state: 'started', pct: 15 })]
        : [job({ state: 'success', outcome: 'completed', pct: 100, imported: 55719, total: 55719 })],
    );

    const done = followCostDbLoad('ENG_TORONTO');
    await vi.advanceTimersByTimeAsync(8 * MINUTE);
    const result = await done;

    expect(result.outcome).toBe('completed');
    const report = costDbLoadReport(result, 'Toronto');
    expect(report.toast.type).toBe('success');
    expect(report.toast.title).toBe('Toronto loaded');
    expect(report.toast.message).toBe('Cost items available: 55,719');
    // It went through the provisioning job, never the direct import route.
    expect(api.apiPost.mock.calls.map(([p]) => p)).toEqual(['/v1/onboarding/provision']);
  });

  it('a failed load says so, without the server error text', async () => {
    serve(() => [job({ state: 'failed', outcome: 'failed', pct: 15, error: "Can't reconnect" })]);

    const done = followCostDbLoad('ENG_TORONTO');
    await vi.advanceTimersByTimeAsync(5_000);
    const result = await done;

    expect(result.outcome).toBe('failed');
    const report = costDbLoadReport(result, 'Toronto');
    expect(report.toast.type).toBe('error');
    expect(report.toast.title).toBe('Toronto could not be loaded');
    expect(JSON.stringify(report)).not.toContain('reconnect');
  });

  it('a partial load counts what was left out', async () => {
    serve(() => [
      job({ state: 'success', outcome: 'partial', pct: 100, imported: 55717, total: 55717, failed_items: 2 }),
    ]);

    const done = followCostDbLoad('ENG_TORONTO');
    await vi.advanceTimersByTimeAsync(5_000);
    const result = await done;

    expect(result.outcome).toBe('partial');
    const report = costDbLoadReport(result, 'Toronto');
    expect(report.toast.type).toBe('warning');
    expect(report.toast.message).toBe('Cost items left out: 2');
  });

  it('a base that was already loaded reports the items it holds', async () => {
    serve(() => [job({ state: 'success', outcome: 'completed', pct: 100, imported: 0, total: 55719 })]);

    const done = followCostDbLoad('ENG_TORONTO');
    await vi.advanceTimersByTimeAsync(5_000);
    const report = costDbLoadReport(await done, 'Toronto');

    expect(report.toast.message).toBe('Cost items available: 55,719');
  });

  it('losing the server mid-load is not reported as a failure', async () => {
    serve(() => new Error('offline'));

    const done = followCostDbLoad('ENG_TORONTO', { maxMissedPolls: 3 });
    await vi.advanceTimersByTimeAsync(10_000);
    const result = await done;

    expect(result.outcome).toBe('unconfirmed');
    const report = costDbLoadReport(result, 'Toronto');
    expect(report.toast.type).toBe('warning');
    expect(report.toast.title).toMatch(/may still finish/);
  });

  it('a load that could not be started is a failure', async () => {
    api.apiPost.mockRejectedValue(new Error('403'));

    const result = await followCostDbLoad('ENG_TORONTO');

    expect(result).toEqual({ outcome: 'failed', job: null });
  });
});
