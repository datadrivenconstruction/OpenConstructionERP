// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// RetainagePanel - PO retainage dialog (Gap F).
//
// Opens from a PO row's "Retainage" action and surfaces:
//   * three summary tiles (retention %, withheld, held),
//   * the retainage-release audit log (date, amount, reason),
//   * a release form (MANAGER only) that POSTs
//     /v1/procurement/{po_id}/release-retainage/ and refreshes the log.
//
// Money is shown in the PO's own currency; the backend never blends
// currencies, so this panel is single-currency by construction.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { invalidateFinanceFigures } from '@/features/finance/financeQueryKeys';
import { Loader2, AlertTriangle, Percent, PiggyBank, Lock } from 'lucide-react';
import { WideModal, Badge, Button, EmptyState } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { listPORetainageReleases, releasePORetainage } from './api';
import { fmtPercent, fmtFixed } from '@/shared/lib/formatters';

interface RetainagePanelProps {
  open: boolean;
  onClose: () => void;
  poId: string;
  poNumber: string;
  currency: string;
  /** Computed withheld total (Decimal string) from the PO response. */
  retainageAmount: string;
  /** Currently-held balance (Decimal string) from the PO response. */
  retainageHeld: string;
  retentionPercent: string;
  /** Whether the current user may release retainage (MANAGER+). */
  canRelease: boolean;
}

