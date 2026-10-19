// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The onboarding "Ready-made Pack" install routes the user into the app and
// keeps loading in the background. Without internet the cost database step
// fails, the install carries on to the sample projects, and the banner used to
// end on one red row among green ones: the workspace had no prices and nothing
// said so or offered to try again. These pin the explicit message, the retry,
// and the line that says the AI search index is not built during setup.

import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { BackgroundInstallBanner } from './BackgroundInstallBanner';
import { useBackgroundInstallStore } from '@/stores/useBackgroundInstallStore';

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function finishWith(costStatus: 'ok' | 'error') {
  const s = useBackgroundInstallStore.getState();
  s.begin('germany-de', 'Germany', [
    { step: 'apply_pack', label: 'Apply pack', status: 'pending' },
    { step: 'cost_db', label: 'Cost database', status: 'pending' },
    { step: 'demos', label: 'Example projects', status: 'pending' },
  ]);
  s.markDone('apply_pack', 'ok');
  s.markDone('cost_db', costStatus);
  s.markDone('demos', 'ok');
  s.finish(costStatus === 'error');
}

beforeEach(() => {
  useBackgroundInstallStore.getState().dismiss();
});

afterEach(() => {
  cleanup();
  useBackgroundInstallStore.getState().dismiss();
});

describe('the background install banner after a cost database failure', () => {
  it('says the workspace has no prices and offers a retry of that step', () => {
    const retry = vi.fn();
    finishWith('error');
    useBackgroundInstallStore.getState().setRetryCostBase(retry);
    render(wrap(<BackgroundInstallBanner />));

    expect(screen.getByTestId('bg-install-no-prices').textContent).toMatch(/no prices yet/);
    fireEvent.click(screen.getByTestId('bg-install-retry-cost'));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it('shows no retry button when the install cannot be retried step by step', () => {
    finishWith('error');
    render(wrap(<BackgroundInstallBanner />));
    expect(screen.getByTestId('bg-install-no-prices')).toBeTruthy();
    expect(screen.queryByTestId('bg-install-retry-cost')).toBeNull();
  });

  it('says nothing about prices when the cost database loaded', () => {
    finishWith('ok');
    render(wrap(<BackgroundInstallBanner />));
    expect(screen.queryByTestId('bg-install-no-prices')).toBeNull();
  });

  it('says the AI search index is not built during setup', () => {
    finishWith('ok');
    render(wrap(<BackgroundInstallBanner />));
    const note = screen.getByTestId('bg-install-search-index');
    expect(note.textContent).toMatch(/not built during setup/);
    expect(note.querySelector('a')?.getAttribute('href')).toBe('/setup/databases');
  });

  it('a new install does not inherit the retry of the one before it', () => {
    finishWith('error');
    useBackgroundInstallStore.getState().setRetryCostBase(vi.fn());
    // The plain region path begins its own install and sets no retry.
    useBackgroundInstallStore.getState().begin('region', 'Germany', []);
    expect(useBackgroundInstallStore.getState().retryCostBase).toBeNull();
  });

  it('a retry puts the finished install back into the running state', () => {
    finishWith('error');
    useBackgroundInstallStore.getState().reopen();
    const install = useBackgroundInstallStore.getState().install;
    expect(install?.running).toBe(true);
    expect(install?.done).toBe(false);
  });
});
