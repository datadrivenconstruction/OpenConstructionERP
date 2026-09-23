// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// AIAApplicationPanel — AIA G702 (Application and Certificate for Payment)
// summary + G703 (Continuation Sheet) grid for one progress claim.
//
// AIA G702/G703 is the US progress-billing format, also used in Canada and
// Australia. This panel renders ONLY for AIA-eligible projects: the parent
// page gates it on `project.is_aia_eligible` (computed server-side from the
// project country), and the backend independently raises 404 for any other
// market, so the format is never forced on, say, a DACH or UK project.
//
// The panel is an additive presentation layer over the existing progress
// claim: it does not move money or change claim state. It reads the AIA view,
// shows the G702 nine-line summary, the G703 schedule-of-values continuation
// (responsive: a table on desktop, stacked cards on mobile), the architect /
// owner certification block, and a "Download G702/G703 PDF" action.

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { FileText, Download } from 'lucide-react';

import { Button, Card, RecoveryCard, SkeletonTable } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  getAiaApplication,
  downloadAiaApplicationPdf,
  type AIAApplication,
} from './api';
import { fmtPercent } from '@/shared/lib/formatters';

function toNum(v: string | number | null | undefined): number {
  if (v === null || v === undefined) return 0;
  const n = typeof v === 'string' ? Number(v) : v;
  return Number.isFinite(n) ? n : 0;
}

interface AIAApplicationPanelProps {
  claimId: string;
  currency: string;
}

