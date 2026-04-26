/**
 * Dataset Integrity Overview (T07).
 *
 * Renders a per-column data-quality table for a snapshot:
 *
 *   column · dtype · nulls · uniques · completeness bar · issue badges
 *
 * Clicking a row expands a drawer showing the top-5 sample values and
 * (for numeric columns) min / max / mean / outlier counts. The whole
 * panel is read-only — the user takes the badges as a prompt to fix
 * the data upstream and re-import.
 *
 * The integrity computation lives entirely on the server. We only
 * decide *how* to render it: which badge colour each issue code earns,
 * how to format the completeness bar, which sub-detail to show for the
 * inferred type.
 */
import { useCallback, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, ChevronDown, ChevronRight, RefreshCw, ShieldCheck } from 'lucide-react';

import { Badge, Button, Card, EmptyState, Skeleton } from '@/shared/ui';

import {
  getIntegrityReport,
  type IntegrityColumn,
  type IntegrityIssueCode,
  type IntegrityReport,
} from './api';

export interface IntegrityOverviewProps {
  snapshotId: string;
  projectId: string;
  /**
   * If set, only columns with at least one issue are rendered. Useful
   * for the compact "issues only" mode in the dashboards landing page.
   */
  issuesOnly?: boolean;
}

/**
 * Issue-code → tone map. The tone drives the badge colour:
 *
 *   "danger"  – red    (block-the-user severity, e.g. all-null column)
 *   "warning" – amber  (likely-broken severity)
 *   "info"    – sky    (advisory, e.g. uuid_like)
 */
const ISSUE_TONE: Record<IntegrityIssueCode, 'danger' | 'warning' | 'info'> = {
  all_null: 'danger',
  high_null_pct: 'warning',
  constant: 'warning',
  dtype_mismatch: 'warning',
  outliers_present: 'warning',
  high_zero_pct: 'warning',
  low_cardinality_string: 'info',
  uuid_like: 'info',
};

const TONE_CLASSES: Record<'danger' | 'warning' | 'info', string> = {
  danger: 'bg-rose-500/15 text-rose-300 border border-rose-500/30',
  warning: 'bg-amber-500/15 text-amber-300 border border-amber-500/30',
  info: 'bg-sky-500/15 text-sky-300 border border-sky-500/30',
};

export function IntegrityOverview({
  snapshotId,
  projectId,
  issuesOnly = false,
}: IntegrityOverviewProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState<string | null>(null);

  const reportQuery = useQuery({
    queryKey: ['dashboards-integrity-report', snapshotId, projectId],
    queryFn: () => getIntegrityReport({ snapshotId, projectId }),
    enabled: !!snapshotId && !!projectId,
    staleTime: 5 * 60 * 1000,
  });

  const handleRefresh = useCallback(() => {
    reportQuery.refetch();
  }, [reportQuery]);

  const handleToggleRow = useCallback((columnName: string) => {
    setExpanded((current) => (current === columnName ? null : columnName));
  }, []);

  const visibleColumns = useMemo(() => {
    const all = reportQuery.data?.columns ?? [];
    return issuesOnly ? all.filter((c) => c.issues.length > 0) : all;
  }, [reportQuery.data?.columns, issuesOnly]);

  return (
    <Card data-testid="integrity-overview">
      <div className="flex items-center justify-between border-b border-border-light px-4 py-2">
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('dashboards.integrity_title', {
              defaultValue: 'Dataset integrity',
            })}
          </h3>
          <p className="text-xs text-content-tertiary">
            {t('dashboards.integrity_subtitle', {
              defaultValue:
                'Per-column null counts, dtype mismatches and outliers — fix upstream issues before slicing.',
            })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {reportQuery.data && (
            <CompletenessChip score={reportQuery.data.completeness_score} />
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={handleRefresh}
            disabled={reportQuery.isFetching}
            data-testid="integrity-refresh"
          >
            <RefreshCw
              className={`mr-1 h-3 w-3 ${reportQuery.isFetching ? 'animate-spin' : ''}`}
            />
            {t('common.refresh', { defaultValue: 'Refresh' })}
          </Button>
        </div>
      </div>

      <div className="p-3">
        {reportQuery.isLoading && (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-9" />
            ))}
          </div>
        )}

        {reportQuery.isError && (
          <div
            className="rounded border border-rose-400/30 bg-rose-500/10 p-3 text-xs text-rose-300"
            data-testid="integrity-error"
          >
            {t('dashboards.integrity_error', {
              defaultValue: 'Could not load the integrity report for this snapshot.',
            })}
          </div>
        )}

        {!reportQuery.isLoading &&
          !reportQuery.isError &&
          reportQuery.data &&
          visibleColumns.length === 0 && (
            <EmptyState
              icon={<ShieldCheck className="h-8 w-8 text-emerald-400" />}
              title={t('dashboards.integrity_empty_title', {
                defaultValue: 'No integrity issues found',
              })}
              description={t('dashboards.integrity_empty_desc', {
                defaultValue:
                  'Every column passed the null / dtype / outlier checks. Slice with confidence.',
              })}
            />
          )}

        {visibleColumns.length > 0 && reportQuery.data && (
          <IntegrityTable
            report={reportQuery.data}
            columns={visibleColumns}
            expanded={expanded}
            onToggleRow={handleToggleRow}
          />
        )}
      </div>
    </Card>
  );
}

