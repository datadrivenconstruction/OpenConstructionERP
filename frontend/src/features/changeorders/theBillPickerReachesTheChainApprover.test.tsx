// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Tests for who gets asked "which bill?" on the change order detail view.
//
// The backend now refuses an approval it cannot place: a project holding more
// than one unlocked bill of quantities gets HTTP 409 instead of a silent
// write into whichever bill happened to be oldest. That turns the picker
// below the header from decoration into the only way to answer, and it makes
// the render condition a correctness question rather than a layout one -
// an approver who cannot see the picker meets a refusal with no field to
// reply in, and the change order simply cannot be approved from the UI.
//
// The two approval paths authorise differently, which is the whole point of
// these tests. The single-step path is role-gated (admin or manager). The
// chain path is not: `advance_approval` carries no role dependency, and the
// timeline hands its decision buttons to whoever sits at the cursor. So the
// picker follows the union, and both halves need a control - a gate stuck at
// `true` would satisfy the editor case, and a gate left at `canApprove` would
// satisfy the admin case. Only the pair pins the actual rule.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

/* ── i18n ──────────────────────────────────────────────────────────────────
   Both `t(key, 'English default')` and `t(key, { defaultValue })` appear on
   this page and in the chrome it renders inside, so both arities are handled
   here. Without it the page renders bare `changeorders.*` keys and the label
   the picker is found by never appears. */

/* ── Routing ───────────────────────────────────────────────────────────────
   The shared setup stubs `useSearchParams` to a permanently empty set, which
   is right for the pages that only write to it and wrong here: the register
   reads `?highlight=<id>` to open straight on a record, and with the shared
   stub in place the detail view this file is about never mounts at all. The
   factory registered last wins, so this one replaces it for this file only,
   and hands back a real, fixed query string rather than a live one - nothing
   here navigates. */

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useParams: () => ({}),
    useSearchParams: () => [new URLSearchParams('?highlight=co-1'), vi.fn()],
  };
});

vi.mock('react-i18next', () => {
  type Opts = Record<string, unknown>;
  const fill = (template: string, opts?: Opts): string => {
    if (!opts) return template;
    const scope = (opts.replace as Opts | undefined) ?? opts;
    return template.replace(/\{\{(\w+)\}\}/g, (_match, name: string) =>
      scope[name] === undefined ? `{{${name}}}` : String(scope[name]),
    );
  };
  return {
    useTranslation: () => ({
      t: (key: string, second?: string | Opts, third?: Opts) => {
        if (typeof second === 'string') return fill(second, third);
        const dflt = second?.defaultValue;
        return fill(typeof dflt === 'string' ? dflt : key, second);
      },
      i18n: { language: 'en', changeLanguage: vi.fn() },
    }),
    Trans: ({ children }: { children?: unknown }) => children ?? null,
    initReactI18next: { type: '3rdParty', init: () => undefined },
    I18nextProvider: ({ children }: { children?: unknown }) => children ?? null,
  };
});

/* ── Transport ─────────────────────────────────────────────────────────────
   One router keyed by URL, spread over the real module so `ApiError` stays
   the class the page's `instanceof` check is written against. Unknown URLs
   answer an empty list rather than throwing: the detail view pulls in an
   evidence panel, a contracts lookup and a user directory that have nothing
   to do with the picker, and each of them failing loudly would bury it. */

const apiGetMock = vi.fn();

vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/api')>();
  return {
    ...actual,
    apiGet: (url: string, ...rest: unknown[]) => apiGetMock(url, ...rest),
    apiPost: vi.fn(() => Promise.resolve({})),
    apiDelete: vi.fn(() => Promise.resolve({})),
  };
});

/* Feature api: spread the real module so `isWritebackRefusal` keeps its real
   behaviour, and replace only the calls that would hit the network. */
const getApprovalsMock = vi.fn();

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    getApprovals: (...args: unknown[]) => getApprovalsMock(...args),
    advanceApproval: vi.fn(() => Promise.resolve({})),
    startApprovalChain: vi.fn(() => Promise.resolve([])),
    simulateImpact: vi.fn(() => Promise.resolve({})),
    publishScenario: vi.fn(() => Promise.resolve({})),
    aiDraftChangeOrder: vi.fn(() => Promise.resolve({})),
  };
});

