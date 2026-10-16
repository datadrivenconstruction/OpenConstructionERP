// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The status history panel and the register ageing panel of the interface
// register. Fixtures mirror the backend response models
// (backend/app/modules/interface_management/schemas.py:
// InterfaceHistoryResponse, InterfaceRegisterResponse,
// InterfaceValidationResponse).
//
// Coverage:
//   1. History reads the per-interface endpoint and shows who moved the
//      interface, from which status to which, with the comment.
//   2. An approval-route entry with no status move shows the event only.
//   3. Ageing tiles and bands render the register numbers, overdue in red.
//   4. Register checks name the failing rule per interface reference, and
//      say so when everything passes.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

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
  getErrorMessage: (e: unknown) => String(e),
}));
vi.mock('@/shared/lib/api', () => apiMocks);

import { InterfaceHistoryPanel } from '../InterfaceHistoryPanel';
import { RegisterAgeingPanel } from '../RegisterAgeingPanel';
import type {
  InterfaceHistoryEntry,
  InterfaceRecord,
  InterfaceRegister,
  InterfaceValidationReport,
} from '../api';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const history: InterfaceHistoryEntry[] = [
  {
    id: 'h1',
    interface_id: 'if-1',
    event: 'created',
    from_status: null,
    to_status: 'identified',
    actor_id: 'u1',
    actor_name: 'Dana Coordinator',
    comment: null,
    approval_instance_id: null,
    changed_at: '2026-10-10T08:00:00Z',
  },
  {
    id: 'h2',
    interface_id: 'if-1',
    event: 'status_changed',
    from_status: 'identified',
    to_status: 'in_progress',
    actor_id: 'u1',
    actor_name: 'Dana Coordinator',
    comment: 'Kick-off held with both packages',
    approval_instance_id: null,
    changed_at: '2026-10-11T08:00:00Z',
  },
  {
    id: 'h3',
    interface_id: 'if-1',
    event: 'approval_rejected',
    from_status: 'in_progress',
    to_status: 'in_progress',
    actor_id: null,
    actor_name: null,
    comment: null,
    approval_instance_id: 'inst-1',
    changed_at: '2026-10-12T08:00:00Z',
  },
];

describe('InterfaceHistoryPanel', () => {
  it('reads the history endpoint and shows who moved the interface, from where to where, and why', async () => {
    apiMocks.apiGet.mockResolvedValueOnce(history);
    wrap(<InterfaceHistoryPanel projectId="p-1" interfaceId="if-1" />);

    expect(await screen.findByText('Kick-off held with both packages')).toBeInTheDocument();
    expect(apiMocks.apiGet).toHaveBeenCalledWith('/v1/interface-management/projects/p-1/interfaces/if-1/history');
    const items = within(screen.getByTestId('interface-history')).getAllByRole('listitem');
    expect(items).toHaveLength(3);
    expect(items[1]).toHaveTextContent('Status changed');
    expect(items[1]).toHaveTextContent('Identified');
    expect(items[1]).toHaveTextContent('In progress');
    expect(items[1]).toHaveTextContent('Dana Coordinator');
    // A route event that did not move the status names the event, and a row
    // with no actor reads as the system rather than as an empty name.
    expect(items[2]).toHaveTextContent('Rejected on route');
    expect(items[2]).toHaveTextContent('System');
  });

  it('says so when nothing was recorded yet', async () => {
    apiMocks.apiGet.mockResolvedValueOnce([]);
    wrap(<InterfaceHistoryPanel projectId="p-1" interfaceId="if-1" />);
    await waitFor(() => expect(screen.getByText(/No changes recorded yet/)).toBeInTheDocument());
  });
});

const register: InterfaceRegister = {
  project_id: 'p-1',
  as_of: '2026-10-16',
  total: 4,
  per_status: {},
  per_priority: {},
  per_type: {},
  agreed_pct: '25.00',
  overall_health_score: '50.00',
  total_open_actions: 0,
  is_healthy: false,
  overdue: [],
  disputed: [],
  work_packages: [],
  open_count: 3,
  overdue_count: 2,
  ageing: { '0_7': 1, '8_30': 1, '31_60': 1, '61_90': 0, over_90: 0, unknown: 0 },
  overdue_ageing: { '1_7': 1, '8_30': 0, '31_60': 0, over_60: 1 },
  average_open_age_days: '17.00',
  oldest_open_age_days: 40,
  max_days_overdue: 70,
};

const interfaces = [{ id: 'if-1', reference: 'IF-014' }] as InterfaceRecord[];

describe('RegisterAgeingPanel', () => {
  it('renders the ageing tiles and both distributions', () => {
    wrap(<RegisterAgeingPanel register={register} validation={undefined} interfaces={interfaces} />);
    expect(screen.getByTestId('ageing-tile-open')).toHaveTextContent('3');
    expect(screen.getByTestId('ageing-tile-overdue')).toHaveTextContent('2');
    expect(screen.getByTestId('ageing-tile-overdue').className).toContain('text-semantic-error');
    expect(screen.getByTestId('ageing-tile-avg')).toHaveTextContent('17 d');
    expect(screen.getByTestId('ageing-tile-oldest')).toHaveTextContent('40 d');
    expect(screen.getByTestId('ageing-tile-late')).toHaveTextContent('70 d');
    expect(screen.getByTestId('band-neutral-31_60')).toHaveTextContent('1');
    expect(screen.getByTestId('band-error-over_60')).toHaveTextContent('1');
    expect(screen.queryByTestId('register-checks')).toBeNull();
  });

  it('names each failing check by its interface reference', () => {
    const validation: InterfaceValidationReport = {
      project_id: 'p-1',
      status: 'errors',
      errors: 1,
      warnings: 1,
      passed: 3,
      results: [
        {
          rule_id: 'interface_management.rfi_in_project',
          severity: 'error',
          passed: false,
          message: 'IF-014: RFI x is not an RFI of this project',
          element_ref: 'if-1',
        },
        {
          rule_id: 'interface_management.need_by_before_activity_finish',
          severity: 'warning',
          passed: false,
          message: 'late',
          element_ref: 'if-1',
        },
        {
          rule_id: 'interface_management.agreed_has_agreed_date',
          severity: 'error',
          passed: true,
          message: 'OK',
          element_ref: 'if-1',
        },
      ],
    };
    wrap(<RegisterAgeingPanel register={register} validation={validation} interfaces={interfaces} />);
    const checks = screen.getByTestId('register-checks');
    expect(checks).toHaveTextContent('1 errors');
    expect(within(checks).getAllByRole('listitem')).toHaveLength(2);
    expect(checks).toHaveTextContent('IF-014');
    expect(checks).toHaveTextContent('Linked RFI is not an RFI of this project');
    expect(checks).toHaveTextContent('Need-by date is after the linked activity finishes');
    // The backend's English message is not what the screen shows.
    expect(checks).not.toHaveTextContent('RFI x');
  });

  it('reports a clean register when every check passes', () => {
    const validation: InterfaceValidationReport = {
      project_id: 'p-1',
      status: 'passed',
      errors: 0,
      warnings: 0,
      passed: 1,
      results: [],
    };
    wrap(<RegisterAgeingPanel register={register} validation={validation} interfaces={interfaces} />);
    expect(screen.getByText('Links, dates and approvals are consistent.')).toBeInTheDocument();
  });
});
