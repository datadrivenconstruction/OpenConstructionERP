// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Tests for <ApprovalRoutesPage /> — admin surface for approval-route
// templates (Wave-2, Epic A).
//
// Coverage:
//   1. Render-doesn't-crash: tabs render with at least one route present
//      (proves the page chrome + the table render path both mount).
//   2. Basic interaction: clicking "New route" opens the editor.
//   3. Happy-path API mock: the page actually calls the listRoutes helper
//      with the expected target-kind / includeInactive flags.
//
// Mocking strategy mirrors the accommodation `ux_overhaul.test.tsx` —
// we stub the feature-local `../api` module (high level) rather than the
// `@/shared/lib/api` JSON wrapper, which keeps the test light and
// deterministic even though the page imports the entire `@/shared/ui`
// barrel.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import type { ApprovalRoute } from '../types';

/* ── Toast store mock ─────────────────────────────────────────────── */

const toastMocks = vi.hoisted(() => ({ addToast: vi.fn() }));
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: Object.assign(
    (selector: (s: { addToast: typeof toastMocks.addToast }) => unknown) =>
      selector({ addToast: toastMocks.addToast }),
    { getState: () => ({ addToast: toastMocks.addToast }) },
  ),
}));

/* ── Feature-local API mock ───────────────────────────────────────── */

vi.mock('../api', () => ({
  listRoutes: vi.fn(),
  getRoute: vi.fn(),
  getMeta: vi.fn(() =>
    Promise.resolve({
      target_kinds: [
        'markup',
        'submittal',
        'change_order',
        'rfi',
        'contract',
        'variation',
        'invoice',
        'purchase_order',
      ],
      step_modes: ['all', 'any', 'majority'],
      instance_statuses: ['pending', 'approved', 'rejected', 'cancelled'],
    }),
  ),
  createRoute: vi.fn(),
  updateRoute: vi.fn(),
  deleteRoute: vi.fn(),
  listInstances: vi.fn(),
  getInstance: vi.fn(),
  startInstance: vi.fn(),
  decideInstance: vi.fn(),
  cancelInstance: vi.fn(),
  approvalRoutesKeys: {
    meta: () => ['approval-routes', 'meta'] as const,
    routes: (projectId?: string | null, targetKind?: string | null) =>
      ['approval-routes', 'routes', projectId ?? null, targetKind ?? null] as const,
    route: (id: string) => ['approval-routes', 'route', id] as const,
    instances: (
      targetKind?: string | null,
      targetId?: string | null,
      projectId?: string | null,
      status?: string | null,
    ) =>
      [
        'approval-routes',
        'instances',
        targetKind ?? null,
        targetId ?? null,
        projectId ?? null,
        status ?? null,
      ] as const,
    instance: (id: string) => ['approval-routes', 'instance', id] as const,
  },
}));

/* ── Heavy inner components stubbed ───────────────────────────────── */

vi.mock('../ApprovalInstancesList', () => ({
  ApprovalInstancesList: () => <div data-testid="instances-list-stub" />,
}));

vi.mock('../RouteEditor', () => ({
  RouteEditor: ({ open }: { open: boolean }) =>
    open ? <div data-testid="route-editor-open" /> : null,
}));

import { listRoutes } from '../api';
import { ApprovalRoutesPage } from '../ApprovalRoutesPage';

/* ── Helpers ──────────────────────────────────────────────────────── */

const SAMPLE_ROUTE: ApprovalRoute = {
  id: 'route-1',
  name: 'Std submittal review',
  target_kind: 'submittal',
  project_id: null,
  is_active: true,
  steps: [
    {
      id: 'step-1',
      route_id: 'route-1',
      ordinal: 1,
      approver_role: 'engineer',
      approver_user_id: null,
      mode: 'any',
      sla_hours: 24,
    },
  ],
  created_at: '2026-05-20T00:00:00Z',
  updated_at: '2026-05-20T00:00:00Z',
  created_by: 'user-1',
};

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <ApprovalRoutesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

/* ── Tests ────────────────────────────────────────────────────────── */

describe('<ApprovalRoutesPage />', () => {
  it('renders the page chrome and the route row from the API mock', async () => {
    (listRoutes as ReturnType<typeof vi.fn>).mockResolvedValue([SAMPLE_ROUTE]);
    renderPage();

    // Once the route lands the table row renders with the route name.
    await waitFor(() => {
      expect(screen.getByText('Std submittal review')).toBeTruthy();
    });

    // Tabs are visible alongside the table.
    expect(screen.getByRole('tab', { name: /Route templates/i })).toBeTruthy();
    expect(
      screen.getByRole('tab', { name: /Running & history/i }),
    ).toBeTruthy();
  });

  it('opens the route editor when "New route" is clicked', async () => {
    (listRoutes as ReturnType<typeof vi.fn>).mockResolvedValue([SAMPLE_ROUTE]);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Std submittal review')).toBeTruthy();
    });

    // The header button + the empty-state button both say "New route";
    // pick the first match deterministically.
    const newRouteButtons = screen.getAllByRole('button', {
      name: /New route/i,
    });
    expect(newRouteButtons.length).toBeGreaterThan(0);
    fireEvent.click(newRouteButtons[0]!);

    await waitFor(() => {
      expect(screen.getByTestId('route-editor-open')).toBeTruthy();
    });
  });

  it('calls listRoutes with includeInactive when the page loads', async () => {
    (listRoutes as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    renderPage();

    await waitFor(() => {
      expect(listRoutes).toHaveBeenCalled();
    });

    const call = (listRoutes as ReturnType<typeof vi.fn>).mock.calls[0]?.[0];
    expect(call).toMatchObject({ includeInactive: true });
  });

  it('renders a full-width root container (no centered max-width clamp)', async () => {
    // Founder UX: the Approval Routes tab must fill the width like its
    // Permissions (governance) / Validation siblings, which use a plain
    // "space-y-5 animate-fade-in" root with no "mx-auto max-w-7xl" clamp.
    (listRoutes as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    const { container } = renderPage();

    const root = container.firstChild as HTMLElement;
    expect(root.className).not.toContain('mx-auto');
    expect(root.className).not.toContain('max-w-7xl');
    expect(root.className).toContain('px-4');
    expect(root.className).toContain('py-4');
    expect(root.className).toContain('animate-fade-in');
  });
});