vi.mock('@/features/contracts/api', () => ({
  listContracts: vi.fn(() => Promise.resolve([])),
}));

/* Panels that own their own data and none of this question. Stubbing them
   keeps a failure here about the picker. */
vi.mock('@/features/claims-evidence', () => ({
  ProvabilityGauge: () => null,
  EvidenceThreadPanel: () => null,
}));

vi.mock('@/features/insights', () => ({
  InsightsPanel: () => null,
  InsightsToggleButton: () => null,
  useModuleInsights: () => ({ open: false, toggle: vi.fn(), insights: [], kpis: [], series: [] }),
}));

vi.mock('./ImpactSimulator', () => ({ ImpactSimulator: () => null }));
vi.mock('./AIDraftModal', () => ({ AIDraftModal: () => null }));

vi.mock('@/stores/useProjectContextStore', () => {
  const state = { activeProjectId: 'proj-1' };
  return {
    useProjectContextStore: (selector?: (s: typeof state) => unknown) =>
      selector ? selector(state) : state,
  };
});

vi.mock('@/stores/useToastStore', () => {
  const state = { addToast: vi.fn(), toasts: [], removeToast: vi.fn() };
  return {
    useToastStore: (selector?: (s: typeof state) => unknown) =>
      selector ? selector(state) : state,
  };
});

/* Auth is what the tests vary, so it reads a mutable box rather than a
   frozen literal. */
const auth = { userRole: 'admin', accessToken: '' };

vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (selector?: (s: typeof auth) => unknown) => (selector ? selector(auth) : auth),
}));

import type { ApprovalRow } from './api';
import { ChangeOrdersPage } from './ChangeOrdersPage';

/* ── Fixtures ──────────────────────────────────────────────────────────── */

const ME = '11111111-1111-4111-8111-111111111111';
const SOMEONE_ELSE = '22222222-2222-4222-8222-222222222222';

/** A JWT-shaped token carrying `sub`. The page decodes this claim to decide
 *  whether the viewer is the approver at the cursor, exactly as the backend
 *  reads it, so a hand-built fixture has to be a real three-part token. */
function tokenFor(userId: string): string {
  const b64 = (o: unknown) => btoa(JSON.stringify(o)).replace(/=+$/, '');
  return `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64({ sub: userId })}.signature`;
}

const ORDER = {
  id: 'co-1',
  project_id: 'proj-1',
  code: 'CO-001',
  title: 'Revised ground floor slab',
  description: 'Thicker slab to carry the plant room.',
  reason_category: 'design_change',
  status: 'submitted',
  submitted_by: SOMEONE_ELSE,
  submitted_by_name: 'Site QS',
  approved_by: null,
  approved_by_name: null,
  rejected_by: null,
  rejected_by_name: null,
  submitted_at: '2026-08-01T10:00:00Z',
  approved_at: null,
  rejected_at: null,
  cost_impact: '12500.00',
  schedule_impact_days: 4,
  currency: 'EUR',
  metadata: {},
  item_count: 1,
  created_at: '2026-08-01T09:00:00Z',
  updated_at: '2026-08-01T10:00:00Z',
  current_approval_step: 2,
  items: [],
};

/** Two unlocked bills is the ambiguous project: the approval has a question.
 *  The locked one is here so a picker that forgot to filter shows three
 *  options and fails on the count. */
const TWO_UNLOCKED = [
  { id: 'boq-a', name: 'Main contract bill', is_locked: false },
  { id: 'boq-b', name: 'Enabling works bill', is_locked: false },
  { id: 'boq-c', name: 'Closed out bill', is_locked: true },
];

const ONE_UNLOCKED = [
  { id: 'boq-a', name: 'Main contract bill', is_locked: false },
  { id: 'boq-c', name: 'Closed out bill', is_locked: true },
];

/** A two-step chain sitting at step 2. */
function chain(approverAtCursor: string): ApprovalRow[] {
  return [
    {
      id: 'ap-1',
      change_order_id: 'co-1',
      step_order: 1,
      approver_user_id: SOMEONE_ELSE,
      decision: 'approved',
      decided_at: '2026-08-02T09:00:00Z',
      comments: null,
      created_at: '2026-08-01T11:00:00Z',
    },
    {
      id: 'ap-2',
      change_order_id: 'co-1',
      step_order: 2,
      approver_user_id: approverAtCursor,
      decision: 'pending',
      decided_at: null,
      comments: null,
      created_at: '2026-08-01T11:00:00Z',
    },
  ];
}

