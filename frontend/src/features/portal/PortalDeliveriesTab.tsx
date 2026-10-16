// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Supplier portal - Deliveries tab (magic-link surface).
 *
 * A supplier holding a `po` access rule sees the orders shared with it and,
 * where the rule grants `submit`, tells the site what is on its way: the
 * delivery note, the quantity per line, the batch or heat number and the
 * material certificates, with the scans uploaded here. The submission becomes
 * a DRAFT goods receipt; the site checks it and confirms it, so nothing sent
 * from here counts as received on its own.
 *
 * Mobile-first: stacked cards at 375px. No hardcoded strings.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertCircle, Loader2, Truck, Upload } from 'lucide-react';
import { Badge, Button, Card, EmptyState } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import {
  listMyDeliveries,
  listMyPurchaseOrders,
  submitMyDelivery,
  uploadMyDeliveryDocument,
  type PortalDeliverySubmit,
  type PortalPurchaseOrder,
} from './api';

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

export interface DeliveryLineDraft {
  po_item_id: string;
  quantity: string;
  batch_lot: string;
  certificate_type: string;
  certificate_number: string;
  certificate_document_id: string;
}

export interface DeliveryDraft {
  po_id: string;
  delivery_note_number: string;
  delivery_date: string;
  delivery_note_document_id: string;
  lines: DeliveryLineDraft[];
}

/** One empty draft line per order line, the certificate type prefilled from what the order asks for. */
export function draftLinesFor(po: PortalPurchaseOrder | undefined): DeliveryLineDraft[] {
  return (po?.lines ?? []).map((line) => ({
    po_item_id: line.id,
    quantity: '',
    batch_lot: '',
    certificate_type: line.required_certificate_type ?? '',
    certificate_number: '',
    certificate_document_id: '',
  }));
}

/**
 * The submission body: lines without a positive quantity are left out, and a
 * certificate is sent only when it has a type and a number or a scan.
 */
export function buildDeliveryPayload(draft: DeliveryDraft): PortalDeliverySubmit {
  const lines = draft.lines
    .filter((l) => Number(l.quantity) > 0)
    .map((l) => {
      const hasCert = Boolean(l.certificate_type) && Boolean(l.certificate_number.trim() || l.certificate_document_id);
      return {
        po_item_id: l.po_item_id,
        quantity: l.quantity.trim(),
        batch_lot: l.batch_lot.trim() || null,
        certificates: hasCert
          ? [
              {
                certificate_type: l.certificate_type,
                certificate_number: l.certificate_number.trim(),
                document_id: l.certificate_document_id || null,
                batch_number: l.batch_lot.trim() || null,
              },
            ]
          : [],
      };
    });
  return {
    po_id: draft.po_id,
    delivery_note_number: draft.delivery_note_number.trim(),
    delivery_date: draft.delivery_date,
    delivery_note_document_id: draft.delivery_note_document_id || null,
    lines,
  };
}

