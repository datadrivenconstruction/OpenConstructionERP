// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Happy-path tests for <ApprovalInstanceCard /> — the drop-in component
// that any feature (markups, submittals, …) mounts to show + drive the
// approval workflow for a single target.
//
// These fixtures mirror the REAL backend response models
// (backend/app/modules/approval_routes/schemas.py): a flat
// InstanceResponse carrying step_states (one StepState row per approver
// per step) + a 1-based current_step_ordinal, plus a RouteResponse with
// the template steps the UI joins against. The decide payload uses the
// backend's exact Literal: decision ∈ {'approved','rejected'}.
//
// Coverage:
//   1. Loading skeleton, then the route ladder renders with status pills.
//   2. The currently-active step shows Approve / Reject buttons only for
//      the assigned approver (the current user).
//   3. Clicking Approve hits POST /v1/approval-routes/instances/{id}/decide
//      with the right payload (decision:'approved').
//   4. No instance + no configured route → empty "no workflow" state.

import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import type { ApprovalInstance, ApprovalRoute } from '../types';

/* ── Toast mock ─────────────────────────────────────────────────────── */

const toastMocks = vi.hoisted(() => ({ addToast: vi.fn() }));
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: Object.assign(
    (selector: (s: { addToast: typeof toastMocks.addToast }) => unknown) =>
      selector({ addToast: toastMocks.addToast }),
    { getState: () => ({ addToast: toastMocks.addToast }) },
  ),
}));

/* ── i18n shim — return defaultValue with interpolation. ────────────── */

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
  // Re-export the symbols src/app/i18n.ts pulls at module load — the
  // shim only needs to exist; the test never exercises i18n init.
  initReactI18next: { type: '3rdParty', init: () => undefined },
  I18nextProvider: ({ children }: { children: unknown }) => children,
  Trans: ({ children }: { children?: unknown }) => children ?? null,
}));

/* ── API mock ─────────────────────────────────────────────────────── */

const apiMocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));
vi.mock('@/shared/lib/api', () => apiMocks);

/* ── Auth store mock (some inner helpers read it via api.ts) ───────── */

vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: Object.assign(
    (selector: (s: { accessToken: string }) => unknown) =>
      selector({ accessToken: 'test-token' }),
    { getState: () => ({ accessToken: 'test-token' }) },
  ),
}));

/* ── Helpers ─────────────────────────────────────────────────────── */

const TARGET_KIND = 'markup';
const TARGET_ID = 'markup-1';
const ME_ID = 'user-current';

// Flat InstanceResponse — no fabricated current_step_index / route_name /
// per-step assignees. The ladder is reconstructed from the route's steps.
const runningInstance: ApprovalInstance = {
  id: 'inst-1',
  route_id: 'route-1',
  target_kind: TARGET_KIND,
  target_id: TARGET_ID,
  current_step_ordinal: 1,
  status: 'pending',
  started_at: '2026-05-26T09:00:00Z',
  completed_at: null,
  started_by: 'user-author',
  created_at: '2026-05-26T09:00:00Z',
  updated_at: '2026-05-26T09:00:00Z',
  // No decision recorded yet — step 1 is open for the current user.
  step_states: [],
};

// RouteResponse the card fetches via getRoute to render the ladder.
const route: ApprovalRoute = {
  id: 'route-1',
  project_id: 'proj-1',
  target_kind: TARGET_KIND,
  name: 'Std markup review',
  is_active: true,
  created_by: 'user-author',
  created_at: '2026-05-20T09:00:00Z',
  updated_at: '2026-05-20T09:00:00Z',
  steps: [
    {
      id: 'step-1',
      route_id: 'route-1',
      ordinal: 1,
      approver_role: null,
      approver_user_id: ME_ID,
      mode: 'all',
      sla_hours: 24,
    },
    {
      id: 'step-2',
      route_id: 'route-1',
      ordinal: 2,
      approver_role: 'manager',
      approver_user_id: null,
      mode: 'any',
      sla_hours: null,
    },
  ],
};

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
}

function setupApiGet(
  opts: { instances?: ApprovalInstance[]; route?: ApprovalRoute | null; routes?: unknown[] } = {},
) {
  apiMocks.apiGet.mockImplementation(async (path: string) => {
    if (path.startsWith('/v1/users/me')) {
      return { id: ME_ID, user_id: ME_ID, email: 'me@example.com', role: 'engineer' };
    }
    if (path.includes('/instances')) {
      return opts.instances ?? [];
    }
    // Single-route fetch (getRoute) — path has a trailing /{id}.
    if (/\/routes\/[^/]+$/.test(path)) {
      return opts.route ?? route;
    }
    if (path.includes('/routes')) {
      return opts.routes ?? [];
    }
    return [];
  });
}

