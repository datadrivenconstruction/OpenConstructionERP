// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Category, tags and the field flag of one photo, plus the records it can start.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { X } from 'lucide-react';
import { updatePhoto, type PhotoCategory as DocPhotoCategory } from '@/features/documents/api';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { photosKeys, type ArchivePhoto } from '../api';
import { bulkPatch, parseTags, PHOTO_CATEGORIES } from '../model';

/** Where a photo can start a record, with the create convention each page reads. */
export function raiseRoute(photo: ArchivePhoto, target: 'punch' | 'ncr' | 'safety'): string {
  const params = new URLSearchParams({ create: 'true', photo_id: photo.id });
  const seed = photo.caption || photo.filename;
  if (seed) params.set('title', seed);
  const route = target === 'punch' ? '/punchlist' : target === 'ncr' ? '/ncr' : '/safety';
  return `${route}?${params.toString()}`;
}

export function dayDiaryRoute(photo: ArchivePhoto): string {
  const day = (photo.taken_at || photo.created_at || '').slice(0, 10);
  return day ? `/daily-diary?date=${day}` : '/daily-diary';
}

export function PhotoMetaEditor({ photo }: { photo: ArchivePhoto }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const [tags, setTags] = useState<string[]>(photo.tags);
  const [tagText, setTagText] = useState('');
  useEffect(() => setTags(photo.tags), [photo.id, photo.tags]);

  const save = useMutation({
    mutationFn: (body: { category?: string; tags?: string[] }) =>
      updatePhoto(photo.id, { ...body, category: body.category as DocPhotoCategory | undefined }),
    onSuccess: (_res, body) => {
      if (body.tags) setTags(body.tags);
      qc.invalidateQueries({ queryKey: photosKeys.all });
    },
    onError: (err) => addToast({ type: 'error', title: t('photoArchive.save_failed'), message: getErrorMessage(err) }),
  });
  const current = { category: photo.category, tags };
  const isField = tags.some((x) => x.toLowerCase() === 'field');
  const addTags = () => {
    const body = bulkPatch(current, { kind: 'addTags', tags: parseTags(tagText) });
    setTagText('');
    if (body) save.mutate(body);
  };
  const link = 'rounded border border-border-light px-2 py-1 text-xs hover:bg-surface-secondary';

  return (
    <div className="space-y-3" data-testid="photo-meta-editor">
      <label className="flex items-center gap-2 text-xs">
        <span className="text-content-tertiary">{t('photos.category')}</span>
        <select
          value={photo.category}
          disabled={save.isPending}
          onChange={(e) => save.mutate({ category: e.target.value })}
          className="rounded border border-border-light bg-surface-primary px-2 py-1 text-xs"
        >
          {PHOTO_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {t(`photos.cat_${c}`)}
            </option>
          ))}
        </select>
      </label>

      <div className="space-y-1">
        <div className="flex flex-wrap gap-1">
          {tags.map((tag) => (
            <span key={tag} className="inline-flex items-center gap-1 rounded bg-surface-secondary px-1.5 py-0.5 text-xs">
              {tag}
              <button
                type="button"
                onClick={() => save.mutate({ tags: tags.filter((x) => x !== tag) })}
                aria-label={t('photos.remove_tag')}
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
        <div className="flex gap-1">
          <input
            value={tagText}
            onChange={(e) => setTagText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                addTags();
              }
            }}
            placeholder={t('photos.add_tag')}
            aria-label={t('photos.add_tag')}
            className="min-w-0 flex-1 rounded border border-border-light bg-surface-primary px-2 py-1 text-xs"
          />
          <button
            type="button"
            onClick={() => save.mutate(bulkPatch(current, { kind: 'field', on: !isField })!)}
            aria-pressed={isField}
            title={t('photos.field_category_hint')}
            className={`${link} ${isField ? 'bg-emerald-100 text-emerald-800' : ''}`}
          >
            {isField ? t('photoArchive.field_unmark') : t('photos.quick_tag_field')}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1">
        <span className="text-xs text-content-tertiary">{t('photos.raise_from')}</span>
        <button type="button" className={link} title={t('photos.raise_punch_hint')} onClick={() => navigate(raiseRoute(photo, 'punch'))}>
          {t('photos.raise_punch')}
        </button>
        <button type="button" className={link} title={t('photos.raise_ncr_hint')} onClick={() => navigate(raiseRoute(photo, 'ncr'))}>
          {t('photos.raise_ncr')}
        </button>
        <button type="button" className={link} title={t('photos.raise_safety_hint')} onClick={() => navigate(raiseRoute(photo, 'safety'))}>
          {t('photos.raise_safety')}
        </button>
        <button type="button" className={link} title={t('photos.open_day_diary_hint')} onClick={() => navigate(dayDiaryRoute(photo))}>
          {t('photos.open_day_diary')}
        </button>
      </div>
    </div>
  );
}