function UploadButton({
  poId,
  label,
  onUploaded,
}: {
  poId: string;
  label: string;
  onUploaded: (documentId: string, name: string) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [name, setName] = useState('');
  const upload = useMutation({
    mutationFn: (file: File) => uploadMyDeliveryDocument(poId, file),
    onSuccess: (doc) => {
      setName(doc.name);
      onUploaded(doc.document_id, doc.name);
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-oe-blue">
      {upload.isPending ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
      <span>{name || label}</span>
      <input
        type="file"
        className="sr-only"
        accept=".pdf,image/*"
        disabled={upload.isPending}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) upload.mutate(file);
          e.target.value = '';
        }}
      />
    </label>
  );
}

export function PortalDeliveriesTab() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const today = new Date().toISOString().split('T')[0] ?? '';

  const ordersQ = useQuery({ queryKey: ['portal-deliveries', 'orders'], queryFn: () => listMyPurchaseOrders() });
  const deliveriesQ = useQuery({ queryKey: ['portal-deliveries', 'list'], queryFn: () => listMyDeliveries() });

  const orders = useMemo(() => ordersQ.data?.items ?? [], [ordersQ.data]);
  const types = ordersQ.data?.certificate_types ?? [];
  const deliverable = orders.filter((o) => o.can_deliver);

  const [draft, setDraft] = useState<DeliveryDraft>({
    po_id: '',
    delivery_note_number: '',
    delivery_date: today,
    delivery_note_document_id: '',
    lines: [],
  });
  const po = orders.find((o) => o.id === draft.po_id);

  useEffect(() => {
    if (!draft.po_id && deliverable.length === 1) {
      const only = deliverable[0]!;
      setDraft((d) => ({ ...d, po_id: only.id, lines: draftLinesFor(only) }));
    }
  }, [deliverable, draft.po_id]);

  const setLine = (idx: number, patch: Partial<DeliveryLineDraft>) =>
    setDraft((d) => ({ ...d, lines: d.lines.map((l, i) => (i === idx ? { ...l, ...patch } : l)) }));

  const payload = buildDeliveryPayload(draft);
  const canSubmit = Boolean(payload.po_id && payload.delivery_note_number && payload.delivery_date && payload.lines.length);

  const submit = useMutation({
    mutationFn: () => submitMyDelivery(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['portal-deliveries'] });
      setDraft({ po_id: '', delivery_note_number: '', delivery_date: today, delivery_note_document_id: '', lines: [] });
      addToast({
        type: 'success',
        title: t('portal.deliveries.submitted', { defaultValue: 'Delivery sent to the site for confirmation' }),
      });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  if (ordersQ.isLoading) {
    return (
      <div className="flex justify-center py-10">
        <Loader2 size={20} className="animate-spin text-content-tertiary" />
      </div>
    );
  }
  if (ordersQ.isError) {
    return (
      <Card className="p-6 text-sm text-semantic-error">
        <AlertCircle size={16} className="mb-2" />
        {(ordersQ.error as Error).message}
      </Card>
    );
  }
  if (orders.length === 0) {
    return (
      <EmptyState
        icon={<Truck size={28} strokeWidth={1.5} />}
        title={t('portal.deliveries.no_orders', { defaultValue: 'No purchase orders shared with you' })}
        description={t('portal.deliveries.no_orders_desc', {
          defaultValue: 'When a buyer shares a purchase order with you, you can announce its deliveries here.',
        })}
      />
    );
  }

  const deliveries = deliveriesQ.data?.items ?? [];

  return (
    <div className="space-y-4">
      {deliverable.length > 0 && (
        <Card className="space-y-4 p-4">
          <h2 className="text-sm font-semibold text-content-primary">
            {t('portal.deliveries.new', { defaultValue: 'Announce a delivery' })}
          </h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <select
              aria-label={t('portal.deliveries.order', { defaultValue: 'Purchase order' })}
              value={draft.po_id}
              onChange={(e) => {
                const next = orders.find((o) => o.id === e.target.value);
                setDraft((d) => ({ ...d, po_id: e.target.value, delivery_note_document_id: '', lines: draftLinesFor(next) }));
              }}
              className={inputCls}
            >
              <option value="">{t('portal.deliveries.order', { defaultValue: 'Purchase order' })}</option>
              {deliverable.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.po_number}
                </option>
              ))}
            </select>
            <input
              aria-label={t('portal.deliveries.note_number', { defaultValue: 'Delivery note number' })}
              placeholder={t('portal.deliveries.note_number', { defaultValue: 'Delivery note number' })}
              value={draft.delivery_note_number}
              maxLength={100}
              onChange={(e) => setDraft((d) => ({ ...d, delivery_note_number: e.target.value }))}
              className={inputCls}
            />
            <input
              type="date"
              aria-label={t('portal.deliveries.date', { defaultValue: 'Delivery date' })}
              value={draft.delivery_date}
              onChange={(e) => setDraft((d) => ({ ...d, delivery_date: e.target.value }))}
              className={inputCls}
            />
          </div>
          {po && (
            <>
              <UploadButton
                key={`note-${po.id}`}
                poId={po.id}
                label={t('portal.deliveries.upload_note', { defaultValue: 'Upload the delivery note (PDF or photo)' })}
                onUploaded={(id) => setDraft((d) => ({ ...d, delivery_note_document_id: id }))}
              />
              <div className="space-y-3">
                {po.lines.map((line, idx) => {
                  const l = draft.lines[idx];
                  if (!l) return null;
                  return (
                    <div key={line.id} className="rounded-lg border border-border-light p-3 space-y-2">
                      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                        <span className="text-content-primary">{line.description}</span>
                        <span className="text-xs text-content-tertiary tabular-nums">
                          {t('portal.deliveries.open_qty', {
                            defaultValue: '{{received}} of {{ordered}} {{unit}} delivered',
                            received: line.quantity_received,
                            ordered: line.quantity_ordered,
                            unit: line.unit ?? '',
                          })}
                        </span>
                      </div>
                      {line.required_certificate_type && (
                        <Badge variant="neutral" size="sm">
                          {t('portal.deliveries.needs_certificate', {
                            defaultValue: 'Needs {{type}}',
                            type: types.find((tp) => tp.code === line.required_certificate_type)?.label ??
                              line.required_certificate_type,
                          })}
                        </Badge>
                      )}
                      <div className="grid grid-cols-2 gap-2">
                        <input
                          type="number"
                          step="any"
                          min="0"
                          aria-label={t('portal.deliveries.quantity', { defaultValue: 'Quantity delivered' })}
                          placeholder={t('portal.deliveries.quantity', { defaultValue: 'Quantity delivered' })}
                          value={l.quantity}
                          onChange={(e) => setLine(idx, { quantity: e.target.value })}
                          className={inputCls}
                        />
                        <input
                          aria-label={t('portal.deliveries.batch', { defaultValue: 'Batch or heat number' })}
                          placeholder={t('portal.deliveries.batch', { defaultValue: 'Batch or heat number' })}
                          value={l.batch_lot}
                          maxLength={100}
                          onChange={(e) => setLine(idx, { batch_lot: e.target.value })}
                          className={inputCls}
                        />
                        <select
                          aria-label={t('portal.deliveries.certificate_type', { defaultValue: 'Certificate type' })}
                          value={l.certificate_type}
                          onChange={(e) => setLine(idx, { certificate_type: e.target.value })}
                          className={inputCls}
                        >
                          <option value="">
                            {t('portal.deliveries.no_certificate', { defaultValue: 'No certificate' })}
                          </option>
                          {types.map((tp) => (
                            <option key={tp.code} value={tp.code}>
                              {tp.label}
                            </option>
                          ))}
                        </select>
                        <input
                          aria-label={t('portal.deliveries.certificate_number', { defaultValue: 'Certificate number' })}
                          placeholder={t('portal.deliveries.certificate_number', {
                            defaultValue: 'Certificate number',
                          })}
                          value={l.certificate_number}
                          maxLength={100}
                          onChange={(e) => setLine(idx, { certificate_number: e.target.value })}
                          className={inputCls}
                        />
                      </div>
                      {l.certificate_type && (
                        <UploadButton
                          key={`cert-${po.id}-${line.id}`}
                          poId={po.id}
                          label={t('portal.deliveries.upload_certificate', {
                            defaultValue: 'Upload the certificate scan',
                          })}
                          onUploaded={(id) => setLine(idx, { certificate_document_id: id })}
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          )}
          <div className="flex justify-end">
            <Button onClick={() => submit.mutate()} disabled={!canSubmit || submit.isPending}>
              {submit.isPending && <Loader2 size={14} className="animate-spin mr-1" />}
              {t('portal.deliveries.submit', { defaultValue: 'Send to the site' })}
            </Button>
          </div>
        </Card>
      )}

      <Card className="p-4">
        <h2 className="mb-3 text-sm font-semibold text-content-primary">
          {t('portal.deliveries.sent', { defaultValue: 'Deliveries you announced' })}
        </h2>
        {deliveries.length === 0 ? (
          <p className="text-xs text-content-tertiary">
            {t('portal.deliveries.none_sent', { defaultValue: 'Nothing announced yet.' })}
          </p>
        ) : (
          <ul className="divide-y divide-border-light">
            {deliveries.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <span className="text-content-primary">
                  {d.po_number} / {d.delivery_note_number ?? '-'}
                </span>
                <span className="flex items-center gap-2 text-xs text-content-tertiary">
                  <DateDisplay value={d.receipt_date} />
                  <Badge variant={d.status === 'confirmed' ? 'success' : 'neutral'} size="sm">
                    {d.status === 'confirmed'
                      ? t('portal.deliveries.status_confirmed', { defaultValue: 'Confirmed by the site' })
                      : t('portal.deliveries.status_draft', { defaultValue: 'Waiting for the site' })}
                  </Badge>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
