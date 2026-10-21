// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// CreateRequisitionModal - raise one material requisition from buy-list rows.
//
// A buy-list row groups resources by name and unit for reading. That is not
// proof the resources are the same material, so the requisition keeps them as
// separate lines unless they name the same catalogue item, or the person ticks
// the box confirming that rows with the same name and unit are one material.
// Either way every line carries the BOQ positions it came from.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { Button, WideModal } from '@/shared/ui';
import { QuantityDisplay } from '@/shared/ui/QuantityDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { buildRequisitionLinesFromBuyList, createRequisition } from '@/features/procurement/requisitionsApi';
import type { MaterialBuyListItem } from './api';

const fieldCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

interface CreateRequisitionModalProps {
  open: boolean;
  projectId: string;
  rows: MaterialBuyListItem[];
  onClose: () => void;
  onCreated: (requisitionId: string) => void;
}

export function CreateRequisitionModal({ open, projectId, rows, onClose, onCreated }: CreateRequisitionModalProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [title, setTitle] = useState('');
  const [neededBy, setNeededBy] = useState('');
  const [combine, setCombine] = useState(false);
  const [useRemaining, setUseRemaining] = useState(true);

  const lines = useMemo(
    () => buildRequisitionLinesFromBuyList(rows, { combineUncoded: combine, useRemaining }),
    [rows, combine, useRemaining],
  );

  const create = useMutation({
    mutationFn: () =>
      createRequisition({
        project_id: projectId,
        title: title.trim() || null,
        required_date: neededBy || null,
        items: lines,
      }),
    onSuccess: (req) => {
      queryClient.invalidateQueries({ queryKey: ['procurement-requisitions', projectId] });
      addToast({
        type: 'success',
        title: t('resourceSummary.requisition.created', {
          defaultValue: 'Requisition {{number}} created as a draft',
          number: req.req_number ?? '',
        }),
      });
      onCreated(req.id);
    },
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={create.isPending}
      size="lg"
      title={t('resourceSummary.requisition.title', { defaultValue: 'Create requisition' })}
      subtitle={t('resourceSummary.requisition.subtitle', {
        defaultValue:
          'The requisition is saved as a draft. You can review and edit it under Procurement before submitting it.',
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={create.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button onClick={() => create.mutate()} disabled={create.isPending || lines.length === 0}>
            {create.isPending && <Loader2 size={14} className="mr-1 animate-spin" />}
            {t('resourceSummary.requisition.create', { defaultValue: 'Create draft requisition' })}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-xs font-medium text-content-secondary">
            {t('resourceSummary.requisition.field_title', { defaultValue: 'Title' })}
            <input
              className={`${fieldCls} mt-1`}
              value={title}
              maxLength={500}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label className="block text-xs font-medium text-content-secondary">
            {t('resourceSummary.requisition.field_needed_by', { defaultValue: 'Needed on site by' })}
            <input type="date" className={`${fieldCls} mt-1`} value={neededBy} onChange={(e) => setNeededBy(e.target.value)} />
          </label>
        </div>

        <label className="flex items-start gap-2 text-sm text-content-secondary">
          <input type="checkbox" className="mt-0.5" checked={combine} onChange={(e) => setCombine(e.target.checked)} />
          <span>
            {t('resourceSummary.requisition.combine', {
              defaultValue:
                'Combine positions with the same name and unit into one line. Tick this only if they are the same material; lines with the same catalogue item are always combined.',
            })}
          </span>
        </label>

        <label className="flex items-start gap-2 text-sm text-content-secondary">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={useRemaining}
            onChange={(e) => setUseRemaining(e.target.checked)}
          />
          <span>
            {t('resourceSummary.requisition.use_remaining', {
              defaultValue:
                'Request only what is not yet on a submitted requisition. Untick to request the whole BOQ quantity.',
            })}
          </span>
        </label>

        {lines.length === 0 && (
          <p className="text-sm text-content-tertiary">
            {t('resourceSummary.requisition.nothing_left', {
              defaultValue: 'Everything selected is already on requisitions.',
            })}
          </p>
        )}

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light text-left text-2xs uppercase tracking-wide text-content-tertiary">
                <th className="py-1.5 pr-3 font-medium">
                  {t('resourceSummary.buyList.col.material', { defaultValue: 'Material' })}
                </th>
                <th className="py-1.5 pr-3 font-medium">{t('resourceSummary.col.unit', { defaultValue: 'Unit' })}</th>
                <th className="py-1.5 pr-3 text-right font-medium">
                  {t('resourceSummary.requisition.col_quantity', { defaultValue: 'Quantity' })}
                </th>
                <th className="py-1.5 pr-3 text-right font-medium">
                  {t('resourceSummary.requisition.col_unit_cost', { defaultValue: 'Estimated unit cost' })}
                </th>
                <th className="py-1.5 text-right font-medium">
                  {t('resourceSummary.requisition.col_sources', { defaultValue: 'BOQ sources' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {lines.map((line, i) => (
                <tr key={i} className="border-b border-border-light/60 last:border-0">
                  <td className="py-1.5 pr-3 text-content-primary">{line.description}</td>
                  <td className="py-1.5 pr-3 text-content-tertiary">{line.unit || '-'}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">
                    <QuantityDisplay value={line.quantity_requested} unit={line.unit ?? ''} precision={2} />
                  </td>
                  <td className="py-1.5 pr-3 text-right tabular-nums text-content-secondary">
                    {line.unit_cost ? (
                      `${line.unit_cost} ${line.currency_code ?? ''}`.trim()
                    ) : (
                      <span className="text-xs text-content-tertiary">
                        {t('resourceSummary.requisition.cost_unavailable', {
                          defaultValue: 'Indicative cost unavailable',
                        })}
                      </span>
                    )}
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-content-tertiary">{line.sources.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </WideModal>
  );
}