export function RetainagePanel({
  open,
  onClose,
  poId,
  poNumber,
  currency,
  retainageAmount,
  retainageHeld,
  retentionPercent,
  canRelease,
}: RetainagePanelProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [amount, setAmount] = useState('');
  const [reason, setReason] = useState('');

  const {
    data: releases,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['procurement-retainage-releases', poId],
    queryFn: () => listPORetainageReleases(poId),
    enabled: open && Boolean(poId),
  });

  const releaseMut = useMutation({
    mutationFn: () =>
      releasePORetainage(poId, {
        amount: amount.trim(),
        reason: reason.trim() || undefined,
      }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('procurement.retainage_released', {
          defaultValue: 'Retainage released',
        }),
      });
      setAmount('');
      setReason('');
      // Refresh the release log AND the PO list so the held badge updates.
      void queryClient.invalidateQueries({
        queryKey: ['procurement-retainage-releases', poId],
      });
      void queryClient.invalidateQueries({ queryKey: ['procurement-po'] });
      void invalidateFinanceFigures(queryClient);
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      }),
  });

  const heldNum = Number(retainageHeld) || 0;
  const amountNum = Number(amount) || 0;
  const amountInvalid =
    amount.trim() === '' || amountNum <= 0 || amountNum > heldNum;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={t('procurement.retainage_title', {
        defaultValue: 'Retainage - {{po}}',
        po: poNumber,
      })}
      subtitle={t('procurement.retainage_subtitle', {
        defaultValue: 'Withheld retention and release history',
      })}
      size="lg"
    >
      <div className="space-y-6">
        {/* ── Summary tiles ──────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <SummaryTile
            icon={<Percent size={16} />}
            label={t('procurement.retainage_percent', {
              defaultValue: 'Retention',
            })}
            value={fmtPercent(Number(retentionPercent), 2)}
          />
          <SummaryTile
            icon={<PiggyBank size={16} />}
            label={t('procurement.retainage_withheld', {
              defaultValue: 'Withheld',
            })}
            value={
              currency ? (
                <MoneyDisplay amount={retainageAmount} currency={currency} />
              ) : (
                retainageAmount
              )
            }
          />
          <SummaryTile
            icon={<Lock size={16} />}
            label={t('procurement.retainage_held', { defaultValue: 'Held' })}
            value={
              currency ? (
                <MoneyDisplay amount={retainageHeld} currency={currency} />
              ) : (
                retainageHeld
              )
            }
            tone="amber"
          />
        </div>

        {/* ── Release form (MANAGER only) ────────────────────────────────── */}
        {canRelease && (
          <form
            className="rounded-lg border border-border bg-surface-secondary/40 p-4 space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (!amountInvalid) releaseMut.mutate();
            }}
          >
            <div className="text-sm font-semibold text-content-primary">
              {t('procurement.retainage_release_heading', {
                defaultValue: 'Release retainage',
              })}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <label className="block">
                <span className="text-2xs uppercase tracking-wider font-medium text-content-tertiary">
                  {t('procurement.retainage_amount_label', {
                    defaultValue: 'Amount',
                  })}
                </span>
                <input
                  type="number"
                  inputMode="decimal"
                  min="0"
                  step="0.01"
                  max={heldNum}
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  className="mt-1 w-full rounded-md border border-border bg-surface-primary px-3 py-2 text-sm tabular-nums focus:border-oe-blue focus:outline-none"
                  placeholder="0.00"
                  aria-label={t('procurement.retainage_amount_label', {
                    defaultValue: 'Amount',
                  })}
                />
              </label>
              <label className="block">
                <span className="text-2xs uppercase tracking-wider font-medium text-content-tertiary">
                  {t('procurement.retainage_reason_label', {
                    defaultValue: 'Reason (optional)',
                  })}
                </span>
                <input
                  type="text"
                  maxLength={255}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  className="mt-1 w-full rounded-md border border-border bg-surface-primary px-3 py-2 text-sm focus:border-oe-blue focus:outline-none"
                  placeholder={t('procurement.retainage_reason_placeholder', {
                    defaultValue: 'e.g. Defects liability period ended',
                  })}
                  aria-label={t('procurement.retainage_reason_label', {
                    defaultValue: 'Reason (optional)',
                  })}
                />
              </label>
            </div>
            {amount.trim() !== '' && amountNum > heldNum && (
              <p className="text-xs text-rose-600 dark:text-rose-400">
                {t('procurement.retainage_exceeds_held', {
                  defaultValue:
                    'Amount cannot exceed the held balance ({{held}}).',
                  held: retainageHeld,
                })}
              </p>
            )}
            <div className="flex justify-end">
              <Button
                type="submit"
                variant="primary"
                size="sm"
                disabled={amountInvalid || releaseMut.isPending}
              >
                {releaseMut.isPending && (
                  <Loader2 size={14} className="animate-spin mr-1.5" />
                )}
                {t('procurement.retainage_release_action', {
                  defaultValue: 'Release',
                })}
              </Button>
            </div>
          </form>
        )}

        {/* ── Release log ────────────────────────────────────────────────── */}
        <div>
          <div className="text-sm font-semibold text-content-primary mb-2">
            {t('procurement.retainage_log_heading', {
              defaultValue: 'Release history',
            })}
          </div>

          {isLoading && (
            <div className="flex items-center justify-center py-8 text-content-tertiary">
              <Loader2 size={18} className="animate-spin mr-2" />
              {t('common.loading', { defaultValue: 'Loading...' })}
            </div>
          )}

          {isError && !isLoading && (
            <EmptyState
              icon={<AlertTriangle size={22} strokeWidth={1.5} />}
              title={t('common.error', { defaultValue: 'Error' })}
              description={t('procurement.retainage_log_error', {
                defaultValue: 'Failed to load release history.',
              })}
            />
          )}

          {releases && !isLoading && releases.items.length === 0 && (
            <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-4 py-6 text-center text-sm text-content-tertiary">
              {t('procurement.retainage_log_empty', {
                defaultValue: 'No retainage has been released yet.',
              })}
            </div>
          )}

          {releases && releases.items.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead className="bg-surface-secondary text-content-tertiary">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">
                      {t('procurement.retainage_col_date', {
                        defaultValue: 'Date',
                      })}
                    </th>
                    <th className="px-3 py-2 text-right font-medium">
                      {t('procurement.retainage_col_amount', {
                        defaultValue: 'Amount',
                      })}
                    </th>
                    <th className="px-3 py-2 text-left font-medium">
                      {t('procurement.retainage_col_reason', {
                        defaultValue: 'Reason',
                      })}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {releases.items.map((r) => (
                    <tr key={r.id} className="border-t border-border-light">
                      <td className="px-3 py-2 text-content-secondary">
                        <DateDisplay value={r.release_date} />
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {currency ? (
                          <MoneyDisplay
                            amount={r.release_amount}
                            currency={currency}
                          />
                        ) : (
                          r.release_amount
                        )}
                      </td>
                      <td className="px-3 py-2 text-content-secondary">
                        {r.release_reason || (
                          <span className="text-content-tertiary">-</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </WideModal>
  );
}

/* ── Subcomponents ─────────────────────────────────────────────────────── */

function SummaryTile({
  icon,
  label,
  value,
  tone = 'neutral',
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  tone?: 'neutral' | 'amber';
}) {
  const bg =
    tone === 'amber'
      ? 'bg-amber-50 dark:bg-amber-950/20 border-amber-200 dark:border-amber-900'
      : 'bg-surface-primary border-border';
  const text =
    tone === 'amber'
      ? 'text-amber-700 dark:text-amber-400'
      : 'text-content-primary';
  return (
    <div className={`rounded-lg border px-4 py-3 ${bg}`}>
      <div className="flex items-center gap-2 text-2xs uppercase tracking-wider font-medium text-content-tertiary">
        {icon}
        <span>{label}</span>
      </div>
      <div className={`mt-1 text-base font-semibold tabular-nums ${text}`}>
        {value}
      </div>
    </div>
  );
}

/* ── Amber list-row badge shown when a PO carries retention > 0 ─────────── */

export function RetainageBadge({ percent }: { percent?: string }) {
  const { t } = useTranslation();
  const pct = Number(percent) || 0;
  if (pct <= 0) return null;
  return (
    <Badge variant="warning" size="sm">
      {t('procurement.retainage_badge', {
        defaultValue: 'Retainage {{pct}}%',
        pct: fmtFixed(pct, pct % 1 === 0 ? 0 : 2),
      })}
    </Badge>
  );
}