/* ── Harness ───────────────────────────────────────────────────────────── */

function setTransport(boqs: unknown[]): void {
  apiGetMock.mockImplementation((url: string) => {
    if (url.startsWith('/v1/boq/boqs/')) return Promise.resolve(boqs);
    // The list, read through fetchProjectList, not the project detail.
    if (url.startsWith('/v1/projects/?')) {
      return Promise.resolve([{ id: 'proj-1', name: 'Riverside', currency: 'EUR' }]);
    }
    if (url.startsWith('/v1/changeorders/co-1')) return Promise.resolve(ORDER);
    return Promise.resolve([]);
  });
}

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      {/* ?highlight= opens the register straight on the record, which is how
          the Variations page deep-links into it. */}
      <MemoryRouter initialEntries={['/changeorders?highlight=co-1']}>
        <ChangeOrdersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The picker, found by the accessible name it is labelled with. */
function picker(): HTMLSelectElement | null {
  return screen.queryByLabelText(
    'Bill of quantities to receive the approved scope',
  ) as HTMLSelectElement | null;
}

/** Waits for the detail view to be on screen, so "no picker" is a real
 *  absence rather than a page that has not loaded yet. */
async function detailIsUp(): Promise<void> {
  await screen.findByText('Revised ground floor slab');
  await waitFor(() => expect(apiGetMock).toHaveBeenCalledWith(expect.stringContaining('/v1/boq/boqs/')));
}

describe('the bill picker on an ambiguous project', () => {
  beforeEach(() => {
    auth.userRole = 'admin';
    auth.accessToken = tokenFor(ME);
    apiGetMock.mockReset();
    getApprovalsMock.mockReset();
    getApprovalsMock.mockResolvedValue([]);
  });

  afterEach(() => cleanup());

  it('reaches an editor who is the approver at the cursor', async () => {
    // The case that was broken. `advance_approval` has no role check, so this
    // editor is authorised to finish the chain, and finishing it is exactly
    // what triggers the writeback the backend refuses to guess at.
    auth.userRole = 'editor';
    getApprovalsMock.mockResolvedValue(chain(ME));
    setTransport(TWO_UNLOCKED);
    renderDetail();
    await detailIsUp();

    const el = await screen.findByLabelText('Bill of quantities to receive the approved scope');
    const options = Array.from((el as HTMLSelectElement).options).map((o) => o.textContent);
    // The prompt plus the two unlocked bills; the locked one is not offered
    // because it cannot take the write.
    expect(options).toEqual(['Select BOQ...', 'Main contract bill', 'Enabling works bill']);
  });

  it('does not reach an editor who is not the one being asked', async () => {
    // The control for the test above. Without it a gate that simply dropped
    // the role check would pass, and every viewer of the record would be
    // offered a decision that is not theirs to make.
    auth.userRole = 'editor';
    getApprovalsMock.mockResolvedValue(chain(SOMEONE_ELSE));
    setTransport(TWO_UNLOCKED);
    renderDetail();
    await detailIsUp();

    expect(picker()).toBeNull();
  });

  it('still reaches an admin on the single-step path', async () => {
    // The other control: the role gate has to keep working for the plain
    // approval, which has no chain and no cursor to fall back on.
    auth.userRole = 'admin';
    getApprovalsMock.mockResolvedValue([]);
    setTransport(TWO_UNLOCKED);
    renderDetail();
    await detailIsUp();

    expect(picker()).not.toBeNull();
  });

  it('is absent when the project has a single unlocked bill', async () => {
    // Nothing ambiguous, nothing to ask: the backend places the scope without
    // a question, so asking one would be a step invented by the UI.
    auth.userRole = 'admin';
    getApprovalsMock.mockResolvedValue([]);
    setTransport(ONE_UNLOCKED);
    renderDetail();
    await detailIsUp();

    expect(picker()).toBeNull();
  });
});