/* ── Completeness chip ──────────────────────────────────────────────────── */

interface CompletenessChipProps {
  score: number;
}

function CompletenessChip({ score }: CompletenessChipProps) {
  const { t } = useTranslation();
  const pct = Math.round(score * 100);
  const tone = score >= 0.95 ? 'emerald' : score >= 0.7 ? 'amber' : 'rose';
  const colour = {
    emerald: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    amber: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
    rose: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
  }[tone];
  return (
    <span
      data-testid="integrity-completeness-score"
      className={`flex items-center gap-1 rounded border px-2 py-0.5 text-xs font-medium ${colour}`}
    >
      {t('dashboards.integrity_completeness', { defaultValue: 'Completeness' })}: {pct}%
    </span>
  );
}

/* ── Table ──────────────────────────────────────────────────────────────── */

interface IntegrityTableProps {
  report: IntegrityReport;
  columns: IntegrityColumn[];
  expanded: string | null;
  onToggleRow: (columnName: string) => void;
}

function IntegrityTable({ report, columns, expanded, onToggleRow }: IntegrityTableProps) {
  const { t } = useTranslation();

  return (
    <div
      role="table"
      aria-label={t('dashboards.integrity_table_aria', {
        defaultValue: 'Dataset integrity per-column report',
      })}
      data-testid="integrity-table"
      className="text-xs"
    >
      {/* Header row. */}
      <div
        role="row"
        className="grid grid-cols-[1fr_120px_90px_90px_140px_1fr] items-center gap-2 border-b border-border-light px-2 py-1.5 text-content-secondary"
      >
        <div role="columnheader">
          {t('dashboards.integrity_col_name', { defaultValue: 'Column' })}
        </div>
        <div role="columnheader">
          {t('dashboards.integrity_col_dtype', { defaultValue: 'Type' })}
        </div>
        <div role="columnheader" className="text-right">
          {t('dashboards.integrity_col_nulls', { defaultValue: 'Nulls' })}
        </div>
        <div role="columnheader" className="text-right">
          {t('dashboards.integrity_col_uniques', { defaultValue: 'Uniques' })}
        </div>
        <div role="columnheader">
          {t('dashboards.integrity_col_completeness', { defaultValue: 'Completeness' })}
        </div>
        <div role="columnheader">
          {t('dashboards.integrity_col_issues', { defaultValue: 'Issues' })}
        </div>
      </div>

      {columns.map((col) => (
        <IntegrityRow
          key={col.name}
          column={col}
          rowCount={report.row_count}
          isExpanded={expanded === col.name}
          onToggle={() => onToggleRow(col.name)}
        />
      ))}
    </div>
  );
}

/* ── Row ────────────────────────────────────────────────────────────────── */

interface IntegrityRowProps {
  column: IntegrityColumn;
  rowCount: number;
  isExpanded: boolean;
  onToggle: () => void;
}

function IntegrityRow({ column, rowCount, isExpanded, onToggle }: IntegrityRowProps) {
  const { t } = useTranslation();
  const completenessPct = Math.round(column.completeness * 100);
  const nullPctLabel = `${(column.null_pct * 100).toFixed(1)}%`;

  return (
    <div data-testid={`integrity-row-${column.name}`}>
      <button
        type="button"
        role="row"
        onClick={onToggle}
        aria-expanded={isExpanded}
        className="grid w-full grid-cols-[1fr_120px_90px_90px_140px_1fr] items-center gap-2 border-b border-border-light/60 px-2 py-1.5 text-left hover:bg-surface-secondary"
        data-testid={`integrity-row-button-${column.name}`}
      >
        <div role="cell" className="flex items-center gap-1.5 truncate">
          {isExpanded ? (
            <ChevronDown className="h-3 w-3 flex-shrink-0 text-content-tertiary" />
          ) : (
            <ChevronRight className="h-3 w-3 flex-shrink-0 text-content-tertiary" />
          )}
          <span className="truncate font-mono text-content-primary" title={column.name}>
            {column.name}
          </span>
        </div>
        <div role="cell" className="truncate text-content-secondary" title={column.dtype}>
          <Badge variant="neutral" className="text-[10px]">
            {column.inferred_type}
          </Badge>
        </div>
        <div role="cell" className="text-right text-content-secondary tabular-nums">
          {column.null_count} <span className="text-content-tertiary">({nullPctLabel})</span>
        </div>
        <div role="cell" className="text-right text-content-secondary tabular-nums">
          {column.unique_count}
        </div>
        <div role="cell">
          <CompletenessBar pct={completenessPct} />
        </div>
        <div role="cell" className="flex flex-wrap gap-1">
          {column.issues.length === 0 ? (
            <span className="text-content-tertiary">
              {t('dashboards.integrity_no_issues', { defaultValue: '—' })}
            </span>
          ) : (
            column.issues.map((issue) => (
              <IssueBadge key={issue} code={issue} />
            ))
          )}
        </div>
      </button>

      {isExpanded && (
        <RowDetail column={column} rowCount={rowCount} />
      )}
    </div>
  );
}

