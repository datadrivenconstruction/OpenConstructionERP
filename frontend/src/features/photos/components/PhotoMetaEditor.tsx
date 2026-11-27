// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Category, tags and the field flag of one photo, plus the records it can start.

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, X } from 'lucide-react';
import { getErrorMessage } from '@/shared/lib/api';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { useToastStore } from '@/stores/useToastStore';
import { fetchAlbums, patchPhoto, photosKeys, setPhotoAlbums, type ArchivePhoto } from '../api';
import { bulkPatch, parseTags, PHOTO_CATEGORIES } from '../model';
import { fmtList } from '@/shared/lib/formatters';

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

type SavedField = 'category' | 'album' | 'tags';

/**
 * The drawer edits the gallery record (`/v1/photos/{id}/`) and reads the saved
 * row back, so a choice stays put after the save instead of falling back to
 * the copy of the photo the drawer was opened with.
 */
export function PhotoMetaEditor({ photo, onChange }: { photo: ArchivePhoto; onChange?: (photo: ArchivePhoto) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const canEdit = useHasPermission('photos.edit');
  const readOnlyReason = canEdit ? undefined : t('photoArchive.meta.edit_needs_editor');
  const [category, setCategory] = useState(photo.category);
  const [albumIds, setAlbumIds] = useState<string[]>(photo.album_ids ?? []);
  const [tags, setTags] = useState<string[]>(photo.tags);
  const [tagText, setTagText] = useState('');
  const [saved, setSaved] = useState<SavedField | null>(null);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => setTags(photo.tags), [photo.id, photo.tags]);
  useEffect(() => setCategory(photo.category), [photo.id, photo.category]);
  const albumKey = (photo.album_ids ?? []).join(',');
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => setAlbumIds(photo.album_ids ?? []), [photo.id, albumKey]);
  useEffect(
    () => () => {
      if (savedTimer.current) clearTimeout(savedTimer.current);
    },
    [],
  );

  const albums = useQuery({ queryKey: photosKeys.albums(photo.project_id), queryFn: () => fetchAlbums(photo.project_id) });

  const landed = (next: ArchivePhoto, field: SavedField) => {
    const merged: ArchivePhoto = {
      ...photo,
      ...next,
      category: next.category ?? category,
      tags: next.tags ?? tags,
      album_ids: next.album_ids ?? albumIds,
    };
    setCategory(merged.category);
    setTags(merged.tags);
    setAlbumIds(merged.album_ids ?? []);
    onChange?.(merged);
    qc.invalidateQueries({ queryKey: photosKeys.all });
    setSaved(field);
    if (savedTimer.current) clearTimeout(savedTimer.current);
    savedTimer.current = setTimeout(() => setSaved(null), 2500);
  };

  const save = useMutation({
    mutationFn: (body: { category?: string; tags?: string[] }) => patchPhoto(photo.id, body),
    onSuccess: (res, body) => landed(res, body.category !== undefined ? 'category' : 'tags'),
    onError: (err) => {
      setCategory(photo.category);
      addToast({ type: 'error', title: t('photoArchive.save_failed'), message: getErrorMessage(err) });
    },
  });
  const saveAlbums = useMutation({
    mutationFn: (ids: string[]) => setPhotoAlbums(photo.id, ids),
    onSuccess: (res) => landed(res, 'album'),
    onError: (err) => {
      setAlbumIds(photo.album_ids ?? []);
      addToast({ type: 'error', title: t('photoArchive.save_failed'), message: getErrorMessage(err) });
    },
  });
  const current = { category, tags };
  const albumList = albums.data ?? [];
  const albumValue = albumIds.length === 0 ? '' : albumIds.length === 1 ? albumIds[0]! : '__several__';
  const severalNames = fmtList(
    albumIds.map((id) => albumList.find((a) => a.id === id)?.name).filter((n): n is string => Boolean(n)),
  );
  const savedNote = (field: SavedField) =>
    saved === field ? (
      <span role="status" className="inline-flex items-center gap-1 text-xs text-semantic-success" data-testid={`photo-saved-${field}`}>
        <Check className="h-3 w-3" aria-hidden />
        {field === 'album'
          ? t('photoArchive.meta.saved_album')
          : field === 'category'
            ? t('photoArchive.meta.saved_category')
            : t('common.saved')}
      </span>
    ) : null;
  const isField = tags.some((x) => x.toLowerCase() === 'field');
  const addTags = () => {
    const body = bulkPatch(current, { kind: 'addTags', tags: parseTags(tagText) });
    setTagText('');
    if (body) save.mutate(body);
  };
  const link = 'rounded border border-border-light px-2 py-1 text-xs hover:bg-surface-secondary';

  return (
    <div className="space-y-3" data-testid="photo-meta-editor">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <label className="flex items-center gap-2" title={readOnlyReason}>
          <span className="text-content-tertiary">{t('photos.category')}</span>
          <select
            value={category}
            disabled={!canEdit || save.isPending}
            onChange={(e) => {
              setCategory(e.target.value);
              save.mutate({ category: e.target.value });
            }}
            className="oe-select oe-input-sm"
            data-testid="photo-category-select"
          >
            {PHOTO_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {t(`photos.cat_${c}`)}
              </option>
            ))}
          </select>
        </label>
        {savedNote('category')}
      </div>

      <div className="space-y-1 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2" title={readOnlyReason}>
            <span className="text-content-tertiary">{t('photoArchive.meta.album')}</span>
            <select
              value={albumValue}
              disabled={!canEdit || saveAlbums.isPending || albums.isLoading}
              onChange={(e) => {
                const ids = e.target.value ? [e.target.value] : [];
                setAlbumIds(ids);
                saveAlbums.mutate(ids);
              }}
              className="oe-select oe-input-sm max-w-[14rem]"
              data-testid="photo-album-select"
            >
              <option value="">{t('photoArchive.meta.no_album')}</option>
              {albumValue === '__several__' && (
                <option value="__several__" disabled>
                  {t('photoArchive.meta.several_albums', { names: severalNames })}
                </option>
              )}
              {albumList.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          {savedNote('album')}
        </div>
        {albums.isError && <p className="text-semantic-error">{t('photoArchive.meta.albums_failed')}</p>}
        {!albums.isLoading && !albums.isError && albumList.length === 0 && (
          <p className="text-content-tertiary">{t('photoArchive.meta.no_albums_hint')}</p>
        )}
      </div>

      <div className="space-y-1">
        <div className="flex flex-wrap gap-1">
          {tags.map((tag) => (
            <span key={tag} className="inline-flex items-center gap-1 rounded bg-surface-secondary px-1.5 py-0.5 text-xs">
              {tag}
              <button
                type="button"
                onClick={() => save.mutate({ tags: tags.filter((x) => x !== tag) })}
                disabled={!canEdit}
                title={readOnlyReason}
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
            disabled={!canEdit}
            title={readOnlyReason}
            className="min-w-0 flex-1 oe-input oe-input-sm"
          />
          <button
            type="button"
            onClick={() => save.mutate(bulkPatch(current, { kind: 'field', on: !isField })!)}
            aria-pressed={isField}
            disabled={!canEdit}
            title={readOnlyReason ?? t('photos.field_category_hint')}
            className={`${link} ${isField ? 'bg-semantic-success-bg text-semantic-success' : ''}`}
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
