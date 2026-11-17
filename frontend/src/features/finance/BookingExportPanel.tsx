// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Booking export for one configured booking connector: pick a period, see what is left out and
 * why, create an immutable file for the bookkeeper. Re-export of already exported invoices needs
 * an explicit tick.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, Card } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  createBooking,
  downloadBookingBatch,
  listBookingBatches,
  previewBooking,
  previousMonth,
} from './bookingExportApi';

export function BookingExportPanel({ configId }: { configId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toast = useToastStore((s) => s.addToast);
  const month = previousMonth(new Date());
  const [from, setFrom] = useState(month.from);
  const [to, setTo] = useState(month.to);
  const [reexport, setReexport] = useState(false);
  const request = { connector_config_id: configId, period_from: from, period_to: to, reexport };

  const preview = useQuery({
    queryKey: ['booking-preview', configId, from, to, reexport],
    queryFn: () => previewBooking(request),
    enabled: from <= to,
  });
  const batches = useQuery({ queryKey: ['booking-batches'], queryFn: listBookingBatches, select: (p) => p.items });
  const create = useMutation({
    mutationFn: () => createBooking(request),
    onSuccess: (batch) => {
      void qc.invalidateQueries({ queryKey: ['booking-batches'] });
      void qc.invalidateQueries({ queryKey: ['booking-preview'] });
      void downloadBookingBatch(batch);
    },
    onError: (e) => toast({ type: 'error', title: getErrorMessage(e) }),
  });
  const data = preview.data;

  return (
    <Card className="space-y-3 p-4" data-testid="booking-export-panel">
      <h4 className="text-sm font-medium">{t('finance.booking_export.title', { defaultValue: 'Booking export' })}</h4>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <input type="date" className="oe-input" value={from} onChange={(e) => setFrom(e.target.value)} />
        <input type="date" className="oe-input" value={to} onChange={(e) => setTo(e.target.value)} />
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={reexport} onChange={(e) => setReexport(e.target.checked)} />
          {t('finance.booking_export.reexport', { defaultValue: 'Include invoices exported before' })}
        </label>
      </div>
      {data && (
        <div className="space-y-2">
          <p className="text-sm">
            {t('finance.booking_export.summary', {
              defaultValue: '{{invoices}} invoices, {{rows}} rows',
              invoices: data.invoices,
              rows: data.rows,
            })}
          </p>
          <ul className="space-y-1 text-sm">
            {data.findings.map((f, i) => (
              <li key={i} className={f.severity === 'error' ? 'text-semantic-error' : 'text-content-secondary'}>
                {t(`validation.${f.rule_id}`, { defaultValue: f.rule_id, no: f.invoice, ...f.details })}
                {f.invoice ? ` (${f.invoice})` : ''}
              </li>
            ))}
          </ul>
          <Button disabled={data.blocked || data.rows === 0} loading={create.isPending} onClick={() => create.mutate()}>
            {t('finance.booking_export.create', { defaultValue: 'Create file' })}
          </Button>
        </div>
      )}
      {batches.data && batches.data.length > 0 && (
        <table className="oe-table w-full text-sm">
          <tbody>
            {batches.data.map((b) => (
              <tr key={b.id}>
                <td>B-{b.number}</td>
                <td>
                  <DateDisplay value={b.period_from} format="numeric" /> - <DateDisplay value={b.period_to} format="numeric" />
                </td>
                <td className="text-right tabular-nums">{b.invoice_count}</td>
                <td className="text-right">
                  <Button size="sm" variant="ghost" onClick={() => void downloadBookingBatch(b)}>
                    {t('common.download', { defaultValue: 'Download' })}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
