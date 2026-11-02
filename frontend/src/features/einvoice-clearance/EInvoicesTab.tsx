// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Finance > E-invoices: outbound documents of the project, nearest deadline
 * first, with status / country / due-soon filters and the consolidated wizard
 * for markets that group B2C sales.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Badge, Button, Card, EmptyState, SkeletonTable } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { statusVariant } from './documentStatus';
import { getDocumentsOverview } from './lifecycleApi';
import { deadlineVariant, formatDuration, isDueSoon } from './lifecycleView';
import { ConsolidatedModal } from './ConsolidatedModal';
import { MARKET_SETTINGS_PATH } from './EInvoiceCard';
import { useEInvoiceMarkets } from './useEInvoiceMarkets';

export function EInvoicesTab({ projectId }: { projectId: string }) {
  const { t, i18n } = useTranslation();
  const markets = useEInvoiceMarkets();
  const [status, setStatus] = useState('');
  const [country, setCountry] = useState('');
  const [dueSoon, setDueSoon] = useState(false);
  const [search, setSearch] = useState('');
  const [consolidating, setConsolidating] = useState(false);

  const q = useQuery({
    queryKey: ['einvoice-clearance', 'overview', projectId],
    queryFn: () => getDocumentsOverview(projectId),
  });
  const rows = useMemo(
    () =>
      (q.data ?? []).filter(
        (r) =>
          (!status || r.status === status) &&
          (!country || r.country === country) &&
          (!dueSoon || isDueSoon(r.deadline)) &&
          (!search || `${r.invoice_number} ${r.buyer_name}`.toLowerCase().includes(search.toLowerCase())),
      ),
    [q.data, status, country, dueSoon, search],
  );
  const grouping = markets.rows.find((r) => r.has_consolidation && r.profile_id);
  const statuses = ['draft', 'validated', 'submitted', 'cleared', 'reported', 'delivered', 'rejected', 'cancelled'];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={t('common.status', { defaultValue: 'Status' })}
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-sm"
        >
          <option value="">{t('common.all_statuses', { defaultValue: 'All statuses' })}</option>
          {statuses.map((s) => (
            <option key={s} value={s}>
              {t(`einvoice.status.${s}`, { defaultValue: s })}
            </option>
          ))}
        </select>
        <select
          aria-label={t('einvoice.list.country', { defaultValue: 'Country' })}
          value={country}
          onChange={(e) => setCountry(e.target.value)}
          className="rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-sm"
        >
          <option value="">{t('einvoice.list.allCountries', { defaultValue: 'All countries' })}</option>
          {markets.rows.map((m) => (
            <option key={m.country} value={m.country}>
              {m.country} · {m.platform}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={dueSoon} onChange={(e) => setDueSoon(e.target.checked)} />
          {t('einvoice.list.dueSoon', { defaultValue: 'Due soon' })}
        </label>
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('common.search', { defaultValue: 'Search' })}
          className="rounded-lg border border-border-light bg-surface-primary px-2 py-1.5 text-sm"
        />
        <div className="ms-auto flex gap-2">
          <Link to={MARKET_SETTINGS_PATH} className="text-xs underline self-center">
            {t('einvoice.setup.linkFromFinance', { defaultValue: 'Set up in Market & standards' })}
          </Link>
          {grouping?.profile_id && (
            <Button size="sm" onClick={() => setConsolidating(true)}>
              {t('einvoice.consolidated.open', { defaultValue: 'Create consolidated…' })}
            </Button>
          )}
        </div>
      </div>

      {q.isLoading && <SkeletonTable rows={5} />}
      {q.isError && (
        <Card className="p-4 flex items-center justify-between">
          <span>{t('einvoice.error.load', { defaultValue: 'Could not load e-invoices' })}</span>
          <Button size="sm" variant="secondary" onClick={() => void q.refetch()}>
            {t('common.retry', { defaultValue: 'Retry' })}
          </Button>
        </Card>
      )}
      {!q.isLoading && !q.isError && rows.length === 0 && (
        <EmptyState
          title={t('einvoice.empty.outbound', { defaultValue: 'No e-invoices yet. Issue an invoice to create one.' })}
          action={
            <Link to="/finance?tab=invoices" className="underline text-sm">
              {t('einvoice.empty.goToInvoices', { defaultValue: 'Go to invoices' })}
            </Link>
          }
        />
      )}
      {rows.length > 0 && (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-start text-xs text-content-secondary">
                <th className="px-3 py-2 text-start">{t('einvoice.list.number', { defaultValue: 'Number' })}</th>
                <th className="px-3 py-2 text-start">{t('einvoice.list.buyer', { defaultValue: 'Buyer' })}</th>
                <th className="px-3 py-2 text-start">{t('common.date', { defaultValue: 'Date' })}</th>
                <th className="px-3 py-2 text-end">{t('einvoice.list.amount', { defaultValue: 'Amount' })}</th>
                <th className="px-3 py-2 text-start">{t('einvoice.list.country', { defaultValue: 'Country' })}</th>
                <th className="px-3 py-2 text-start">{t('common.status', { defaultValue: 'Status' })}</th>
                <th className="px-3 py-2 text-start">{t('einvoice.list.deadline', { defaultValue: 'Deadline' })}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-border-light">
                  <td className="px-3 py-2" dir="ltr">{r.invoice_number}</td>
                  <td className="px-3 py-2">{r.buyer_name}</td>
                  <td className="px-3 py-2"><DateDisplay value={r.invoice_date} /></td>
                  <td className="px-3 py-2 text-end"><MoneyDisplay amount={r.total_amount} currency={r.currency_code} /></td>
                  <td className="px-3 py-2">{r.country}</td>
                  <td className="px-3 py-2">
                    <Badge variant={statusVariant(r.status)}>{t(`einvoice.status.${r.status}`, { defaultValue: r.status })}</Badge>
                  </td>
                  <td className="px-3 py-2">
                    {r.deadline && (
                      <Badge variant={deadlineVariant(r.deadline.state)}>
                        {r.deadline.state === 'overdue'
                          ? t('einvoice.deadline.overdue', {
                              defaultValue: 'Deadline passed {{duration}} ago',
                              duration: formatDuration(r.deadline.seconds_left, i18n.language),
                            })
                          : t('einvoice.deadline.reportWithin', {
                              defaultValue: 'Report within {{duration}}',
                              duration: formatDuration(r.deadline.seconds_left, i18n.language),
                            })}
                      </Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {consolidating && grouping?.profile_id && (
        <ConsolidatedModal
          open
          onClose={() => setConsolidating(false)}
          projectId={projectId}
          profileId={grouping.profile_id}
        />
      )}
    </div>
  );
}
