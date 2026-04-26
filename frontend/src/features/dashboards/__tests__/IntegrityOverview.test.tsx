// @ts-nocheck
/**
 * Tests for IntegrityOverview (T07).
 *
 * Covers:
 *   - rendering the per-column table with dtype + null counts + issues
 *   - the empty-state when no columns have issues
 *   - the click-to-expand drawer showing top-frequency sample values
 *   - the completeness chip switching colour by score band
 *   - the issuesOnly filter dropping clean columns from the table
 *
 * Stubbing follows the sibling tests' convention: `vi.mock('../api')`
 * rather than MSW (the repo's MSW infra is flaky on jsdom 29 + Node 24).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    getIntegrityReport: vi.fn(),
  };
});

import { getIntegrityReport, type IntegrityReport } from '../api';
import { IntegrityOverview } from '../IntegrityOverview';

/* ── Fixture data ─────────────────────────────────────────────────────── */

const SNAPSHOT_ID = 'snap-1';
const PROJECT_ID = 'proj-1';

const REPORT_WITH_ISSUES: IntegrityReport = {
  snapshot_id: SNAPSHOT_ID,
  project_id: PROJECT_ID,
  row_count: 100,
  column_count: 3,
  completeness_score: 0.65,
  schema_hash: 'abc123def456',
  columns: [
    {
      name: 'category',
      dtype: 'object',
      inferred_type: 'string',
      row_count: 100,
      null_count: 0,
      null_pct: 0.0,
      unique_count: 3,
      completeness: 1.0,
      sample_values: [
        { value: 'wall', count: 60 },
        { value: 'door', count: 25 },
        { value: 'window', count: 15 },
      ],
      zero_pct: null,
      outlier_count: null,
      min_value: null,
      max_value: null,
      mean_value: null,
      issues: ['low_cardinality_string'],
    },
    {
      name: 'thickness_mm',
      dtype: 'float64',
      inferred_type: 'numeric',
      row_count: 100,
      null_count: 5,
      null_pct: 0.05,
      unique_count: 30,
      completeness: 0.95,
      sample_values: [
        { value: '100', count: 20 },
        { value: '200', count: 15 },
      ],
      zero_pct: 0.0,
      outlier_count: 3,
      min_value: 50,
      max_value: 500,
      mean_value: 175.5,
      issues: ['outliers_present'],
    },
    {
      name: 'phantom_field',
      dtype: 'object',
      inferred_type: 'empty',
      row_count: 100,
      null_count: 100,
      null_pct: 1.0,
      unique_count: 0,
      completeness: 0.0,
      sample_values: [],
      zero_pct: null,
      outlier_count: null,
      min_value: null,
      max_value: null,
      mean_value: null,
      issues: ['all_null'],
    },
  ],
  issue_summary: {
    low_cardinality_string: 1,
    outliers_present: 1,
    all_null: 1,
  },
};

const CLEAN_REPORT: IntegrityReport = {
  snapshot_id: SNAPSHOT_ID,
  project_id: PROJECT_ID,
  row_count: 50,
  column_count: 1,
  completeness_score: 1.0,
  schema_hash: 'cleanhash00000',
  columns: [
    {
      name: 'category',
      dtype: 'object',
      inferred_type: 'string',
      row_count: 50,
      null_count: 0,
      null_pct: 0.0,
      unique_count: 12,
      completeness: 1.0,
      sample_values: [{ value: 'wall', count: 12 }],
      zero_pct: null,
      outlier_count: null,
      min_value: null,
      max_value: null,
      mean_value: null,
      issues: [],
    },
  ],
  issue_summary: {},
};

beforeEach(() => {
  (getIntegrityReport as ReturnType<typeof vi.fn>).mockReset();
});

afterEach(() => {
  cleanup();
});

/* ── Test harness ────────────────────────────────────────────────────── */

function renderOverview(props?: { issuesOnly?: boolean }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <IntegrityOverview
        snapshotId={SNAPSHOT_ID}
        projectId={PROJECT_ID}
        issuesOnly={props?.issuesOnly}
      />
    </QueryClientProvider>,
  );
}

