// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { Button, Card } from '@/shared/ui';
import { claimKey } from './claimQueries';
import { loadLenderPreparation } from './lenderDrawSources';
import type { LenderPreparation, LenderPreparationContext } from './lenderDrawPreview';

/** Remount on navigation: a previous claim's open draft must not follow the reader. */
export function LenderDrawPreviewPanel(props: LenderPreparationContext) {
  return <PreparationPanel key={`${props.projectId}:${props.contractId}:${props.claimId}`} {...props} />;
}

function PreparationPanel(context: LenderPreparationContext) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const refreshLock = useRef(false);
  const queryClient = useQueryClient();
  const queryKey = [...claimKey(context.claimId), 'lender-preparation', context.contractId, context.projectId];
  const query = useQuery({
    queryKey,
    queryFn: () => loadLenderPreparation(context),
    enabled: open,
    staleTime: 0,
    placeholderData: undefined,
  });
  const draft = query.data;
  const ready = !refreshing && query.isSuccess && query.fetchStatus === 'idle' &&
    draft?.application.claim_id === context.claimId &&
    draft.application.contract_id === context.contractId &&
    draft.application.project_id === context.projectId;

  async function refresh() {
    if (refreshLock.current) return;
    // Query notifications are batched. Block export in this click handler,
    // before a notification can leave the previous draft briefly enabled.
    refreshLock.current = true;
    setRefreshing(true);
    try {
      await query.refetch();
    } finally {
      refreshLock.current = false;
      setRefreshing(false);
    }
  }

  function download() {
    if (refreshLock.current || !ready || !draft) return;
    // Another panel may invalidate or replace this cache entry before React
    // receives its batched notification. Check the live snapshot as well.
    const current = queryClient.getQueryState<LenderPreparation>(queryKey);
    if (current?.status !== 'success' || current.fetchStatus !== 'idle' || current.data !== draft) return;
    const blob = new Blob([JSON.stringify(draft, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `lender-preparation-${context.claimId}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <Card padding="sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">
          {t('contracts.lender_preparation.title', { defaultValue: 'Draft lender preparation' })}
        </h2>
        <Button variant="secondary" onClick={() => setOpen(!open)}>
          {open ? t('common.close', { defaultValue: 'Close' }) : t('common.view', { defaultValue: 'View' })}
        </Button>
      </div>
      {open && (
        <div className="mt-3 space-y-3 text-sm">
          <p>{t('contracts.lender_preparation.notice', {
            defaultValue: 'Read-only working copy. This is not a lender submission, certification or disbursement. Source records are read separately and may change.',
          })}</p>
          <p className="text-content-secondary">{t('contracts.lender_preparation.missing', {
            defaultValue: 'Not included: loan facility, lender approval, stored-material evidence and the contract-specific change-order log.',
          })}</p>
          {!ready && !query.isError && <p role="status">{t('common.loading', { defaultValue: 'Loading...' })}</p>}
          {query.isError && <p role="alert">{t('contracts.lender_preparation.error', {
            defaultValue: 'The payment application could not be loaded. Refresh to try again.',
          })}</p>}
          {ready && draft && (
            <>
              <p>{draft.application.application_number}: {draft.application.period_start ?? '—'} — {draft.application.period_end ?? '—'}</p>
              <p>{t('common.status', { defaultValue: 'Status' })}: {t(`contracts.claim_status_${draft.application.claim_status}`, { defaultValue: draft.application.claim_status })}</p>
              <dl className="grid gap-2 sm:grid-cols-2">
                {([
                  ['contracts.aia.original_contract_sum', 'Original contract sum', draft.application.summary.original_contract_sum],
                  ['contracts.aia.change_orders_net', 'Net change by change orders', draft.application.summary.change_orders_net],
                  ['contracts.aia.previous_certificates', 'Less previous certificates for payment', draft.application.summary.previous_certificates_total],
                  ['contracts.aia.retainage', 'Retainage', draft.application.summary.retainage],
                  ['contracts.aia.current_payment_due', 'Current payment due', draft.application.summary.current_payment_due],
                ] as const).map(([key, label, amount]) => (
                  <div key={key}>
                    <dt className="text-content-secondary">{t(key, { defaultValue: label })}</dt>
                    <dd dir="ltr">{draft.application.currency} {amount}</dd>
                  </div>
                ))}
                <div>
                  <dt className="text-content-secondary">{t('contracts.lender_preparation.certified', { defaultValue: 'Recorded certified amount' })}</dt>
                  <dd dir="ltr">{draft.application.certification.certified_amount == null
                    ? t('common.not_set', { defaultValue: 'Not set' })
                    : `${draft.application.currency} ${draft.application.certification.certified_amount}`}</dd>
                </div>
              </dl>
              {draft.application.summary.previous_certificates_basis === 'reconstructed' && <p role="note">
                {t('contracts.claim_validation.reconstructed', {
                  defaultValue: 'Previous certified amounts are rebuilt from earlier claims because the previous claim stores no certified totals yet. Check them against what was actually certified.',
                })}
              </p>}
              <ul className="space-y-1">
                {([
                  ['contracts.lender_preparation.subcontractors', 'Subcontractor payment applications', draft.subcontractors],
                  ['contracts.lender_preparation.documents', 'Contract document references', draft.contract_documents],
                  ['contracts.lender_preparation.waivers', 'Claim waiver references', draft.claim_waivers],
                ] as const).map(([key, label, source]) => (
                  <li key={key}>
                    {t(key, { defaultValue: label })}: {source.status === 'available'
                      ? t('contracts.lender_preparation.loaded', {
                        count: Array.isArray(source.data) ? source.data.length : source.data.included.length,
                        defaultValue: '{{count}} recorded; not independently verified',
                      })
                      : t('contracts.lender_preparation.unavailable', { defaultValue: 'Unavailable; omitted from this draft' })}
                  </li>
                ))}
              </ul>
              {draft.subcontractors.status === 'available' && (
                <>
                  {draft.subcontractors.data.skipped_foreign_currency > 0 && <p role="note">
                    {t('subcontractors.rollup_hint_currency', {
                      count: draft.subcontractors.data.skipped_foreign_currency,
                      defaultValue: '{{count}} pay application line(s) left out: a different currency than this claim (never blended).',
                    })}
                  </p>}
                  {draft.subcontractors.data.period_matching === 'explicit_only' && <p role="note">
                    {t('contracts.lender_preparation.no_period', {
                      defaultValue: 'This claim has no period dates. Subcontractor payment applications are not matched by date.',
                    })}
                  </p>}
                  <p>{t('contracts.lender_preparation.findings', { defaultValue: 'Recorded certificate findings' })}: {draft.subcontractors.data.included.reduce(
                    (count, item) => count + item.certificate_findings.length + (item.payment_date_findings?.length ?? 0), 0,
                  )}</p>
                </>
              )}
            </>
          )}
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" disabled={refreshing || query.fetchStatus !== 'idle'} onClick={() => void refresh()}>
              {t('common.refresh', { defaultValue: 'Refresh' })}
            </Button>
            <Button disabled={!ready} onClick={download}>
              {t('contracts.lender_preparation.download', { defaultValue: 'Download draft JSON' })}
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
