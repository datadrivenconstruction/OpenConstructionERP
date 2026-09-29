// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Tests for the out-of-office DELEGATION manager and the one-tap
// REASSIGNMENT dialog - the two surfaces that consume the previously
// unused approval_routes delegation + reassign endpoints.
//
// These mock @/shared/lib/api (the JSON wrapper) directly so we can
// assert the exact HTTP verb + path + body each control sends, mirroring
// the backend router (POST /instances/{id}/reassign, GET/POST/DELETE
// /delegations). The i18n shim returns defaultValue with interpolation so
// assertions read against the English copy.

import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import type { ApprovalDelegation, ApprovalInstance } from '../types';

/* -- Toast mock ------------------------------------------------------- */

const toastMocks = vi.hoisted(() => ({ addToast: vi.fn() }));
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: Object.assign(
    (selector: (s: { addToast: typeof toastMocks.addToast }) => unknown) =>
      selector({ addToast: toastMocks.addToast }),
    { getState: () => ({ addToast: toastMocks.addToast }) },
  ),
}));

/* -- i18n shim - return defaultValue with interpolation. -- */

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (
      _key: string,
      opts?: { defaultValue?: string } & Record<string, unknown>,
    ) => {
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

/* -- API mock ------------------------------------------------------- */

const apiMocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  getErrorMessage: (e: unknown) => String(e),
}));
vi.mock('@/shared/lib/api', () => apiMocks);

// The pickers read the user directory, which needs users.list (manager).
vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: Object.assign(
    (selector: (s: { accessToken: string; userRole: string }) => unknown) =>
      selector({ accessToken: 'test-token', userRole: 'manager' }),
    { getState: () => ({ accessToken: 'test-token', userRole: 'manager' }) },
  ),
}));

import { ReassignDialog } from '../ReassignDialog';
import { DelegationManager } from '../DelegationManager';

/* -- Fixtures ------------------------------------------------------- */

const USERS = [
  {
    id: 'user-1',
    email: 'ann@example.com',
    full_name: 'Ann Approver',
    role: 'manager',
    is_active: true,
  },
  {
    id: 'user-2',
    email: 'ben@example.com',
    full_name: 'Ben Backup',
    role: 'engineer',
    is_active: true,
  },
];

const PENDING_INSTANCE: ApprovalInstance = {
  id: 'inst-1',
  route_id: 'route-1',
  target_kind: 'submittal',
  target_id: 'target-1',
  current_step_ordinal: 1,
  status: 'pending',
  started_at: '2026-05-26T09:00:00Z',
  completed_at: null,
  started_by: 'user-author',
  current_assignee_user_id: null,
  created_at: '2026-05-26T09:00:00Z',
  updated_at: '2026-05-26T09:00:00Z',
  step_states: [],
};

const DELEGATION: ApprovalDelegation = {
  id: 'del-1',
  delegator_user_id: 'me',
  delegate_user_id: 'user-2',
  project_id: null,
  starts_at: null,
  ends_at: null,
  is_active: true,
  reason: 'On leave',
  created_by: 'me',
  created_at: '2026-05-26T09:00:00Z',
  updated_at: '2026-05-26T09:00:00Z',
};

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

beforeEach(() => {
  cleanup();
  apiMocks.apiGet.mockReset();
  apiMocks.apiPost.mockReset();
  apiMocks.apiDelete.mockReset();
  toastMocks.addToast.mockReset();
  // Default: users list for the pickers, empty for everything else.
  apiMocks.apiGet.mockImplementation(async (path: string) => {
    if (path.includes('/users')) return USERS;
    if (path.includes('/projects')) return [];
    if (path.includes('/delegations')) return [];
    return [];
  });
});

afterEach(() => {
  cleanup();
});

/* -- Reassign ------------------------------------------------------- */