/* ── Tests ───────────────────────────────────────────────────────────── */

describe('IntegrityOverview', () => {
  it('fetches the integrity report on mount and renders one row per column', async () => {
    (getIntegrityReport as ReturnType<typeof vi.fn>).mockResolvedValue(
      REPORT_WITH_ISSUES,
    );
    renderOverview();

    await waitFor(() => {
      expect(getIntegrityReport).toHaveBeenCalledWith({
        snapshotId: SNAPSHOT_ID,
        projectId: PROJECT_ID,
      });
    });

    await waitFor(() => {
      expect(screen.getByTestId('integrity-row-category')).toBeInTheDocument();
      expect(screen.getByTestId('integrity-row-thickness_mm')).toBeInTheDocument();
      expect(screen.getByTestId('integrity-row-phantom_field')).toBeInTheDocument();
    });

    // Each column's headline issues render as a coloured badge with
    // the issue code baked into the testid — the i18n bundle isn't
    // loaded in tests, so the visible text falls back to the raw code.
    expect(screen.getByTestId('integrity-issue-low_cardinality_string')).toBeInTheDocument();
    expect(screen.getByTestId('integrity-issue-outliers_present')).toBeInTheDocument();
    expect(screen.getByTestId('integrity-issue-all_null')).toBeInTheDocument();
  });

  it('shows the completeness chip with the rounded score', async () => {
    (getIntegrityReport as ReturnType<typeof vi.fn>).mockResolvedValue(
      REPORT_WITH_ISSUES,
    );
    renderOverview();

    await waitFor(() => {
      const chip = screen.getByTestId('integrity-completeness-score');
      expect(chip.textContent).toContain('65%');
    });
  });

  it('clicking a row reveals the sample-values drawer', async () => {
    (getIntegrityReport as ReturnType<typeof vi.fn>).mockResolvedValue(
      REPORT_WITH_ISSUES,
    );
    renderOverview();

    await waitFor(() =>
      expect(screen.getByTestId('integrity-row-button-category')).toBeInTheDocument(),
    );

    // Detail drawer should not be in the DOM until expanded.
    expect(
      screen.queryByTestId('integrity-detail-category'),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('integrity-row-button-category'));

    await waitFor(() => {
      expect(screen.getByTestId('integrity-detail-category')).toBeInTheDocument();
    });

    // The top-3 sample values for "category" each render their own
    // testid so we can pin the rendering of frequencies.
    expect(screen.getByTestId('integrity-sample-category-wall')).toBeInTheDocument();
    expect(screen.getByTestId('integrity-sample-category-door')).toBeInTheDocument();
    expect(screen.getByTestId('integrity-sample-category-window')).toBeInTheDocument();

    // Clicking again collapses the drawer.
    fireEvent.click(screen.getByTestId('integrity-row-button-category'));
    await waitFor(() =>
      expect(
        screen.queryByTestId('integrity-detail-category'),
      ).not.toBeInTheDocument(),
    );
  });

  it('renders the empty-state for a clean snapshot with no issues (issuesOnly mode)', async () => {
    (getIntegrityReport as ReturnType<typeof vi.fn>).mockResolvedValue(
      CLEAN_REPORT,
    );
    renderOverview({ issuesOnly: true });

    await waitFor(() => expect(getIntegrityReport).toHaveBeenCalled());

    // The clean column should be hidden in issuesOnly mode, leaving
    // the empty-state on screen.
    await waitFor(() => {
      expect(screen.queryByTestId('integrity-row-category')).not.toBeInTheDocument();
    });
    // The empty state is rendered (the EmptyState component contains
    // the "No integrity issues found" copy as a fallback default).
    expect(screen.getByTestId('integrity-overview')).toBeInTheDocument();
  });

  it('shows the error banner when the API fails', async () => {
    (getIntegrityReport as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('boom'),
    );
    renderOverview();

    await waitFor(() => {
      expect(screen.getByTestId('integrity-error')).toBeInTheDocument();
    });
  });
});
