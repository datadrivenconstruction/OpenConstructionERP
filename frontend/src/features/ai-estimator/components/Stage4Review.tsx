// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Stage 4 - Review & apply (human-confirm checkpoint #4). The assembled
// estimate preview: positions with expandable resource sub-rows, pinned
// per-currency subtotals + base-currency grand total, a validation
// traffic-light that drills down into every failing rule, completeness
// ring, and a single explicit "Create / append to BOQ" action gated behind
// an "I have reviewed this" checkbox. NEVER auto-writes. ERROR-severity
// rules block the write (the backend's can_apply is the source of truth).

import { Fragment, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  ChevronDown,
  ChevronRight,
  ShieldCheck,
  AlertTriangle,
  XCircle,
  CircleDashed,
  FileSpreadsheet,
  Info,
} from 'lucide-react';
import { Button, Card, AIDisclaimerBanner, AITrustNote } from '@/shared/ui';
import { ResourceBreakdown } from './ResourceBreakdown';
import {
  fmtMoneyStr,
  validationTone,
  scoreColor,
  scorePercent,
  toNum,
} from '../helpers';
import { useScoreThresholds } from '../meta';
import type {
  PreviewResponse,
  ValidationReport,
  ValidationResultItem,
  ValidationSeverity,
} from '../api';

function severityTone(sev: ValidationSeverity): string {
  switch (sev) {
    case 'error':
      return 'text-rose-600 dark:text-rose-400';
    case 'warning':
      return 'text-amber-600 dark:text-amber-400';
    default:
      return 'text-content-tertiary';
  }
}

/** Expandable traffic-light that drills into each rule result. */
function ValidationPanel({ report }: { report: ValidationReport | null }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const status = report?.status ?? null;
  const tone = validationTone(status);

  const Icon =
    status === 'passed'
      ? ShieldCheck
      : status === 'warnings'
        ? AlertTriangle
        : status === 'errors'
          ? XCircle
          : CircleDashed;

  // Failing rules first (errors, then warnings) for drill-down.
  const failing: ValidationResultItem[] = report
    ? [...report.errors, ...report.warnings]
    : [];
  const hasDetail = failing.length > 0 || (report?.passed.length ?? 0) > 0;

  return (
    <Card padding="sm" className={clsx('ring-1', tone.ring)}>
      <button
        type="button"
        onClick={() => hasDetail && setOpen((o) => !o)}
        aria-expanded={hasDetail ? open : undefined}
        disabled={!hasDetail}
        className="flex w-full items-center gap-2.5 text-left disabled:cursor-default"
      >
        <span className={clsx('flex h-8 w-8 items-center justify-center rounded-full', tone.dot)}>
          <Icon className="h-4 w-4 text-white" />
        </span>
        <div className="min-w-0 flex-1">
          <div className={clsx('text-sm font-semibold capitalize', tone.label)}>
            {t(`aiest.validation.status_${status ?? 'pending'}`, {
              defaultValue: status ?? 'pending',
            })}
          </div>
          {report && (
            <div className="text-xs text-content-tertiary">
              {t('aiest.validation.counts', {
                defaultValue: '{{p}} passed · {{w}} warnings · {{e}} errors',
                p: report.passed.length,
                w: report.warnings.length,
                e: report.errors.length,
              })}
            </div>
          )}
        </div>
        {hasDetail &&
          (open ? (
            <ChevronDown className="h-4 w-4 shrink-0 text-content-tertiary" />
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0 text-content-tertiary" />
          ))}
      </button>

      {open && report && (
        <ul className="mt-3 space-y-1.5 border-t border-border-light pt-3">
          {failing.length === 0 ? (
            <li className="text-xs text-content-tertiary">
              {t('aiest.validation.all_passed', {
                defaultValue: 'All checks passed - no issues to resolve.',
              })}
            </li>
          ) : (
            failing.map((r, i) => (
              <li key={`${r.rule_id}-${i}`} className="flex items-start gap-2 text-xs">
                <span className={clsx('mt-0.5 shrink-0', severityTone(r.severity))}>
                  {r.severity === 'error' ? (
                    <XCircle className="h-3.5 w-3.5" />
                  ) : (
                    <AlertTriangle className="h-3.5 w-3.5" />
                  )}
                </span>
                <div className="min-w-0">
                  <span className="text-content-primary">{r.message}</span>
                  <div className="text-[10px] text-content-tertiary">
                    <span className="font-mono">{r.rule_id}</span>
                    {r.element_ref && (
                      <span>
                        {' · '}
                        {r.element_ref}
                      </span>
                    )}
                  </div>
                </div>
              </li>
            ))
          )}
        </ul>
      )}
    </Card>
  );
}

