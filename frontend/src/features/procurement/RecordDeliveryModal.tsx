// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// RecordDeliveryModal - create a goods receipt against an issued PO.
//
// Wave 7 (frontend wiring): the Goods-Receipts tab was read-only even
// though the backend has fully-functional create + confirm endpoints
// (POST /v1/procurement/goods-receipts/ and .../{id}/confirm/). This
// modal closes that gap: pick a receivable PO, enter the quantity
// received per line, and POST a draft goods receipt. Confirmation stays
// a separate step (the Confirm action on a draft GR row) because only
// confirmation runs the over-receipt cap, rolls the PO up to
// partially_received/completed and fires the finance event.
//
// Quantities are Decimal-as-string on the wire (the backend validates
// each as a non-negative decimal); we keep them as the strings the user
// typed and never coerce money/qty through a float round-trip.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, PackageCheck, Truck } from 'lucide-react';
import { WideModal, Button } from '@/shared/ui';
import { apiGet, apiPost, getErrorMessage, type Page } from '@/shared/lib/api';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import { useToastStore } from '@/stores/useToastStore';
import { invalidateFinanceFigures } from '@/features/finance/financeQueryKeys';

/* ── Wire types (subset of the backend POResponse / GR contract) ───────── */

interface ReceivablePOItem {
  id: string;
  description: string;
  quantity: string | number;
  unit: string | null;
}

interface ReceivablePO {
  id: string;
  po_number: string;
  vendor_name: string | null;
  items: ReceivablePOItem[];
}

interface POListItem {
  id: string;
  po_number: string;
  vendor_name: string | null;
  status: string;
}

/** Per-line received-quantity entry in the form. */
interface DeliveryLineForm {
  poItemId: string;
  description: string;
  unit: string | null;
  orderedQty: string;
  receivedQty: string;
}

interface RecordDeliveryModalProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  /** Pre-select this PO (e.g. opened from a PO row). Optional. */
  initialPoId?: string | null;
}

// A PO can only receive goods once it has been issued (the backend rejects
// goods receipts for any other status). Mirror that here so the picker only
// lists POs the create call will accept.
const RECEIVABLE_STATUSES = ['issued', 'partially_received'];

/** Per-line received-quantity validity tags surfaced as inline errors. */
export type DeliveryLineIssue = 'invalid' | 'over_ordered' | null;

/**
 * Validate a single received-quantity entry against the ordered quantity.
 * Both arrive as the strings the user typed / the wire returned (Decimal-as-
 * string). Returns:
 *   * 'invalid'      - blank, non-numeric, or negative received quantity.
 *   * 'over_ordered' - received exceeds ordered (the backend caps this too).
 *   * null           - valid.
 * Mirrors the backend cap in ProcurementService.create_goods_receipt so the
 * UI gives immediate feedback; the server stays authoritative.
 */
export function validateDeliveryLine(
  receivedQty: string,
  orderedQty: string,
): DeliveryLineIssue {
  const received = Number(receivedQty);
  const ordered = Number(orderedQty);
  if (receivedQty.trim() === '' || !Number.isFinite(received) || received < 0) {
    return 'invalid';
  }
  if (Number.isFinite(ordered) && received > ordered) {
    return 'over_ordered';
  }
  return null;
}

const fieldCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

