// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// PopulatePreviewModal — preview + commit the claim lines derived from the
// latest progress observations (Gap I bridge).
//
// Flow:
//   1. On open, GET /populate-from-progress returns the populatable lines
//      (SoV lines linked to a BOQ position that has an observation).
//   2. The user reviews, deselects rows they don't want, and sees a live
//      selected-count + selected-gross.
//   3. Commit PUTs /commit-populated-lines with only the selected rows; the
//      server re-rolls the claim totals and the parent refetches.
//
// Field progress is a proposal, not a figure to bill blindly: the percent to
// date on each row can be corrected before commit. The row then shows what
// the server will bill, worked out the way the server works it out (percent
// to date x line value, less what earlier claims billed, never below zero),
// and the commit sends the percent alone so the server recomputes the period
// value from the earlier claims as they stand at that moment. A percent below
// what was billed before bills nothing on the line and says so. A preview
// from another source (the subcontractors' approved amounts) is not a
// percent, so its rows stay read-only and commit their values as before.
//
// Currency safety: every previewed value is in the claim currency. Lines in a
// different currency are skipped server-side and surfaced as a hint count, so
// the modal never blends currencies into one total.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Download, AlertTriangle, Info, RotateCcw } from 'lucide-react';

import { Button } from '@/shared/ui';
import {
  WideModal,
  WideModalSection,
} from '@/shared/ui/WideModal';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtPercent } from '@/shared/lib/formatters';
import {
  populateClaimPreview,
  commitClaimLines,
  type ProgressClaimPopulatePreview,
  type ProgressClaimPopulatePreviewItem,
} from './api';
import { billingModeErrorMessage } from './billingModeErrors';

function toNum(v: number | string | null | undefined): number {
  if (v === null || v === undefined) return 0;
  const n = typeof v === 'string' ? Number(v) : v;
  return Number.isFinite(n) ? n : 0;
}

/** A row as it would be billed, after any percent the person corrected. */
interface PreviewRowFigures {
  item: ProgressClaimPopulatePreviewItem;
  pct: number;
  edited: boolean;
  invalid: boolean;
  prior: number;
  period: number;
  cumulative: number;
  regressed: boolean;
}

/**
 * Work a previewed row out again at the percent the person typed.
 *
 * Mirrors the server's compute_progress_claim_line: the percent is to date
 * and clamped to 0-100, the period bills it less what earlier claims billed,
 * and a period that would go the wrong way is held at zero and flagged. An
 * empty or unreadable entry keeps the observed figures as the server sent them.
 */
function rowFigures(
  item: ProgressClaimPopulatePreviewItem,
  raw: string | undefined,
): PreviewRowFigures {
  const observed = toNum(item.observed_pct);
  const prior =
    item.prior_completed_value !== undefined
      ? toNum(item.prior_completed_value)
      : toNum(item.cumulative_completed_value) - toNum(item.period_completed_value);
  const trimmed = raw === undefined ? '' : raw.trim();
  const typed = trimmed === '' ? NaN : Number(trimmed);
  const invalid = trimmed !== '' && (!Number.isFinite(typed) || typed < 0 || typed > 100);
  if (trimmed === '' || invalid || typed === observed) {
    return {
      item,
      pct: observed,
      edited: false,
      invalid,
      prior,
      period: toNum(item.period_completed_value),
      cumulative: toNum(item.cumulative_completed_value),
      regressed: Boolean(item.percent_regressed),
    };
  }
  const lineValue = toNum(item.contract_line_value);
  const requested = (lineValue * typed) / 100;
  let period = requested - prior;
  // A credit line bills towards a negative total, so "backwards" flips there.
  if ((lineValue >= 0 && period < 0) || (lineValue < 0 && period > 0)) period = 0;
  const regressed = prior > 0 ? requested < prior : prior < 0 ? requested > prior : false;
  return {
    item,
    pct: typed,
    edited: true,
    invalid: false,
    prior,
    period,
    cumulative: prior + period,
    regressed,
  };
}

export interface PopulatePreviewModalProps {
  claimId: string;
  currency: string;
  onClose: () => void;
  onCommitted?: () => void;
  // Another source of suggested lines in the same shape, e.g. the
  // subcontractors' approved amounts. Committing is unchanged either way.
  // Leave these out and the modal previews field progress, as it always has.
  loadPreview?: (claimId: string) => Promise<ProgressClaimPopulatePreview>;
  title?: string;
  subtitle?: string;
  emptyText?: string;
  successText?: string;
}

