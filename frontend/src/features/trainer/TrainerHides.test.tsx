// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// TrainerHides: hides its children from a learner, and is invisible otherwise.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiPut: vi.fn() }));
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

import { ApiError } from '@/shared/lib/api';
import { SYSTEM_STATUS_QUERY_KEY } from '@/shared/hooks/useSystemStatus';
import { useAuthStore } from '@/stores/useAuthStore';
import { meFixture } from './__fixtures__/me';
import { trainerKeys } from './queries';
import { TrainerHides } from './TrainerHides';
import { TRAINER_MODE_STORAGE_KEY, __resetTrainerCacheOwnerForTests } from './useTrainerMode';
import { useTrainerUiStore } from './useTrainerUiStore';

let client: QueryClient;

// Backstop only, for a loaded full run.
const BACKSTOP = { timeout: 5000 };

function Tour() {
  return (
    <div className="tour">
      <button type="button">Start the tour</button>
    </div>
  );
}

function plainHtml(): string {
  const view = render(<Tour />);
  const html = view.container.innerHTML;
  view.unmount();
  return html;
}

function renderHides() {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/dashboard']}>
        <TrainerHides>
          <Tour />
        </TrainerHides>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function seed(academy: boolean, me?: unknown) {
  client.setQueryData(SYSTEM_STATUS_QUERY_KEY, { academy_mode: academy });
  if (me !== undefined) client.setQueryData(trainerKeys.me(), me);
}

function expectNoRequests() {
  expect(api.apiGet).not.toHaveBeenCalled();
  expect(api.apiPost).not.toHaveBeenCalled();
  expect(api.apiPut).not.toHaveBeenCalled();
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  api.apiGet.mockReset();
  api.apiPost.mockReset();
  api.apiPut.mockReset();
  localStorage.clear();
  __resetTrainerCacheOwnerForTests();
  useTrainerUiStore.getState().reset();
  useAuthStore.setState({ isAuthenticated: true, userId: 'user-a', accessToken: null });
});
afterEach(() => {
  cleanup();
  client.clear();
  useAuthStore.setState({ isAuthenticated: false, userId: null, accessToken: null });
});

describe('TrainerHides', () => {
  it('a normal install renders the children unchanged and asks nothing', () => {
    const expected = plainHtml();
    seed(false);
    const view = renderHides();
    expect(view.container.innerHTML).toBe(expected);
    expectNoRequests();
  });

  it('signed out: the children, and not even the status is asked', () => {
    const expected = plainHtml();
    useAuthStore.setState({ isAuthenticated: false, userId: null, accessToken: null });
    localStorage.setItem(TRAINER_MODE_STORAGE_KEY, '1');
    const view = renderHides();
    expect(view.container.innerHTML).toBe(expected);
    expectNoRequests();
  });

  it('an academy box without an enrolment keeps the children', () => {
    seed(true, null);
    renderHides();
    expect(screen.getByRole('button', { name: 'Start the tour' })).toBeInTheDocument();
  });

  it('an enrolled learner does not get them', () => {
    seed(true, meFixture);
    const view = renderHides();
    expect(view.container.innerHTML).toBe('');
  });

  it('hidden while the status is unknown but the cached flag says academy', () => {
    localStorage.setItem(TRAINER_MODE_STORAGE_KEY, '1');
    api.apiGet.mockImplementation(() => new Promise(() => {}));
    const view = renderHides();
    expect(view.container.innerHTML).toBe('');
  });

  it('hidden while the course loads', () => {
    seed(true);
    api.apiGet.mockImplementation(() => new Promise(() => {}));
    const view = renderHides();
    expect(view.container.innerHTML).toBe('');
  });

  it('hidden when the course failed to load', async () => {
    seed(true);
    api.apiGet.mockRejectedValue(new ApiError(503, 'Unavailable', undefined));
    const view = renderHides();
    await waitFor(() => expect(api.apiGet).toHaveBeenCalled(), BACKSTOP);
    expect(view.container.innerHTML).toBe('');
  });
});
