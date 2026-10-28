// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { Fragment, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, FileText, Hourglass, Lock } from 'lucide-react';
import clsx from 'clsx';
import { Card, Badge, EmptyState, RecoveryCard, SkeletonTable } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { ApiError } from '@/shared/lib/api';
import { legalEntitiesApi } from '@/features/legal-entities/api';
import { AGEING_BUCKETS, getAgeing, type AgeingBucket, type AgeingRollup } from './api';
import { StatementOfAccountModal } from './StatementOfAccountModal';

const inputCls =
  'h-10 rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

type Scope = 'project' | 'all';
type DirectionFilter = '' | 'payable' | 'receivable';

/** A 403 (missing ``finance.read``) is surfaced as an access-required state. */
function isForbidden(err: unknown): boolean {
  return err instanceof ApiError && err.status === 403;
}

/** Column heading of an ageing bucket. */
export function bucketLabel(t: TFunction, bucket: AgeingBucket): string {
  switch (bucket) {
    case 'current':
      return t('finance.ageing_bucket_current', { defaultValue: 'Not yet due' });
    case '1_30':
      return t('finance.ageing_bucket_1_30', { defaultValue: '1-30 days' });
    case '31_60':
      return t('finance.ageing_bucket_31_60', { defaultValue: '31-60 days' });
    case '61_90':
      return t('finance.ageing_bucket_61_90', { defaultValue: '61-90 days' });
    default:
      return t('finance.ageing_bucket_over_90', { defaultValue: 'Over 90 days' });
  }
}

function directionLabel(t: TFunction, direction: string): string {
  if (direction === 'payable') return t('finance.ageing_payable', { defaultValue: 'Payable (AP)' });
  if (direction === 'receivable') return t('finance.ageing_receivable', { defaultValue: 'Receivable (AR)' });
  return direction;
}

function directionVariant(direction: string): 'blue' | 'warning' | 'neutral' {
  if (direction === 'receivable') return 'blue';
  if (direction === 'payable') return 'warning';
  return 'neutral';
}

function rollupKey(row: AgeingRollup): string {
  return `${row.legal_entity_id ?? 'none'}-${row.currency_code}-${row.direction}-${row.contact_id ?? 'none'}`;
}

/** Money cell that stays quiet on a zero, so the late columns stand out. */
function Amount({ value, currency, strong }: { value: string; currency: string; strong?: boolean }) {
  const zero = Number(value) === 0;
  return (
    <span
      className={clsx(
        'tabular-nums',
        zero ? 'text-content-tertiary' : strong ? 'font-semibold text-content-primary' : 'text-content-primary',
      )}
    >
      {zero ? '-' : <MoneyDisplay amount={value} currency={currency || undefined} />}
    </span>
  );
}

/**
 * AR / AP ageing: what is owed, to or by whom, and how late, per legal entity.
 * Every invoice is aged on its open balance as of the cutoff, so a partial
 * payment counts and retention is shown apart rather than as overdue. The
 * server keeps entities, currencies and directions apart and limits the
 * report to the projects the reader can open.
 */
