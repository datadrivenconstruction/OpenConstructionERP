// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ContractAnalyticsPanels — the "Analytics & close-out" grouping on the
// contract detail drawer. It surfaces seven read-only backend endpoints that had
// no frontend consumer:
//
//   • GET /contracts/{id}/sov-status              → SoV billed/earned/paid table
//   • GET /contracts/{id}/completeness            → traffic-light rule report
//   • GET /contracts/{id}/eot-summary             → extension-of-time exposure
//   • GET /contracts/{id}/final-account-checklist → close-out readiness list
//   • GET /contracts/{id}/gainshare-preview       → GMP gain/pain split preview
//   • GET /contracts/{id}/security-coverage       → bonds/guarantees coverage
//   • GET /contracts/{id}/milestone-schedule      → payment milestone schedule
//
// Each panel owns its React Query (keyed by contract id), renders loading /
// error / empty states consistent with the rest of the page, degrades a 403 to
// a friendly "no access" line, right-aligns money as tabular-nums, and colours
// tie-outs with the module's success / warning / danger semantics (emerald /
// amber / red, matching ComplianceGate.tsx).

import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  BarChart3,
  Table2,
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  MinusCircle,
  CalendarClock,
  Clock,
  ListChecks,
  RefreshCw,
  Loader2,
  Lock,
  Info,
  Scale,
  Landmark,
  Flag,
  Coins,
} from 'lucide-react';

import { Card, Badge, Button, Input } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import {
  getSovStatus,
  getContractCompleteness,
  getEotSummary,
  getFinalAccountChecklist,
  getGainsharePreview,
  getSecurityCoverage,
  getMilestoneSchedule,
  listContractLines,
  type CompletenessFinding,
  type FinalAccountCheckItem,
  type MilestoneScheduleItem,
} from './api';

/* ── Semantic tie-out colours (mirror ComplianceGate.tsx) ─────────────── */

const SUCCESS = 'text-emerald-600 dark:text-emerald-400';
const WARNING = 'text-amber-600 dark:text-amber-400';
const DANGER = 'text-red-600 dark:text-red-400';
const MUTED = 'text-content-tertiary';

/** Mirror of the (unexported) Badge variant union, for status → badge mapping. */
type BadgeTone = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

/** Coerce a decimal-string (or number) money value to a finite number. */
function toNum(v: number | string | null | undefined): number {
  if (v === null || v === undefined) return 0;
  const n = typeof v === 'string' ? Number(v) : v;
  return Number.isFinite(n) ? n : 0;
}

function fmtPct(v: number | string | null | undefined): string {
  return `${toNum(v).toFixed(1)}%`;
}

/** Narrow a thrown ApiError to a 403 without importing the class. */
function isForbidden(err: unknown): boolean {
  return errorStatus(err) === 403;
}

/** Read the HTTP status off a thrown ApiError, or undefined for other errors. */
function errorStatus(err: unknown): number | undefined {
  if (err && typeof err === 'object' && 'status' in err) {
    const s = (err as { status: unknown }).status;
    return typeof s === 'number' ? s : undefined;
  }
  return undefined;
}

/** Humanise a backend enum value ("performance_bond" → "Performance bond"). */
function humanize(v: string): string {
  const spaced = v.replace(/[_-]+/g, ' ').trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : v;
}

/* ── Shared panel chrome ──────────────────────────────────────────────── */

function PanelHeader({
  icon,
  title,
  right,
}: {
  icon: ReactNode;
  title: string;
  right?: ReactNode;
}) {
  return (
    <div className="mb-2 flex items-center justify-between gap-2">
      <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-secondary">
        {icon}
        {title}
      </p>
      {right}
    </div>
  );
}

function PanelLoading({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 py-3 text-sm text-content-tertiary">
      <Loader2 size={14} className="animate-spin" />
      {label}
    </div>
  );
}

function PanelForbidden() {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-2 py-3 text-sm text-content-tertiary">
      <Lock size={14} />
      {t('contracts.analytics_forbidden', {
        defaultValue: 'You do not have access to this data.',
      })}
    </div>
  );
}

function PanelError({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-between gap-2 py-3 text-sm">
      <span className={clsx('flex items-center gap-2', WARNING)}>
        <AlertTriangle size={14} />
        {t('contracts.analytics_error', {
          defaultValue: 'Could not load this panel.',
        })}
      </span>
      <Button
        size="sm"
        variant="ghost"
        icon={<RefreshCw size={12} />}
        onClick={onRetry}
      >
        {t('contracts.analytics_retry', { defaultValue: 'Retry' })}
      </Button>
    </div>
  );
}

function PanelEmpty({ label }: { label: string }) {
  return <p className="py-3 text-sm text-content-tertiary">{label}</p>;
}

/**
 * Minimal structural shape of a React Query result used by {@link fallbackNode}
 * so the helper does not have to import the generic `UseQueryResult` type.
 */