export function RecordDeliveryModal({
  open,
  onClose,
  projectId,
  initialPoId,
}: RecordDeliveryModalProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // `split('T')[0]` is `string | undefined` under noUncheckedIndexedAccess;
  // the ?? '' keeps todayStr a plain string for the string-typed setters.
  const todayStr = new Date().toISOString().split('T')[0] ?? '';
  const [selectedPoId, setSelectedPoId] = useState<string>(initialPoId ?? '');
  const [receiptDate, setReceiptDate] = useState<string>(todayStr);
  const [deliveryNote, setDeliveryNote] = useState<string>('');
  const [notes, setNotes] = useState<string>('');
  const [lines, setLines] = useState<DeliveryLineForm[]>([]);
  const [formError, setFormError] = useState<string>('');

  // Reset the form each time the modal is (re)opened so a previous draft
  // does not leak into a fresh entry.
  useEffect(() => {
    if (!open) return;
    setSelectedPoId(initialPoId ?? '');
    setReceiptDate(todayStr);
    setDeliveryNote('');
    setNotes('');
    setLines([]);
    setFormError('');
    // todayStr is recomputed every render but is stable within a day; we
    // intentionally only re-run when the modal opens or the seed PO changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialPoId]);

  // List receivable POs for the picker. We pull the project's POs and keep
  // only the issued / partially_received ones (the only states the create
  // endpoint accepts).
  const { data: receivablePage, isLoading: posLoading } = useQuery({
    queryKey: ['procurement-receivable-po', projectId],
    queryFn: () =>
      apiGet<Page<POListItem>>(`/v1/procurement/?project_id=${projectId}&limit=100`),
    enabled: open && Boolean(projectId),
  });
  // The status narrowing happens here rather than in the queryFn so the cache
  // holds the server page and the notice below can say how much of the
  // project's order book this picker was handed. 100 is the server cap, so a
  // project past 100 orders has receivable ones this dropdown cannot offer.
  const receivablePOs = useMemo(
    () => (receivablePage?.items ?? []).filter((po) => RECEIVABLE_STATUSES.includes(po.status)),
    [receivablePage],
  );

  // Load the chosen PO's line items so the form can offer a row per item.
  const { data: poDetail, isLoading: detailLoading } = useQuery({
    queryKey: ['procurement-po-detail', selectedPoId],
    queryFn: () => apiGet<ReceivablePO>(`/v1/procurement/${selectedPoId}`),
    enabled: open && Boolean(selectedPoId),
  });

  // Seed one form row per PO line whenever a new PO is loaded. Received
  // quantity defaults to the ordered quantity (the common "full delivery"
  // case); the user can reduce it for a partial delivery.
  useEffect(() => {
    if (!poDetail) {
      setLines([]);
      return;
    }
    setLines(
      (poDetail.items ?? []).map((it) => {
        const ordered = it.quantity != null ? String(it.quantity) : '0';
        return {
          poItemId: it.id,
          description: it.description,
          unit: it.unit,
          orderedQty: ordered,
          receivedQty: ordered,
        };
      }),
    );
    setFormError('');
  }, [poDetail]);

  const updateReceived = (poItemId: string, value: string) => {
    setLines((prev) =>
      prev.map((l) =>
        l.poItemId === poItemId ? { ...l, receivedQty: value } : l,
      ),
    );
  };

  // The submit is valid when a PO is chosen, it has at least one line, and
  // every entered received quantity is a finite, non-negative number that
  // does not exceed the ordered quantity (the backend enforces the same cap
  // and 400s otherwise - this just gives immediate feedback).
  const lineErrors = useMemo(() => {
    const errs: Record<string, string> = {};
    for (const l of lines) {
      const issue = validateDeliveryLine(l.receivedQty, l.orderedQty);
      if (issue === 'invalid') {
        errs[l.poItemId] = t('procurement.gr_qty_invalid', {
          defaultValue: 'Enter a valid quantity',
        });
      } else if (issue === 'over_ordered') {
        errs[l.poItemId] = t('procurement.gr_qty_exceeds_ordered', {
          defaultValue: 'Cannot exceed ordered quantity',
        });
      }
    }
    return errs;
  }, [lines, t]);

  const hasAnyReceived = lines.some((l) => Number(l.receivedQty) > 0);
  const canSubmit =
    Boolean(selectedPoId) &&
    lines.length > 0 &&
    Object.keys(lineErrors).length === 0 &&
    hasAnyReceived;

  const createGRMut = useMutation({
    mutationFn: () =>
      apiPost<{ id: string }>(`/v1/procurement/goods-receipts/`, {
        po_id: selectedPoId,
        receipt_date: receiptDate,
        delivery_note_number: deliveryNote.trim() || undefined,
        status: 'draft',
        notes: notes.trim() || undefined,
        items: lines.map((l) => ({
          po_item_id: l.poItemId,
          quantity_ordered: l.orderedQty || '0',
          quantity_received: l.receivedQty || '0',
        })),
      }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('procurement.gr_created', {
          defaultValue: 'Delivery recorded',
        }),
        message: t('procurement.gr_created_confirm_hint', {
          defaultValue: 'Confirm the goods receipt to update the PO.',
        }),
      });
      // Refresh the GR list and the PO list (a confirmed receipt later rolls
      // the PO status up, so keep both in sync).
      void queryClient.invalidateQueries({ queryKey: ['procurement-gr', projectId] });
      void queryClient.invalidateQueries({ queryKey: ['procurement-po', projectId] });
      void invalidateFinanceFigures(queryClient);
      onClose();
    },
    onError: (e) => {
      const msg = getErrorMessage(e);
      setFormError(msg);
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: msg,
      });
    },
  });

  const handleSubmit = () => {
    if (!selectedPoId) {
      setFormError(
        t('procurement.gr_select_po_first', {
          defaultValue: 'Select a purchase order first.',
        }),
      );
      return;
    }
    if (!canSubmit) return;
    setFormError('');
    createGRMut.mutate();
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={createGRMut.isPending}
      title={t('procurement.record_delivery', { defaultValue: 'Record Delivery' })}
      subtitle={t('procurement.record_delivery_subtitle', {
        defaultValue:
          'Log a goods receipt against an issued purchase order. Confirm it afterwards to update the PO and budget.',
      })}
      size="xl"
      footer={
        <>
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={createGRMut.isPending}
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={handleSubmit}
            disabled={!canSubmit || createGRMut.isPending}
          >
            {createGRMut.isPending ? (
              <Loader2 size={16} className="animate-spin mr-1.5" />
            ) : (
              <PackageCheck size={16} className="mr-1.5" />
            )}
            {t('procurement.gr_save', { defaultValue: 'Record Delivery' })}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {/* ── PO + delivery header ─────────────────────────────────────── */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="sm:col-span-1">
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('procurement.po_number', { defaultValue: 'PO #' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <select
              value={selectedPoId}
              onChange={(e) => setSelectedPoId(e.target.value)}
              className={fieldCls}
              disabled={posLoading}
            >
              <option value="">
                {posLoading
                  ? t('common.loading', { defaultValue: 'Loading...' })
                  : t('procurement.gr_select_po', {
                      defaultValue: 'Select a purchase order',
                    })}
              </option>
              {receivablePOs.map((po) => (
                <option key={po.id} value={po.id}>
                  {po.po_number}
                  {po.vendor_name ? ` - ${po.vendor_name}` : ''}
                </option>
              ))}
            </select>
            {/* Counts the order book, not the receivable subset: the dropdown
                offers what it was handed, and this says how much it was
                handed. Anything else would compare two different sets. */}
            {receivablePage && <TruncationNotice page={receivablePage} className="mt-1" />}
          </div>
          <div className="sm:col-span-1">
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('procurement.receipt_date', { defaultValue: 'Date' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              type="date"
              value={receiptDate}
              onChange={(e) => setReceiptDate(e.target.value)}
              className={fieldCls}
            />
          </div>
          <div className="sm:col-span-1">
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('procurement.delivery_note', {
                defaultValue: 'Delivery Note #',
              })}
            </label>
            <input
              type="text"
              value={deliveryNote}
              onChange={(e) => setDeliveryNote(e.target.value)}
              maxLength={100}
              placeholder={t('procurement.delivery_note_placeholder', {
                defaultValue: 'Optional reference',
              })}
              className={fieldCls}
            />
          </div>
        </div>

        {/* ── No receivable POs ────────────────────────────────────────── */}
        {!posLoading && receivablePOs.length === 0 && (
          <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-4 py-6 text-center text-sm text-content-tertiary">
            <Truck size={22} className="mx-auto mb-2 opacity-60" />
            {t('procurement.gr_no_receivable_po', {
              defaultValue:
                'No issued purchase orders are awaiting delivery. Issue a PO first to record a goods receipt against it.',
            })}
          </div>
        )}

        {/* ── Line items ───────────────────────────────────────────────── */}
        {selectedPoId && (
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-3">
              {t('procurement.gr_quantities_received', {
                defaultValue: 'Quantities Received',
              })}
            </h3>

            {detailLoading && (
              <div className="flex items-center justify-center py-8 text-content-tertiary">
                <Loader2 size={18} className="animate-spin mr-2" />
                {t('common.loading', { defaultValue: 'Loading...' })}
              </div>
            )}

            {!detailLoading && lines.length === 0 && (
              <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-4 py-6 text-center text-sm text-content-tertiary">
                {t('procurement.gr_no_lines', {
                  defaultValue:
                    'This purchase order has no line items to receive.',
                })}
              </div>
            )}

            {!detailLoading && lines.length > 0 && (
              <div className="space-y-2">
                <div className="hidden sm:grid grid-cols-[1fr_90px_110px] gap-3 text-2xs font-medium text-content-tertiary uppercase tracking-wider px-1">
                  <span>{t('procurement.item_description', { defaultValue: 'Description' })}</span>
                  <span className="text-right">{t('procurement.gr_ordered', { defaultValue: 'Ordered' })}</span>
                  <span className="text-right">{t('procurement.gr_received', { defaultValue: 'Received' })}</span>
                </div>
                {lines.map((l) => (
                  <div
                    key={l.poItemId}
                    className="grid grid-cols-1 sm:grid-cols-[1fr_90px_110px] gap-3 items-start"
                  >
                    <div className="text-sm text-content-primary pt-2">
                      {l.description}
                      {l.unit ? (
                        <span className="text-content-tertiary text-xs ml-1">
                          ({l.unit})
                        </span>
                      ) : null}
                    </div>
                    <div className="text-sm text-content-secondary tabular-nums text-right pt-2">
                      {l.orderedQty}
                    </div>
                    <div>
                      <input
                        type="number"
                        inputMode="decimal"
                        min="0"
                        step="any"
                        value={l.receivedQty}
                        onChange={(e) => updateReceived(l.poItemId, e.target.value)}
                        className={`h-9 w-full rounded-lg border bg-surface-primary px-2.5 text-sm tabular-nums text-right focus:outline-none focus:ring-2 focus:ring-oe-blue/30 ${
                          lineErrors[l.poItemId]
                            ? 'border-semantic-error'
                            : 'border-border focus:border-oe-blue'
                        }`}
                        aria-label={t('procurement.gr_received_for', {
                          defaultValue: 'Received quantity for {{item}}',
                          item: l.description,
                        })}
                      />
                      {lineErrors[l.poItemId] && (
                        <p className="mt-1 text-2xs text-semantic-error">
                          {lineErrors[l.poItemId]}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Notes ────────────────────────────────────────────────────── */}
        {selectedPoId && lines.length > 0 && (
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('procurement.notes', { defaultValue: 'Notes' })}
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              maxLength={5000}
              className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2.5 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              placeholder={t('procurement.gr_notes_placeholder', {
                defaultValue: 'Optional notes about this delivery...',
              })}
            />
          </div>
        )}

        {formError && (
          <p className="text-sm text-semantic-error">{formError}</p>
        )}
      </div>
    </WideModal>
  );
}