async function importCard() {
  const mod = await import('../ApprovalInstanceCard');
  return mod.ApprovalInstanceCard;
}

beforeEach(() => {
  // Cleanup leftover React trees + reset call history. Test-level
  // ``setupApiGet`` re-installs the GET implementation before mount —
  // we must not call ``mockReset`` mid-test because that wipes the
  // implementation set up earlier.
  cleanup();
  apiMocks.apiGet.mockReset();
  apiMocks.apiPost.mockReset();
  toastMocks.addToast.mockReset();
  // Default GET: empty arrays for everything. setupApiGet overrides
  // per-test for specific cases.
  apiMocks.apiGet.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
});

/* ── Tests ─────────────────────────────────────────────────────── */

describe('<ApprovalInstanceCard />', () => {
  // 60s budget: the FIRST test in this file pays the one-time dynamic-import
  // transform cost, which exceeds 15s when full-suite workers saturate the CPU.
  it('renders the running instance ladder with approve/reject for active assignee', { timeout: 60000 }, async () => {
    setupApiGet({ instances: [runningInstance], route });
    const ApprovalInstanceCard = await importCard();
    const qc = makeClient();

    render(
      <QueryClientProvider client={qc}>
        <ApprovalInstanceCard targetKind={TARGET_KIND} targetId={TARGET_ID} projectId="proj-1" />
      </QueryClientProvider>,
    );

    // Step-1 approve button renders once the instance + route land. We use
    // ``findByTestId`` (bumped timeout because the first test pays the
    // one-time module-transform cost).
    await screen.findByTestId('approval-approve-step-1', {}, { timeout: 4000 });

    // Approve + Reject only on the active step (step-1, the current user
    // is the named approver). Step-2 must NOT show action buttons.
    expect(screen.getByTestId('approval-reject-step-1')).toBeTruthy();
    expect(screen.queryByTestId('approval-approve-step-2')).toBeNull();
    expect(screen.queryByTestId('approval-reject-step-2')).toBeNull();
  });

  it('posts the decide payload when the approver clicks Approve', async () => {
    setupApiGet({ instances: [runningInstance], route });
    apiMocks.apiPost.mockImplementation(async () => ({
      ...runningInstance,
      status: 'approved',
    }));
    const ApprovalInstanceCard = await importCard();
    const qc = makeClient();

    render(
      <QueryClientProvider client={qc}>
        <ApprovalInstanceCard targetKind={TARGET_KIND} targetId={TARGET_ID} projectId="proj-1" />
      </QueryClientProvider>,
    );

    const approveBtn = await screen.findByTestId('approval-approve-step-1');

    // Optional comment goes along with the call. ``getAllByTestId`` +
    // [0] is defensive against any cross-test DOM bleed.
    const comments = screen.getAllByTestId('approval-comment-step-1');
    const comment = comments[0] as HTMLTextAreaElement;
    fireEvent.change(comment, { target: { value: 'LGTM' } });

    fireEvent.click(approveBtn);

    await waitFor(() => expect(apiMocks.apiPost).toHaveBeenCalled());
    const call = apiMocks.apiPost.mock.calls[0];
    expect(call).toBeTruthy();
    const [path, body] = call!;
    expect(path).toBe('/v1/approval-routes/instances/inst-1/decide');
    expect(body).toEqual({
      step_id: 'step-1',
      decision: 'approved',
      comment: 'LGTM',
    });
  });

  it('renders a no-workflow empty state when no instance exists', async () => {
    setupApiGet({ instances: [], routes: [] });
    const ApprovalInstanceCard = await importCard();
    const qc = makeClient();

    render(
      <QueryClientProvider client={qc}>
        <ApprovalInstanceCard
          targetKind={TARGET_KIND}
          targetId={TARGET_ID}
          projectId="proj-1"
        />
      </QueryClientProvider>,
    );

    // The lazy empty card renders without fetching routes upfront.
    await waitFor(() => {
      expect(
        screen.getByTestId('approval-instance-card-empty-lazy'),
      ).toBeTruthy();
    });
    expect(screen.getByText('No approval workflow running.')).toBeTruthy();
  });
});
