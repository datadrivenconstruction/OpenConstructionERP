// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Pins on the selected model element: the records already pinned to it, and a way to pin a new one. */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { MapPin, X } from 'lucide-react';
import { createRegistryPin, fetchBimPins } from '@/features/plan-room/api';
import { EMPTY_PIN_DRAFT, PinDraftForm, type PinDraftValue } from '@/features/plan-room/PinDraftForm';
import { createRecordForPin, kindMeta, recordPath } from '@/features/plan-room/pinKinds';

interface Props {
  projectId: string;
  modelId: string;
  elementId: string;
  elementName?: string | null;
}

export function BIMElementPin({ projectId, modelId, elementId, elementName }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<PinDraftValue>(EMPTY_PIN_DRAFT);
  const key = ['plan-room-pins', 'bim', modelId];
  const { data } = useQuery({ queryKey: key, queryFn: () => fetchBimPins(modelId), enabled: !!modelId, retry: false });
  const here = (data?.items ?? []).filter((p) => p.bim_element_id === elementId);

  const save = useMutation({
    mutationFn: async () => {
      const targetId =
        draft.kind === 'note'
          ? null
          : draft.mode === 'link'
            ? draft.targetId
            : await createRecordForPin(draft.kind, projectId, draft.title.trim(), draft.note.trim());
      return createRegistryPin({
        project_id: projectId,
        target_kind: draft.kind,
        target_id: targetId,
        bim_model_id: modelId,
        bim_element_id: elementId,
        note: draft.note.trim() || null,
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['plan-room-pins'] });
      setOpen(false);
      setDraft(EMPTY_PIN_DRAFT);
    },
  });

  return (
    <div
      className="absolute left-3 top-3 z-20 w-72 rounded-xl border border-border-light bg-surface-primary/95 p-3 text-sm shadow-lg backdrop-blur"
      data-testid="bim-element-pin"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-1.5 font-semibold text-content-primary">
          <MapPin size={14} aria-hidden />
          <span className="truncate">{elementName || t('plan_room.bim_element', { defaultValue: 'Selected element' })}</span>
        </span>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="rounded-md px-2 py-0.5 text-xs font-medium text-oe-blue hover:bg-surface-secondary"
        >
          {open ? <X size={14} aria-label={t('common.cancel', { defaultValue: 'Cancel' })} /> : t('plan_room.bim_pin_here', { defaultValue: 'Pin a record here' })}
        </button>
      </div>
      {here.length > 0 && (
        <ul className="mt-2 space-y-1">
          {here.map((p) => (
            <li key={p.id} className="flex items-center justify-between gap-2 text-xs">
              <span className="truncate text-content-secondary">
                {t(kindMeta(p.target_kind).labelKey, { defaultValue: kindMeta(p.target_kind).defaultLabel })}
                {p.target_label ? `: ${p.target_label}` : ''}
              </span>
              {recordPath(p.target_kind, p.target_id) && (
                <Link to={recordPath(p.target_kind, p.target_id) ?? '#'} className="shrink-0 font-medium text-oe-blue hover:underline">
                  {t('plan_room.open_record', { defaultValue: 'Open record' })}
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
      {open && (
        <div className="mt-2">
          <PinDraftForm
            projectId={projectId}
            value={draft}
            onChange={setDraft}
            onSave={() => save.mutate()}
            onCancel={() => setOpen(false)}
            isSaving={save.isPending}
          />
        </div>
      )}
    </div>
  );
}
