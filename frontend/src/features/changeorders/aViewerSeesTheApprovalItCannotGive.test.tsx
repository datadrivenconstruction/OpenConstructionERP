// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What a user may read never depends on what they may write. A viewer opening
// a submitted change order sees the same approval controls and the same
// approvals section as a manager; only the actions are disabled, each saying
// who can take them. The harness is the one landedPillsOpenTheBillAndBudget uses.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const navigateSpy = vi.fn();

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useNavigate: () => navigateSpy,
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

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    getApprovals: vi.fn(() => Promise.resolve([])),
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

const auth = { userRole: 'admin', accessToken: '' };

vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (selector?: (s: typeof auth) => unknown) => (selector ? selector(auth) : auth),
}));

import { ChangeOrdersPage } from './ChangeOrdersPage';

function order(status: string, metadata: Record<string, unknown>) {
  return {
    id: 'co-1',
    project_id: 'proj-1',
    code: 'CO-001',
    title: 'Revised ground floor slab',
    description: 'Thicker slab to carry the plant room.',
    reason_category: 'design_change',
    status,
    submitted_by: null,
    submitted_by_name: null,
    approved_by: status === 'approved' || status === 'executed' ? 'u-2' : null,
    approved_by_name: null,
    rejected_by: null,
    rejected_by_name: null,
    submitted_at: null,
    approved_at: status === 'approved' || status === 'executed' ? '2026-08-02T09:00:00Z' : null,
    rejected_at: null,
    cost_impact: '12500.00',
    schedule_impact_days: 4,
    currency: 'EUR',
    metadata,
    item_count: 0,
    created_at: '2026-08-01T09:00:00Z',
    updated_at: '2026-08-01T10:00:00Z',
    current_approval_step: 0,
    items: [],
  };
}

function setTransport(record: ReturnType<typeof order>): void {
  apiGetMock.mockImplementation((url: string) => {
    if (url.startsWith('/v1/projects/?')) {
      return Promise.resolve([{ id: 'proj-1', name: 'Riverside', currency: 'EUR' }]);
    }
    if (url.startsWith('/v1/changeorders/co-1')) return Promise.resolve(record);
    return Promise.resolve([]);
  });
}

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/changeorders?highlight=co-1']}>
        <ChangeOrdersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  navigateSpy.mockClear();
  apiGetMock.mockReset();
});

afterEach(() => {
  cleanup();
  auth.userRole = 'admin';
});

describe('a viewer reads the approval the way an approver does', () => {
  it('shows Approve and Reject to a viewer, disabled, saying a manager can', async () => {
    auth.userRole = 'viewer';
    setTransport(order('submitted', {}));
    renderDetail();

    const approve = await screen.findByRole('button', { name: /^Approve$/ });
    const reject = screen.getByRole('button', { name: /^Reject$/ });
    for (const button of [approve, reject]) {
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute('title', 'Only a manager or administrator can do this.');
    }
    expect(screen.getByText('Awaiting approval')).toBeInTheDocument();
    // The approvals section and its action are on screen for the viewer too.
    expect(screen.getByText('Approvals')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start approval chain' })).toBeDisabled();
    // Line items need an editor: the add button stays, disabled with its reason.
    expect(screen.getByRole('button', { name: /Add Item/ })).toHaveAttribute(
      'title',
      'Only an editor, manager or administrator can do this.',
    );
  });

  it('gives a manager the same controls, enabled', async () => {
    auth.userRole = 'manager';
    setTransport(order('submitted', {}));
    renderDetail();

    const approve = await screen.findByRole('button', { name: /^Approve$/ });
    expect(approve).toBeEnabled();
    expect(approve).not.toHaveAttribute('title');
    expect(screen.getByRole('button', { name: /^Reject$/ })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Start approval chain' })).toBeEnabled();
    expect(screen.queryByText('Awaiting approval')).toBeNull();
  });
});
