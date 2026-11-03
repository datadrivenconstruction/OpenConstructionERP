// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Actions on the selected photos: category, tags, field flag, album, compare, export, delete.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { Tag, Trash2 } from 'lucide-react';
import { ConfirmDialog } from '@/shared/ui';
import { updatePhoto, type PhotoCategory as DocPhotoCategory } from '@/features/documents/api';
import { useToastStore } from '@/stores/useToastStore';
import { deletePhoto, photosKeys, type ArchivePhoto } from '../api';
import { bulkPatch, parseTags, PHOTO_CATEGORIES, type BulkAction } from '../model';

interface BulkBarProps {
  photos: ArchivePhoto[];
  selected: string[];
  allIds: string[];
  onSelect: (ids: string[]) => void;
  children?: React.ReactNode;
}

export function BulkBar({ photos, selected, allIds, onSelect, children }: BulkBarProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [tagText, setTagText] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const picked = photos.filter((p) => selected.includes(p.id));
  const allSelected = allIds.length > 0 && allIds.every((id) => selected.includes(id));

  // One PATCH per photo on the gallery endpoint; failures stay selected so they can be retried.
  const apply = async (action: BulkAction) => {
    setBusy(true);
    const failed: string[] = [];
    let changed = 0;
    for (const p of picked) {
      const body = bulkPatch(p, action);
      if (!body) continue;
      try {
        await updatePhoto(p.id, { ...body, category: body.category as DocPhotoCategory | undefined });
        changed += 1;
      } catch {
        failed.push(p.id);
      }
    }
    setBusy(false);
    qc.invalidateQueries({ queryKey: photosKeys.all });
    if (changed) addToast({ type: 'success', title: t('photoArchive.bulk.updated', { count: changed }) });
    if (failed.length) {
      addToast({ type: 'error', title: t('photoArchive.bulk.failed', { count: failed.length }) });
      onSelect(failed);
    }
  };

  const removeSelected = async () => {
    setBusy(true);
    const failed: string[] = [];
    for (const id of selected) {
      try {
        await deletePhoto(id);
      } catch {
        failed.push(id);
      }
    }
    setBusy(false);
    setConfirmDelete(false);
    qc.invalidateQueries({ queryKey: photosKeys.all });
    const ok = selected.length - failed.length;
    if (ok) addToast({ type: 'success', title: t('photoArchive.bulk.removed', { count: ok }) });
    if (failed.length) addToast({ type: 'error', title: t('photoArchive.bulk.failed', { count: failed.length }) });
    onSelect(failed);
  };

  const control = 'rounded border border-border-light bg-surface-primary px-2 py-1 text-xs disabled:opacity-50';
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg bg-surface-secondary px-3 py-2 text-sm" data-testid="bulk-bar">
      <span>{t('photoArchive.selected', { count: selected.length })}</span>
      <button type="button" className="text-xs text-oe-blue hover:underline" onClick={() => onSelect(allSelected ? [] : allIds)}>
        {allSelected ? t('photoArchive.bulk.deselect_all') : t('photoArchive.bulk.select_all')}
      </button>
      <select
        value=""
        disabled={busy}
        aria-label={t('photoArchive.bulk.set_category')}
        onChange={(e) => e.target.value && void apply({ kind: 'category', category: e.target.value })}
        className={control}
      >
        <option value="">{t('photoArchive.bulk.set_category')}</option>
        {PHOTO_CATEGORIES.map((c) => (
          <option key={c} value={c}>
            {t(`photos.cat_${c}`)}
          </option>
        ))}
      </select>
      <form
        className="flex gap-1"
        onSubmit={(e) => {
          e.preventDefault();
          const tags = parseTags(tagText);
          if (!tags.length) return;
          setTagText('');
          void apply({ kind: 'addTags', tags });
        }}
      >
        <input
          value={tagText}
          onChange={(e) => setTagText(e.target.value)}
          placeholder={t('photoArchive.bulk.tags_placeholder')}
          aria-label={t('photoArchive.bulk.add_tags')}
          className={`${control} w-36`}
        />
        <button type="submit" disabled={busy || !parseTags(tagText).length} className={`${control} inline-flex items-center gap-1`}>
          <Tag className="h-3 w-3" aria-hidden />
          {t('photoArchive.bulk.add_tags')}
        </button>
      </form>
      <button type="button" disabled={busy} onClick={() => void apply({ kind: 'field', on: true })} className={control}>
        {t('photoArchive.bulk.mark_field')}
      </button>
      <button type="button" disabled={busy} onClick={() => void apply({ kind: 'field', on: false })} className={control}>
        {t('photoArchive.bulk.unmark_field')}
      </button>
      {children}
      <button
        type="button"
        disabled={busy}
        onClick={() => setConfirmDelete(true)}
        className={`${control} inline-flex items-center gap-1 text-semantic-error`}
      >
        <Trash2 className="h-3 w-3" aria-hidden />
        {t('photoArchive.bulk.remove', { count: selected.length })}
      </button>
      <button type="button" onClick={() => onSelect([])} className="text-xs text-oe-blue hover:underline">
        {t('photoArchive.clear_selection')}
      </button>
      <ConfirmDialog
        open={confirmDelete}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => void removeSelected()}
        loading={busy}
        variant="danger"
        title={t('photoArchive.bulk.remove_title', { count: selected.length })}
        message={t('photoArchive.bulk.remove_message')}
        confirmLabel={t('photoArchive.bulk.remove', { count: selected.length })}
      />
    </div>
  );
}
