// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Validation across projects" dashboard card.
 *
 * The card renders what `GET /v1/validation/portfolio-status/` decided; the
 * backend owns the ranking and the "nothing checked is not a pass" rule (see
 * backend/tests/unit/test_validation_portfolio_status.py). What can still go
 * wrong here, and is pinned below:
 *
 *   - a failed read or a pending read must not look like an empty workspace;
 *   - the server's worst-first order must survive rendering;
 *   - a not-validated project must never print "Passed", including when the
 *     server sends a state this build does not know;
 *   - every estimate link must land on the exact report the row shows, or on
 *     the estimate itself when it has never been validated;
 *   - the query must sit under the ['validation'] root that a validation run
 *     invalidates, or the card goes stale after a re-run.
 *
 * Run: npx vitest run src/features/dashboard/__tests__/ValidationPortfolioCard.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { ValidationPortfolioCard } from '../ValidationPortfolioCard';
import {
  VALIDATION_PORTFOLIO_QUERY_KEY,
  estimateValidationHref,
  type PortfolioEstimate,
  type PortfolioProject,
  type ValidationPortfolio,
} from '../validationPortfolio';
import { apiGet } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn() };
});

const mockedGet = vi.mocked(apiGet);

function estimate(over: Partial<PortfolioEstimate> & { boq_id: string; boq_name: string }): PortfolioEstimate {
  return {
    state: 'not_validated',
    report_id: null,
    report_status: null,
    rule_sets: [],
    unsupported_rule_sets: [],
    error_count: 0,
    warning_count: 0,
    passed_count: 0,
    total_rules: 0,
    score: null,
    validated_at: null,
    ...over,
  };
}

function project(
  over: Partial<PortfolioProject> & { project_id: string; project_name: string },
): PortfolioProject {
  const estimates = over.estimates ?? [];
  return {
    state: 'not_validated',
    estimate_count: estimates.length,
    validated_count: 0,
    not_validated_count: estimates.length,
    error_count: 0,
    warning_count: 0,
    passed_count: 0,
    rule_sets: [],
    last_validated_at: null,
    ...over,
    estimates,
  };
}

const FAILING = project({
  project_id: 'p-hospital',
  project_name: 'Riverside Hospital',
  state: 'errors',
  error_count: 4,
  warning_count: 1,
  validated_count: 2,
  not_validated_count: 0,
  last_validated_at: '2026-09-20T10:00:00Z',
  rule_sets: ['din276', 'boq_quality'],
  estimates: [
    estimate({
      boq_id: 'b-shell',
      boq_name: 'Shell and core',
      state: 'errors',
      report_id: 'r-shell',
      report_status: 'errors',
      rule_sets: ['din276', 'boq_quality'],
      error_count: 4,
      warning_count: 1,
      passed_count: 10,
      total_rules: 15,
      validated_at: '2026-09-20T10:00:00Z',
    }),
    estimate({
      boq_id: 'b-fitout',
      boq_name: 'Fit-out',
      state: 'passed',
      report_id: 'r-fitout',
      report_status: 'passed',
      rule_sets: ['boq_quality'],
      passed_count: 8,
      total_rules: 8,
      validated_at: '2026-09-18T10:00:00Z',
    }),
  ],
});

// One passed estimate next to one that was never validated.
const HALF_CHECKED = project({
  project_id: 'p-depot',
  project_name: 'Northern Depot',
  state: 'not_validated',
  validated_count: 1,
  not_validated_count: 1,
  estimates: [
    estimate({ boq_id: 'b-draft', boq_name: 'Draft bill' }),
    estimate({
      boq_id: 'b-ok',
      boq_name: 'Approved bill',
      state: 'passed',
      report_id: 'r-ok',
      report_status: 'passed',
      passed_count: 5,
      total_rules: 5,
      validated_at: '2026-09-01T10:00:00Z',
    }),
  ],
});

const NO_ESTIMATES = project({ project_id: 'p-empty', project_name: 'Greenfield Site' });

function portfolio(projects: PortfolioProject[]): ValidationPortfolio {
  return {
    project_count: projects.length,
    summary: { errors: 1, warnings: 0, not_validated: 2, info: 0, passed: 0 },
    projects,
  };
}

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ValidationPortfolioCard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedGet.mockReset();
  useProjectContextStore.setState({ activeProjectId: null });
});