interface QueryLike {
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => unknown;
}

/**
 * Resolve the shared loading / forbidden / error node for a query, or `null`
 * when the query has settled with data (the caller then renders the body).
 */
function fallbackNode(q: QueryLike, loadingLabel: string): ReactNode {
  if (q.isLoading) return <PanelLoading label={loadingLabel} />;
  if (isForbidden(q.error)) return <PanelForbidden />;
  if (q.isError) return <PanelError onRetry={() => void q.refetch()} />;
  return null;
}

/* ── 1 · Schedule-of-Values status ────────────────────────────────────── */

function SovStatusPanel({
  contractId,
  currency,
}: {
  contractId: string;
  currency: string;
}) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['contracts', 'sov-status', contractId],
    queryFn: () => getSovStatus(contractId),
    retry: false,
  });
  // Shares the drawer's line query (same key) so no extra round-trip; used to
  // label each SoV row and keep the display in contract-line order.
  const linesQ = useQuery({
    queryKey: ['contracts', 'lines', contractId],
    queryFn: () => listContractLines(contractId),
  });

  const fallback = fallbackNode(
    q,
    t('contracts.sov_loading', {
      defaultValue: 'Loading schedule of values…',
    }),
  );

  const money = (v: number | string) => (
    <MoneyDisplay amount={toNum(v)} currency={currency || undefined} />
  );

  let body: ReactNode = fallback;
  if (!fallback && q.data) {
    const orderIndex = new Map(
      (linesQ.data ?? []).map((l) => [l.id, l.order_index] as const),
    );
    const labelFor = (id: string): string => {
      const line = (linesQ.data ?? []).find((l) => l.id === id);
      return line?.code || line?.description || id.slice(0, 8);
    };
    const rows = Object.entries(q.data.by_line).sort(
      (a, b) => (orderIndex.get(a[0]) ?? 0) - (orderIndex.get(b[0]) ?? 0),
    );

    if (rows.length === 0) {
      body = (
        <PanelEmpty
          label={t('contracts.sov_empty', {
            defaultValue: 'No schedule-of-values lines to report.',
          })}
        />
      );
    } else {
      const totals = q.data.totals;
      body = (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-2xs uppercase tracking-wide text-content-tertiary">
              <tr>
                <th className="py-1 text-left">
                  {t('contracts.sov_line', { defaultValue: 'Line' })}
                </th>
                <th className="py-1 text-right">
                  {t('contracts.sov_scheduled', { defaultValue: 'Scheduled' })}
                </th>
                <th className="py-1 text-right">
                  {t('contracts.sov_billed', { defaultValue: 'Billed' })}
                </th>
                <th className="py-1 text-right">
                  {t('contracts.sov_earned', { defaultValue: 'Earned' })}
                </th>
                <th className="py-1 text-right">
                  {t('contracts.sov_paid', { defaultValue: 'Paid' })}
                </th>
                <th className="py-1 text-right">
                  {t('contracts.sov_percent', { defaultValue: '% Complete' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([lineId, row]) => {
                // Tie-out: earning past the scheduled value is an over-claim.
                const over = toNum(row.earned) > toNum(row.scheduled);
                const pct = toNum(row.percent_complete);
                const pctColor = over
                  ? DANGER
                  : pct >= 100
                    ? SUCCESS
                    : pct > 0
                      ? 'text-content-primary'
                      : MUTED;
                return (
                  <tr key={lineId} className="border-t border-border-light">
                    <td className="py-1 pr-2 font-mono text-xs text-content-secondary">
                      {labelFor(lineId)}
                    </td>
                    <td className="py-1 text-right tabular-nums text-content-secondary">
                      {money(row.scheduled)}
                    </td>
                    <td className="py-1 text-right tabular-nums text-content-secondary">
                      {money(row.billed)}
                    </td>
                    <td
                      className={clsx(
                        'py-1 text-right tabular-nums',
                        over ? DANGER : 'text-content-secondary',
                      )}
                    >
                      {money(row.earned)}
                    </td>
                    <td className="py-1 text-right tabular-nums text-content-secondary">
                      {money(row.paid)}
                    </td>
                    <td
                      className={clsx(
                        'py-1 text-right tabular-nums font-medium',
                        pctColor,
                      )}
                    >
                      {pct.toFixed(1)}%
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-border-light font-medium">
                <td className="py-1 pr-2 text-xs uppercase tracking-wide text-content-tertiary">
                  {t('contracts.sov_total', { defaultValue: 'Total' })}
                </td>
                <td className="py-1 text-right tabular-nums">
                  {money(totals.scheduled)}
                </td>
                <td className="py-1 text-right tabular-nums">
                  {money(totals.billed)}
                </td>
                <td className="py-1 text-right tabular-nums">
                  {money(totals.earned)}
                </td>
                <td className="py-1 text-right tabular-nums">
                  {money(totals.paid)}
                </td>
                <td className="py-1 text-right tabular-nums">
                  {fmtPct(totals.percent_complete)}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      );
    }
  }

  return (
    <Card padding="sm">
      <PanelHeader
        icon={<Table2 size={14} className="text-oe-blue" />}
        title={t('contracts.sov_status_title', {
          defaultValue: 'Schedule of values status',
        })}
        right={
          q.data ? (
            <span className="text-2xs uppercase tracking-wide text-content-tertiary">
              {t('contracts.sov_complete_badge', {
                defaultValue: '{{pct}} complete',
                pct: fmtPct(q.data.totals.percent_complete),
              })}
            </span>
          ) : undefined
        }
      />
      {body}
    </Card>
  );
}

/* ── 2 · Completeness (traffic-light) ─────────────────────────────────── */

function FindingList({
  tone,
  title,
  findings,
}: {
  tone: 'error' | 'warning';
  title: string;
  findings: CompletenessFinding[];
}) {
  const isError = tone === 'error';
  return (
    <div>
      <p className={clsx('mb-1 text-2xs font-semibold uppercase tracking-wide', isError ? DANGER : WARNING)}>
        {title} ({findings.length})
      </p>
      <ul className="space-y-1.5">
        {findings.map((f, i) => (
          <li
            key={`${f.rule_id}-${f.element_ref ?? i}`}
            className={clsx(
              'rounded-lg border px-3 py-2 text-sm',
              isError
                ? 'border-red-200 bg-red-50/60 dark:border-red-900 dark:bg-red-950/30'
                : 'border-amber-200 bg-amber-50/60 dark:border-amber-800 dark:bg-amber-950/30',
            )}
          >
            <div className="flex items-start gap-2">
              {isError ? (
                <ShieldX size={14} className={clsx('mt-0.5 shrink-0', DANGER)} />
              ) : (
                <AlertTriangle size={14} className={clsx('mt-0.5 shrink-0', WARNING)} />
              )}
              <div className="min-w-0">
                <p className="text-content-primary">{f.message}</p>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-2xs text-content-tertiary">
                  <span className="font-mono">{f.rule_id}</span>
                  {f.element_ref && <span className="font-mono">· {f.element_ref}</span>}
                </div>
                {f.suggestion && (
                  <p className="mt-1 text-2xs text-content-secondary">{f.suggestion}</p>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CompletenessPanel({ contractId }: { contractId: string }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['contracts', 'completeness', contractId],
    queryFn: () => getContractCompleteness(contractId),
    retry: false,
  });

  const fallback = fallbackNode(
    q,
    t('contracts.completeness_loading', {
      defaultValue: 'Running completeness checks…',
    }),
  );

  let body: ReactNode = fallback;
  if (!fallback && q.data) {
    const report = q.data;
    const errors = report.errors ?? [];
    const warnings = report.warnings ?? [];
    const passedCount = report.summary?.counts?.passed ?? 0;

    const banner = (() => {
      if (report.status === 'errors') {
        return {
          cls: 'border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/40',
          icon: <ShieldX size={18} className={clsx('mt-0.5 shrink-0', DANGER)} />,
          titleCls: 'text-red-800 dark:text-red-300',
          title: t('contracts.completeness_errors_title', {
            defaultValue: 'Completeness check found blocking issues',
          }),
        };
      }
      if (report.status === 'warnings') {
        return {
          cls: 'border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/40',
          icon: <ShieldAlert size={18} className={clsx('mt-0.5 shrink-0', WARNING)} />,
          titleCls: 'text-amber-800 dark:text-amber-300',
          title: t('contracts.completeness_warnings_title', {
            defaultValue: 'Complete, with warnings to review',
          }),
        };
      }
      if (report.status === 'passed') {
        return {
          cls: 'border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/40',
          icon: <ShieldCheck size={18} className={clsx('mt-0.5 shrink-0', SUCCESS)} />,
          titleCls: 'text-emerald-800 dark:text-emerald-300',
          title: t('contracts.completeness_passed_title', {
            defaultValue: 'All completeness checks passed',
          }),
        };
      }
      // skipped / unsupported / info (or any unexpected status): neutral, never
      // mislabelled as a green pass.
      return {
        cls: 'border-border-light bg-surface-secondary',
        icon: <Info size={18} className="mt-0.5 shrink-0 text-content-tertiary" />,
        titleCls: 'text-content-secondary',
        title: t('contracts.completeness_skipped_title', {
          defaultValue: 'No applicable completeness rules',
        }),
      };
    })();

    body = (
      <div className="space-y-3">
        <div className={clsx('flex items-start gap-3 rounded-lg border px-3 py-2.5', banner.cls)}>
          {banner.icon}
          <div>
            <p className={clsx('text-sm font-semibold', banner.titleCls)}>{banner.title}</p>
            <div className="mt-1 flex flex-wrap items-center gap-3 text-2xs">
              <span className={clsx('inline-flex items-center gap-1', SUCCESS)}>
                <CheckCircle2 size={12} /> {passedCount}{' '}
                {t('contracts.completeness_passed_label', { defaultValue: 'passed' })}
              </span>
              <span className={clsx('inline-flex items-center gap-1', WARNING)}>
                <ShieldAlert size={12} /> {warnings.length}{' '}
                {t('contracts.completeness_warnings_label', { defaultValue: 'warnings' })}
              </span>
              <span className={clsx('inline-flex items-center gap-1', DANGER)}>
                <ShieldX size={12} /> {errors.length}{' '}
                {t('contracts.completeness_errors_label', { defaultValue: 'errors' })}
              </span>
            </div>
          </div>
        </div>

        {errors.length > 0 && (
          <FindingList
            tone="error"
            title={t('contracts.completeness_errors_heading', {
              defaultValue: 'Blocking errors',
            })}
            findings={errors}
          />
        )}
        {warnings.length > 0 && (
          <FindingList
            tone="warning"
            title={t('contracts.completeness_warnings_heading', {
              defaultValue: 'Warnings',
            })}
            findings={warnings}
          />
        )}
        {errors.length === 0 && warnings.length === 0 && (
          <p className="text-sm text-content-secondary">
            {t('contracts.completeness_no_findings', {
              defaultValue: 'No completeness findings. Every applicable rule passed.',
            })}
          </p>
        )}
      </div>
    );
  }

  return (
    <Card padding="sm">
      <PanelHeader
        icon={<ShieldCheck size={14} className="text-oe-blue" />}
        title={t('contracts.completeness_title', {
          defaultValue: 'Contract completeness',
        })}
      />
      {body}
    </Card>
  );
}

/* ── 3 · Extension-of-time summary ────────────────────────────────────── */

function EotStat({
  label,
  value,
  valueCls,
}: {
  label: string;
  value: ReactNode;
  valueCls?: string;
}) {
  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary px-3 py-2">
      <p className="text-2xs uppercase tracking-wide text-content-tertiary">{label}</p>
      <p className={clsx('mt-0.5 text-sm font-semibold text-content-primary', valueCls)}>
        {value}
      </p>
    </div>
  );
}

function EotSummaryPanel({ contractId }: { contractId: string }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['contracts', 'eot-summary', contractId],
    queryFn: () => getEotSummary(contractId),
    retry: false,
  });

  const fallback = fallbackNode(
    q,
    t('contracts.eot_loading', { defaultValue: 'Loading extension-of-time…' }),
  );

  let body: ReactNode = fallback;
  if (!fallback && q.data) {
    const s = q.data;
    if (s.claims_count === 0) {
      body = (
        <PanelEmpty
          label={t('contracts.eot_empty', {
            defaultValue: 'No extension-of-time claims raised on this contract.',
          })}
        />
      );
    } else {
      const daysUnit = t('contracts.eot_days_unit', { defaultValue: 'days' });
      body = (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <EotStat
              label={t('contracts.eot_days_claimed', { defaultValue: 'Days claimed' })}
              value={`${s.total_days_claimed} ${daysUnit}`}
            />
            <EotStat
              label={t('contracts.eot_days_granted', { defaultValue: 'Days granted' })}
              value={`${s.total_days_granted} ${daysUnit}`}
              valueCls={s.total_days_granted > 0 ? SUCCESS : undefined}
            />
            <EotStat
              label={t('contracts.eot_pending', { defaultValue: 'Pending' })}
              value={s.pending_count}
              valueCls={s.pending_count > 0 ? WARNING : undefined}
            />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 text-2xs text-content-tertiary">
            <span className="inline-flex items-center gap-1">
              <Clock size={12} />
              {t('contracts.eot_decided_of', {
                defaultValue: '{{decided}} of {{total}} claims decided',
                decided: s.decided_count,
                total: s.claims_count,
              })}
            </span>
            <span className="inline-flex items-center gap-1">
              <CalendarClock size={12} />
              {t('contracts.eot_revised_completion', {
                defaultValue: 'Revised completion:',
              })}{' '}
              {s.latest_revised_completion_date ? (
                <span className="font-medium text-content-secondary">
                  <DateDisplay value={s.latest_revised_completion_date} />
                </span>
              ) : (
                '—'
              )}
            </span>
          </div>
        </div>
      );
    }
  }

  return (
    <Card padding="sm">
      <PanelHeader
        icon={<CalendarClock size={14} className="text-oe-blue" />}
        title={t('contracts.eot_title', {
          defaultValue: 'Extension of time',
        })}
      />
      {body}
    </Card>
  );
}

/* ── 4 · Final-account close-out checklist ─────────────────────────────── */

/** Human-readable English fallback labels for the stable check keys. */
const CHECK_LABELS: Record<string, string> = {
  progress_claims_settled: 'Progress claims settled',
  eot_claims_decided: 'Extension-of-time claims decided',
  securities_released: 'Securities released',
  retention_released: 'Retention released',
  final_certificate_issued: 'Final account agreed & signed off',
  final_value_reconciled: 'Final value reconciled',
};

function checkLabel(t: TFunction, key: string): string {
  return t(`contracts.final_account_check_${key}`, {
    defaultValue: CHECK_LABELS[key] ?? key.replace(/_/g, ' '),
  });
}

function ChecklistRow({
  item,
  label,
}: {
  item: FinalAccountCheckItem;
  label: string;
}) {
  const icon =
    item.status === 'pass' ? (
      <CheckCircle2 size={15} className={clsx('mt-0.5 shrink-0', SUCCESS)} />
    ) : item.status === 'fail' ? (
      <XCircle size={15} className={clsx('mt-0.5 shrink-0', DANGER)} />
    ) : (
      <MinusCircle size={15} className={clsx('mt-0.5 shrink-0', MUTED)} />
    );
  return (
    <li className="flex items-start gap-2 border-b border-border-light py-1.5 last:border-0">
      {icon}
      <div className="min-w-0">
        <p
          className={clsx(
            'text-sm',
            item.status === 'not_applicable'
              ? 'text-content-tertiary line-through'
              : 'text-content-primary',
          )}
        >
          {label}
        </p>
        <p className="text-2xs text-content-tertiary">{item.reason}</p>
      </div>
    </li>
  );
}

function FinalAccountChecklistPanel({ contractId }: { contractId: string }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['contracts', 'final-account-checklist', contractId],
    queryFn: () => getFinalAccountChecklist(contractId),
    retry: false,
  });

  const fallback = fallbackNode(
    q,
    t('contracts.final_account_loading', {
      defaultValue: 'Loading close-out checklist…',
    }),
  );

  let body: ReactNode = fallback;
  let readyBadge: ReactNode = null;
  if (!fallback && q.data) {
    const data = q.data;
    readyBadge = (
      <Badge variant={data.ready ? 'success' : 'warning'} dot>
        {data.ready
          ? t('contracts.final_account_ready', { defaultValue: 'Ready to close' })
          : t('contracts.final_account_not_ready', { defaultValue: 'Not ready' })}
      </Badge>
    );
    body = (
      <div className="space-y-3">
        <div>
          <div className="flex items-center justify-between text-2xs text-content-tertiary">
            <span>
              {t('contracts.final_account_progress', {
                defaultValue: '{{passed}} of {{applicable}} checks passed',
                passed: data.passed_count,
                applicable: data.applicable_count,
              })}
            </span>
            <span className="font-medium text-content-secondary">
              {fmtPct(data.completion_percent)}
            </span>
          </div>
          <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary">
            <div
              className={clsx('h-full rounded-full', data.ready ? 'bg-emerald-500' : 'bg-amber-500')}
              style={{ width: `${Math.min(100, Math.max(0, toNum(data.completion_percent)))}%` }}
            />
          </div>
        </div>
        {data.items.length === 0 ? (
          <PanelEmpty
            label={t('contracts.final_account_empty', {
              defaultValue: 'No close-out conditions to evaluate yet.',
            })}
          />
        ) : (
          <ul>
            {data.items.map((item) => (
              <ChecklistRow key={item.key} item={item} label={checkLabel(t, item.key)} />
            ))}
          </ul>
        )}
      </div>
    );
  }

  return (
    <Card padding="sm">
      <PanelHeader
        icon={<ListChecks size={14} className="text-oe-blue" />}
        title={t('contracts.final_account_title', {
          defaultValue: 'Close-out readiness',
        })}
        right={readyBadge ?? undefined}
      />
      {body}
    </Card>
  );
}

/* ── Shared metric tile (gain-share & security panels) ────────────────── */

/** Compact labelled metric tile (twin of {@link EotStat}, reused by panels 5-6). */
function StatTile({
  label,
  value,
  valueCls,
}: {
  label: string;
  value: ReactNode;
  valueCls?: string;
}) {
  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary px-3 py-2">
      <p className="text-2xs uppercase tracking-wide text-content-tertiary">{label}</p>
      <p className={clsx('mt-0.5 text-sm font-semibold text-content-primary', valueCls)}>
        {value}
      </p>
    </div>
  );
}

/* ── 5 · Gain-share (GMP target-cost) preview ─────────────────────────── */

function GainsharePanel({
  contractId,
  currency,
}: {
  contractId: string;
  currency: string;
}) {
  const { t } = useTranslation();
  const [costInput, setCostInput] = useState('');
  const [submitted, setSubmitted] = useState<number | null>(null);

  const q = useQuery({
    queryKey: ['contracts', 'gainshare-preview', contractId, submitted],
    queryFn: () => getGainsharePreview(contractId, submitted as number),
    enabled: submitted != null,
    retry: false,
  });

  const parsed = Number(costInput);
  const canSubmit =
    costInput.trim() !== '' && Number.isFinite(parsed) && parsed > 0;

  const money = (v: number | string) => (
    <MoneyDisplay amount={toNum(v)} currency={currency || undefined} />
  );

  let body: ReactNode;
  if (submitted == null) {
    body = (
      <PanelEmpty
        label={t('contracts.gainshare_prompt', {
          defaultValue:
            'Enter an out-turn cost above to preview the gain and pain split.',
        })}
      />
    );
  } else if (q.isLoading) {
    body = (
      <PanelLoading
        label={t('contracts.gainshare_loading', {
          defaultValue: 'Calculating gain and pain split...',
        })}
      />
    );
  } else if (q.isError) {
    const st = errorStatus(q.error);
    if (st === 403) {
      body = <PanelForbidden />;
    } else if (st === 400) {
      body = (
        <PanelEmpty
          label={t('contracts.gainshare_not_applicable', {
            defaultValue:
              'Gain share applies to guaranteed maximum price contracts only.',
          })}
        />
      );
    } else if (st === 404) {
      body = (
        <PanelEmpty
          label={t('contracts.gainshare_no_config', {
            defaultValue:
              'No target cost and share split is configured for this contract yet.',
          })}
        />
      );
    } else {
      body = <PanelError onRetry={() => void q.refetch()} />;
    }
  } else if (q.data) {
    const d = q.data;
    const savings = toNum(d.savings);
    const overrun = toNum(d.overrun);
    body = (
      <div className="space-y-2">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <StatTile
            label={t('contracts.gainshare_actual_cost', {
              defaultValue: 'Out-turn cost',
            })}
            value={money(d.actual_cost)}
          />
          <StatTile
            label={t('contracts.gainshare_target_cost', {
              defaultValue: 'Target cost',
            })}
            value={money(d.target_cost)}
          />
          <StatTile
            label={t('contracts.gainshare_gmp_cap', {
              defaultValue: 'Guaranteed maximum',
            })}
            value={money(d.gmp_cap)}
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <StatTile
            label={t('contracts.gainshare_savings', {
              defaultValue: 'Savings (gain)',
            })}
            value={money(d.savings)}
            valueCls={savings > 0 ? SUCCESS : undefined}
          />
          <StatTile
            label={t('contracts.gainshare_overrun', {
              defaultValue: 'Overrun (pain)',
            })}
            value={money(d.overrun)}
            valueCls={overrun > 0 ? DANGER : undefined}
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <StatTile
            label={t('contracts.gainshare_owner_share', {
              defaultValue: 'Owner share',
            })}
            value={money(d.owner_share)}
          />
          <StatTile
            label={t('contracts.gainshare_contractor_share', {
              defaultValue: 'Contractor share',
            })}
            value={money(d.contractor_share)}
          />
        </div>
        <p className="text-2xs text-content-tertiary">
          {t('contracts.gainshare_overrun_responsibility', {
            defaultValue: 'Overrun carried by',
          })}
          :{' '}
          <span className="font-medium text-content-secondary">
            {humanize(d.overrun_responsibility)}
          </span>
        </p>
      </div>
    );
  } else {
    body = null;
  }

  return (
    <Card padding="sm">
      <PanelHeader
        icon={<Scale size={14} className="text-oe-blue" />}
        title={t('contracts.gainshare_title', {
          defaultValue: 'Gain share preview',
        })}
      />
      <p className="mb-2 text-2xs text-content-tertiary">
        {t('contracts.gainshare_intro', {
          defaultValue:
            'Enter a forecast or actual out-turn cost to preview the target-cost gain and pain split.',
        })}
      </p>
      <form
        className="mb-3 flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSubmit) setSubmitted(parsed);
        }}
      >
        <div className="flex-1">
          <Input
            type="number"
            inputMode="decimal"
            min="0"
            step="any"
            value={costInput}
            onChange={(e) => setCostInput(e.target.value)}
            icon={<Coins size={14} />}
            placeholder={t('contracts.gainshare_cost_placeholder', {
              defaultValue: 'e.g. 4800000',
            })}
            aria-label={t('contracts.gainshare_cost_label', {
              defaultValue: 'Out-turn cost',
            })}
          />
        </div>
        <Button
          type="submit"
          size="sm"
          variant="secondary"
          disabled={!canSubmit}
          loading={submitted != null && q.isFetching}
        >
          {t('contracts.gainshare_preview_action', { defaultValue: 'Preview' })}
        </Button>
      </form>
      {body}
    </Card>
  );
}

/* ── 6 · Security / bonds coverage ────────────────────────────────────── */

/** English fallback labels for the stable security-status enum. */
const SECURITY_STATUS_LABELS: Record<string, string> = {
  required: 'Required',
  received: 'Received',
  active: 'Active',
  expired: 'Expired',
  released: 'Released',
  claimed: 'Claimed',
};

function securityStatusLabel(t: TFunction, status: string): string {
  return t(`contracts.security_status_${status}`, {
    defaultValue: SECURITY_STATUS_LABELS[status] ?? humanize(status),
  });
}

function securityStatusTone(status: string): BadgeTone {
  switch (status) {
    case 'active':
      return 'success';
    case 'received':
      return 'blue';
    case 'required':
    case 'expired':
      return 'warning';
    case 'claimed':
      return 'error';
    default:
      return 'neutral';
  }
}

function SecurityCoveragePanel({
  contractId,
  currency,
}: {
  contractId: string;
  currency: string;
}) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['contracts', 'security-coverage', contractId],
    queryFn: () => getSecurityCoverage(contractId),
    retry: false,
  });

  const fallback = fallbackNode(
    q,
    t('contracts.security_coverage_loading', {
      defaultValue: 'Loading security coverage...',
    }),
  );

  let body: ReactNode = fallback;
  if (!fallback && q.data) {
    const d = q.data;
    if (d.count === 0) {
      body = (
        <PanelEmpty
          label={t('contracts.security_coverage_empty', {
            defaultValue:
              'No bonds, guarantees or insurance recorded for this contract.',
          })}
        />
      );
    } else {
      const cur = d.currency || currency;
      const statuses = Object.entries(d.by_status).sort((a, b) => b[1] - a[1]);
      body = (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <StatTile
              label={t('contracts.security_coverage_active_amount', {
                defaultValue: 'Active cover',
              })}
              value={
                <MoneyDisplay
                  amount={toNum(d.total_active_amount)}
                  currency={cur || undefined}
                />
              }
              valueCls={d.active_count > 0 ? SUCCESS : undefined}
            />
            <StatTile
              label={t('contracts.security_coverage_active_count', {
                defaultValue: 'Active securities',
              })}
              value={d.active_count}
            />
            <StatTile
              label={t('contracts.security_coverage_total_count', {
                defaultValue: 'Total recorded',
              })}
              value={d.count}
            />
          </div>

          <div>
            <p className="mb-1 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
              {t('contracts.security_coverage_by_status', {
                defaultValue: 'By status',
              })}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {statuses.map(([status, n]) => (
                <Badge key={status} variant={securityStatusTone(status)} dot>
                  {securityStatusLabel(t, status)} · {n}
                </Badge>
              ))}
            </div>
          </div>

          {d.active_types.length > 0 && (
            <div>
              <p className="mb-1 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                {t('contracts.security_coverage_active_types', {
                  defaultValue: 'Active types',
                })}
              </p>
              <div className="flex flex-wrap gap-1.5">
                {d.active_types.map((ty) => (
                  <span
                    key={ty}
                    className="rounded-md border border-border-light bg-surface-secondary px-2 py-0.5 text-2xs text-content-secondary"
                  >
                    {humanize(ty)}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      );
    }
  }

  return (
    <Card padding="sm">
      <PanelHeader
        icon={<Landmark size={14} className="text-oe-blue" />}
        title={t('contracts.security_coverage_title', {
          defaultValue: 'Security and bonds coverage',
        })}
      />
      {body}
    </Card>
  );
}

/* ── 7 · Milestone payment schedule ───────────────────────────────────── */

/** English fallback labels for the stable milestone-status enum. */
const MILESTONE_STATUS_LABELS: Record<string, string> = {
  pending: 'Pending',
  reached: 'Reached',
  invoiced: 'Invoiced',
  paid: 'Paid',
};

function milestoneStatusLabel(t: TFunction, status: string): string {
  return t(`contracts.milestone_status_${status}`, {
    defaultValue: MILESTONE_STATUS_LABELS[status] ?? humanize(status),
  });
}

function milestoneStatusTone(status: string): BadgeTone {
  switch (status) {
    case 'paid':
      return 'success';
    case 'invoiced':
    case 'reached':
      return 'blue';
    default:
      return 'neutral';
  }
}

function MilestoneRow({
  m,
  currency,
  label,
  tone,
}: {
  m: MilestoneScheduleItem;
  currency: string;
  label: string;
  tone: BadgeTone;
}) {
  return (
    <tr className="border-t border-border-light">
      <td className="py-1 pr-2">
        {m.code && (
          <span className="mr-1 font-mono text-2xs text-content-tertiary">
            {m.code}
          </span>
        )}
        <span className="text-content-primary">{m.name}</span>
      </td>
      <td className="py-1 pr-2 text-content-secondary">
        {m.planned_date ? <DateDisplay value={m.planned_date} /> : '-'}
      </td>
      <td className="py-1 pr-2 text-2xs text-content-tertiary">
        {humanize(m.trigger)}
      </td>
      <td className="py-1 pr-2">
        <Badge variant={tone}>{label}</Badge>
      </td>
      <td className="py-1 text-right tabular-nums text-content-secondary">
        <MoneyDisplay amount={toNum(m.value)} currency={currency || undefined} />
      </td>
    </tr>
  );
}

function MilestoneSchedulePanel({
  contractId,
  currency,
}: {
  contractId: string;
  currency: string;
}) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['contracts', 'milestone-schedule', contractId],
    queryFn: () => getMilestoneSchedule(contractId),
    retry: false,
  });

  const fallback = fallbackNode(
    q,
    t('contracts.milestone_schedule_loading', {
      defaultValue: 'Loading milestone schedule...',
    }),
  );

  let body: ReactNode = fallback;
  let totalBadge: ReactNode = null;
  if (!fallback && q.data) {
    const d = q.data;
    const cur = d.currency || currency;
    if (d.count === 0) {
      body = (
        <PanelEmpty
          label={t('contracts.milestone_schedule_empty', {
            defaultValue: 'No payment milestones defined for this contract.',
          })}
        />
      );
    } else {
      totalBadge = (
        <span className="text-2xs uppercase tracking-wide text-content-tertiary">
          {t('contracts.milestone_schedule_total', {
            defaultValue: 'Total scheduled',
          })}
          :{' '}
          <span className="font-medium text-content-secondary">
            <MoneyDisplay
              amount={toNum(d.scheduled_value)}
              currency={cur || undefined}
            />
          </span>
        </span>
      );
      // Order by planned date (unscheduled milestones last), then by code.
      const rows = [...d.milestones].sort((a, b) => {
        if (a.planned_date && b.planned_date) {
          return a.planned_date.localeCompare(b.planned_date);
        }
        if (a.planned_date) return -1;
        if (b.planned_date) return 1;
        return a.code.localeCompare(b.code);
      });
      body = (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-2xs uppercase tracking-wide text-content-tertiary">
              <tr>
                <th className="py-1 text-left">
                  {t('contracts.milestone_col_milestone', {
                    defaultValue: 'Milestone',
                  })}
                </th>
                <th className="py-1 text-left">
                  {t('contracts.milestone_col_date', {
                    defaultValue: 'Planned date',
                  })}
                </th>
                <th className="py-1 text-left">
                  {t('contracts.milestone_col_trigger', {
                    defaultValue: 'Trigger',
                  })}
                </th>
                <th className="py-1 text-left">
                  {t('contracts.milestone_col_status', {
                    defaultValue: 'Status',
                  })}
                </th>
                <th className="py-1 text-right">
                  {t('contracts.milestone_col_value', {
                    defaultValue: 'Value',
                  })}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <MilestoneRow
                  key={m.id}
                  m={m}
                  currency={cur}
                  label={milestoneStatusLabel(t, m.status)}
                  tone={milestoneStatusTone(m.status)}
                />
              ))}
            </tbody>
          </table>
        </div>
      );
    }
  }

  return (
    <Card padding="sm">
      <PanelHeader
        icon={<Flag size={14} className="text-oe-blue" />}
        title={t('contracts.milestone_schedule_title', {
          defaultValue: 'Milestone schedule',
        })}
        right={totalBadge ?? undefined}
      />
      {body}
    </Card>
  );
}