function CompletenessBar({ pct }: { pct: number }) {
  const tone = pct >= 95 ? 'emerald' : pct >= 70 ? 'amber' : 'rose';
  const fill = {
    emerald: 'bg-emerald-500',
    amber: 'bg-amber-500',
    rose: 'bg-rose-500',
  }[tone];
  return (
    <div className="flex items-center gap-2" data-testid={`integrity-completeness-bar-${pct}`}>
      <div className="h-2 flex-1 overflow-hidden rounded bg-surface-secondary">
        <div className={`h-full ${fill}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-9 text-right text-content-tertiary tabular-nums">{pct}%</span>
    </div>
  );
}

function IssueBadge({ code }: { code: IntegrityIssueCode }) {
  const { t } = useTranslation();
  const tone = ISSUE_TONE[code] ?? 'info';
  const label = t(`dashboards.integrity_issue_${code}`, {
    // Fall back to the raw code if the translation key isn't loaded —
    // tests rely on this so an empty i18next bundle still renders
    // recognisable text.
    defaultValue: code.replace(/_/g, ' '),
  });
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${TONE_CLASSES[tone]}`}
      data-testid={`integrity-issue-${code}`}
      title={label}
    >
      <AlertTriangle className="mr-1 inline h-2.5 w-2.5" />
      {label}
    </span>
  );
}

/* ── Expanded row detail ────────────────────────────────────────────────── */

interface RowDetailProps {
  column: IntegrityColumn;
  rowCount: number;
}

function RowDetail({ column, rowCount }: RowDetailProps) {
  const { t } = useTranslation();
  return (
    <div
      data-testid={`integrity-detail-${column.name}`}
      className="grid grid-cols-1 gap-3 border-b border-border-light/60 bg-surface-secondary px-4 py-3 text-xs sm:grid-cols-2"
    >
      <div>
        <div className="mb-1 text-content-secondary">
          {t('dashboards.integrity_top_values', {
            defaultValue: 'Top values',
          })}
        </div>
        {column.sample_values.length === 0 ? (
          <span className="text-content-tertiary">
            {t('dashboards.integrity_no_sample', {
              defaultValue: 'No values to show.',
            })}
          </span>
        ) : (
          <ul className="space-y-1">
            {column.sample_values.map((s) => {
              const pct = rowCount > 0 ? (s.count / rowCount) * 100 : 0;
              return (
                <li
                  key={s.value}
                  className="flex items-center justify-between gap-2"
                  data-testid={`integrity-sample-${column.name}-${s.value}`}
                >
                  <span className="truncate font-mono text-content-primary" title={s.value}>
                    {s.value}
                  </span>
                  <span className="text-content-tertiary tabular-nums">
                    {s.count} ({pct.toFixed(1)}%)
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div>
        <div className="mb-1 text-content-secondary">
          {t('dashboards.integrity_stats', { defaultValue: 'Statistics' })}
        </div>
        <dl className="grid grid-cols-[100px_1fr] gap-x-2 gap-y-0.5 text-content-secondary">
          <dt>
            {t('dashboards.integrity_dtype', { defaultValue: 'dtype' })}
          </dt>
          <dd className="font-mono text-content-primary">{column.dtype}</dd>

          {column.inferred_type === 'numeric' && (
            <>
              <dt>{t('dashboards.integrity_min', { defaultValue: 'min' })}</dt>
              <dd className="tabular-nums text-content-primary">
                {formatStat(column.min_value)}
              </dd>
              <dt>{t('dashboards.integrity_max', { defaultValue: 'max' })}</dt>
              <dd className="tabular-nums text-content-primary">
                {formatStat(column.max_value)}
              </dd>
              <dt>{t('dashboards.integrity_mean', { defaultValue: 'mean' })}</dt>
              <dd className="tabular-nums text-content-primary">
                {formatStat(column.mean_value)}
              </dd>
              <dt>{t('dashboards.integrity_zero_pct', { defaultValue: 'zero %' })}</dt>
              <dd className="tabular-nums text-content-primary">
                {column.zero_pct === null
                  ? '—'
                  : `${(column.zero_pct * 100).toFixed(1)}%`}
              </dd>
              <dt>
                {t('dashboards.integrity_outliers', { defaultValue: 'outliers' })}
              </dt>
              <dd className="tabular-nums text-content-primary">
                {column.outlier_count ?? '—'}
              </dd>
            </>
          )}
        </dl>
      </div>
    </div>
  );
}

function formatStat(value: number | null): string {
  if (value === null) return '—';
  if (Math.abs(value) >= 1000) return value.toFixed(1);
  if (Math.abs(value) >= 1) return value.toFixed(3);
  return value.toFixed(4);
}
