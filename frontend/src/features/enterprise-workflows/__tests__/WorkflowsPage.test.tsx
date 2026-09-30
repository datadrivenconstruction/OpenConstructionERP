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
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
  if (route === '/v1/enterprise-workflows/requests/') {
    // The pending counter asks for one row and reads the envelope's total.
    if (path.includes('status=pending') && path.includes('limit=1')) {
      return { items: REQUESTS.items.slice(0, 1), total: 73, offset: 0, limit: 1 };
    }
    return REQUESTS;
  }
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
    // The badge on the cancelled row, not the filter option of the same name.
    expect(screen.getAllByText('Cancelled').some((el) => el.tagName !== 'OPTION')).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: /Approve/ }));
    await waitFor(() =>
      expect(apiMocks.apiPost).toHaveBeenCalledWith(
        `/v1/enterprise-workflows/requests/${REQUEST_ID}/approve/`,
        undefined,
      ),
    );
  });

  it('creates a workflow with role-gated steps in the keys the backend checks and reads them back', async () => {
    // What the server stores is what it returns: steps travel as plain dicts
    // (``steps: list[dict]`` in WorkflowCreate/WorkflowResponse), and the
    // approval engine reads ``role`` and ``action_type`` from each one.
    let stored: Array<Record<string, unknown>> = [];
    apiMocks.apiGet.mockImplementation(async (path: string) => {
      const [route] = path.split('?');
      if (route === '/v1/enterprise-workflows/') {
        return {
          items: stored.length ? [{ ...WORKFLOW, id: 'wf-new', name: 'Variation sign-off', steps: stored }] : [],
          total: stored.length ? 1 : 0,
          offset: 0,
          limit: 50,
        };
      }
      return routeGet(path);
    });
    apiMocks.apiPost.mockImplementation(async (path: string, body: { steps: Array<Record<string, unknown>> }) => {
      if (path !== '/v1/enterprise-workflows/') throw new NotFound(`404 POST ${path}`);
      stored = body.steps;
      return { ...WORKFLOW, id: 'wf-new', name: 'Variation sign-off', steps: body.steps };
    });

    renderPage();
    fireEvent.click((await screen.findAllByRole('button', { name: /New Workflow/ }))[0]!);

    fireEvent.change(screen.getByLabelText('Workflow Name'), { target: { value: 'Variation sign-off' } });
    fireEvent.change(screen.getByLabelText('Entity Type'), { target: { value: 'variation' } });
    // Step 1: a manager approves. Step 2: a final sign-off by an admin.
    fireEvent.change(screen.getByLabelText('Step 1 Required role'), { target: { value: 'manager' } });
    fireEvent.click(screen.getByRole('button', { name: /Add step/ }));
    fireEvent.change(screen.getByLabelText('Step 2 Required role'), { target: { value: 'admin' } });
    fireEvent.change(screen.getByLabelText('Step 2 Action'), { target: { value: 'sign_off' } });
    fireEvent.click(screen.getByRole('button', { name: /^Create$/ }));

    await waitFor(() => expect(apiMocks.apiPost).toHaveBeenCalled());
    const [, body] = apiMocks.apiPost.mock.calls[0]!;
    expect(body.steps).toEqual([
      { role: 'manager', action_type: 'approve' },
      { role: 'admin', action_type: 'sign_off' },
    ]);
    for (const step of body.steps) {
      expect(step).not.toHaveProperty('approver_role');
      expect(step).not.toHaveProperty('action');
    }

    // Read-back: the list shows each step's role and action from the stored dicts.
    expect(await screen.findByText('Variation sign-off')).toBeInTheDocument();
    expect(screen.getByText(/1\. Manager · Approve/)).toBeInTheDocument();
    expect(screen.getByText(/2\. Admin · Sign-off/)).toBeInTheDocument();
  });

  it('counts pending approvals from the envelope total, not from the page it shows', async () => {
    renderPage();
    await screen.findByText('Invoice sign-off');

    // One pending request sits on the page; the backend says 73 exist.
    expect((await screen.findAllByText('73')).length).toBeGreaterThan(0);
  });

  it('filters requests by every status the backend has, cancelled included', async () => {
    renderPage();
    await screen.findByText('Invoice sign-off');
    fireEvent.click(screen.getByRole('tab', { name: /Approval Requests/ }));
    await screen.findByText('Please check the retention line');

    const options = screen.getAllByRole('option').map((o) => (o as HTMLOptionElement).value);
    expect(options).toEqual(expect.arrayContaining(['pending', 'approved', 'rejected', 'cancelled']));
  });

  it('offers only step actions the engine enforces', async () => {
    renderPage();
    fireEvent.click((await screen.findAllByRole('button', { name: /New Workflow/ }))[0]!);

    const actions = within(screen.getByLabelText('Step 1 Action'))
      .getAllByRole('option')
      .map((o) => (o as HTMLOptionElement).value);
    expect(actions).toEqual(['approve', 'sign_off']);
  });
});