/* ── Grouping ─────────────────────────────────────────────────────────── */

/**
 * "Analytics & close-out" grouping for the contract detail drawer. Renders the
 * seven analytics panels as stacked cards, each with its own query so a slow or
 * forbidden endpoint never blocks the others.
 */
export function ContractAnalyticsPanels({
  contractId,
  currency,
}: {
  contractId: string;
  currency: string;
}) {
  const { t } = useTranslation();
  return (
    <section className="space-y-4">
      <div className="flex items-center gap-2 border-t border-border-light pt-4">
        <BarChart3 size={15} className="text-oe-blue" />
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('contracts.analytics_section_title', {
              defaultValue: 'Analytics & close-out',
            })}
          </h3>
          <p className="text-2xs text-content-tertiary">
            {t('contracts.analytics_section_subtitle', {
              defaultValue:
                'Live billing, completeness, time exposure and close-out readiness for this contract.',
            })}
          </p>
        </div>
      </div>

      <SovStatusPanel contractId={contractId} currency={currency} />
      <CompletenessPanel contractId={contractId} />
      <EotSummaryPanel contractId={contractId} />
      <FinalAccountChecklistPanel contractId={contractId} />
      <GainsharePanel contractId={contractId} currency={currency} />
      <SecurityCoveragePanel contractId={contractId} currency={currency} />
      <MilestoneSchedulePanel contractId={contractId} currency={currency} />
    </section>
  );
}
