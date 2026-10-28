// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// PORemovalDialog - the confirm step for taking a purchase order out of play.
//
// A purchase order is a commercial document, so there is no single "remove"
// button. Which verb applies is decided by what the document has already done,
// and the dialog says which one it is about to use before it uses it:
//
//   * a DRAFT that has never been approved or issued is DELETED. The row and
//     its line items go for good.
//   * anything approved or issued is CANCELLED. The row and its number stay in
//     the register, marked cancelled, and the budget commitment is released.
//     The number is never reused, because a gap in the sequence is what an
//     auditor asks about.
//
// The backend has the final say on both and refuses with a structured 409 when
// something still points at the order. That refusal is rendered here as a
// readable list of what is holding it, not as a raw error string.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Ban, Loader2, Trash2 } from 'lucide-react';
import { Button, WideModal } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  cancelPurchaseOrder,
  deletePurchaseOrder,
  parseRemovalRefusal,
  type RemovalRefusal,
} from './api';

/**
 * The slice of a purchase order this dialog needs to describe what is going.
 *
 * Kept structural rather than importing the page's own `PurchaseOrder` so the
 * dialog can be handed a row from the list endpoint or a single fetched order
 * without either shape having to grow fields for the other.
 */
export interface RemovablePO {
  id: string;
  po_number: string;
  status: string;
  vendor_name?: string | null;
  amount_total?: string | number | null;
  currency_code?: string | null;
  line_items_count?: number;
}

/**
 * Which verb applies to a purchase order in this status.
 *
 * `delete` only for a draft. The backend additionally refuses a draft that was
 * once issued and later reopened - the UI cannot see that history, so it
 * offers delete and lets the 409 explain. Offering the narrower verb and being
 * corrected is better than offering cancel on a row that only needs deleting.
 *
 * `null` means no removal verb applies at all: a completed order records what
 * was actually bought, and one already cancelled has nothing left to do.
 */
export function removalVerbFor(status: string): 'delete' | 'cancel' | null {
  if (status === 'draft') return 'delete';
  if (status === 'completed' || status === 'cancelled') return null;
  return 'cancel';
}

/**
 * What to say for each refusal code the backend can return.
 *
 * The server sends an English `message` and `remediation` for the benefit of
 * callers that are not this app - a script, a log line, a curl. This app shows
 * its own translated text, the same split the demonstration read-only refusal
 * already uses, so a reader in any language is not handed an English sentence
 * the server happened to build. An unrecognised code falls back to the
 * server's own wording, which beats saying nothing.
 */
const REFUSAL_COPY: Record<string, { key: string; fallback: string }> = {
  purchase_order_has_dependents: {
    key: 'procurement.remove_po_blocked_dependents',
    fallback:
      'Removing it would take those records with it, so the purchase order stays as it is.',
  },
  purchase_order_not_deletable: {
    key: 'procurement.remove_po_blocked_not_deletable',
    fallback:
      'This purchase order has been approved or issued, so its number is already in circulation. Cancel it instead - the record survives and the number is never reused.',
  },
  purchase_order_not_cancellable: {
    key: 'procurement.remove_po_blocked_not_cancellable',
    fallback:
      'A completed purchase order records what was actually bought. Raise a credit note or a variation against it instead.',
  },
  purchase_order_already_cancelled: {
    key: 'procurement.remove_po_blocked_already_cancelled',
    fallback: 'This purchase order is already cancelled.',
  },
};

/** Translation keys for the holder kinds the backend can name. */
const HOLDER_LABEL_KEYS: Record<string, { key: string; fallback: string }> = {
  goods_receipt: {
    key: 'procurement.holder_goods_receipt',
    fallback: 'Goods receipts',
  },
  payable_invoice: {
    key: 'procurement.holder_payable_invoice',
    fallback: 'Payable invoices',
  },
  retainage_release: {
    key: 'procurement.holder_retainage_release',
    fallback: 'Retainage releases',
  },
  requisition: {
    key: 'procurement.holder_requisition',
    fallback: 'Material requisitions',
  },
};

