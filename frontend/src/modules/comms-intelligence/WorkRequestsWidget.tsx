// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Project hub widget: what the departments are holding on this job.
 *
 * One row per department (open / overdue / with you, and hours logged
 * against the quote) and the five most urgent open requests, each wearing
 * its reference chip. Sits beside the Registers widget on /projects/:id so
 * an engineering, drafting, workshop, automation or hazardous-area request
 * is visible from the job itself, not only from the module.
 *
 * The module ships separately: a 404 from its API renders a quiet "not
 * available" line rather than an error, and the raise button stays away.
 */
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, Plus, Wrench } from 'lucide-react';
import clsx from 'clsx';
import { Card, Skeleton } from '@/shared/ui';
import { fmtDate } from '@/shared/lib/formatters';
import {
  departmentColour,
  fetchOpenWorkRequests,
  fetchWorkRequestSummary,
  fmtHours,
  hoursProgress,
  isModuleAbsent,
  openOnly,
  projectWorkRequestsUrl,
  raiseWorkRequestUrl,
  sortByUrgency,
  workRequestUrl,
  type WorkRequestRow,
  type WorkRequestSummary,
} from './WorkRequestsApi';

const CHIP_TONE = {
  open:
    'border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 dark:border-blue-800 dark:bg-blue-900/30 dark:text-blue-300 dark:hover:bg-blue-900/50',
  overdue:
    'border-red-200 bg-red-50 text-red-700 hover:bg-red-100 dark:border-red-800 dark:bg-red-900/30 dark:text-red-300 dark:hover:bg-red-900/50',
  closed:
    'border-border bg-surface-secondary text-content-tertiary hover:bg-surface-tertiary dark:hover:bg-surface-tertiary',
} as const;

/** The request reference as a chip (`WR-WKS-000012`), coloured by state,
 *  opening the request itself. Same shape as the register chip so the two
 *  read as one family on the hub. */
export function WorkRequestChip({
  item,
  className,
}: {
  item: Pick<WorkRequestRow, 'id' | 'reference' | 'status' | 'is_overdue'> & { title?: string };
  className?: string;
}) {
  const { t } = useTranslation();
  const tone = item.status === 'closed' ? 'closed' : item.is_overdue ? 'overdue' : 'open';
  const hint = t('work_requests.chip_hint', {
    defaultValue: 'Open request {{ref}}',
    ref: item.reference,
  });
  return (
    <Link
      to={workRequestUrl(item.id)}
      onClick={(e) => e.stopPropagation()}
      title={item.title ? `${hint}\n${item.title}` : hint}
      aria-label={hint}
      className={clsx(
        'inline-flex max-w-full items-center gap-1 rounded-full border px-1.5 py-0.5 font-mono text-2xs font-semibold leading-tight whitespace-nowrap transition-colors',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/60',
        CHIP_TONE[tone],
        className,
      )}
    >
      <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-current opacity-70" />
      <span className="truncate">{item.reference}</span>
    </Link>
  );
}

function DepartmentDot({ colour, className }: { colour: string; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={clsx('inline-block h-2 w-2 shrink-0 rounded-full', className)}
      style={{ backgroundColor: departmentColour(colour) }}
    />
  );
}

