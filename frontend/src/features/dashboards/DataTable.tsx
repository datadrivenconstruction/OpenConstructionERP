/**
 * DataTable (T06) — paged, sortable view of a snapshot's raw rows.
 *
 * Lightweight on purpose — no react-window dependency: the API is
 * already paginated, so we render one page at a time (default 50
 * rows). Column-header click toggles sort direction. Filters are
 * driven externally via the ``filters`` prop so this component stays
 * Cascade-Filter-Panel-agnostic.
 */
import { useCallback, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react';

import { Button, Card, Skeleton } from '@/shared/ui';

import { getSnapshotRows, type SnapshotRowsResponse } from './api';

export interface DataTableProps {
  snapshotId: string;
  /** Optional: restrict the projected columns (defaults to all). */
  columns?: string[];
  /** Optional: column → allowed values; mirrors :class:`CascadeFilterPanel`. */
  filters?: Record<string, string[]>;
  pageSize?: number;
}

interface SortSpec {
  column: string;
  direction: 'asc' | 'desc';
}

export function DataTable({
  snapshotId,
  columns,
  filters,
  pageSize = 50,
}: DataTableProps) {
  const { t } = useTranslation();
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState<SortSpec | null>(null);

  const queryKey = useMemo(
    () => [
      'dashboards-rows',
      snapshotId,
      columns ?? null,
      filters ?? null,
      sort,
      page,
      pageSize,
    ],
    [snapshotId, columns, filters, sort, page, pageSize],
  );

  const rowsQuery = useQuery<SnapshotRowsResponse>({
    queryKey,
    queryFn: () =>
      getSnapshotRows(snapshotId, {
        columns,
        filters,
        orderBy: sort ? `${sort.column}:${sort.direction}` : undefined,
        limit: pageSize,
        offset: page * pageSize,
      }),
    enabled: !!snapshotId,
    staleTime: 30 * 1000,
    placeholderData: (prev) => prev,
  });

  const handleHeaderClick = useCallback((column: string) => {
    setSort((prev) => {
      if (prev?.column === column) {
        return {
          column,
          direction: prev.direction === 'asc' ? 'desc' : 'asc',
        };
      }
      return { column, direction: 'asc' };
    });
    // Re-sorting always resets to page 1 — otherwise rows shuffle under
    // the user's cursor and "page 5" stops being meaningful.
    setPage(0);
  }, []);

  const total = rowsQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const rows = rowsQuery.data?.rows ?? [];
  const cols = rowsQuery.data?.columns ?? columns ?? [];

  return (
    <Card data-testid="data-table" className="overflow-hidden">
      <div className="flex items-center justify-between border-b border-border-light px-3 py-2 text-xs">
        <div className="text-content-tertiary">
          {t('dashboards.data_table_summary', {
            defaultValue: '{{shown}} of {{total}} rows',
            shown: rows.length,
            total,
          })}
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0 || rowsQuery.isFetching}
            data-testid="data-table-prev"
          >
            {t('common.prev', { defaultValue: 'Prev' })}
          </Button>
          <span data-testid="data-table-page" className="px-2 tabular-nums">
            {page + 1} / {totalPages}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              setPage((p) => (p + 1 < totalPages ? p + 1 : p))
            }
            disabled={page + 1 >= totalPages || rowsQuery.isFetching}
            data-testid="data-table-next"
          >
            {t('common.next', { defaultValue: 'Next' })}
          </Button>
        </div>
      </div>

      <div className="max-h-[60vh] overflow-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-surface-secondary">
            <tr>
              {cols.map((col) => (
                <th
                  key={col}
                  onClick={() => handleHeaderClick(col)}
                  className="cursor-pointer border-b border-border-light px-2 py-1 text-left font-semibold text-content-secondary hover:text-content-primary"
                  data-testid={`data-table-header-${col}`}
                  scope="col"
                >
                  <span className="inline-flex items-center gap-1">
                    {col}
                    <SortIcon
                      active={sort?.column === col}
                      direction={sort?.direction}
                    />
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rowsQuery.isLoading && rows.length === 0 && (
              <tr>
                <td colSpan={cols.length || 1} className="p-3">
                  <Skeleton className="h-4 w-full" />
                </td>
              </tr>
            )}
            {!rowsQuery.isLoading && rows.length === 0 && (
              <tr>
                <td
                  colSpan={cols.length || 1}
                  className="p-6 text-center text-content-tertiary"
                  data-testid="data-table-empty"
                >
                  {t('dashboards.data_table_empty', {
                    defaultValue: 'No rows match the current filters.',
                  })}
                </td>
              </tr>
            )}
            {rows.map((row, idx) => (
              <tr
                key={idx}
                className="border-b border-border-light/40 hover:bg-surface-secondary/40"
                data-testid={`data-table-row-${idx}`}
              >
                {cols.map((col) => (
                  <td
                    key={col}
                    className="px-2 py-1 align-top text-content-primary"
                  >
                    {formatCell(row[col])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function SortIcon({
  active,
  direction,
}: {
  active: boolean;
  direction?: 'asc' | 'desc';
}) {
  if (!active) {
    return <ChevronsUpDown className="h-3 w-3 text-content-tertiary" />;
  }
  return direction === 'asc' ? (
    <ArrowUp className="h-3 w-3 text-oe-blue" />
  ) : (
    <ArrowDown className="h-3 w-3 text-oe-blue" />
  );
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean')
    return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
