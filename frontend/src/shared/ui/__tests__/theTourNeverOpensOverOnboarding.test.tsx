// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The first-run product tour used to decide whether onboarding was done from
// the localStorage flag alone. That flag outlives a server-side onboarding
// reset, so the tour armed on the dashboard from a stale `true`, the server
// answer then sent the user to /onboarding, and the tour opened on top of the
// wizard. What is pinned here: the server answer decides, the tour never
// shows on /onboarding, closing it there does not count as dismissing it, and
// finishing the wizard in this session still starts it at once.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import type { NavigateFunction } from 'react-router-dom';

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return {
    ...actual,
    apiGet: (url: string) => api.get(url),
    apiPut: (url: string, body: unknown) => api.put(url, body),
  };
});

import { ProductTour } from '../ProductTour';

const STEPS = [{ selector: null, titleKey: 'test.tour_title', bodyKey: 'test.tour_body' }];

let resolveOnboarding: (value: { completed: boolean }) => void = () => {};
let navigateTo: NavigateFunction = () => {};

function NavigateHandle() {
  navigateTo = useNavigate();
  return null;
}

function mountTour(path = '/dashboard') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <NavigateHandle />
        <ProductTour steps={STEPS} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function tourShown(): boolean {
  return document.querySelector('[data-product-tour="tooltip"]') !== null;
}

/** Answer the onboarding request the tour made, once it has made it. */
async function answerOnboarding(completed: boolean) {
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/v1/users/me/onboarding/'));
  await act(async () => {
    resolveOnboarding({ completed });
  });
}

/** Run the tour's 600 ms auto-start delay, and a wide margin, on real timers. */
async function pastTheAutoStartDelay() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 1200));
  });
}

/** Wait for the tour to open, allowing a slow machine its time. */
async function tourOpens() {
  await waitFor(() => expect(tourShown()).toBe(true), { timeout: 4000 });
}

beforeEach(() => {
  localStorage.clear();
  api.get.mockImplementation((url: string) => {
    if (url === '/v1/users/me/tour-state/') return Promise.resolve({ tours: {} });
    if (url === '/v1/users/me/onboarding/') {
      return new Promise((resolve) => {
        resolveOnboarding = resolve;
      });
    }
    return Promise.resolve({});
  });
  api.put.mockResolvedValue({});
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('ProductTour and the onboarding wizard', () => {
  it('does not start from a stale local flag while the server has not answered', async () => {
    // Left over from before an onboarding reset on the server.
    localStorage.setItem('oe_onboarding_completed', 'true');
    mountTour();

    await pastTheAutoStartDelay();
    expect(tourShown()).toBe(false);

    // The server says onboarding is not done, and the dashboard sends the
    // user to the wizard.
    await answerOnboarding(false);
    await pastTheAutoStartDelay();
    expect(tourShown()).toBe(false);

    await act(async () => {
      navigateTo('/onboarding');
    });
    await pastTheAutoStartDelay();
    expect(tourShown()).toBe(false);
  });

  it('starts once the server says onboarding is done', async () => {
    mountTour();
    await answerOnboarding(true);
    await tourOpens();
  });

  it('closes on /onboarding without recording a dismissal', async () => {
    mountTour();
    await answerOnboarding(true);
    await tourOpens();

    await act(async () => {
      navigateTo('/onboarding');
    });
    expect(tourShown()).toBe(false);
    expect(api.put).not.toHaveBeenCalled();
    expect(localStorage.getItem('oe.tour_completed')).toBeNull();
  });

  it('starts at once when the wizard completes in this session', async () => {
    mountTour();
    await answerOnboarding(false);
    await pastTheAutoStartDelay();
    expect(tourShown()).toBe(false);

    await act(async () => {
      window.dispatchEvent(new CustomEvent('oe:onboarding-completed'));
    });
    await tourOpens();
    expect(screen.getByRole('dialog')).toBeTruthy();
  });
});
