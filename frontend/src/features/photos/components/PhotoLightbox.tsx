// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// One photo full size, with where and when it was taken, its links, plan pins and AI review.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, Download, MapPin, Trash2, X } from 'lucide-react';
import { AuthImage, ConfirmDialog } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { downloadWithAuth, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  deletePhoto,
  fetchPins,
  fetchSuggestions,
  patchPhoto,
  photosKeys,
  removeLink,
  type ArchivePhoto,
} from '../api';
import { bboxStyle, sourceRoute } from '../model';
import { AISuggestionList } from './AISuggestionList';
import { LinkPicker } from './LinkPicker';
import { PhotoMetaEditor } from './PhotoMetaEditor';
import { fmtNumberForInput } from '@/shared/lib/formatters';

interface PhotoLightboxProps {
  photo: ArchivePhoto;
  photos?: ArchivePhoto[];
  onClose: () => void;
  onNavigate?: (photo: ArchivePhoto) => void;
}

export function PhotoLightbox({ photo, photos = [], onClose, onNavigate }: PhotoLightboxProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [caption, setCaption] = useState(photo.caption ?? '');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const index = photos.findIndex((p) => p.id === photo.id);
  const prev = index > 0 ? photos[index - 1] : undefined;
  const next = index >= 0 && index < photos.length - 1 ? photos[index + 1] : undefined;

  useEffect(() => setCaption(photo.caption ?? ''), [photo.id, photo.caption]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowLeft' && prev) onNavigate?.(prev);
      if (e.key === 'ArrowRight' && next) onNavigate?.(next);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, onNavigate, prev, next]);

  const pins = useQuery({ queryKey: photosKeys.pins(photo.id), queryFn: () => fetchPins(photo.id), staleTime: 60_000 });
  const suggestions = useQuery({
    queryKey: photosKeys.suggestions(photo.id),
    queryFn: () => fetchSuggestions(photo.id),
  });
  const hazards = (suggestions.data ?? []).filter((s) => s.kind === 'hazard' && s.status !== 'rejected');

  const refresh = () => qc.invalidateQueries({ queryKey: photosKeys.all });
  const save = useMutation({
    mutationFn: () => patchPhoto(photo.id, { caption: caption.trim() || null }),
    onSuccess: () => {
      refresh();
      addToast({ type: 'success', title: t('photoArchive.saved') });
    },
    onError: (err) => addToast({ type: 'error', title: t('photoArchive.save_failed'), message: getErrorMessage(err) }),
  });
  const unlink = useMutation({
    mutationFn: (l: { target_kind: string; target_id: string }) => removeLink(photo.id, l.target_kind, l.target_id),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: () => deletePhoto(photo.id),
    onSuccess: (res) => {
      refresh();
      addToast({
        type: 'success',
        title: res.result === 'archived' ? t('photoArchive.archived') : t('photoArchive.deleted'),
      });
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: t('photoArchive.delete_failed'), message: getErrorMessage(err) }),
  });
  const from = sourceRoute(photo.source_module);
  const ownedElsewhere = photo.source_module !== 'documents';

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={photo.caption || photo.filename}
      className="fixed inset-0 z-50 flex flex-col bg-black/90 lg:flex-row"
      data-testid="photo-lightbox"
    >
      <div className="relative flex min-h-0 flex-1 items-center justify-center p-4">
        <div className="relative max-h-full max-w-full">
          <AuthImage
            src={photo.file_url}
            alt={photo.caption || photo.filename}
            className="max-h-[80vh] max-w-full object-contain"
          />
          {hazards.map((h) => {
            const style = bboxStyle(h.payload.bbox);
            return style ? (
              <div
                key={h.id}
                className="pointer-events-none absolute border-2 border-amber-400"
                style={style}
                title={String(h.payload.hazard ?? '')}
              />
            ) : null;
          })}
        </div>
        {prev && (
          <button
            type="button"
            onClick={() => onNavigate?.(prev)}
            className="absolute left-2 top-1/2 -translate-y-1/2 rounded-full bg-white/20 p-2 text-white hover:bg-white/30"
            aria-label={t('photoArchive.previous')}
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
        )}
        {next && (
          <button
            type="button"
            onClick={() => onNavigate?.(next)}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-white/20 p-2 text-white hover:bg-white/30"
            aria-label={t('photoArchive.next')}
          >
            <ChevronRight className="h-5 w-5" />
          </button>
        )}
      </div>

      <aside className="max-h-[50vh] w-full space-y-4 overflow-y-auto bg-surface-primary p-4 lg:max-h-none lg:w-96">
        <div className="flex items-start justify-between gap-2">
          <h2 className="break-all text-sm font-semibold">{photo.filename}</h2>
          <button type="button" onClick={onClose} aria-label={t('photoArchive.close')} className="rounded p-1 hover:bg-surface-secondary">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-1">
          <label htmlFor="photo-caption" className="text-xs font-medium text-content-secondary">
            {t('photoArchive.caption')}
          </label>
          <div className="flex gap-2">
            <input
              id="photo-caption"
              value={caption}
              onChange={(e) => setCaption(e.target.value)}
              className="min-w-0 flex-1 rounded border border-border-light bg-surface-primary px-2 py-1 text-sm"
            />
            <button
              type="button"
              onClick={() => save.mutate()}
              disabled={save.isPending || caption === (photo.caption ?? '')}
              className="rounded bg-oe-blue px-2 py-1 text-xs text-white disabled:opacity-50"
            >
              {t('photoArchive.save')}
            </button>
          </div>
        </div>

        <PhotoMetaEditor photo={photo} />

        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          <dt className="text-content-tertiary">{t('photoArchive.meta.taken')}</dt>
          <dd>
            {photo.taken_at ? <DateDisplay value={photo.taken_at} format="datetime" /> : t('photoArchive.undated')}
            {photo.taken_at_source && (
              <span className="ml-1 text-content-tertiary">({t(`photoArchive.meta.source_${photo.taken_at_source}`)})</span>
            )}
          </dd>
          <dt className="text-content-tertiary">{t('photoArchive.meta.location')}</dt>
          <dd>
            {photo.gps_lat != null && photo.gps_lon != null ? (
              <span className="inline-flex items-center gap-1">
                <MapPin className="h-3 w-3" aria-hidden />
                {fmtNumberForInput(photo.gps_lat, 5)}, {fmtNumberForInput(photo.gps_lon, 5)}
                {photo.gps_accuracy_m != null && (
                  <span className="text-content-tertiary">
                    {t('photoArchive.meta.accuracy', { value: Math.round(photo.gps_accuracy_m) })}
                  </span>
                )}
              </span>
            ) : (
              t('photoArchive.meta.no_location')
            )}
          </dd>
          {photo.width && photo.height ? (
            <>
              <dt className="text-content-tertiary">{t('photoArchive.meta.size')}</dt>
              <dd>
                {photo.width} × {photo.height}
              </dd>
            </>
          ) : null}
          <dt className="text-content-tertiary">{t('photoArchive.meta.evidence')}</dt>
          <dd>{t(`photoArchive.evidence.${photo.evidence_grade}`)}</dd>
          <dt className="text-content-tertiary">{t('photoArchive.meta.from')}</dt>
          <dd>
            {from ? (
              <Link to={from} className="text-oe-blue hover:underline">
                {t(`photoArchive.source.${photo.source_module}`)}
              </Link>
            ) : (
              t(`photoArchive.source.${photo.source_module}`)
            )}
          </dd>
          {photo.tags.length > 0 && (
            <>
              <dt className="text-content-tertiary">{t('photoArchive.meta.tags')}</dt>
              <dd className="flex flex-wrap gap-1">
                {photo.tags.map((tag) => (
                  <span key={tag} className="rounded bg-surface-secondary px-1.5 py-0.5">
                    {tag}
                  </span>
                ))}
              </dd>
            </>
          )}
        </dl>

        <section className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
            {t('photoArchive.links.title')}
          </h3>
          {photo.links.length === 0 ? (
            <p className="text-xs text-content-tertiary">{t('photoArchive.links.none')}</p>
          ) : (
            <ul className="space-y-1">
              {photo.links.map((l) => (
                <li key={l.id} className="flex items-center justify-between gap-2 text-xs">
                  <span className="truncate">
                    {t(`photoArchive.target.${l.target_kind}`)} · {l.target_id.slice(0, 8)}
                  </span>
                  <button
                    type="button"
                    onClick={() => unlink.mutate(l)}
                    className="text-content-tertiary hover:text-semantic-error"
                    aria-label={t('photoArchive.links.remove')}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <LinkPicker photoId={photo.id} projectId={photo.project_id} linked={photo.links} />
        </section>

        {(pins.data ?? []).length > 0 && (
          <section className="space-y-1">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
              {t('photoArchive.pins.title')}
            </h3>
            <ul className="space-y-1 text-xs">
              {(pins.data ?? []).map((p) => (
                <li key={p.id}>
                  <Link to={`/plan-room?document=${encodeURIComponent(p.document_id)}&page=${p.page}`} className="text-oe-blue hover:underline">
                    {t('photoArchive.pins.on_page', { page: p.page })}
                  </Link>
                  {p.note && <span className="ml-1 text-content-tertiary">{p.note}</span>}
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-content-secondary">{t('photoArchive.ai.title')}</h3>
          <AISuggestionList photoId={photo.id} />
        </section>

        <div className="flex gap-2 border-t border-border-light pt-3">
          <button
            type="button"
            onClick={() => downloadWithAuth(photo.file_url, photo.filename)}
            className="inline-flex items-center gap-1 rounded border border-border-light px-2 py-1 text-xs"
          >
            <Download className="h-3 w-3" aria-hidden />
            {t('photoArchive.download')}
          </button>
          <button
            type="button"
            onClick={() => setConfirmDelete(true)}
            className="inline-flex items-center gap-1 rounded border border-border-light px-2 py-1 text-xs text-semantic-error"
          >
            <Trash2 className="h-3 w-3" aria-hidden />
            {ownedElsewhere ? t('photoArchive.archive') : t('photoArchive.delete')}
          </button>
        </div>
      </aside>

      <ConfirmDialog
        open={confirmDelete}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => remove.mutate()}
        loading={remove.isPending}
        variant="danger"
        title={ownedElsewhere ? t('photoArchive.archive_title') : t('photoArchive.delete_title')}
        message={ownedElsewhere ? t('photoArchive.archive_message') : t('photoArchive.delete_message')}
        confirmLabel={ownedElsewhere ? t('photoArchive.archive') : t('photoArchive.delete')}
      />
    </div>
  );
}
