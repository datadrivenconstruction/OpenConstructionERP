// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Punch description in the detail drawer​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: read, edit in place, and (when merges
 * exist) the merge history. The edit goes through `updateOrQueue`, so it works
 * offline and sends `If-Match` online.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Pencil } from 'lucide-react';
import { useToastStore } from '@/stores/useToastStore';
import { MergeHistoryList, SavedOnDeviceBadge } from '@/features/field/OfflineRecordBits';
import { updateOrQueue } from '@/features/field/offlineWrite';
import { updatePunchItem, type PunchItem } from './api';

export function PunchDescriptionSection({ item, onSaved }: { item: PunchItem; onSaved: () => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');

  const saveMut = useMutation({
    mutationFn: (description: string) =>
      updateOrQueue<PunchItem>({
        kind: 'punch',
        base: {
          id: item.id,
          version: item.version ?? null,
          snapshot: item as unknown as Record<string, unknown>,
          projectId: item.project_id,
        },
        patch: { description },
        current: item,
        send: (body, version) => updatePunchItem(item.id, body, version),
      }),
    onSuccess: (saved) => {
      setEditing(false);
      onSaved();
      addToast({
        type: 'success',
        title: saved._offline
          ? t('offline_sync.saved_on_device', { defaultValue: 'Saved on this device' })
          : t('punch.description_saved', { defaultValue: 'Description saved' }),
      });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const flag = (item as { _offline?: 'new' | 'edited' })._offline;

  return (
    <section data-testid="punch-description-section" className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h4 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
          {t('punch.field_description', { defaultValue: 'Description' })}
          <SavedOnDeviceBadge flag={flag} />
        </h4>
        {!editing && (
          <button
            type="button"
            data-testid="punch-description-edit"
            onClick={() => {
              setDraft(item.description ?? '');
              setEditing(true);
            }}
            className="inline-flex min-h-[44px] items-center gap-1 rounded-md px-2 text-xs font-medium text-oe-blue hover:underline"
            aria-label={t('punch.edit_description', { defaultValue: 'Edit description' })}
          >
            <Pencil size={12} aria-hidden="true" />
            {t('common.edit', { defaultValue: 'Edit' })}
          </button>
        )}
      </div>
      {editing ? (
        <div className="space-y-2">
          <textarea
            data-testid="punch-description-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={5}
            className="w-full rounded-lg border border-border bg-surface-primary p-2 text-sm text-content-primary"
            aria-label={t('punch.field_description', { defaultValue: 'Description' })}
          />
          <div className="flex gap-2">
            <button
              type="button"
              data-testid="punch-description-save"
              onClick={() => saveMut.mutate(draft)}
              disabled={saveMut.isPending || draft === (item.description ?? '')}
              className="min-h-[44px] rounded-lg bg-oe-blue px-4 text-sm font-semibold text-white disabled:opacity-40"
            >
              {t('common.save', { defaultValue: 'Save' })}
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              disabled={saveMut.isPending}
              className="min-h-[44px] rounded-lg border border-border px-4 text-sm font-medium text-content-primary"
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </button>
          </div>
        </div>
      ) : item.description?.trim() ? (
        <p className="whitespace-pre-wrap text-sm text-content-secondary">{item.description}</p>
      ) : (
        <p className="text-sm text-content-tertiary">
          {t('punch.no_description', { defaultValue: 'No description yet.' })}
        </p>
      )}
      <MergeHistoryList kind="punch" id={item.id} />
    </section>
  );
}
