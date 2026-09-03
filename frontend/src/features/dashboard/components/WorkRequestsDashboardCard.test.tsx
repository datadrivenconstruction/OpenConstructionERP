// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The dashboard's Department requests card: the portfolio rollup per
 * department, each row a link into the module filtered to that
 * department - and a quiet line, not an error, when the module is not
 * mounted on this server.
 *
 * Run: npx vitest run src/features/dashboard/components/WorkRequestsDashboardCard.test.tsx
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { apiGet, ApiError } from '@/shared/lib/api';
import { DepartmentRequestsCard, hasAnyRequests } from './DepartmentRequestsCard';
import type { DepartmentSummaryRow } from '@/modules/comms-intelligence/WorkRequestsApi';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn() };
});

function dept(over: Partial<DepartmentSummaryRow> & { key: string }): DepartmentSummaryRow {
  return {
    name: over.key,
    colour: '#f97316',
    open: 0,
    overdue: 0,
    with_requester: 0,
    due_this_week: 0,
    hours_quoted: 0,
    hours_logged: 0,
    ...over,
  };
}

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DepartmentRequestsCard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const mockedGet = vi.mocked(apiGet);

beforeEach(() => {
  mockedGet.mockReset();
});

describe('hasAnyRequests', () => {
  it('is false for departments with nothing on them', () => {
    expect(hasAnyRequests([dept({ key: 'a' }), dept({ key: 'b' })])).toBe(false);
    expect(hasAnyRequests([dept({ key: 'a' }), dept({ key: 'b', due_this_week: 1 })])).toBe(true);
    expect(hasAnyRequests([])).toBe(false);
  });
});

describe('DepartmentRequestsCard', () => {
  it('reads the portfolio summary (no project) and says so when the module is absent', async () => {
    mockedGet.mockRejectedValue(new ApiError(404, 'Not Found', { detail: 'Not Found' }));
    renderCard();
    await waitFor(() => expect(screen.getByTestId('department-requests-card-absent')).toBeInTheDocument());
    expect(mockedGet).toHaveBeenCalledWith('/v1/work-requests/summary');
    // No link into a module that is not there.
    expect(screen.queryByText('Open work requests')).toBeNull();
  });

  it('shows the empty state when departments exist but hold nothing', async () => {
    mockedGet.mockResolvedValue({ departments: [dept({ key: 'engineering', name: 'Engineering' })] });
    renderCard();
    await waitFor(() => expect(screen.getByText('No department requests yet')).toBeInTheDocument());
    expect(screen.queryByTestId('department-requests-card-rows')).toBeNull();
    expect(screen.getByText('Open work requests')).toHaveAttribute('href', '/work-requests');
  });

  it('renders one row per department with the four counts, linking to the department filter', async () => {
    mockedGet.mockResolvedValue({
      departments: [
        dept({ key: 'engineering', name: 'Engineering', open: 4, overdue: 1, with_requester: 2, due_this_week: 3 }),
        dept({ key: 'hazardous-area', name: 'Hazardous area', open: 0 }),
      ],
    });
    renderCard();
    await waitFor(() => expect(screen.getByTestId('department-requests-card-rows')).toBeInTheDocument());
    const rows = screen.getAllByTestId('department-requests-card-row');
    expect(rows).toHaveLength(2);
    const cells = Array.from(rows[0]!.querySelectorAll('td')).map((td) => td.textContent?.trim());
    expect(cells.slice(1)).toEqual(['4', '1', '2', '3']);
    expect(screen.getByRole('link', { name: 'Engineering' })).toHaveAttribute(
      'href',
      '/work-requests?department=engineering',
    );
    expect(screen.getByRole('link', { name: 'Hazardous area' })).toHaveAttribute(
      'href',
      '/work-requests?department=hazardous-area',
    );
  });
});
