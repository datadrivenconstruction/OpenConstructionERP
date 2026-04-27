/**
 * FederatedResultsTable (T10 / task #193).
 *
 * Renders a federated aggregate response as a flat table. Provenance
 * columns (`__project_id`, `__snapshot_id`) are surfaced as little
 * chips at the start of each row so the user can drill back to the
 * source snapshot without losing the rollup context. Group-by columns
 * follow, then the numeric measure column on the right.
 */
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import type {
  FederatedAggregateRow,
  FederationAggregateResponse,
} from './api';

export interface FederatedResultsTableProps {
  data: FederationAggregateResponse | null;
  /** Map of `snapshot_id → human-readable label` for the chip text.
   * Optional — when omitted the chip falls back to a short id. */
  snapshotLabels?: Record<string, string>;
  /** Map of `project_id → human-readable label` for the chip text.
   * Optional — when omitted the chip falls back to a short id. */
  projectLabels?: Record<string, string>;
  /** Empty-state copy override. */
  emptyMessage?: string;
}

const PROJECT_COL = '__project_id';
const SNAPSHOT_COL = '__snapshot_id';

export function FederatedResultsTable({
  data,
  snapshotLabels,
  projectLabels,
  emptyMessage,
}: FederatedResultsTableProps) {
  const { t } = useTranslation();

  const orderedColumns = useMemo<string[]>(() => {
    if (!data) return [];
    // Explicit order:
    //  1. provenance (project, snapshot)
    //  2. group-by columns (preserving server order)
    //  3. measure_value (always last)
    const seen = new Set<string>([PROJECT_COL, SNAPSHOT_COL]);
    const out: string[] = [PROJECT_COL, SNAPSHOT_COL];
    for (const c of data.group_by) {
      if (!seen.has(c)) {
        seen.add(c);
        out.push(c);
      }
    }
    if (!seen.has('measure_value')) {
      out.push('measure_value');
    }
    return out;
  }, [data]);

  if (!data || data.rows.length === 0) {
    return (
      <div
        className="rounded border border-border-light bg-surface-secondary p-6 text-center text-sm text-content-tertiary"
        data-testid="federation-results-empty"
      >
        {emptyMessage ??
          t('dashboards.federation.results_empty', {
            defaultValue: 'No federated rows to show yet.',
          })}
      </div>
    );
  }

  return (
    <div
      className="overflow-x-auto rounded border border-border-light"
      data-testid="federation-results-table"
    >
      <table className="min-w-full text-xs">
        <thead className="bg-surface-secondary text-content-secondary">
          <tr>
            {orderedColumns.map((col) => (
              <th
                key={col}
                className="px-3 py-2 text-left font-medium"
                data-testid={`federation-results-th-${col}`}
              >
                {formatHeader(col, t)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, idx) => (
            <tr
              key={`${row[SNAPSHOT_COL] ?? 'unknown'}-${idx}`}
              className="border-t border-border-light hover:bg-surface-secondary/50"
              data-testid={`federation-results-row-${idx}`}
            >
              {orderedColumns.map((col) => (
                <td key={col} className="px-3 py-2">
                  {renderCell(col, row, { snapshotLabels, projectLabels })}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatHeader(col: string, t: ReturnType<typeof useTranslation>['t']): string {
  if (col === PROJECT_COL) {
    return t('dashboards.federation.col_project', { defaultValue: 'Project' });
  }
  if (col === SNAPSHOT_COL) {
    return t('dashboards.federation.col_snapshot', { defaultValue: 'Snapshot' });
  }
  if (col === 'measure_value') {
    return t('dashboards.federation.col_measure', { defaultValue: 'Value' });
  }
  return col;
}

function renderCell(
  col: string,
  row: FederatedAggregateRow,
  opts: {
    snapshotLabels?: Record<string, string>;
    projectLabels?: Record<string, string>;
  },
): JSX.Element {
  const value = row[col];
  if (col === PROJECT_COL && typeof value === 'string') {
    return (
      <span
        className="inline-flex items-center rounded bg-emerald-500/10 px-2 py-0.5 font-mono text-[11px] text-emerald-300"
        data-testid={`federation-chip-project-${value}`}
        title={value}
      >
        {opts.projectLabels?.[value] ?? shortId(value)}
      </span>
    );
  }
  if (col === SNAPSHOT_COL && typeof value === 'string') {
    return (
      <span
        className="inline-flex items-center rounded bg-sky-500/10 px-2 py-0.5 font-mono text-[11px] text-sky-300"
        data-testid={`federation-chip-snapshot-${value}`}
        title={value}
      >
        {opts.snapshotLabels?.[value] ?? shortId(value)}
      </span>
    );
  }
  if (col === 'measure_value') {
    return (
      <span className="tabular-nums text-content-primary">
        {formatNumber(value)}
      </span>
    );
  }
  if (value === null || value === undefined) {
    return <span className="italic text-content-tertiary">—</span>;
  }
  return <span>{String(value)}</span>;
}

function shortId(uuid: string): string {
  // Surface only the leading block — same rule the snapshot picker uses.
  return uuid.length > 8 ? `${uuid.slice(0, 8)}…` : uuid;
}

function formatNumber(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.abs(value) >= 1000
      ? value.toLocaleString(undefined, { maximumFractionDigits: 1 })
      : value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  return String(value);
}
