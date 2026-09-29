/**
 * The approval workflows page against the routes and shapes the backend serves.
 *
 * Both list routes answer with a paged envelope (``WorkflowListResponse`` and
 * ``ApprovalRequestListResponse`` in
 * ``backend/app/modules/enterprise_workflows/schemas.py``), and the app runs
 * with ``redirect_slashes=False``, so a path missing the trailing slash the
 * router declares is a 404 or lands on ``/{workflow_id}``. The HTTP mock below
 * answers only the paths the router really has, which is what the page met in
 * production: it read the envelope as an array and threw on open.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string } & Record<string, unknown>) => {
      if (typeof opts === 'object' && opts && 'defaultValue' in opts) {
        let dv = String(opts.defaultValue ?? '');
        for (const [k, v] of Object.entries(opts)) {
          if (k === 'defaultValue') continue;
          dv = dv.replaceAll(`{{${k}}}`, String(v));
        }
        return dv;
      }
      return _key;
    },
    i18n: { language: 'en' },
  }),
  initReactI18next: { type: '3rdParty', init: () => undefined },
  I18nextProvider: ({ children }: { children: unknown }) => children,
  Trans: ({ children }: { children?: unknown }) => children ?? null,
}));

const apiMocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('@/shared/lib/api');
  return { ...actual, ...apiMocks };
});

import { WorkflowsPage } from '../WorkflowsPage';

const WORKFLOW_ID = '44444444-4444-4444-8444-444444444444';
const REQUEST_ID = '55555555-5555-4555-8555-555555555555';
const USER_ID = '66666666-6666-4666-8666-666666666666';

// WorkflowResponse
const WORKFLOW = {
  id: WORKFLOW_ID,
  project_id: null,
  entity_type: 'invoice',
  name: 'Invoice sign-off',
  description: null,
  steps: [{ role: 'manager', action_type: 'approve' }],
  is_active: true,
  metadata: {},
  created_at: '2026-09-20T10:00:00Z',
  updated_at: '2026-09-20T10:00:00Z',
};

// ApprovalRequestResponse
function request(id: string, status: string, notes: string | null) {
  return {
    id,
    workflow_id: WORKFLOW_ID,
    entity_type: 'invoice',
    entity_id: '77777777-7777-4777-8777-777777777777',
    current_step: 1,
    status,
    requested_by: USER_ID,
    decided_by: null,
    decided_at: null,
    decision_notes: notes,
    metadata: {},
    created_at: '2026-09-21T10:00:00Z',
    updated_at: '2026-09-21T10:00:00Z',
  };
}

const REQUESTS = {
  items: [
    request(REQUEST_ID, 'pending', 'Please check the retention line'),
    request('88888888-8888-4888-8888-888888888888', 'cancelled', null),
  ],
  total: 2,
  offset: 0,
  limit: 50,
};

class NotFound extends Error {}

function routeGet(path: string): unknown {
  const [route] = path.split('?');
  if (route === '/v1/enterprise-workflows/') {
    return { items: [WORKFLOW], total: 1, offset: 0, limit: 50 };
  }
  if (route === '/v1/enterprise-workflows/requests/') return REQUESTS;
  throw new NotFound(`404 GET ${path}`);
}

function routePost(path: string): unknown {
  if (path === `/v1/enterprise-workflows/requests/${REQUEST_ID}/approve/`) {
    return { ...REQUESTS.items[0], status: 'approved' };
  }
  throw new NotFound(`404 POST ${path}`);
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <WorkflowsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiMocks.apiGet.mockImplementation(async (path: string) => routeGet(path));
  apiMocks.apiPost.mockImplementation(async (path: string) => routePost(path));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('WorkflowsPage with the backend response shapes', () => {
  it('opens and lists workflows from the paged envelope', async () => {
    renderPage();

    expect(await screen.findByText('Invoice sign-off')).toBeInTheDocument();
    expect(screen.queryByText('Could not load workflow data.')).not.toBeInTheDocument();
  });

  it('lists approval requests, including a cancelled one, and approves on the declared path', async () => {
    renderPage();
    await screen.findByText('Invoice sign-off');

    fireEvent.click(screen.getByRole('tab', { name: /Approval Requests/ }));

    // decision_notes is what the backend calls the note on a request.
    expect(await screen.findByText('Please check the retention line')).toBeInTheDocument();
    expect(screen.getByText('Cancelled')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Approve/ }));
    await waitFor(() =>
      expect(apiMocks.apiPost).toHaveBeenCalledWith(
        `/v1/enterprise-workflows/requests/${REQUEST_ID}/approve/`,
        undefined,
      ),
    );
  });
});