export interface Stage4ReviewProps {
  preview: PreviewResponse | undefined;
  loading: boolean;
  locale?: string;
  applied: boolean;
  appliedBoqId: string | null;
  applyPending: boolean;
  onApply: () => void;
  // Identity for the trust-feedback verdict (so a "helpful / not right" verdict
  // can be lined up later with the run + project that produced this estimate).
  runId?: string | null;
  projectId?: string | null;
}

export function Stage4Review(props: Stage4ReviewProps) {
  const { t } = useTranslation();
  const { preview, loading, locale, applied, appliedBoqId, applyPending, onApply, runId, projectId } =
    props;
  const thresholds = useScoreThresholds();
  const [openRow, setOpenRow] = useState<string | null>(null);
  const [reviewed, setReviewed] = useState(false);

  if (loading || !preview) {
    return (
      <div className="space-y-2.5">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-12 animate-pulse rounded-lg border border-border-light bg-surface-secondary"
          />
        ))}
      </div>
    );
  }

  const subtotals = Object.entries(preview.currency_subtotals);
  const multiCurrency = subtotals.length > 1;
  const hasErrors = preview.validation?.status === 'errors';
  // ERROR-severity validation rules block the write; the backend is the
  // source of truth via can_apply. The reviewed checkbox is the human gate.
  const canApply = preview.can_apply && preview.positions.length > 0 && reviewed;

  return (
    <div className="space-y-4">
      <p className="text-sm text-content-secondary">
        {t('aiest.review.help', {
          defaultValue:
            'The assembled estimate, fully grounded in catalogue rates. Check the totals and validation, then create or append it to a BOQ. Nothing is written until you confirm.',
        })}
      </p>

      <AIDisclaimerBanner variant="compact" />

      {/* Top stats */}
      <div className="grid gap-3 sm:grid-cols-3">
        <ValidationPanel report={preview.validation} />

        <Card padding="sm">
          <div className="text-xs text-content-secondary">
            {t('aiest.review.grand_total', { defaultValue: 'Grand total' })}
          </div>
          <div className="mt-0.5 text-xl font-semibold tabular-nums text-content-primary">
            {fmtMoneyStr(preview.grand_total, preview.currency, locale)}
          </div>
          {multiCurrency && (
            <div className="mt-1 space-y-0.5 border-t border-border-light pt-1">
              <div className="text-[10px] uppercase tracking-wide text-content-tertiary">
                {t('aiest.review.by_currency', { defaultValue: 'By currency' })}
              </div>
              {subtotals.map(([cur, val]) => (
                <div key={cur} className="text-xs text-content-tertiary tabular-nums">
                  {fmtMoneyStr(val, cur, locale)}
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card padding="sm">
          <div className="text-xs text-content-secondary">
            {t('aiest.review.completeness', { defaultValue: 'Scope completeness' })}
          </div>
          <div className="mt-0.5 flex items-baseline gap-2">
            <span
              className={clsx(
                'rounded px-1.5 py-0.5 text-sm font-bold',
                scoreColor(preview.completeness_score, thresholds),
              )}
            >
              {scorePercent(preview.completeness_score)}
            </span>
            <span className="text-xs text-content-tertiary">
              {t('aiest.review.positions_n', {
                defaultValue: '{{n}} positions',
                n: preview.positions.length,
              })}
            </span>
          </div>
        </Card>
      </div>

      {/* Never-blend notice for multi-currency estimates */}
      {multiCurrency && (
        <div className="flex items-start gap-2 rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-xs text-content-secondary">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {t('aiest.review.never_blend', {
            defaultValue:
              'This estimate spans more than one currency. Totals are kept per currency and never converted into a single blended number.',
          })}
        </div>
      )}

      {/* Missing-scope advisory */}
      {preview.missing_items.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-800 dark:border-amber-900/50 dark:bg-amber-900/20 dark:text-amber-200">
          <div className="mb-1 font-medium">
            {t('aiest.review.missing_title', { defaultValue: 'Possibly missing scope' })}
          </div>
          <ul className="list-inside list-disc space-y-0.5">
            {preview.missing_items.slice(0, 8).map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Position table with expandable resources */}
      <div className="overflow-hidden rounded-lg border border-border-light">
        <table className="w-full text-sm">
          <thead className="bg-surface-secondary text-content-secondary">
            <tr>
              <th className="w-8 px-3 py-2" />
              <th className="px-3 py-2 text-left font-medium">
                {t('aiest.review.description', { defaultValue: 'Description' })}
              </th>
              <th className="px-3 py-2 text-right font-medium">
                {t('aiest.review.qty', { defaultValue: 'Qty' })}
              </th>
              <th className="px-3 py-2 text-right font-medium">
                {t('aiest.review.rate', { defaultValue: 'Rate' })}
              </th>
              <th className="px-3 py-2 text-right font-medium">
                {t('aiest.review.total', { defaultValue: 'Total' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {preview.positions.map((p) => {
              const rowKey = p.group_id || p.group_key;
              const expanded = openRow === rowKey;
              const hasRes = p.resources.length > 0;
              return (
                <Fragment key={rowKey}>
                  <tr className="border-t border-border-light/60">
                    <td className="px-3 py-2 text-center">
                      {hasRes && (
                        <button
                          type="button"
                          onClick={() => setOpenRow(expanded ? null : rowKey)}
                          aria-expanded={expanded}
                          aria-label={t('aiest.review.toggle_resources', {
                            defaultValue: 'Toggle resources',
                          })}
                        >
                          {expanded ? (
                            <ChevronDown className="h-4 w-4 text-content-tertiary" />
                          ) : (
                            <ChevronRight className="h-4 w-4 text-content-tertiary" />
                          )}
                        </button>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-content-primary">{p.description}</span>
                        {p.confidence != null && (
                          <span
                            className={clsx(
                              'rounded px-1 py-0.5 text-[10px] font-bold',
                              scoreColor(p.confidence, thresholds),
                            )}
                          >
                            {scorePercent(p.confidence)}
                          </span>
                        )}
                      </div>
                      {p.section_path.length > 0 && (
                        <div className="text-[10px] text-content-tertiary">
                          {p.section_path.join(' › ')}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-content-secondary">
                      {toNum(p.quantity)} {p.unit}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-content-secondary">
                      {fmtMoneyStr(p.unit_rate, p.currency, locale)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums font-medium text-content-primary">
                      {fmtMoneyStr(p.line_total, p.currency, locale)}
                    </td>
                  </tr>
                  {expanded && hasRes && (
                    <tr>
                      <td />
                      <td colSpan={4} className="px-3 pb-3">
                        <ResourceBreakdown
                          resources={p.resources}
                          currency={p.currency}
                          locale={locale}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Trust signal + feedback: the estimate is grounded in catalogue rates,
          its scope-completeness is the honest confidence, and the user can tell
          us whether it turned out right. */}
      <AITrustNote
        surface="ai_estimator"
        refId={runId}
        projectId={projectId}
        confidence={preview.completeness_score}
        producedBy={t('aiest.review.trust_produced', {
          defaultValue: 'Quantities grouped by AI; every rate comes from your cost database, never invented.',
        })}
      />

      {/* Apply */}
      {applied && appliedBoqId ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-900/50 dark:bg-emerald-900/20">
          <div className="flex items-center gap-2 font-medium text-emerald-800 dark:text-emerald-200">
            <ShieldCheck className="h-5 w-5" />
            {t('aiest.review.applied', { defaultValue: 'Estimate written to the BOQ.' })}
          </div>
          <Button
            variant="primary"
            size="sm"
            className="mt-3"
            onClick={() => {
              window.location.assign(`/boq/${appliedBoqId}`);
            }}
          >
            {t('aiest.review.open_boq', { defaultValue: 'Open the BOQ' })}
          </Button>
        </div>
      ) : (
        <div className="space-y-3 rounded-lg border border-border-light bg-surface-secondary p-4">
          <label className="flex cursor-pointer items-start gap-2.5 text-sm">
            <input
              type="checkbox"
              checked={reviewed}
              onChange={(e) => setReviewed(e.target.checked)}
              disabled={hasErrors || preview.positions.length === 0}
              className="mt-0.5 accent-oe-blue"
            />
            <span className="text-content-secondary">
              {t('aiest.review.confirm_checkbox', {
                defaultValue:
                  'I have reviewed the quantities, rates and validation and confirm this estimate is ready to write.',
              })}
            </span>
          </label>

          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="primary"
              size="lg"
              icon={<FileSpreadsheet className="h-4 w-4" />}
              loading={applyPending}
              disabled={!canApply}
              onClick={onApply}
            >
              {t('aiest.review.create_boq', { defaultValue: 'Create / append to BOQ' })}
            </Button>
            {hasErrors ? (
              <span className="inline-flex items-center gap-1 text-xs text-rose-600">
                <AlertTriangle className="h-3.5 w-3.5" />
                {t('aiest.review.blocked', {
                  defaultValue: 'Blocked: resolve validation errors first.',
                })}
              </span>
            ) : (
              !reviewed && (
                <span className="text-xs text-content-tertiary">
                  {t('aiest.review.tick_to_enable', {
                    defaultValue: 'Tick the box above to enable writing.',
                  })}
                </span>
              )
            )}
          </div>
        </div>
      )}
    </div>
  );
}
