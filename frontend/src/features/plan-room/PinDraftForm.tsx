// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The form behind the pin tool: which record the pin is for (a new one, or one that exists) and a note.
 * It only collects the choice; the page creates the record and the pin.
 */

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { Loader2 } from 'lucide-react';
import { Button } from '@/shared/ui';
import type { PinTargetKind } from './api';
import { PIN_KINDS, listRecordOptions } from './pinKinds';

export interface PinDraftValue {
  kind: PinTargetKind;
  mode: 'new' | 'link';
  title: string;
  targetId: string;
  note: string;
}

export const EMPTY_PIN_DRAFT: PinDraftValue = { kind: 'rfi', mode: 'new', title: '', targetId: '', note: '' };

/** A pin can be saved once it names a title (new record), a record (linked) or, for a note, nothing. */
export function isPinDraftValid(d: PinDraftValue): boolean {
  if (d.kind === 'note') return d.note.trim().length > 0;
  return d.mode === 'new' ? d.title.trim().length > 0 : d.targetId.length > 0;
}

interface Props {
  projectId: string;
  value: PinDraftValue;
  onChange: (next: PinDraftValue) => void;
  onSave: () => void;
  onCancel: () => void;
  isSaving: boolean;
}

export function PinDraftForm({ projectId, value, onChange, onSave, onCancel, isSaving }: Props) {
  const { t } = useTranslation();
  const linking = value.kind !== 'note' && value.mode === 'link';
  const options = useQuery({
    queryKey: ['plan-room-pin-records', projectId, value.kind],
    queryFn: () => listRecordOptions(value.kind, projectId),
    enabled: linking && !!projectId,
  });
  const set = (patch: Partial<PinDraftValue>) => onChange({ ...value, ...patch });

  return (
    <div className="space-y-2">
      <div role="radiogroup" aria-label={t('plan_room.pin_kind', { defaultValue: 'Pin for' })} className="flex flex-wrap gap-1">
        {PIN_KINDS.map((k) => (
          <button
            key={k.kind}
            type="button"
            role="radio"
            aria-checked={value.kind === k.kind}
            onClick={() => set({ kind: k.kind, targetId: '' })}
            className={clsx(
              'rounded-full border px-2 py-0.5 text-xs font-medium',
              value.kind === k.kind
                ? 'border-transparent text-white'
                : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary',
            )}
            style={value.kind === k.kind ? { backgroundColor: k.color } : undefined}
          >
            {t(k.labelKey, { defaultValue: k.defaultLabel })}
          </button>
        ))}
      </div>

      {value.kind !== 'note' && (
        <div className="flex gap-3 text-xs text-content-secondary">
          {(['new', 'link'] as const).map((m) => (
            <label key={m} className="inline-flex items-center gap-1">
              <input type="radio" name="pin-mode" checked={value.mode === m} onChange={() => set({ mode: m })} />
              {m === 'new'
                ? t('plan_room.mode_new', { defaultValue: 'Create new' })
                : t('plan_room.mode_link', { defaultValue: 'Link existing' })}
            </label>
          ))}
        </div>
      )}

      {value.kind !== 'note' && value.mode === 'new' && (
        <input
          value={value.title}
          onChange={(e) => set({ title: e.target.value })}
          autoFocus
          maxLength={200}
          placeholder={t('plan_room.title_placeholder', { defaultValue: 'Short title of the record' })}
          aria-label={t('plan_room.title_label', { defaultValue: 'Title' })}
          className="oe-input w-full"
        />
      )}

      {linking && (
        <select
          value={value.targetId}
          onChange={(e) => set({ targetId: e.target.value })}
          aria-label={t('plan_room.pick_record', { defaultValue: 'Record' })}
          className="oe-input w-full"
        >
          <option value="">
            {options.isLoading
              ? t('common.loading', { defaultValue: 'Loading...' })
              : t('plan_room.pick_record_ph', { defaultValue: 'Choose a record' })}
          </option>
          {(options.data ?? []).map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </select>
      )}

      <textarea
        value={value.note}
        onChange={(e) => set({ note: e.target.value })}
        rows={2}
        autoFocus={value.kind === 'note'}
        placeholder={t('plan_room.note_placeholder', { defaultValue: 'Add a note (optional)...' })}
        className="w-full resize-none oe-textarea"
      />

      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={isSaving}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={onSave}
          disabled={isSaving || !isPinDraftValid(value)}
          icon={isSaving ? <Loader2 size={14} className="animate-spin" /> : undefined}
        >
          {t('plan_room.save_pin', { defaultValue: 'Save pin' })}
        </Button>
      </div>
    </div>
  );
}