describe('ValidationPortfolioCard', () => {
  it('reads from the validation endpoint under the root a validation run invalidates', () => {
    expect(VALIDATION_PORTFOLIO_QUERY_KEY[0]).toBe('validation');
    mockedGet.mockReturnValue(new Promise(() => {}));
    renderCard();
    expect(mockedGet).toHaveBeenCalledWith('/v1/validation/portfolio-status/');
  });

  it('shows a loading state, not an empty one, while the read is pending', () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    renderCard();
    expect(screen.getByTestId('validation-portfolio-loading')).toHaveAttribute('aria-busy', 'true');
    expect(screen.queryByText(/No projects to show yet/)).not.toBeInTheDocument();
  });

  it('tells a failed read apart from an empty workspace', async () => {
    mockedGet.mockRejectedValue(new Error('boom'));
    renderCard();
    expect(await screen.findByText('Validation status could not be loaded.')).toBeInTheDocument();
    expect(screen.queryByText(/No projects to show yet/)).not.toBeInTheDocument();
    expect(screen.queryByTestId('validation-portfolio-list')).not.toBeInTheDocument();
  });

  it('shows the empty state when the caller has no projects', async () => {
    mockedGet.mockResolvedValue(portfolio([]));
    renderCard();
    expect(await screen.findByText(/No projects to show yet/)).toBeInTheDocument();
  });

  it('keeps the server order, worst first', async () => {
    mockedGet.mockResolvedValue(portfolio([FAILING, HALF_CHECKED, NO_ESTIMATES]));
    renderCard();
    await screen.findByTestId('validation-portfolio-list');
    const rows = screen.getAllByTestId('validation-portfolio-project');
    expect(rows.map((r) => r.getAttribute('data-project-id'))).toEqual(['p-hospital', 'p-depot', 'p-empty']);
    expect(within(rows[0]!).getByText('Riverside Hospital')).toBeInTheDocument();
    expect(within(rows[0]!).getByText(/2 of 2 estimates validated · 4 errors · 1 warning/)).toBeInTheDocument();
  });

  it('never prints Passed for a project that is not fully validated', async () => {
    mockedGet.mockResolvedValue(portfolio([HALF_CHECKED, NO_ESTIMATES]));
    renderCard();
    await screen.findByTestId('validation-portfolio-list');
    const [half, empty] = screen.getAllByTestId('validation-portfolio-project');

    const halfPill = half!.querySelector('[data-state]');
    expect(halfPill).toHaveAttribute('data-state', 'not_validated');
    expect(halfPill).toHaveTextContent('Not validated');
    expect(within(half!).getByText(/1 of 2 estimates validated/)).toBeInTheDocument();
    expect(within(half!).getByText(/Never validated/)).toBeInTheDocument();

    const emptyPill = empty!.querySelector('[data-state]');
    expect(emptyPill).toHaveTextContent('Not validated');
    expect(within(empty!).getByText('No estimates yet')).toBeInTheDocument();
  });

  it('reads a state it does not know as not validated, never as a pass', async () => {
    const odd = project({
      project_id: 'p-odd',
      project_name: 'Future state',
      state: 'something_new' as unknown as PortfolioProject['state'],
    });
    mockedGet.mockResolvedValue(portfolio([odd]));
    renderCard();
    const row = await screen.findByTestId('validation-portfolio-project');
    expect(row.querySelector('[data-state]')).toHaveTextContent('Not validated');
  });

  it('links each estimate to its exact report, or to the estimate when never validated', async () => {
    mockedGet.mockResolvedValue(portfolio([FAILING, HALF_CHECKED, NO_ESTIMATES]));
    renderCard();
    await screen.findByTestId('validation-portfolio-list');

    const shell = screen.getByRole('link', { name: 'Open the validation of Shell and core' });
    const shellUrl = new URL(shell.getAttribute('href')!, 'http://x');
    expect(shellUrl.pathname).toBe('/validation');
    expect(shellUrl.searchParams.get('project')).toBe('p-hospital');
    expect(shellUrl.searchParams.get('boq_id')).toBe('b-shell');
    expect(shellUrl.searchParams.get('report')).toBe('r-shell');

    const draft = screen.getByRole('link', { name: 'Open the validation of Draft bill' });
    const draftUrl = new URL(draft.getAttribute('href')!, 'http://x');
    expect(draftUrl.searchParams.get('project')).toBe('p-depot');
    expect(draftUrl.searchParams.get('boq_id')).toBe('b-draft');
    expect(draftUrl.searchParams.has('report')).toBe(false);

    const register = screen.getByRole('link', { name: /Open estimates/ });
    expect(register).toHaveAttribute('href', '/projects/p-empty/boq');
  });

  it('builds the same href the validation page reads', () => {
    const href = estimateValidationHref('p 1', estimate({ boq_id: 'b&1', boq_name: 'x', report_id: 'r/1' }));
    const url = new URL(href, 'http://x');
    expect(url.searchParams.get('project')).toBe('p 1');
    expect(url.searchParams.get('boq_id')).toBe('b&1');
    expect(url.searchParams.get('report')).toBe('r/1');
  });

  it('previews three estimates per project and expands to all of them', async () => {
    const many = project({
      project_id: 'p-many',
      project_name: 'Campus',
      estimates: Array.from({ length: 5 }, (_, i) => estimate({ boq_id: `b-${i}`, boq_name: `Lot ${i + 1}` })),
    });
    mockedGet.mockResolvedValue(portfolio([many]));
    renderCard();
    const row = await screen.findByTestId('validation-portfolio-project');
    expect(within(row).getAllByRole('link')).toHaveLength(3);

    const toggle = within(row).getByRole('button', { name: /Show all 5 estimates/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(toggle);
    expect(within(row).getAllByRole('link')).toHaveLength(5);
    expect(within(row).getByRole('button', { name: /Show fewer/ })).toHaveAttribute('aria-expanded', 'true');
  });

  it('marks the project selected in the top bar without filtering the others out', async () => {
    useProjectContextStore.setState({ activeProjectId: 'p-depot' });
    mockedGet.mockResolvedValue(portfolio([FAILING, HALF_CHECKED]));
    renderCard();
    await screen.findByTestId('validation-portfolio-list');
    const rows = screen.getAllByTestId('validation-portfolio-project');
    expect(rows).toHaveLength(2);
    expect(within(rows[1]!).getByText('Selected project')).toBeInTheDocument();
    expect(within(rows[0]!).queryByText('Selected project')).not.toBeInTheDocument();
  });
});
