// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Subcontractor-portal payment-application submission form.
 *
 * Mobile-first (375px single column). The subcontractor picks one of their
 * accessible agreements, enters a claimed amount per work package, and the
 * gross / retention / net summary updates live. Retention is shown as an
 * estimate computed from the agreement's retention_percent; the BACKEND
 * recomputes the authoritative figures on submit (the client never drives
 * money). Currency is always the agreement's own currency.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Send, AlertCircle } from 'lucide-react';
import { Button, Card, EmptyState, SkeletonTable } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  listMyPaymentAgreements,
  submitMyPaymentApplication,
  type PortalAgreementSummary,
} from './api';
import { fmtFixed } from '@/shared/lib/formatters';
import { parseDecimalInput, toDecimalPayloadString } from '@/shared/lib/parseDecimal';

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/** Parse a free-typed money string into a Number for the live summary only. */
function toNumber(v: string): number {
  const n = parseDecimalInput(v);
  return n !== null && n > 0 ? n : 0;
}

function money(n: number, currency: string): string {
  const s = fmtFixed(n, 2);
  return currency ? `${currency} ${s}` : s;
}

export function PaymentApplicationForm({
  onDone,
  onCancel,
}: {
  onDone: (newId: string) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const agreementsQ = useQuery({
    queryKey: ['portal', 'payment-agreements'],
    queryFn: () => listMyPaymentAgreements(),
  });

  const agreements = agreementsQ.data?.items ?? [];
  const [agreementId, setAgreementId] = useState('');
  const [periodStart, setPeriodStart] = useState('');
  const [periodEnd, setPeriodEnd] = useState('');
  // work_package_id -> claimed amount (raw string)
  const [claims, setClaims] = useState<Record<string, string>>({});

  const selected: PortalAgreementSummary | undefined = useMemo(
    () => agreements.find((a) => a.id === agreementId),
    [agreements, agreementId],
  );

  const currency = selected?.currency ?? '';
  const retentionPct = selected ? toNumber(selected.retention_percent) : 0;

  const grossTotal = useMemo(
    () => Object.values(claims).reduce((acc, v) => acc + toNumber(v), 0),
    [claims],
  );
  const retentionEst = (grossTotal * retentionPct) / 100;
  const netPayable = grossTotal - retentionEst;

  const submitMut = useMutation({
    mutationFn: () => {
      const lines = (selected?.work_packages ?? [])
        .map((wp) => ({
          work_package_id: wp.id,
          claimed_amount: claims[wp.id]?.trim() ?? '',
        }))
        .filter((l) => toNumber(l.claimed_amount) > 0)
        .map((l) => ({
          work_package_id: l.work_package_id,
          // Send the raw string so the backend Decimal stays exact.
          claimed_amount: toDecimalPayloadString(l.claimed_amount),
        }));
      return submitMyPaymentApplication({
        agreement_id: agreementId,
        period_start: periodStart || null,
        period_end: periodEnd || null,
        lines,
      });
    },
    onSuccess: (created) => {
      addToast({
        type: 'success',
        title: t('payportal.submitted_ok', { defaultValue: 'Payment application submitted' }),
      });
      qc.invalidateQueries({ queryKey: ['portal', 'payment-applications'] });
      onDone(created.id);
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('payportal.submit_failed', {
          defaultValue: 'Could not submit the application',
        }),
        message: err instanceof Error ? err.message : undefined,
      }),
  });

  const canSubmit = !!agreementId && grossTotal > 0 && !submitMut.isPending;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" icon={<ArrowLeft size={14} />} onClick={onCancel}>
          {t('payportal.back_to_list', { defaultValue: 'Back to applications' })}
        </Button>
      </div>

      <h1 className="text-xl font-semibold text-content-primary">
        {t('payportal.form_title', { defaultValue: 'New payment application' })}
      </h1>

      {agreementsQ.isLoading ? (
        <Card padding="md">
          <SkeletonTable rows={4} columns={2} />
        </Card>
      ) : agreementsQ.error ? (
        <Card padding="none">
          <EmptyState
            icon={<AlertCircle size={22} />}
            title={t('payportal.load_failed', { defaultValue: 'Could not load' })}
            description={agreementsQ.error instanceof Error ? agreementsQ.error.message : ''}
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => void agreementsQ.refetch(),
            }}
          />
        </Card>
      ) : agreements.length === 0 ? (
        <Card padding="none">
          <EmptyState
            icon={<AlertCircle size={22} />}
            title={t('payportal.no_agreements', {
              defaultValue: 'You have no agreements you can claim against yet.',
            })}
          />
        </Card>
      ) : (
        <>
          <Card padding="md" className="space-y-4">
            <div>
              <label className="mb-1 block text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                {t('payportal.agreement', { defaultValue: 'Agreement' })}
              </label>
              <select
                value={agreementId}
                onChange={(e) => {
                  setAgreementId(e.target.value);
                  setClaims({});
                }}
                className={inputCls}
              >
                <option value="">
                  {t('payportal.select_agreement', { defaultValue: 'Select an agreement' })}
                </option>
                {agreements.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.title} {a.currency ? `(${a.currency})` : ''}
                  </option>
                ))}
              </select>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                  {t('payportal.period_start', { defaultValue: 'Period start' })}
                </label>
                <input
                  type="date"
                  value={periodStart}
                  onChange={(e) => setPeriodStart(e.target.value)}
                  className={inputCls}
                />
              </div>
              <div>
                <label className="mb-1 block text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                  {t('payportal.period_end', { defaultValue: 'Period end' })}
                </label>
                <input
                  type="date"
                  value={periodEnd}
                  onChange={(e) => setPeriodEnd(e.target.value)}
                  className={inputCls}
                />
              </div>
            </div>
          </Card>

          {selected ? (
            <Card padding="md">
              {selected.work_packages.length === 0 ? (
                <p className="py-4 text-center text-sm text-content-secondary">
                  {t('payportal.no_work_packages', {
                    defaultValue: 'This agreement has no work packages to claim against.',
                  })}
                </p>
              ) : (
                <ul className="space-y-3">
                  {selected.work_packages.map((wp) => (
                    <li
                      key={wp.id}
                      className="rounded-lg border border-border-light p-3 sm:flex sm:items-center sm:gap-4"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-content-primary">
                          {wp.name}
                        </p>
                        <p className="text-2xs text-content-tertiary">
                          {t('payportal.planned', { defaultValue: 'Planned' })}:{' '}
                          {money(toNumber(wp.planned_value), currency)}
                        </p>
                      </div>
                      <div className="mt-2 sm:mt-0 sm:w-44">
                        <label className="mb-1 block text-2xs uppercase tracking-wide text-content-tertiary">
                          {t('payportal.claimed', { defaultValue: 'Claimed this period' })}
                        </label>
                        <input
                          type="text"
                          inputMode="decimal"
                          value={claims[wp.id] ?? ''}
                          onChange={(e) =>
                            setClaims((prev) => ({ ...prev, [wp.id]: e.target.value }))
                          }
                          placeholder="0.00"
                          className={inputCls}
                        />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          ) : null}

          {/* Live summary — backend recomputes the authoritative figures. */}
          <Card padding="md" className="space-y-2">
            <p className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
              {t('payportal.summary', { defaultValue: 'Summary' })}
            </p>
            <SummaryRow
              label={t('payportal.gross_total', { defaultValue: 'Gross total' })}
              value={money(grossTotal, currency)}
            />
            <SummaryRow
              label={t('payportal.retention_est', {
                defaultValue: 'Retention ({{percent}}%)',
                percent: retentionPct,
              })}
              value={`- ${money(retentionEst, currency)}`}
            />
            <div className="border-t border-border-light pt-2">
              <SummaryRow
                strong
                label={t('payportal.net_payable', { defaultValue: 'Net payable' })}
                value={money(netPayable, currency)}
              />
            </div>
          </Card>

          {/* Sticky submit on mobile */}
          <div className="sticky bottom-0 -mx-1 bg-surface-secondary/80 px-1 py-3 backdrop-blur sm:static sm:bg-transparent sm:p-0">
            <div className="flex gap-2">
              <Button variant="ghost" onClick={onCancel} disabled={submitMut.isPending}>
                {t('payportal.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                className="flex-1 sm:flex-none"
                variant="primary"
                icon={<Send size={14} />}
                disabled={!canSubmit}
                loading={submitMut.isPending}
                onClick={() => {
                  if (grossTotal <= 0) {
                    addToast({
                      type: 'error',
                      title: t('payportal.enter_one_amount', {
                        defaultValue: 'Enter a claimed amount on at least one work package.',
                      }),
                    });
                    return;
                  }
                  submitMut.mutate();
                }}
              >
                {submitMut.isPending
                  ? t('payportal.submitting', { defaultValue: 'Submitting…' })
                  : t('payportal.submit', { defaultValue: 'Submit application' })}
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function SummaryRow({
  label,
  value,
  strong,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className={strong ? 'font-semibold text-content-primary' : 'text-content-secondary'}>
        {label}
      </span>
      <span
        className={strong ? 'font-semibold text-content-primary' : 'text-content-primary'}
      >
        {value}
      </span>
    </div>
  );
}