export function WorkRequestsWidget({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const summaryQ = useQuery<WorkRequestSummary>({
    queryKey: ['work-requests', projectId, 'summary'],
    queryFn: () => fetchWorkRequestSummary(projectId),
    retry: false,
    staleTime: 30_000,
  });
  const openQ = useQuery<WorkRequestRow[]>({
    queryKey: ['work-requests', projectId, 'hub-open'],
    queryFn: () => fetchOpenWorkRequests(projectId),
    retry: false,
    staleTime: 30_000,
  });

  // A department with nothing open and no hours booked is noise on a hub
  // card - the row comes back once something lands on it.
  const rows = useMemo(
    () =>
      (summaryQ.data?.departments ?? []).filter(
        (d) => d.open > 0 || d.overdue > 0 || d.hours_logged > 0,
      ),
    [summaryQ.data],
  );
  const deptOf = useMemo(() => {
    const m = new Map<string, { name: string; colour: string }>();
    (summaryQ.data?.departments ?? []).forEach((d) => m.set(d.key, { name: d.name, colour: d.colour }));
    return m;
  }, [summaryQ.data]);
  // Five is a sample of the most pressing, and the CTA says where the rest are.
  const urgent = useMemo(() => sortByUrgency(openOnly(openQ.data ?? [])).slice(0, 5), [openQ.data]);

  const isLoading = summaryQ.isLoading || openQ.isLoading;
  const absent = isModuleAbsent(summaryQ.error) || isModuleAbsent(openQ.error);
  const isError = !absent && summaryQ.isError && openQ.isError;
  const isEmpty = !isLoading && !absent && !isError && rows.length === 0 && urgent.length === 0;

  const withYou = t('project.widget.work-requests.with_you', { defaultValue: 'With you' });

  return (
    <Card padding="sm" className="flex h-full flex-col" data-testid="work-requests-widget">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-start gap-2">
          <span className="mt-0.5 shrink-0 text-content-tertiary">
            <Wrench size={16} />
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-sm font-semibold text-content-primary">
              {t('project.widget.work-requests.title', { defaultValue: 'Department requests' })}
            </h3>
            <p className="truncate text-2xs text-content-tertiary">
              {t('project.widget.work-requests.card_subtitle', {
                defaultValue: 'Engineering, drafting, workshop, automation and hazardous-area requests',
              })}
            </p>
          </div>
        </div>
        {!absent && (
          <button
            type="button"
            onClick={() => navigate(projectWorkRequestsUrl(projectId))}
            className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-2xs font-medium text-oe-blue transition-colors hover:bg-oe-blue/10"
          >
            {t('project.widget.work-requests.open', { defaultValue: 'Open the requests' })}
            <ArrowRight size={12} />
          </button>
        )}
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} height={24} className="w-full" rounded="md" />
          ))}
        </div>
      ) : absent ? (
        <p
          className="py-2 text-center text-2xs text-content-quaternary"
          data-testid="work-requests-widget-absent"
        >
          {t('project.widget.work-requests.module_absent', {
            defaultValue: 'The Work requests module is not available on this server.',
          })}
        </p>
      ) : isError ? (
        <p className="py-2 text-center text-2xs text-content-quaternary">
          {t('project.widget.work-requests.unavailable', {
            defaultValue: 'Department requests could not be read for this job.',
          })}
        </p>
      ) : isEmpty ? (
        <p className="py-2 text-center text-2xs text-content-quaternary" data-testid="work-requests-widget-empty">
          {t('project.widget.work-requests.empty', {
            defaultValue: 'No department requests on this job yet.',
          })}
        </p>
      ) : (
        <div className="space-y-3">
          {rows.length > 0 && (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-2xs uppercase tracking-wide text-content-tertiary">
                  <th className="pb-1 text-left font-medium">
                    {t('project.widget.work-requests.col_department', { defaultValue: 'Department' })}
                  </th>
                  <th className="pb-1 text-right font-medium">
                    {t('project.widget.work-requests.col_open', { defaultValue: 'Open' })}
                  </th>
                  <th className="pb-1 text-right font-medium">
                    {t('project.widget.work-requests.col_overdue', { defaultValue: 'Overdue' })}
                  </th>
                  <th className="pb-1 text-right font-medium">{withYou}</th>
                  <th className="pb-1 text-right font-medium">
                    {t('project.widget.work-requests.col_hours', { defaultValue: 'Hours' })}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {rows.map((r) => {
                  const p = hoursProgress(r.hours_logged, r.hours_quoted);
                  const hoursTitle = t('project.widget.work-requests.hours_title', {
                    defaultValue: '{{logged}} h logged of {{quoted}} h quoted',
                    logged: fmtHours(r.hours_logged),
                    quoted: fmtHours(r.hours_quoted),
                  });
                  return (
                    <tr key={r.key}>
                      <td className="py-1 text-content-primary">
                        <span className="inline-flex items-center gap-1.5">
                          <DepartmentDot colour={r.colour} />
                          <span className="truncate">{r.name}</span>
                        </span>
                      </td>
                      <td className="py-1 text-right font-mono text-content-secondary">{r.open}</td>
                      <td
                        className={clsx(
                          'py-1 text-right font-mono',
                          r.overdue > 0 ? 'font-semibold text-semantic-error' : 'text-content-tertiary',
                        )}
                      >
                        {r.overdue}
                      </td>
                      <td
                        className={clsx(
                          'py-1 text-right font-mono',
                          r.with_requester > 0 ? 'text-amber-600 dark:text-amber-400' : 'text-content-tertiary',
                        )}
                      >
                        {r.with_requester}
                      </td>
                      <td className="py-1 text-right">
                        <span className="inline-flex items-center justify-end gap-1.5" title={hoursTitle}>
                          {p.hasQuote || p.pct > 0 ? (
                            <span className="h-1.5 w-12 overflow-hidden rounded-full bg-surface-secondary">
                              <span
                                className={clsx(
                                  'block h-full rounded-full',
                                  p.over ? 'bg-semantic-error' : 'bg-oe-blue',
                                )}
                                style={{ width: `${p.pct}%` }}
                              />
                            </span>
                          ) : null}
                          <span
                            className={clsx(
                              'font-mono text-2xs',
                              p.over ? 'font-semibold text-semantic-error' : 'text-content-tertiary',
                            )}
                          >
                            {fmtHours(r.hours_logged)}/{fmtHours(r.hours_quoted)}
                          </span>
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}

          {urgent.length > 0 && (
            <div>
              <p className="mb-1 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                {t('project.widget.work-requests.urgent', { defaultValue: 'Most urgent' })}
              </p>
              <ul className="-mx-2 divide-y divide-border-light">
                {urgent.map((item) => {
                  const dept = deptOf.get(item.department);
                  const deptName = dept?.name ?? item.department;
                  const withThem = item.ball_in_court === 'requester';
                  return (
                    <li key={item.id} className="flex items-center gap-2 px-2 py-1.5">
                      <WorkRequestChip item={item} className="shrink-0" />
                      <span className="min-w-0 flex-1 truncate text-sm text-content-primary">
                        {item.title && item.title !== item.reference
                          ? item.title
                          : <span className="text-content-tertiary">{t('work_requests.untitled', { defaultValue: '(no title)' })}</span>}
                      </span>
                      <span
                        className="hidden shrink-0 items-center gap-1 text-2xs text-content-tertiary sm:inline-flex"
                        title={deptName}
                      >
                        <DepartmentDot colour={dept?.colour ?? ''} />
                        <span className="max-w-[7rem] truncate">{deptName}</span>
                      </span>
                      {item.due_date && (
                        <span
                          className={clsx(
                            'shrink-0 text-2xs',
                            item.is_overdue ? 'font-semibold text-semantic-error' : 'text-content-tertiary',
                          )}
                          title={t('project.widget.work-requests.due', { defaultValue: 'Due' })}
                        >
                          {fmtDate(item.due_date)}
                        </span>
                      )}
                      <span
                        className={clsx(
                          'shrink-0 rounded-full border px-1.5 py-0.5 text-2xs font-medium leading-tight whitespace-nowrap',
                          withThem
                            ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-900/30 dark:text-amber-300'
                            : 'border-border bg-surface-secondary text-content-tertiary',
                        )}
                        title={t('project.widget.work-requests.ball_in_court', { defaultValue: 'Ball in court' })}
                      >
                        {withThem
                          ? withYou
                          : t('project.widget.work-requests.with_department', {
                              defaultValue: 'With {{name}}',
                              name: deptName,
                            })}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>
      )}

      {!absent && !isLoading && (
        <div className="mt-auto border-t border-border-light pt-2">
          <button
            type="button"
            onClick={() => navigate(raiseWorkRequestUrl(projectId))}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-2xs font-medium text-oe-blue transition-colors hover:bg-oe-blue/10"
            data-testid="work-requests-widget-raise"
          >
            <Plus size={12} />
            {t('project.widget.work-requests.raise', { defaultValue: 'Raise a request' })}
          </button>
        </div>
      )}
    </Card>
  );
}
