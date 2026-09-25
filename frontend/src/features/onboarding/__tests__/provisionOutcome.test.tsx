// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A country install must end by telling the user what actually happened.
//
// Picking a country runs the cost base import and a sample project install as
// background jobs. The driver used to resolve 'done' as soon as every job had
// stopped, however it stopped, and the wizard turned 'done' into "Canada is
// ready". A load that failed read as ready, and the banner in the corner, with
// a red cross next to the cost database, said "workspace ready, with some items
// skipped". These tests hold the three honest endings apart: complete, complete
// with items left out, and failed.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

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

import { startBackgroundOnboardingProvision } from '../OnboardingWizard';
import { countryProvisionToast } from '../provisionOutcome';
import type { OnboardingJobState } from '../onboardingApi';
import { BackgroundInstallBanner } from '@/shared/ui/BackgroundInstallBanner';
import { useBackgroundInstallStore } from '@/stores/useBackgroundInstallStore';

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

/** Provision answers with the given jobs pending; the status route with them finished. */
function serve(finished: OnboardingJobState[]): void {
  api.apiPost.mockImplementation((path: string) => {
    if (path === '/v1/onboarding/provision') {
      return Promise.resolve({ jobs: finished.map((j) => ({ ...j, state: 'pending', outcome: null })) });
    }
    return Promise.reject(new Error(`no fake for POST ${path}`));
  });
  api.apiGet.mockImplementation((path: string) => {
    if (path === '/v1/onboarding/jobs/') return Promise.resolve({ jobs: finished });
    return Promise.reject(new Error(`no fake for GET ${path}`));
  });
}

beforeEach(() => {
  api.apiGet.mockReset();
  api.apiPost.mockReset();
  useBackgroundInstallStore.getState().dismiss();
});

afterEach(() => {
  cleanup();
  useBackgroundInstallStore.getState().dismiss();
});

describe('the country install reports how the load ended', () => {
  it('a failed cost base load is reported as failed, not ready', async () => {
    serve([
      job({ state: 'failed', outcome: 'failed', pct: 15, error: "Can't reconnect" }),
      job({ id: 'job-demo', kind: 'onboarding.install_demo', arg: 'demo', state: 'success', outcome: 'completed' }),
    ]);

    const result = await startBackgroundOnboardingProvision({
      region: 'ENG_TORONTO',
      demoIds: ['demo'],
      country: 'Canada',
    });

    expect(result.phase).toBe('done');
    expect(result.outcome).toBe('failed');
    const toast = countryProvisionToast(result, 'Canada');
    expect(toast.type).toBe('error');
    expect(toast.title).not.toMatch(/ready/i);
    expect(toast.title).toContain('Canada');
    // The server's own error text never reaches the user.
    expect(JSON.stringify(toast)).not.toContain('reconnect');
  });

  it('a load that left rows out says how many', async () => {
    serve([job({ state: 'success', outcome: 'partial', pct: 100, imported: 55717, failed_items: 2 })]);

    const result = await startBackgroundOnboardingProvision({ region: 'ENG_TORONTO', country: 'Canada' });

    expect(result.outcome).toBe('partial');
    expect(result.failedItems).toBe(2);
    const toast = countryProvisionToast(result, 'Canada');
    expect(toast.type).toBe('warning');
    expect(toast.title).toContain('2');
  });

  it('a complete load is ready', async () => {
    serve([job({ state: 'success', outcome: 'completed', pct: 100, imported: 55719 })]);

    const result = await startBackgroundOnboardingProvision({ region: 'ENG_TORONTO', country: 'Canada' });

    expect(result.outcome).toBe('completed');
    const toast = countryProvisionToast(result, 'Canada');
    expect(toast.type).toBe('success');
    expect(toast.title).toBe('Canada is ready');
  });
});

describe('the background banner does not call a failed install ready', () => {
  function renderBanner() {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <BackgroundInstallBanner />
      </QueryClientProvider>,
    );
  }

  it('a step that failed makes the headline say the setup had errors', () => {
    const store = useBackgroundInstallStore.getState();
    store.begin('onboarding:ENG_TORONTO', 'Canada', [
      { step: 'cost_db', label: 'Cost database', status: 'pending' },
      { step: 'demos', label: 'Example projects', status: 'pending' },
    ]);
    store.markDone('cost_db', 'error');
    store.markDone('demos', 'ok');
    store.finish(true);

    renderBanner();

    expect(screen.queryByText(/ready/i)).toBeNull();
    expect(screen.getByText('Canada setup finished with errors')).toBeTruthy();
  });

  it('a clean finish still reads ready', () => {
    const store = useBackgroundInstallStore.getState();
    store.begin('onboarding:ENG_TORONTO', 'Canada', [{ step: 'cost_db', label: 'Cost database', status: 'pending' }]);
    store.markDone('cost_db', 'ok');
    store.finish(false);

    renderBanner();

    expect(screen.getByText('Canada workspace is ready')).toBeTruthy();
  });
});