interface PORemovalDialogProps {
  po: RemovablePO | null;
  projectId: string;
  onClose: () => void;
}

export function PORemovalDialog({ po, projectId, onClose }: PORemovalDialogProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [reason, setReason] = useState('');
  const [refusal, setRefusal] = useState<RemovalRefusal | null>(null);
  const [fallbackError, setFallbackError] = useState<string | null>(null);

  // A fresh row is a fresh decision: clear whatever the previous one was
  // refused for, so a stale blocker list cannot be read as this order's.
  useEffect(() => {
    setReason('');
    setRefusal(null);
    setFallbackError(null);
  }, [po?.id]);

  const verb = po ? removalVerbFor(po.status) : null;

  // The copy for this refusal, looked up once. Indexing the record inside
  // the conditional narrows only the expression that was tested, so every
  // repeat of the same index reads as possibly undefined again.
  const refusalCopy = refusal ? REFUSAL_COPY[refusal.code] : undefined;

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['procurement-po', projectId] });
    queryClient.invalidateQueries({ queryKey: ['finance', 'dashboard', projectId] });
  };

  const onFailure = (err: unknown) => {
    const parsed = parseRemovalRefusal(err);
    if (parsed) {
      setRefusal(parsed);
      setFallbackError(null);
      return;
    }
    // Not the structured refusal - anything from a 403 to a dropped
    // connection. Show the sentence the API client already built rather than
    // an empty dialog.
    setRefusal(null);
    setFallbackError(getErrorMessage(err));
  };

  const cancelMut = useMutation({
    mutationFn: (id: string) => cancelPurchaseOrder(id, reason.trim()),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('procurement.po_cancelled_toast', { defaultValue: 'Purchase order cancelled' }),
        message: t('procurement.po_cancelled_kept', {
          defaultValue: 'The order keeps its number and stays in the register.',
        }),
      });
      onClose();
    },
    onError: onFailure,
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deletePurchaseOrder(id),
    onSuccess: () => {
      invalidate();
      addToast({
        type: 'success',
        title: t('procurement.po_deleted_toast', { defaultValue: 'Purchase order deleted' }),
      });
      onClose();
    },
    onError: onFailure,
  });

  const busy = cancelMut.isPending || deleteMut.isPending;

  if (!po || !verb) return null;

  const isDelete = verb === 'delete';
  const lineCount = po.line_items_count ?? 0;

  const title = isDelete
    ? t('procurement.remove_po_title_delete', {
        defaultValue: 'Delete purchase order {{number}}?',
        number: po.po_number,
      })
    : t('procurement.remove_po_title_cancel', {
        defaultValue: 'Cancel purchase order {{number}}?',
        number: po.po_number,
      });

  return (
    <WideModal
      open
      onClose={busy ? () => undefined : onClose}
      size="sm"
      busy={busy}
      title={title}
      subtitle={
        isDelete
          ? t('procurement.remove_po_subtitle_delete', {
              defaultValue: 'This order has never been approved or issued.',
            })
          : t('procurement.remove_po_subtitle_cancel', {
              defaultValue: 'The order stays in the register with its number.',
            })
      }
      footer={
        <div className="flex justify-end gap-3">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('procurement.remove_po_keep', { defaultValue: 'Keep it' })}
          </Button>
          <Button
            variant="danger"
            disabled={busy || refusal !== null}
            onClick={() => (isDelete ? deleteMut.mutate(po.id) : cancelMut.mutate(po.id))}
            icon={
              busy ? (
                <Loader2 size={14} className="animate-spin" />
              ) : isDelete ? (
                <Trash2 size={14} />
              ) : (
                <Ban size={14} />
              )
            }
          >
            {isDelete
              ? t('procurement.remove_po_confirm_delete', { defaultValue: 'Delete it' })
              : t('procurement.remove_po_confirm_cancel', { defaultValue: 'Cancel the order' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        {/* What is about to go, in the terms the register shows it. */}
        <div className="rounded-lg border border-border-light bg-surface-secondary px-4 py-3 text-sm">
          <div className="flex items-baseline justify-between gap-3">
            <span className="font-semibold text-content-primary">{po.po_number}</span>
            <MoneyDisplay amount={po.amount_total ?? '0'} currency={po.currency_code ?? ''} />
          </div>
          {po.vendor_name ? (
            <p className="mt-1 text-content-secondary">{po.vendor_name}</p>
          ) : null}
          {isDelete && lineCount > 0 ? (
            <p className="mt-1 text-content-tertiary">
              {t('procurement.remove_po_line_count', {
                defaultValue: 'Line items that go with it: {{count}}',
                count: lineCount,
              })}
            </p>
          ) : null}
        </div>

        <p className="text-sm text-content-secondary">
          {isDelete
            ? t('procurement.remove_po_delete_body', {
                defaultValue:
                  'The order and its line items are removed for good. This cannot be undone. If the order has ever been approved or issued it will be refused, because its number is already in circulation.',
              })
            : t('procurement.remove_po_cancel_body', {
                defaultValue:
                  'The order is marked cancelled and keeps its number, so the number is never reused. Any budget it committed is released.',
              })}
        </p>

        {!isDelete && (
          <div>
            <label
              htmlFor="po-cancel-reason"
              className="mb-1 block text-xs font-semibold uppercase tracking-wide text-content-secondary"
            >
              {t('procurement.remove_po_reason_label', { defaultValue: 'Reason' })}
            </label>
            <textarea
              id="po-cancel-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              maxLength={1000}
              disabled={busy}
              placeholder={t('procurement.remove_po_reason_placeholder', {
                defaultValue: 'Why is this order being cancelled?',
              })}
              className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue disabled:opacity-50"
            />
            <p className="mt-1 text-xs text-content-tertiary">
              {t('procurement.remove_po_reason_hint', {
                defaultValue: 'Stored with the order so the register explains itself later.',
              })}
            </p>
          </div>
        )}

        {/* The server's refusal, as readable text. */}
        {refusal && (
          <div
            role="alert"
            className="rounded-lg border border-semantic-error/40 bg-semantic-error/5 px-4 py-3"
          >
            <div className="flex items-start gap-2">
              <AlertTriangle size={16} className="mt-0.5 shrink-0 text-semantic-error" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-content-primary">
                  {t('procurement.remove_po_blocked_title', {
                    defaultValue: 'This purchase order cannot be removed',
                  })}
                </p>
                {refusal.holders.length > 0 ? (
                  <>
                    <p className="mt-1 text-sm text-content-secondary">
                      {t('procurement.remove_po_blocked_intro', {
                        defaultValue: 'These records still refer to it:',
                      })}
                    </p>
                    <ul className="mt-2 space-y-1">
                      {refusal.holders.map((holder) => {
                        const label = HOLDER_LABEL_KEYS[holder.kind];
                        return (
                          <li
                            key={holder.kind}
                            className="flex items-baseline justify-between gap-3 text-sm"
                          >
                            <span className="text-content-secondary">
                              {label
                                ? t(label.key, { defaultValue: label.fallback })
                                : holder.kind.replace(/_/g, ' ')}
                            </span>
                            <span className="font-semibold tabular-nums text-content-primary">
                              {holder.count}
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                  </>
                ) : null}
                {/* Why, and what to do instead - in the reader's language. A
                    code we do not recognise falls back to the server's own
                    English sentence rather than leaving the box unexplained. */}
                <p className="mt-2 text-sm text-content-secondary">
                  {refusalCopy
                    ? t(refusalCopy.key, { defaultValue: refusalCopy.fallback })
                    : refusal.message}
                </p>
              </div>
            </div>
          </div>
        )}

        {fallbackError && (
          <p role="alert" className="text-sm text-semantic-error">
            {fallbackError}
          </p>
        )}
      </div>
    </WideModal>
  );
}
