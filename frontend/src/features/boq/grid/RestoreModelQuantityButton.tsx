// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Beside a quantity the estimator overrode while model elements are linked: asks, then puts the linked
 * elements' figure back (bim_hub restore-model-quantity) and shows where the new figure came from.
 */
import { useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { RotateCcw } from 'lucide-react';
import { ConfirmDialog } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { restoreModelQuantity } from '@/features/bim/api';

interface Props {
  positionId: string;
  boqId?: string | null;
  manualQuantity: string;
  modelQuantity: string | null | undefined;
  unit: string;
}

export function RestoreModelQuantityButton({ positionId, boqId, manualQuantity, modelQuantity, unit }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const [busy, setBusy] = useState(false);

  async function run(e: React.MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    const ok = await confirm({
      title: t('boq.restore_model_qty', { defaultValue: 'Restore model quantity' }),
      message: t('boq.restore_model_qty_confirm', {
        defaultValue: 'Replace your quantity {{manual}} with the model quantity {{model}} {{unit}}?',
        manual: manualQuantity,
        model: modelQuantity ?? '-',
        unit,
      }),
      confirmLabel: t('boq.restore_model_qty', { defaultValue: 'Restore model quantity' }),
      variant: 'warning',
    });
    if (!ok) return;
    setBusy(true);
    try {
      const res = await restoreModelQuantity(positionId);
      const p = res.provenance;
      addToast({
        type: 'success',
        title: t('boq.restore_model_qty_done', {
          defaultValue: 'Model quantity restored: {{quantity}} {{unit}}',
          quantity: res.quantity ?? '-',
          unit: res.unit ?? unit,
        }),
        message: t('boq.restore_model_qty_provenance', {
          defaultValue: 'Linked elements: {{elements}}. Formula: {{formula}}',
          elements: p?.element_count ?? 0,
          formula: p?.formula ?? '-',
        }),
      });
      await queryClient.invalidateQueries({ queryKey: boqId ? ['boq', boqId] : ['boq'] });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('boq.restore_model_qty_failed', { defaultValue: 'Could not restore the model quantity' }),
        message: getErrorMessage(err),
      });
    } finally {
      setBusy(false);
    }
  }

  const label = t('boq.restore_model_qty', { defaultValue: 'Restore model quantity' });
  return (
    <>
      <button
        type="button"
        onClick={run}
        onMouseDown={(e) => e.stopPropagation()}
        onDoubleClick={(e) => e.stopPropagation()}
        disabled={busy}
        title={label}
        aria-label={label}
        data-testid={`restore-model-qty-${positionId}`}
        className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded text-semantic-warning hover:bg-oe-blue-subtle hover:text-oe-blue-text disabled:opacity-50"
      >
        <RotateCcw className="h-3 w-3" aria-hidden="true" />
      </button>
      {confirmProps.open && createPortal(<ConfirmDialog {...confirmProps} />, document.body)}
    </>
  );
}
