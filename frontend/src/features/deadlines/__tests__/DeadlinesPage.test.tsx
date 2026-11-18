// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Tests for <DeadlinesPage /> - the cross-module deadline register (item #18).
//
// Coverage (design section 9.2):
//   1. renders the grouped register (group headers + rows across two modules).
//   2. shows the critical (error) chip for an overdue row.
//   3. empty payload -> the calm empty-state copy, no table.
//   4. pending query -> loading spinner.
//   5. failing query -> error copy + retry button that refetches.
//   6. clicking the "Overdue" filter issues a new fetch with status=overdue.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

/* ── API mock - fetchDeadlines calls apiGet directly. ─────────────────── */

const apiMocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  getErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
  ApiError: class ApiError extends Error {},
  getAuthToken: () => null,
  API_BASE: '/api',
}));
vi.mock('@/shared/lib/api', () => apiMocks);

/* ── i18n stub - return the English defaultValue, interpolate {{count}}. ── */

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string; count?: number }) => {
      let s = opts?.defaultValue ?? key;
      if (opts && typeof opts.count === 'number') s = s.replace('{{count}}', String(opts.count));
      return s;
    },
  }),
  // Replacing the module wholesale hides every export the stub omits, and the
  // page pulls in ErrorBoundary, which imports the real i18n singleton and
  // calls `.use(initReactI18next)` at module scope. Without this the suite
  // fails to collect at all.
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

/* ── Project context - a fixed active project id. ─────────────────────── */

vi.mock('@/stores/useProjectContextStore', () => ({
  useProjectContextStore: (selector: (s: { activeProjectId: string | null }) => unknown) =>
    selector({ activeProjectId: 'proj-1' }),
}));

// The statutory section has its own suite; here it would share the api mock.
vi.mock('@/features/statutory', () => ({ StatutoryChecksSection: () => null }));

import { DeadlinesPage } from '../DeadlinesPage';
import type { DeadlineItem, DeadlineRegister } from '../api';

/* ── Helpers ──────────────────────────────────────────────────────────── */

function makeItem(over: Partial<DeadlineItem> = {}): DeadlineItem {
  return {
    id: 'punchlist:1',
    module: 'punchlist',
    entity_type: 'punch_item',
    entity_id: '1',
    project_id: 'proj-1',
    project_name: 'Tower A',
    title: 'Seal roof penetration',
    due_date: '2026-07-10',
    owner_user_id: 'user-1',
    owner_name: 'Dana Lee',
    status: 'open',
    classification: 'overdue',
    days_overdue: 2,
    severity: 'critical',
    action_url: '/punchlist?highlight=1',
    ...over,
  };
}

function makeRegister(over: Partial<DeadlineRegister> = {}): DeadlineRegister {
  return {
    items: [],
    overdue_count: 0,
    approaching_count: 0,
    generated_at: '2026-07-24T00:00:00+00:00',
    ...over,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DeadlinesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiMocks.apiGet.mockReset();
});
afterEach(() => cleanup());

/* ── Tests ────────────────────────────────────────────────────────────── */

describe('DeadlinesPage', () => {
  it('renders a grouped register with rows across two modules', async () => {
    apiMocks.apiGet.mockResolvedValue(
      makeRegister({
        items: [
          makeItem({ id: 'punchlist:1', module: 'punchlist', title: 'Seal roof penetration' }),
          makeItem({
            id: 'correspondence:9',
            module: 'correspondence',
            entity_type: 'correspondence',
            title: 'Reply to variation notice',
            classification: 'approaching',
            days_overdue: -1,
            severity: 'warning',
            action_url: '/correspondence',
          }),
        ],
        overdue_count: 1,
        approaching_count: 1,
      }),
    );
    renderPage();
    expect(await screen.findByText('Seal roof penetration')).toBeInTheDocument();
    expect(screen.getByText('Reply to variation notice')).toBeInTheDocument();
    // Group headers for both modules. Scoped to the table because the "how it
    // fits together" explainer links to the same modules by name.
    const table = within(screen.getByRole('table'));
    expect(table.getByText('Punch list')).toBeInTheDocument();
    expect(table.getByText('Correspondence')).toBeInTheDocument();
    // Owner name resolved.
    expect(screen.getAllByText('Dana Lee').length).toBeGreaterThan(0);
  });

  it('shows the critical chip for an overdue row', async () => {
    apiMocks.apiGet.mockResolvedValue(
      makeRegister({ items: [makeItem({ days_overdue: 2 })], overdue_count: 1 }),
    );
    const { container } = renderPage();
    expect(await screen.findByText('2d overdue')).toBeInTheDocument();
    expect(container.querySelector('.text-semantic-error')).not.toBeNull();
  });

  it('renders the empty state when nothing is due', async () => {
    apiMocks.apiGet.mockResolvedValue(makeRegister());
    renderPage();
    expect(
      await screen.findByText("Nothing overdue or approaching. You're on top of it."),
    ).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('shows a loading spinner while the query is pending', () => {
    apiMocks.apiGet.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('shows an error state with a retry that refetches', async () => {
    apiMocks.apiGet.mockRejectedValue(new Error('boom'));
    renderPage();
    expect(await screen.findByText("Couldn't load the deadline register")).toBeInTheDocument();
    const callsBefore = apiMocks.apiGet.mock.calls.length;
    fireEvent.click(screen.getByText('Try again'));
    await waitFor(() => expect(apiMocks.apiGet.mock.calls.length).toBeGreaterThan(callsBefore));
  });

  it('refetches with status=overdue when the Overdue filter is clicked', async () => {
    apiMocks.apiGet.mockResolvedValue(makeRegister({ overdue_count: 1 }));
    renderPage();
    await screen.findByText('All');
    // By role, because the explainer mentions "Overdue" as prose too.
    fireEvent.click(screen.getByRole('button', { name: /Overdue/ }));
    await waitFor(() => {
      const urls = apiMocks.apiGet.mock.calls.map((c) => String(c[0]));
      expect(urls.some((u) => u.includes('status=overdue'))).toBe(true);
    });
  });
});
