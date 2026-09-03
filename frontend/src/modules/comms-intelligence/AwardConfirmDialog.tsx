// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Award confirmation — notify the winning supplier.
 *
 * Opens the moment an RFQ is awarded: a server-rendered order confirmation
 * to the winner carrying the PO and any extra notes, previewed byte-for-byte
 * and saved as an editable .eml. No mailbox bridge required, so it works the
 * same on a server as on a desktop: download, open, press Send.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, Loader2, Mail, X } from 'lucide-react';
import { Badge, Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  type ItemEmailPreview,
  type RegisterItemRow,
  downloadAwardConfirmationEml,
  previewAwardConfirmation,
} from './registers-api';

export function AwardConfirmDialog({
  item,
  projectId,
  contactId,
  poNumber,
  amount,
  onClose,
}: {
  item: RegisterItemRow;
  projectId: string;
  contactId: string;
  poNumber: string;
  amount?: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [note, setNote] = useState('');
  const [debouncedNote, setDebouncedNote] = useState('');
  useEffect(() => {
    const h = setTimeout(() => setDebouncedNote(note), 400);
    return () => clearTimeout(h);
  }, [note]);

  const previewQuery = useQuery<ItemEmailPreview>({
    queryKey: ['award-confirmation-preview', item.id, contactId, poNumber, amount ?? '', debouncedNote],
    queryFn: () =>
      previewAwardConfirmation(item.id, {
        contact_id: contactId,
        po_number: poNumber,
        amount: amount ?? '',
        note: debouncedNote,
      }),
  });

  const emlMut = useMutation({
    mutationFn: () =>
      downloadAwardConfirmationEml(
        item.id,
        { contact_id: contactId, po_number: poNumber, amount: amount ?? '', note },
        item.reference,
      ),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('award_confirm.toast_eml', {
          defaultValue: 'Confirmation .eml saved — open it and press Send',
        }),
      });
      void queryClient.invalidateQueries({ queryKey: ['registers', projectId] });
      onClose();
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const p = previewQuery.data;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="flex h-[92vh] w-[96vw] max-w-[1100px] flex-col overflow-hidden rounded-lg border border-border-light bg-surface-primary shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-border-light p-3">
          <Mail className="h-4 w-4 text-emerald-600" />
          <span className="truncate text-sm font-semibold">
            {t('award_confirm.title', { defaultValue: 'Notify the winner — order confirmation' })}
          </span>
          {poNumber ? <Badge variant="blue">PO {poNumber}</Badge> : null}
          <span className="ml-auto flex items-center gap-1">
            <Button size="sm" variant="secondary" onClick={() => emlMut.mutate()} disabled={emlMut.isPending}>
              {emlMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              {t('award_confirm.eml', { defaultValue: 'Download .eml (open & send)' })}
            </Button>
            <Button size="sm" variant="ghost" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </span>
        </div>

        <div className="border-b border-border-light px-3 py-2">
          <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-text-tertiary">
            {t('award_confirm.note', { defaultValue: 'Additional details / notes for this order' })}
          </label>
          <textarea
            className="min-h-[56px] w-full rounded border border-border-light bg-surface-primary px-2 py-1.5 text-sm"
            placeholder={t('award_confirm.note_ph', {
              defaultValue: 'e.g. Deliver to site by Friday. Confirm lead time on receipt of this PO.',
            })}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>

        <div className="min-h-0 flex-1 overflow-auto bg-white">
          {previewQuery.isLoading ? (
            <div className="flex justify-center p-8">
              <Loader2 className="h-6 w-6 animate-spin text-text-tertiary" />
            </div>
          ) : (
            <iframe title="award-confirmation" className="h-full w-full border-0" srcDoc={p?.html ?? ''} />
          )}
        </div>

        <div className="border-t border-border-light p-2 text-center text-xs text-text-tertiary">
          {t('award_confirm.foot', {
            defaultValue:
              'This preview is byte-for-byte the .eml. Sending stays in your hands — download, open and press Send.',
          })}
        </div>
      </div>
    </div>
  );
}