export function AgeingTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const [scope, setScope] = useState<Scope>('project');
  const [direction, setDirection] = useState<DirectionFilter>('');
  const [legalEntityId, setLegalEntityId] = useState('');
  const [asOf, setAsOf] = useState('');
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [statementRow, setStatementRow] = useState<AgeingRollup | null>(null);

  const entitiesQ = useQuery({
    queryKey: ['legal-entities', 'list', 'ageing'],
    queryFn: () => legalEntitiesApi.list(false),
    staleTime: 5 * 60_000,
  });
  const entities = entitiesQ.data?.items ?? [];

  const query = {
    projectId: scope === 'project' ? projectId : undefined,
    legalEntityId: legalEntityId || undefined,
    direction: direction || undefined,
    asOf: asOf || undefined,
  };
  const ageingQ = useQuery({
    queryKey: ['finance', 'ageing', query],
    queryFn: () => getAgeing(query),
  });

  const report = ageingQ.data;
  const loading = !report && !ageingQ.isError;
  const isEmpty = !!report && report.groups.length === 0;
  const multiEntity = new Set((report?.totals ?? []).map((row) => row.legal_entity_id ?? '')).size > 1;
  const noEntity = t('finance.ageing_no_entity', { defaultValue: 'No legal entity' });

  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-oe-blue/15 bg-oe-blue/[0.03] p-3">
        <p className="text-sm text-content-secondary">
          {t('finance.ageing_subtitle', {
            defaultValue:
              'Open receivables and payables by how late they are. Each invoice counts with what is still open on it as of the date: payments made by then are taken off, and retention is shown apart because it is owed but not yet payable. Totals are kept apart per legal entity, currency and direction.',
          })}
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
            {t('finance.ageing_scope', { defaultValue: 'Projects' })}
          </span>
          <select value={scope} onChange={(e) => setScope(e.target.value as Scope)} className={inputCls}>
            <option value="project">{t('finance.ageing_scope_project', { defaultValue: 'This project' })}</option>
            <option value="all">{t('finance.ageing_scope_all', { defaultValue: 'All my projects' })}</option>
          </select>
        </label>
        {entities.length > 0 && (
          <label className="flex flex-col gap-1">
            <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('finance.ageing_entity', { defaultValue: 'Legal entity' })}
            </span>
            <select
              value={legalEntityId}
              onChange={(e) => setLegalEntityId(e.target.value)}
              className={clsx(inputCls, 'max-w-[16rem]')}
            >
              <option value="">{t('finance.ageing_entity_all', { defaultValue: 'All entities' })}</option>
              {entities.map((entity) => (
                <option key={entity.id} value={entity.id}>
                  {entity.code ? `${entity.code} · ${entity.name}` : entity.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="flex flex-col gap-1">
          <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
            {t('finance.ageing_direction', { defaultValue: 'Direction' })}
          </span>
          <select
            value={direction}
            onChange={(e) => setDirection(e.target.value as DirectionFilter)}
            className={inputCls}
          >
            <option value="">{t('finance.ageing_direction_both', { defaultValue: 'AR and AP' })}</option>
            <option value="receivable">{directionLabel(t, 'receivable')}</option>
            <option value="payable">{directionLabel(t, 'payable')}</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
            {t('finance.ageing_as_of', { defaultValue: 'As of' })}
          </span>
          <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className={inputCls} />
        </label>
      </div>

      {ageingQ.isError && isForbidden(ageingQ.error) ? (
        <EmptyState
          icon={<Lock size={26} strokeWidth={1.5} />}
          title={t('finance.retention_forbidden_title', { defaultValue: 'Finance access required' })}
          description={t('finance.ageing_forbidden_desc', {
            defaultValue:
              'You do not have permission to read finance data, so the ageing report cannot be shown. Ask an administrator to grant the finance read role.',
          })}
        />
      ) : ageingQ.isError ? (
        <RecoveryCard error={ageingQ.error} onRetry={() => ageingQ.refetch()} />
      ) : loading ? (
        <SkeletonTable rows={6} columns={7} />
      ) : isEmpty ? (
        <EmptyState
          icon={<Hourglass size={26} strokeWidth={1.5} />}
          title={t('finance.ageing_empty_title', { defaultValue: 'Nothing open' })}
          description={t('finance.ageing_empty_desc', {
            defaultValue:
              'No approved or sent invoice has anything left to pay or to collect for this selection. Drafts are not aged until they are approved.',
          })}
        />
      ) : (
        <>
          <p className="flex flex-wrap items-center gap-1.5 text-xs text-content-tertiary">
            <span>{t('finance.ageing_as_of_caption', { defaultValue: 'Aged as of' })}</span>
            <DateDisplay value={report!.as_of} className="font-medium text-content-secondary" />
            {report!.drafts_excluded > 0 && (
              <span>
                {t('finance.ageing_drafts_excluded', {
                  defaultValue: 'Drafts not counted until approved: {{n}}',
                  n: report!.drafts_excluded,
                })}
              </span>
            )}
          </p>

          {/* Per-(entity, currency, direction) totals */}
          <div className="grid gap-3 lg:grid-cols-2">
            {report!.totals.map((row) => (
              <Card key={rollupKey(row)} padding="none" className="space-y-3 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={directionVariant(row.direction)} size="sm">
                      {directionLabel(t, row.direction)}
                    </Badge>
                    <span className="text-sm font-medium text-content-primary">
                      {row.legal_entity_name || noEntity}
                    </span>
                    <span className="font-mono text-xs text-content-secondary">{row.currency_code}</span>
                  </div>
                  <span className="text-base font-semibold tabular-nums text-content-primary">
                    <MoneyDisplay amount={row.total_due} currency={row.currency_code || undefined} />
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
                  {AGEING_BUCKETS.map((bucket) => (
                    <div key={bucket}>
                      <p className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
                        {bucketLabel(t, bucket)}
                      </p>
                      <p className="mt-0.5 text-sm">
                        <Amount value={row.buckets[bucket]} currency={row.currency_code} />
                      </p>
                    </div>
                  ))}
                </div>
                {(Number(row.retention_held) !== 0 || Number(row.credit) !== 0) && (
                  <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-border/60 pt-2 text-xs text-content-secondary">
                    {Number(row.retention_held) !== 0 && (
                      <span>
                        {t('finance.ageing_retention_held', { defaultValue: 'Retention held' })}:{' '}
                        <MoneyDisplay amount={row.retention_held} currency={row.currency_code || undefined} />
                      </span>
                    )}
                    {Number(row.credit) !== 0 && (
                      <span>
                        {t('finance.ageing_credit', { defaultValue: 'Overpaid, to recover' })}:{' '}
                        <MoneyDisplay amount={row.credit} currency={row.currency_code || undefined} />
                      </span>
                    )}
                  </div>
                )}
              </Card>
            ))}
          </div>

          {/* Per-counterparty lines */}
          <Card padding="none" className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-content-secondary">
                    <th className="px-4 py-3 font-medium">
                      {t('finance.ageing_col_counterparty', { defaultValue: 'Counterparty' })}
                    </th>
                    {AGEING_BUCKETS.map((bucket) => (
                      <th key={bucket} className="whitespace-nowrap px-3 py-3 text-right font-medium">
                        {bucketLabel(t, bucket)}
                      </th>
                    ))}
                    <th className="px-3 py-3 text-right font-medium">
                      {t('finance.ageing_col_total', { defaultValue: 'Total due' })}
                    </th>
                    <th className="px-3 py-3 text-right font-medium">
                      {t('finance.ageing_col_retention', { defaultValue: 'Retention' })}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {report!.groups.map((row) => {
                    const key = rollupKey(row);
                    const expanded = open.has(key);
                    return (
                      <Fragment key={key}>
                        <tr className="border-b border-border/60 hover:bg-surface-secondary/50">
                          <td className="px-4 py-2.5">
                            <div className="flex items-start justify-between gap-2">
                              <button
                                type="button"
                                onClick={() => toggle(key)}
                                aria-expanded={expanded}
                                className="flex items-start gap-1.5 text-left text-content-primary"
                              >
                                {expanded ? (
                                  <ChevronDown size={14} className="mt-0.5 shrink-0" />
                                ) : (
                                  <ChevronRight size={14} className="mt-0.5 shrink-0" />
                                )}
                                <span>
                                  {row.counterparty_name ||
                                    t('finance.retention_unnamed', { defaultValue: 'Unspecified counterparty' })}
                                  <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-2xs text-content-tertiary">
                                    <Badge variant={directionVariant(row.direction)} size="sm">
                                      {directionLabel(t, row.direction)}
                                    </Badge>
                                    {multiEntity && <span>{row.legal_entity_name || noEntity}</span>}
                                    <span className="font-mono">{row.currency_code}</span>
                                    <span>
                                      {t('finance.ageing_invoice_count', {
                                        defaultValue: 'Invoices: {{n}}',
                                        n: row.invoice_count,
                                      })}
                                    </span>
                                  </span>
                                </span>
                              </button>
                              {row.contact_id && (
                                <button
                                  type="button"
                                  onClick={() => setStatementRow(row)}
                                  aria-label={t('finance.statement_action_aria', {
                                    defaultValue: 'Statement of account for {{name}}',
                                    name: row.counterparty_name ?? '',
                                  })}
                                  className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-2xs font-medium text-oe-blue hover:bg-oe-blue/10"
                                >
                                  <FileText size={12} />
                                  {t('finance.statement_action', { defaultValue: 'Statement' })}
                                </button>
                              )}
                            </div>
                          </td>
                          {AGEING_BUCKETS.map((bucket) => (
                            <td key={bucket} className="px-3 py-2.5 text-right">
                              <Amount value={row.buckets[bucket]} currency={row.currency_code} />
                            </td>
                          ))}
                          <td className="px-3 py-2.5 text-right">
                            <Amount value={row.total_due} currency={row.currency_code} strong />
                          </td>
                          <td className="px-3 py-2.5 text-right">
                            <Amount value={row.retention_held} currency={row.currency_code} />
                          </td>
                        </tr>
                        {expanded && (
                          <tr className="border-b border-border/60 bg-surface-secondary/40">
                            <td colSpan={AGEING_BUCKETS.length + 3} className="px-4 py-2">
                              <table className="w-full text-xs">
                                <thead>
                                  <tr className="text-left text-content-tertiary">
                                    <th className="py-1 pr-3 font-medium">
                                      {t('finance.ageing_col_invoice', { defaultValue: 'Invoice' })}
                                    </th>
                                    <th className="py-1 pr-3 font-medium">
                                      {t('finance.ageing_col_due_date', { defaultValue: 'Due date' })}
                                    </th>
                                    <th className="py-1 pr-3 text-right font-medium">
                                      {t('finance.ageing_col_days_late', { defaultValue: 'Days late' })}
                                    </th>
                                    <th className="py-1 pr-3 text-right font-medium">
                                      {t('finance.ageing_col_invoiced', { defaultValue: 'Invoiced' })}
                                    </th>
                                    <th className="py-1 pr-3 text-right font-medium">
                                      {t('finance.ageing_col_paid', { defaultValue: 'Paid' })}
                                    </th>
                                    <th className="py-1 text-right font-medium">
                                      {t('finance.ageing_col_open', { defaultValue: 'Open' })}
                                    </th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {row.invoices.map((line) => (
                                    <tr key={line.invoice_id} className="border-t border-border/40">
                                      <td className="py-1 pr-3 font-mono text-content-primary">
                                        {line.invoice_number}
                                      </td>
                                      <td className="py-1 pr-3 text-content-secondary">
                                        {line.due_date ? <DateDisplay value={line.due_date} /> : '-'}
                                      </td>
                                      <td
                                        className={clsx(
                                          'py-1 pr-3 text-right tabular-nums',
                                          line.days_past_due > 60
                                            ? 'font-medium text-semantic-error'
                                            : 'text-content-secondary',
                                        )}
                                      >
                                        {line.days_past_due}
                                      </td>
                                      <td className="py-1 pr-3 text-right">
                                        <Amount value={line.total} currency={row.currency_code} />
                                      </td>
                                      <td className="py-1 pr-3 text-right">
                                        <Amount value={line.paid} currency={row.currency_code} />
                                      </td>
                                      <td className="py-1 text-right">
                                        <Amount value={line.due} currency={row.currency_code} strong />
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}

      {statementRow && (
        <StatementOfAccountModal
          row={statementRow}
          asOf={asOf || report?.as_of}
          onClose={() => setStatementRow(null)}
        />
      )}
    </div>
  );
}