export function AIAApplicationPanel({ claimId, currency }: AIAApplicationPanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const appQ = useQuery<AIAApplication>({
    queryKey: ['contracts', 'aia-application', claimId],
    queryFn: () => getAiaApplication(claimId),
    enabled: !!claimId,
  });

  const handleDownload = async () => {
    try {
      await downloadAiaApplicationPdf(claimId, appQ.data?.application_number);
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    }
  };

  const money = (value: string | number | null | undefined) => (
    <MoneyDisplay amount={toNum(value)} currency={currency || undefined} />
  );
  // Scheduled value, percent and balance are null on the row for money no
  // schedule line carries: there is nothing to measure them against. An empty
  // cell says there is no answer, where money() and toNum() would print a zero.
  const moneyOrBlank = (value: string | null | undefined) =>
    value === null || value === undefined ? null : money(value);
  const percentOrBlank = (value: string | null | undefined) =>
    value === null || value === undefined ? '' : fmtPercent(toNum(value));

  return (
    <Card padding="sm" data-testid="aia-application-panel">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <FileText size={16} className="text-oe-blue" />
          <h2 className="text-sm font-semibold text-content-primary">
            {t('contracts.aia.title', {
              defaultValue: 'AIA G702 / G703 Application for Payment',
            })}
          </h2>
        </div>
        <Button
          variant="secondary"
          icon={<Download size={14} />}
          onClick={() => void handleDownload()}
          disabled={appQ.isLoading || appQ.isError}
          data-testid="aia-download-pdf"
        >
          {t('contracts.aia.download_pdf', { defaultValue: 'Download G702/G703 PDF' })}
        </Button>
      </div>

      {appQ.isLoading && <SkeletonTable rows={5} columns={4} />}

      {appQ.isError && (
        <RecoveryCard error={appQ.error} onRetry={() => void appQ.refetch()} />
      )}

      {appQ.data && (
        <div className="space-y-5">
          {/* ── G702 summary (nine standard lines) ───────────────────── */}
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-secondary">
              {t('contracts.aia.g702', { defaultValue: 'G702 - Certificate summary' })}
            </p>
            <dl className="divide-y divide-border-light rounded-lg border border-border-light">
              <SummaryRow
                label={t('contracts.aia.original_contract_sum', {
                  defaultValue: 'Original contract sum',
                })}
              >
                {money(appQ.data.summary.original_contract_sum)}
              </SummaryRow>
              <SummaryRow
                label={t('contracts.aia.change_orders_net', {
                  defaultValue: 'Net change by change orders',
                })}
              >
                {money(appQ.data.summary.change_orders_net)}
              </SummaryRow>
              <SummaryRow
                label={t('contracts.aia.contract_sum_to_date', {
                  defaultValue: 'Contract sum to date',
                })}
              >
                {money(appQ.data.summary.contract_sum_to_date)}
              </SummaryRow>
              <SummaryRow
                label={t('contracts.aia.total_completed_stored', {
                  defaultValue: 'Total completed and stored to date',
                })}
              >
                {money(appQ.data.summary.total_completed_stored)}
              </SummaryRow>
              <SummaryRow
                label={t('contracts.aia.retainage', { defaultValue: 'Retainage' })}
              >
                {money(appQ.data.summary.retainage)}
              </SummaryRow>
              {/* Lines 5a and 5b. The form asks for retainage split between
                  work in place and materials on site, and the two together are
                  line 5 above. Shown only when the server sends the split. */}
              {appQ.data.summary.retainage_completed_work !== undefined && (
                <SummaryRow
                  label={t('contracts.aia.retainage_completed_work', {
                    defaultValue: 'Retainage on completed work',
                  })}
                >
                  {money(appQ.data.summary.retainage_completed_work)}
                </SummaryRow>
              )}
              {appQ.data.summary.retainage_stored_materials !== undefined && (
                <SummaryRow
                  label={t('contracts.aia.retainage_stored_materials', {
                    defaultValue: 'Retainage on stored material',
                  })}
                >
                  {money(appQ.data.summary.retainage_stored_materials)}
                </SummaryRow>
              )}
              <SummaryRow
                label={t('contracts.aia.earned_less_retainage', {
                  defaultValue: 'Total earned less retainage',
                })}
              >
                {money(appQ.data.summary.total_earned_less_retainage)}
              </SummaryRow>
              <SummaryRow
                label={t('contracts.aia.previous_certificates', {
                  defaultValue: 'Less previous certificates for payment',
                })}
              >
                {money(appQ.data.summary.previous_certificates_total)}
              </SummaryRow>
              <SummaryRow
                label={t('contracts.aia.current_payment_due', {
                  defaultValue: 'Current payment due',
                })}
                emphasis
              >
                {money(appQ.data.summary.current_payment_due)}
              </SummaryRow>
              <SummaryRow
                label={t('contracts.aia.balance_to_finish', {
                  defaultValue: 'Balance to finish including retainage',
                })}
              >
                {money(appQ.data.summary.balance_to_finish)}
              </SummaryRow>
            </dl>
          </div>

          {/* ── G703 continuation sheet ──────────────────────────────── */}
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-secondary">
              {t('contracts.aia.g703', { defaultValue: 'G703 - Continuation sheet' })}
              <span className="ml-2 normal-case text-content-tertiary">
                ({appQ.data.lines.length})
              </span>
            </p>

            {/* Desktop / tablet: full table */}
            <div className="hidden overflow-x-auto rounded-lg border border-border-light sm:block">
              <table className="w-full text-right text-xs">
                <thead className="bg-surface-secondary text-[10px] uppercase tracking-wide text-content-tertiary">
                  <tr>
                    <th className="px-2 py-2 text-left">
                      {t('contracts.aia.col_item', { defaultValue: 'Item' })}
                    </th>
                    <th className="px-2 py-2 text-left">
                      {t('contracts.aia.col_description', { defaultValue: 'Description' })}
                    </th>
                    <th className="px-2 py-2">
                      {t('contracts.aia.col_scheduled', { defaultValue: 'Scheduled' })}
                    </th>
                    <th className="px-2 py-2">
                      {t('contracts.aia.col_previous', { defaultValue: 'Previous' })}
                    </th>
                    <th className="px-2 py-2">
                      {t('contracts.aia.col_this_period', { defaultValue: 'This period' })}
                    </th>
                    <th className="px-2 py-2">
                      {t('contracts.aia.col_stored', { defaultValue: 'Stored' })}
                    </th>
                    <th className="px-2 py-2">
                      {t('contracts.aia.col_total', { defaultValue: 'Total' })}
                    </th>
                    <th className="px-2 py-2">%</th>
                    <th className="px-2 py-2">
                      {t('contracts.aia.col_balance', { defaultValue: 'Balance' })}
                    </th>
                    <th className="px-2 py-2">
                      {t('contracts.aia.col_retainage', { defaultValue: 'Retainage' })}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-light">
                  {appQ.data.lines.map((ln) => (
                    <tr key={`${ln.line_number}-${ln.item_number}`}>
                      <td className="px-2 py-1.5 text-left font-medium text-content-primary">
                        {ln.item_number}
                      </td>
                      <td className="max-w-[16rem] truncate px-2 py-1.5 text-left text-content-secondary">
                        {ln.description}
                      </td>
                      <td className="px-2 py-1.5">{moneyOrBlank(ln.scheduled_value)}</td>
                      <td className="px-2 py-1.5">{money(ln.previous_value)}</td>
                      <td className="px-2 py-1.5">{money(ln.this_period_value)}</td>
                      <td className="px-2 py-1.5">{money(ln.materials_stored)}</td>
                      <td className="px-2 py-1.5">{money(ln.total_completed_stored)}</td>
                      <td className="px-2 py-1.5 text-content-tertiary">
                        {percentOrBlank(ln.percent_complete)}
                      </td>
                      <td className="px-2 py-1.5">{moneyOrBlank(ln.balance_to_finish)}</td>
                      <td className="px-2 py-1.5">{money(ln.retainage)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Mobile: stacked cards */}
            <div className="space-y-2 sm:hidden">
              {appQ.data.lines.map((ln) => (
                <div
                  key={`m-${ln.line_number}-${ln.item_number}`}
                  className="rounded-lg border border-border-light bg-surface-secondary p-3"
                >
                  <div className="mb-1 flex items-baseline justify-between gap-2">
                    <span className="text-xs font-semibold text-content-primary">
                      {ln.item_number}
                    </span>
                    <span className="text-[10px] text-content-tertiary">
                      {percentOrBlank(ln.percent_complete)}
                    </span>
                  </div>
                  <p className="mb-2 text-xs text-content-secondary">{ln.description}</p>
                  <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                    <MobileCell
                      label={t('contracts.aia.col_scheduled', { defaultValue: 'Scheduled' })}
                    >
                      {moneyOrBlank(ln.scheduled_value)}
                    </MobileCell>
                    <MobileCell
                      label={t('contracts.aia.col_total', { defaultValue: 'Total' })}
                    >
                      {money(ln.total_completed_stored)}
                    </MobileCell>
                    <MobileCell
                      label={t('contracts.aia.col_this_period', {
                        defaultValue: 'This period',
                      })}
                    >
                      {money(ln.this_period_value)}
                    </MobileCell>
                    <MobileCell
                      label={t('contracts.aia.col_balance', { defaultValue: 'Balance' })}
                    >
                      {moneyOrBlank(ln.balance_to_finish)}
                    </MobileCell>
                    <MobileCell
                      label={t('contracts.aia.col_retainage', { defaultValue: 'Retainage' })}
                    >
                      {money(ln.retainage)}
                    </MobileCell>
                  </dl>
                </div>
              ))}
            </div>
          </div>

          {/* ── Certification status ─────────────────────────────────── */}
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-secondary">
              {t('contracts.aia.certification', { defaultValue: 'Certification' })}
            </p>
            <dl className="divide-y divide-border-light rounded-lg border border-border-light">
              <SummaryRow
                label={t('contracts.aia.architect_certified', {
                  defaultValue: 'Architect certified',
                })}
              >
                {appQ.data.certification.architect_certified_by ? (
                  <span className="text-content-primary">
                    {appQ.data.certification.architect_certified_by}
                    {appQ.data.certification.architect_certified_at
                      ? ` · ${appQ.data.certification.architect_certified_at}`
                      : ''}
                  </span>
                ) : (
                  <span className="text-content-tertiary">
                    {t('contracts.aia.not_certified', { defaultValue: 'Not yet certified' })}
                  </span>
                )}
              </SummaryRow>
              <SummaryRow
                label={t('contracts.aia.owner_certified', {
                  defaultValue: 'Owner certified',
                })}
              >
                {appQ.data.certification.owner_certified_by ? (
                  <span className="text-content-primary">
                    {appQ.data.certification.owner_certified_by}
                    {appQ.data.certification.owner_certified_at
                      ? ` · ${appQ.data.certification.owner_certified_at}`
                      : ''}
                  </span>
                ) : (
                  <span className="text-content-tertiary">
                    {t('contracts.aia.not_certified', { defaultValue: 'Not yet certified' })}
                  </span>
                )}
              </SummaryRow>
            </dl>
          </div>
        </div>
      )}
    </Card>
  );
}

function SummaryRow({
  label,
  emphasis,
  children,
}: {
  label: React.ReactNode;
  emphasis?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3 px-3 py-2">
      <dt
        className={
          emphasis
            ? 'text-sm font-semibold text-content-primary'
            : 'text-sm text-content-secondary'
        }
      >
        {label}
      </dt>
      <dd
        className={
          emphasis
            ? 'text-sm font-semibold text-content-primary'
            : 'text-sm text-content-primary'
        }
      >
        {children}
      </dd>
    </div>
  );
}

function MobileCell({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wide text-content-tertiary">{label}</dt>
      <dd className="font-medium text-content-primary">{children}</dd>
    </div>
  );
}