describe('<ReassignDialog />', () => {
  it('posts the reassign payload with the chosen user + reason', async () => {
    apiMocks.apiPost.mockResolvedValue({
      ...PENDING_INSTANCE,
      current_assignee_user_id: 'user-2',
    });
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <ReassignDialog open onClose={() => {}} instance={PENDING_INSTANCE} />
      </QueryClientProvider>,
    );

    // The user <select> is populated from the active-users query.
    const select = (await screen.findByTestId(
      'reassign-user-select',
    )) as HTMLSelectElement;
    await waitFor(() =>
      expect(screen.getByText('Ben Backup')).toBeInTheDocument(),
    );
    fireEvent.change(select, { target: { value: 'user-2' } });

    fireEvent.click(screen.getByRole('button', { name: /^Reassign$/i }));

    await waitFor(() => expect(apiMocks.apiPost).toHaveBeenCalled());
    const [path, body] = apiMocks.apiPost.mock.calls[0]!;
    expect(path).toBe('/v1/approval-routes/instances/inst-1/reassign');
    expect(body).toEqual({ to_user_id: 'user-2', reason: null });
  });

  it('keeps the confirm button disabled until a user is picked', async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <ReassignDialog open onClose={() => {}} instance={PENDING_INSTANCE} />
      </QueryClientProvider>,
    );
    await screen.findByTestId('reassign-user-select');
    const confirm = screen.getByRole('button', {
      name: /^Reassign$/i,
    }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
  });
});

/* -- Delegation manager --------------------------------------------- */

describe('<DelegationManager />', () => {
  it('lists the caller active delegations from GET /delegations', async () => {
    apiMocks.apiGet.mockImplementation(async (path: string) => {
      if (path.includes('/delegations')) return [DELEGATION];
      if (path.includes('/users')) return USERS;
      if (path.includes('/projects')) return [];
      return [];
    });
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <DelegationManager open onClose={() => {}} />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId('delegation-list')).toBeInTheDocument(),
    );
    // The delegate's resolved name shows in the row.
    expect(screen.getByText(/Covered by Ben Backup/i)).toBeInTheDocument();
    // The GET hit the mine-scoped delegations endpoint.
    expect(apiMocks.apiGet).toHaveBeenCalledWith(
      '/v1/approval-routes/delegations?role=mine',
    );
  });

  it('posts a new delegation with the chosen delegate', async () => {
    apiMocks.apiPost.mockResolvedValue(DELEGATION);
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <DelegationManager open onClose={() => {}} />
      </QueryClientProvider>,
    );

    const select = (await screen.findByTestId(
      'delegation-user-select',
    )) as HTMLSelectElement;
    // Wait until the active-users option is mounted, then select it.
    await waitFor(() =>
      expect(screen.getByText('Ben Backup')).toBeInTheDocument(),
    );
    fireEvent.change(select, { target: { value: 'user-2' } });
    expect(select.value).toBe('user-2');

    const createBtn = screen.getByTestId(
      'delegation-create-button',
    ) as HTMLButtonElement;
    await waitFor(() => expect(createBtn.disabled).toBe(false));
    fireEvent.click(createBtn);

    await waitFor(() => expect(apiMocks.apiPost).toHaveBeenCalled());
    const [path, body] = apiMocks.apiPost.mock.calls[0]!;
    expect(path).toBe('/v1/approval-routes/delegations');
    expect(body).toMatchObject({
      delegate_user_id: 'user-2',
      project_id: null,
      starts_at: null,
      ends_at: null,
      reason: null,
    });
  });

  it('revokes a delegation via DELETE after confirmation', async () => {
    apiMocks.apiGet.mockImplementation(async (path: string) => {
      if (path.includes('/delegations')) return [DELEGATION];
      if (path.includes('/users')) return USERS;
      if (path.includes('/projects')) return [];
      return [];
    });
    apiMocks.apiDelete.mockResolvedValue(undefined);
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <DelegationManager open onClose={() => {}} />
      </QueryClientProvider>,
    );

    const revokeBtn = await screen.findByTestId('delegation-revoke-del-1');
    fireEvent.click(revokeBtn);

    // ConfirmDialog opens; confirm via its dedicated test id.
    const confirm = await screen.findByTestId('confirm-dialog-confirm');
    fireEvent.click(confirm);

    await waitFor(() => expect(apiMocks.apiDelete).toHaveBeenCalled());
    expect(apiMocks.apiDelete).toHaveBeenCalledWith(
      '/v1/approval-routes/delegations/del-1',
    );
  });
});
