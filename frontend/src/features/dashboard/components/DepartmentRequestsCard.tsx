// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Dashboard widget - the portfolio's department requests: one row per
// department (engineering, drafting, workshop, automation, hazardous area)
// with what is open, overdue, back with the requester and due this week,
// each row deep-linking to the module filtered to that department.
//
// The Work requests module ships separately: when its API answers 404 the
// card says so in one quiet line rather than erroring.

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ArrowRight, Wrench } from 'lucide-react';
import clsx from 'clsx';

import { Card, EmptyState } from '@/shared/ui';
import {
  departmentColour,
  departmentRequestsUrl,
  fetchWorkRequestSummary,
  isModuleAbsent,
  type DepartmentSummaryRow,
  type WorkRequestSummary,
} from '@/modules/comms-intelligence/WorkRequestsApi';

/** Anything to show at all? A portfolio with departments configured but
 *  nothing raised reads better as the empty state than as a table of zeros. */
export function hasAnyRequests(rows: readonly DepartmentSummaryRow[]): boolean {
  return rows.some((r) => r.open > 0 || r.overdue > 0 || r.with_requester > 0 || r.due_this_week > 0);
}

export function DepartmentRequestsCard() {
  const { t } = useTranslation();
  const q = useQuery<WorkRequestSummary>({
    queryKey: ['work-requests', 'portfolio-summary'],
    queryFn: () => fetchWorkRequestSummary(),
    retry: false,
    staleTime: 60_000,
  });

  const rows = useMemo(() => q.data?.departments ?? [], [q.data]);
  const absent = isModuleAbsent(q.error);
  const showRows = rows.length > 0 && hasAnyRequests(rows);

  return (
    <Card padding="md" data-testid="department-requests-card" className="flex h-full flex-col">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('dashboard.department_requests.title', { defaultValue: 'Department requests' })}
          </h3>
          <p className="text-xs text-content-tertiary">
            {t('dashboard.department_requests.subtitle', {
              defaultValue: 'What each department is holding across your jobs.',
            })}
          </p>
        </div>
        <Wrench size={18} className="text-content-tertiary" />
      </div>

      {q.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-9 w-full animate-pulse rounded-md bg-surface-secondary" />
          ))}
        </div>
      ) : absent ? (
        <p
          className="py-4 text-center text-xs text-content-quaternary"
          data-testid="department-requests-card-absent"
        >
          {t('dashboard.department_requests.module_absent', {
            defaultValue: 'The Work requests module is not available on this server.',
          })}
        </p>
      ) : q.isError ? (
        <p className="py-4 text-center text-xs text-content-quaternary">
          {t('dashboard.department_requests.unavailable', {
            defaultValue: 'Department requests could not be read right now.',
          })}
        </p>
      ) : !showRows ? (
        <EmptyState
          icon={<Wrench size={32} strokeWidth={1.5} />}
          title={t('dashboard.department_requests.empty_title', { defaultValue: 'No department requests yet' })}
          description={t('dashboard.department_requests.empty_description', {
            defaultValue: 'Raise one from a job to put work with engineering, drafting or the workshop.',
          })}
        />
      ) : (
        <table className="w-full text-xs" data-testid="department-requests-card-rows">
          <thead>
            <tr className="text-2xs uppercase tracking-wide text-content-tertiary">
              <th className="pb-1 text-left font-medium">
                {t('dashboard.department_requests.col_department', { defaultValue: 'Department' })}
              </th>
              <th className="pb-1 text-right font-medium">
                {t('dashboard.department_requests.col_open', { defaultValue: 'Open' })}
              </th>
              <th className="pb-1 text-right font-medium">
                {t('dashboard.department_requests.col_overdue', { defaultValue: 'Overdue' })}
              </th>
              <th className="pb-1 text-right font-medium">
                {t('dashboard.department_requests.col_with_requester', { defaultValue: 'With requester' })}
              </th>
              <th className="pb-1 text-right font-medium">
                {t('dashboard.department_requests.col_due_this_week', { defaultValue: 'Due this week' })}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light">
            {rows.map((r) => (
              <tr key={r.key} data-testid="department-requests-card-row">
                <td className="py-1.5">
                  <Link
                    to={departmentRequestsUrl(r.key)}
                    className="group inline-flex min-w-0 items-center gap-1.5 text-sm font-medium text-content-primary transition-colors hover:text-oe-blue"
                    title={t('dashboard.department_requests.open_department', {
                      defaultValue: 'Show {{name}} requests',
                      name: r.name,
                    })}
                  >
                    <span
                      aria-hidden="true"
                      className="inline-block h-2 w-2 shrink-0 rounded-full"
                      style={{ backgroundColor: departmentColour(r.colour) }}
                    />
                    <span className="truncate">{r.name}</span>
                    <ArrowRight
                      size={12}
                      className="shrink-0 text-content-tertiary transition-transform group-hover:translate-x-0.5 group-hover:text-oe-blue"
                    />
                  </Link>
                </td>
                <td className="py-1.5 text-right font-mono tabular-nums text-content-secondary">{r.open}</td>
                <td
                  className={clsx(
                    'py-1.5 text-right font-mono tabular-nums',
                    r.overdue > 0 ? 'font-semibold text-semantic-error' : 'text-content-tertiary',
                  )}
                >
                  {r.overdue}
                </td>
                <td
                  className={clsx(
                    'py-1.5 text-right font-mono tabular-nums',
                    r.with_requester > 0 ? 'text-amber-600 dark:text-amber-400' : 'text-content-tertiary',
                  )}
                >
                  {r.with_requester}
                </td>
                <td className="py-1.5 text-right font-mono tabular-nums text-content-secondary">{r.due_this_week}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {!absent && (
        <div className="mt-auto border-t border-border-light pt-2">
          <Link
            to="/work-requests"
            className="inline-flex items-center gap-1 text-xs font-medium text-oe-blue hover:underline"
          >
            {t('dashboard.department_requests.open_all', { defaultValue: 'Open work requests' })}
            <ArrowRight size={12} />
          </Link>
        </div>
      )}
    </Card>
  );
}
