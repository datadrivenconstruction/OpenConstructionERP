/**
 * ProjectKPIHero — failure-handling coverage (audit #24).
 *
 * The hero strip fires three independent React Query calls (variance,
 * anomalies, summary). The bug being guarded against: on failure each value
 * fell through to a default of 0, and classifyVariance(0) returns 'green', so
 * a backend 500 / permission denial / dropped request rendered a fully GREEN
 * dashboard ("+0.0%", "EUR 0") indistinguishable from a perfectly healthy
 * project — actively misleading on a decision-support surface.
 *
 * Asserts:
 *   1. While any query is loading, a skeleton (not green zero cards) renders.
 *   2. When any query errors, a Retry recovery tile renders and the green KPI
 *      cards do NOT — a failed load never masquerades as a healthy project.
 *   3. On success the real KPI cards render with the classified value.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

// The component only calls apiGet; route each URL to a controllable mock.
const apiGet = vi.fn();
vi.mock('@/shared/lib/api', () => ({
  apiGet: (...args: unknown[]) => apiGet(...args),
  // RecoveryCard reads getErrorMessage from the same module.
  getErrorMessage: (e: unknown) =>
    e instanceof Error ? e.message : 'Something went wrong',
}));

import { ProjectKPIHero } from '../components/ProjectKPIHero';

const VARIANCE_OK = {
  budget: 1_000_000,
  current: 950_000,
  variance_abs: -50_000,
  variance_pct: -5,
  red_line: 0,
  currency: 'EUR',
};
const SUMMARY_OK = { state: { schedule: { baseline_adherence_pct: 95 } } };
const ANOMALIES_OK: unknown[] = [];

function routeApi(
  handlers: Partial<{
    variance: () => Promise<unknown>;
    anomalies: () => Promise<unknown>;
    summary: () => Promise<unknown>;
  }>,
) {
  apiGet.mockImplementation((url: string) => {
    if (url.includes('/costmodel/variance/')) {
      return (handlers.variance ?? (() => Promise.resolve(VARIANCE_OK)))();
    }
    if (url.includes('/boq/anomalies/')) {
      return (handlers.anomalies ?? (() => Promise.resolve(ANOMALIES_OK)))();
    }
    if (url.includes('/project_intelligence/summary/')) {
      return (handlers.summary ?? (() => Promise.resolve(SUMMARY_OK)))();
    }
    return Promise.reject(new Error(`unexpected url ${url}`));
  });
}

function renderHero() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  // RecoveryCard (error branch) calls useLocation, so a router is required.
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <ProjectKPIHero projectId="proj-1" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ProjectKPIHero', () => {
  beforeEach(() => {
    apiGet.mockReset();
  });

  it('shows a skeleton while loading instead of green zero cards', () => {
    // Never-resolving promises keep all three queries pending.
    routeApi({
      variance: () => new Promise(() => {}),
      anomalies: () => new Promise(() => {}),
      summary: () => new Promise(() => {}),
    });
    renderHero();
    expect(screen.getByTestId('kpi-hero-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('kpi-card-variance')).not.toBeInTheDocument();
  });

  it('renders a recovery tile (not green zeros) when a query fails', async () => {
    // Only the variance query fails; the other two succeed. The strip must
    // still refuse to render healthy-looking metrics.
    routeApi({ variance: () => Promise.reject(new Error('boom')) });
    renderHero();

    await waitFor(() =>
      expect(screen.getByTestId('kpi-hero-error')).toBeInTheDocument(),
    );
    expect(
      screen.getByRole('button', { name: /retry/i }),
    ).toBeInTheDocument();

    // The bug: green KPI cards with fabricated zeros must NOT be shown.
    expect(screen.queryByTestId('kpi-card-variance')).not.toBeInTheDocument();
    expect(screen.queryByTestId('kpi-variance-pct')).not.toBeInTheDocument();
    expect(screen.queryByText('+0.0%')).not.toBeInTheDocument();
  });

  it('renders the KPI cards with the classified value on success', async () => {
    routeApi({});
    renderHero();

    await waitFor(() =>
      expect(screen.getByTestId('kpi-card-variance')).toBeInTheDocument(),
    );
    const pct = screen.getByTestId('kpi-variance-pct');
    expect(pct).toHaveTextContent('-5.0%');
    // -5% is amber per classifyVariance, never the green default.
    expect(pct.className).not.toContain('emerald');
    expect(screen.queryByTestId('kpi-hero-error')).not.toBeInTheDocument();
  });
});
