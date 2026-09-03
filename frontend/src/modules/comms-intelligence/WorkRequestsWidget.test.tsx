// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The project hub's department-requests widget in each of its states.
 *
 * The state that matters most is the one a fresh deployment is in: the
 * Work requests module answering 404 because it is not mounted. The widget
 * must say so quietly - no error copy, no raise button pointing at a page
 * that is not there - and the other two states must not be confused with
 * it (a real failure still reads as a failure; an empty job still offers
 * the raise button).
 *
 * Run: npx vitest run src/modules/comms-intelligence/WorkRequestsWidget.test.tsx
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { apiGet, ApiError } from '@/shared/lib/api';
import { WorkRequestsWidget } from './WorkRequestsWidget';
import type { DepartmentSummaryRow, WorkRequestRow } from './WorkRequestsApi';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn() };
});

const PROJECT = '9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d';

function renderWidget() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WorkRequestsWidget projectId={PROJECT} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function dept(over: Partial<DepartmentSummaryRow> & { key: string }): DepartmentSummaryRow {
  return {
    name: over.key,
    colour: '#0ea5e9',
    open: 0,
    overdue: 0,
    with_requester: 0,
    due_this_week: 0,
    hours_quoted: 0,
    hours_logged: 0,
    ...over,
  };
}

function req(over: Partial<WorkRequestRow> & { id: string; reference: string }): WorkRequestRow {
  return {
    project_id: PROJECT,
    project_code: '25406',
    department: 'drafting',
    request_type: 'drawing',
    title: over.reference,
    status: 'open',
    stage: 'in_progress',
    due_date: null,
    is_overdue: false,
    ball_in_court: 'department',
    responsible: null,
    assignees: [],
    hours_logged: 0,
    quoted_hours: 0,
    deviation_hours: 0,
    created_at: '2026-09-01T00:00:00Z',
    ...over,
  };
}

const mockedGet = vi.mocked(apiGet);

beforeEach(() => {
  mockedGet.mockReset();
});

describe('WorkRequestsWidget', () => {
  it('says the module is not available on a 404 and hides the raise button', async () => {
    mockedGet.mockRejectedValue(new ApiError(404, 'Not Found', { detail: 'Not Found' }));
    renderWidget();
    await waitFor(() => expect(screen.getByTestId('work-requests-widget-absent')).toBeInTheDocument());
    expect(screen.getByText(/not available on this server/i)).toBeInTheDocument();
    expect(screen.queryByTestId('work-requests-widget-raise')).toBeNull();
    expect(screen.queryByText(/could not be read/i)).toBeNull();
    // Both reads were attempted against the module's own base path.
    const paths = mockedGet.mock.calls.map((c) => String(c[0]));
    expect(paths.some((p) => p.startsWith(`/v1/work-requests/summary?project_id=${PROJECT}`))).toBe(true);
    expect(paths.some((p) => p.startsWith(`/v1/work-requests/requests?project_id=${PROJECT}`))).toBe(true);
  });

  it('a real failure is not mistaken for an absent module', async () => {
    mockedGet.mockRejectedValue(new ApiError(500, 'Server Error', undefined));
    renderWidget();
    await waitFor(() => expect(screen.getByText(/could not be read for this job/i)).toBeInTheDocument());
    expect(screen.queryByTestId('work-requests-widget-absent')).toBeNull();
  });

  it('an empty job shows the empty line and still offers to raise one', async () => {
    mockedGet.mockImplementation((path: string) =>
      Promise.resolve(path.includes('/summary') ? { departments: [dept({ key: 'workshop', name: 'Workshop' })] } : []),
    );
    renderWidget();
    await waitFor(() => expect(screen.getByTestId('work-requests-widget-empty')).toBeInTheDocument());
    expect(screen.getByText('No department requests on this job yet.')).toBeInTheDocument();
    expect(screen.getByTestId('work-requests-widget-raise')).toBeInTheDocument();
  });

  it('lists the departments holding work and the most urgent requests, chips opening the request', async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path.includes('/summary')) {
        return Promise.resolve({
          departments: [
            dept({ key: 'drafting', name: 'Drafting', open: 2, overdue: 1, with_requester: 1, hours_quoted: 6, hours_logged: 8 }),
            dept({ key: 'workshop', name: 'Workshop', open: 1, hours_quoted: 10, hours_logged: 2 }),
            dept({ key: 'automation', name: 'Automation' }),
          ],
        });
      }
      return Promise.resolve([
        req({ id: 'r-later', reference: 'WR-DRF-000002', title: 'GA drawing rev B', due_date: '2026-09-30' }),
        req({
          id: 'r-overdue',
          reference: 'WR-DRF-000001',
          title: 'Switchboard layout',
          due_date: '2026-08-20',
          is_overdue: true,
          ball_in_court: 'requester',
        }),
        req({ id: 'r-ws', reference: 'WR-WKS-000007', title: 'Bracket fabrication', department: 'workshop', due_date: '2026-09-10' }),
        req({ id: 'r-closed', reference: 'WR-DRF-000009', title: 'Old one', status: 'closed' }),
      ]);
    });
    renderWidget();
    // "Drafting" shows in the department table AND beside each of its
    // requests below, so wait on the table having landed.
    await waitFor(() => expect(screen.getAllByText('Drafting').length).toBeGreaterThan(0));

    // A department with nothing on it stays off the hub card.
    expect(screen.queryByText('Automation')).toBeNull();
    // Hours read logged/quoted; the overrun is visible as text too.
    expect(screen.getByText('8/6')).toBeInTheDocument();
    expect(screen.getByText('2/10')).toBeInTheDocument();

    // Overdue first, then by due date; the closed row never shows.
    const chips = screen.getAllByRole('link', { name: /Open request/ });
    expect(chips.map((c) => c.textContent)).toEqual(['WR-DRF-000001', 'WR-WKS-000007', 'WR-DRF-000002']);
    expect(chips[0]).toHaveAttribute('href', '/work-requests/r-overdue');
    expect(screen.queryByText('Old one')).toBeNull();

    // Ball in court: the overdue one is back with the requester.
    expect(screen.getAllByText('With you').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('With Workshop')).toBeInTheDocument();
    expect(screen.getByTestId('work-requests-widget-raise')).toBeInTheDocument();
  });
});
