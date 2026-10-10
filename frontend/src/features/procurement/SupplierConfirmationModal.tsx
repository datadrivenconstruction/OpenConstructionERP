// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// SupplierConfirmationModal - record the supplier's answer to an issued order.
//
// The supplier has no login; their order confirmation arrives by email or
// phone and the buyer types it in. The confirmed delivery date is kept beside
// the date the order asked for, never written over it, so the gap stays
// visible. A second confirmation replaces the first (suppliers revise them).

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { WideModal, Button } from '@/shared/ui';
import { apiPost, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

const fieldCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

export interface ConfirmablePO {
  id: string;
  po_number: string;
  delivery_date: string | null;
  supplier_reference?: string | null;
  supplier_confirmed_delivery_date?: string | null;
}

interface SupplierConfirmationModalProps {
  po: ConfirmablePO | null;
  projectId: string;
  onClose: () => void;
}

export function SupplierConfirmationModal({ po, projectId, onClose }: SupplierConfirmationModalProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [reference, setReference] = useState('');
  const [confirmedDate, setConfirmedDate] = useState('');

  useEffect(() => {
    setReference(po?.supplier_reference ?? '');
    setConfirmedDate(po?.supplier_confirmed_delivery_date ?? '');
  }, [po]);

  const mut = useMutation({
    mutationFn: () =>
      apiPost(`/v1/procurement/${po!.id}/acknowledge/`, {
        supplier_reference: reference.trim() || null,
        confirmed_delivery_date: confirmedDate || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['procurement-po', projectId] });
      addToast({
        type: 'success',
        title: t('procurement.supplier_confirmation_saved', {
          defaultValue: 'Supplier confirmation recorded',
        }),
      });
      onClose();
    },
    onError: (e: unknown) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      }),
  });

  const dateDiffers = Boolean(confirmedDate && po?.delivery_date && confirmedDate !== po.delivery_date);

  return (
    <WideModal
      open={po !== null}
      onClose={onClose}
      busy={mut.isPending}
      size="md"
      title={t('procurement.supplier_confirmation_title', {
        defaultValue: 'Supplier confirmation for {{po}}',
        po: po?.po_number ?? '',
      })}
      subtitle={t('procurement.supplier_confirmation_subtitle', {
        defaultValue: "Enter what the supplier sent back: their order reference and the delivery date they agreed to.",
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={mut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button onClick={() => mut.mutate()} disabled={mut.isPending}>
            {mut.isPending && <Loader2 size={14} className="animate-spin mr-1" />}
            {t('procurement.supplier_confirmation_save', { defaultValue: 'Save confirmation' })}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <label htmlFor="po-supplier-reference" className="mb-1 block text-xs font-medium text-content-secondary">
            {t('procurement.supplier_reference', { defaultValue: 'Supplier order reference' })}
          </label>
          <input
            id="po-supplier-reference"
            value={reference}
            maxLength={100}
            onChange={(e) => setReference(e.target.value)}
            className={fieldCls}
          />
        </div>
        <div>
          <label htmlFor="po-confirmed-date" className="mb-1 block text-xs font-medium text-content-secondary">
            {t('procurement.supplier_confirmed_delivery_date', { defaultValue: 'Confirmed delivery date' })}
          </label>
          <input
            id="po-confirmed-date"
            type="date"
            value={confirmedDate}
            onChange={(e) => setConfirmedDate(e.target.value)}
            className={fieldCls}
          />
          {dateDiffers && (
            <p className="mt-1 text-xs text-semantic-warning">
              {t('procurement.supplier_date_differs', {
                defaultValue: 'The order asked for {{asked}}. Both dates are kept.',
                asked: po?.delivery_date ?? '',
              })}
            </p>
          )}
        </div>
      </div>
    </WideModal>
  );
}