export function PopulatePreviewModal({
  claimId,
  currency,
  onClose,
  onCommitted,
  loadPreview,
  title,
  subtitle,
  emptyText,
  successText,
}: PopulatePreviewModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const previewQ = useQuery({
    // A supplied loader gets its own cache entry, so the progress preview and
    // the other one never answer for each other.
    queryKey: loadPreview
      ? ['contracts', 'populate-preview', claimId, 'custom-source']
      : ['contracts', 'populate-preview', claimId],
    queryFn: () => (loadPreview ?? populateClaimPreview)(claimId),
  });

  // contract_line_id set of the rows the user wants to commit. Defaults to
  // "all previewed rows selected" once the preview arrives.
  const [deselected, setDeselected] = useState<Set<string>>(new Set());

  // Only field progress is a percent a person can correct; see the header.
  const editable = !loadPreview;
  // contract_line_id -> the percent to date as typed, for corrected rows.
  const [pctEdits, setPctEdits] = useState<Record<string, string>>({});

  const items = previewQ.data?.items ?? [];
  const previewCurrency = previewQ.data?.currency || currency;

  const rows = useMemo(
    () =>
      items.map((it) =>
        rowFigures(it, editable ? pctEdits[it.contract_line_id] : undefined),
      ),
    [items, pctEdits, editable],
  );

  const selectedRows = useMemo(
    () => rows.filter((row) => !deselected.has(row.item.contract_line_id)),
    [rows, deselected],
  );

  const selectedGross = useMemo(
    () => selectedRows.reduce((acc, row) => acc + row.period, 0),
    [selectedRows],
  );

  const anyInvalid = selectedRows.some((row) => row.invalid);

  const setPct = (id: string, value: string | undefined) => {
    setPctEdits((prev) => {
      const next = { ...prev };
      if (value === undefined) delete next[id];
      else next[id] = value;
      return next;
    });
  };

  const toggle = (id: string) => {
    setDeselected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const commitMut = useMutation({
    mutationFn: () =>
      commitClaimLines(
        claimId,
        selectedRows.map((row) =>
          editable
            ? // The percent alone: the server bills it over the earlier
              // claims as they stand when it writes, and flags a percent that
              // went backwards, which a value override would skip.
              { contract_line_id: row.item.contract_line_id, period_completed_pct: row.pct }
            : {
                contract_line_id: row.item.contract_line_id,
                period_completed_pct: toNum(row.item.observed_pct),
                period_completed_value: toNum(row.item.period_completed_value),
              },
        ),
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['contracts', 'claim', claimId] });
      qc.invalidateQueries({ queryKey: ['contracts', 'claim-lines', claimId] });
      addToast({
        type: 'success',
        title: successText ?? t('contracts.populate_committed', {
          defaultValue: 'Claim populated from progress',
        }),
      });
      onCommitted?.();
      onClose();
    },
    onError: (err) =>
      addToast({ type: 'error', title: billingModeErrorMessage(t, err) ?? getErrorMessage(err) }),
  });

  const skippedHints: string[] = [];
  if (previewQ.data) {
    if (previewQ.data.skipped_unlinked > 0) {
      skippedHints.push(
        t('contracts.populate_skipped_unlinked', {
          count: previewQ.data.skipped_unlinked,
          defaultValue:
            '{{count}} schedule-of-values line(s) skipped: not linked to a BOQ position.',
        }),
      );
    }
    if (previewQ.data.skipped_no_progress > 0) {
      skippedHints.push(
        t('contracts.populate_skipped_no_progress', {
          count: previewQ.data.skipped_no_progress,
          defaultValue:
            '{{count}} linked line(s) skipped: no progress observation recorded yet.',
        }),
      );
    }
    if (previewQ.data.skipped_foreign_currency > 0) {
      skippedHints.push(
        t('contracts.populate_skipped_currency', {
          count: previewQ.data.skipped_foreign_currency,
          defaultValue:
            '{{count}} line(s) skipped: a different currency than this claim (never blended).',
        }),
      );
    }
  }

  // A refused preview is not an empty one: "no progress recorded" would send
  // the reader to record progress the server will refuse to bill anyway.
  const previewError = previewQ.isError
    ? billingModeErrorMessage(t, previewQ.error) ?? getErrorMessage(previewQ.error)
    : null;
  const emptyPreview = !previewQ.isLoading && !previewError && items.length === 0;

  return (
    <WideModal
      open
      onClose={onClose}
      title={title ?? t('contracts.populate_title', {
        defaultValue: 'Populate from progress observations',
      })}
      subtitle={
        subtitle ??
        (editable
          ? t('contracts.populate_subtitle_editable', {
              defaultValue:
                'Proposed from the field progress measured up to the end of this claim period. Correct a percent to date where the site says otherwise, deselect what you do not want to bill, then commit.',
            })
          : t('contracts.populate_subtitle', {
              defaultValue:
                'Review the values derived from the latest field observations, deselect any you do not want, then commit.',
            }))
      }
      size="xl"
      busy={commitMut.isPending}
      footer={
        <>
          <div className="mr-auto text-sm text-content-secondary" data-testid="populate-selected-summary">
            {t('contracts.populate_selected', {
              count: selectedRows.length,
              defaultValue: '{{count}} selected',
            })}
            {' · '}
            <MoneyDisplay amount={selectedGross} currency={previewCurrency || undefined} />
          </div>
          <Button variant="ghost" onClick={onClose} disabled={commitMut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => commitMut.mutate()}
            loading={commitMut.isPending}
            disabled={selectedRows.length === 0 || previewQ.isLoading || anyInvalid}
            icon={commitMut.isPending ? <Loader2 size={14} /> : <Download size={14} />}
          >
            {t('contracts.populate_commit', { defaultValue: 'Commit lines' })}
          </Button>
        </>
      }
    >
      <WideModalSection>
        {skippedHints.length > 0 && (
          <div
            className="mb-3 flex flex-col gap-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300"
            role="status"
          >
            {skippedHints.map((h) => (
              <span key={h} className="flex items-center gap-1.5">
                <Info size={12} aria-hidden />
                {h}
              </span>
            ))}
          </div>
        )}

        {previewQ.isLoading ? (
          <p className="py-6 text-center text-sm text-content-tertiary">
            <Loader2 size={16} className="mr-2 inline animate-spin" />
            {t('common.loading', { defaultValue: 'Loading…' })}
          </p>
        ) : previewError ? (
          <div
            className="flex items-center gap-2 rounded-lg border border-semantic-error/30 bg-semantic-error-bg px-3 py-4 text-sm text-semantic-error"
            role="alert"
            data-testid="populate-error"
          >
            <AlertTriangle size={16} aria-hidden />
            {previewError}
          </div>
        ) : emptyPreview ? (
          <div
            className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-secondary px-3 py-4 text-sm text-content-secondary"
            role="alert"
            data-testid="populate-empty"
          >
            <AlertTriangle size={16} className="text-amber-500" aria-hidden />
            {emptyText ?? t('contracts.populate_empty', {
              defaultValue:
                'No progress observations are available for this contract in the current period. Record field progress against BOQ-linked schedule-of-values lines, then try again.',
            })}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="populate-preview-table">
              <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
                <tr>
                  <th className="px-3 py-2 text-left">
                    <span className="sr-only">
                      {t('contracts.populate_include', { defaultValue: 'Include' })}
                    </span>
                  </th>
                  <th className="px-3 py-2 text-left">
                    {t('contracts.line', { defaultValue: 'Line' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {editable
                      ? t('contracts.populate_pct_to_date', { defaultValue: '% to date' })
                      : t('contracts.pct_complete', { defaultValue: '% complete' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('contracts.line_value', { defaultValue: 'Line value' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('contracts.populate_billed_before', { defaultValue: 'Billed before' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('contracts.period_value', { defaultValue: 'Period value' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('contracts.populate_to_date', { defaultValue: 'To date' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <PreviewRow
                    key={row.item.contract_line_id}
                    row={row}
                    raw={pctEdits[row.item.contract_line_id]}
                    editable={editable}
                    currency={previewCurrency}
                    selected={!deselected.has(row.item.contract_line_id)}
                    onToggle={() => toggle(row.item.contract_line_id)}
                    onPct={(value) => setPct(row.item.contract_line_id, value)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </WideModalSection>
    </WideModal>
  );
}

function PreviewRow({
  row,
  raw,
  editable,
  currency,
  selected,
  onToggle,
  onPct,
}: {
  row: PreviewRowFigures;
  raw: string | undefined;
  editable: boolean;
  currency: string;
  selected: boolean;
  onToggle: () => void;
  onPct: (value: string | undefined) => void;
}) {
  const { t } = useTranslation();
  const { item } = row;
  const code = item.contract_line_code || item.contract_line_id.slice(0, 8);
  const observed = toNum(item.observed_pct);
  const money = (amount: number) => (
    <MoneyDisplay amount={amount} currency={currency || undefined} />
  );
  return (
    <>
      <tr className="border-t border-border-light hover:bg-surface-secondary">
        <td className="px-3 py-2">
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            aria-label={t('contracts.populate_include_line', {
              code,
              defaultValue: 'Include line {{code}}',
            })}
            className="h-4 w-4 rounded border-border accent-oe-blue"
          />
        </td>
        <td className="px-3 py-2">
          <div className="font-mono text-xs text-content-secondary">{code}</div>
          {item.contract_line_description && (
            <div className="max-w-[280px] truncate text-content-primary">
              {item.contract_line_description}
            </div>
          )}
          {item.adjusts_contract_line_id && (
            <div className="text-xs text-content-tertiary">
              {t('contracts.populate_adjusts_line', {
                code: item.adjusts_line_code || item.adjusts_contract_line_id.slice(0, 8),
                defaultValue: 'Change order line, billed at the percent of {{code}}',
              })}
            </div>
          )}
        </td>
        <td className="px-3 py-2 text-right">
          {editable ? (
            <div className="flex items-center justify-end gap-1">
              <input
                type="number"
                inputMode="decimal"
                min={0}
                max={100}
                step="0.01"
                value={raw ?? String(observed)}
                onChange={(e) => onPct(e.target.value)}
                aria-label={t('contracts.populate_pct_line', {
                  code,
                  defaultValue: 'Percent complete to date for line {{code}}',
                })}
                aria-invalid={row.invalid || undefined}
                className={`h-8 w-24 rounded border bg-surface-primary px-2 text-right text-sm tabular-nums ${
                  row.invalid ? 'border-semantic-error' : 'border-border'
                }`}
              />
              {row.edited && (
                <button
                  type="button"
                  onClick={() => onPct(undefined)}
                  title={t('contracts.populate_reset_pct', {
                    pct: fmtPercent(observed, 2),
                    defaultValue: 'Back to the measured {{pct}}',
                  })}
                  aria-label={t('contracts.populate_reset_pct', {
                    pct: fmtPercent(observed, 2),
                    defaultValue: 'Back to the measured {{pct}}',
                  })}
                  className="rounded p-1 text-content-tertiary hover:text-content-primary"
                >
                  <RotateCcw size={13} aria-hidden />
                </button>
              )}
            </div>
          ) : (
            fmtPercent(observed, 2)
          )}
        </td>
        <td className="px-3 py-2 text-right text-content-secondary">
          {money(toNum(item.contract_line_value))}
        </td>
        <td className="px-3 py-2 text-right text-content-secondary">{money(row.prior)}</td>
        <td className="px-3 py-2 text-right font-medium" data-testid={`populate-period-${item.contract_line_id}`}>
          {money(row.period)}
        </td>
        <td className="px-3 py-2 text-right" data-testid={`populate-to-date-${item.contract_line_id}`}>
          {money(row.cumulative)}
        </td>
      </tr>
      {(row.invalid || row.regressed || (editable && row.edited)) && (
        <tr>
          <td />
          <td colSpan={6} className="px-3 pb-2 text-xs">
            {row.invalid ? (
              <span className="text-semantic-error" role="alert">
                {t('contracts.populate_pct_invalid', {
                  defaultValue: 'Enter a percent from 0 to 100.',
                })}
              </span>
            ) : row.regressed ? (
              <span className="flex items-center gap-1.5 text-amber-700 dark:text-amber-300" role="status">
                <AlertTriangle size={12} aria-hidden />
                {t('contracts.populate_regressed', {
                  defaultValue:
                    'Below what earlier claims already billed on this line, so this claim bills nothing on it. Check the measurement or the earlier claims.',
                })}
              </span>
            ) : (
              <span className="text-content-tertiary">
                {t('contracts.populate_edited', {
                  pct: fmtPercent(observed, 2),
                  defaultValue: 'Corrected by you; measured on site: {{pct}}',
                })}
              </span>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
