// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// The photos linked to one record (a BOQ position, punch item, activity...), embeddable anywhere.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Images } from 'lucide-react';
import { AuthImage } from '@/shared/ui';
import { fetchByTarget, photosKeys, type ArchivePhoto, type TargetKind } from '../api';
import { PhotoUploadDropzone } from './PhotoUploadDropzone';
import { PhotoLightbox } from './PhotoLightbox';

export interface PhotoStripProps {
  projectId: string | null | undefined;
  kind: TargetKind;
  targetId: string | null | undefined;
  /** Show the camera / upload button; off for read-only surfaces. */
  canUpload?: boolean;
  /** A register with its own gallery passes its module name, so only photos linked from elsewhere show. */
  hideSource?: string;
  className?: string;
}

export function PhotoStrip({ projectId, kind, targetId, canUpload = true, hideSource, className }: PhotoStripProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState<ArchivePhoto | null>(null);
  const enabled = Boolean(projectId && targetId);
  const { data, isLoading, isError } = useQuery({
    queryKey: photosKeys.byTarget(projectId ?? '', kind, targetId ?? ''),
    queryFn: () => fetchByTarget(projectId!, kind, targetId!),
    enabled,
    staleTime: 30_000,
  });
  if (!enabled) return null;
  const photos = (data ?? []).filter((p) => !hideSource || p.source_module !== hideSource);

  return (
    <section className={`space-y-2 ${className ?? ''}`} data-testid="photo-strip" aria-label={t('photoArchive.strip.title')}>
      <div className="flex items-center justify-between">
        <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-secondary">
          <Images className="h-3.5 w-3.5" aria-hidden />
          {hideSource ? t('photoArchive.strip.title_linked') : t('photoArchive.strip.title')}
          {photos.length > 0 && <span className="text-content-tertiary">({photos.length})</span>}
        </h4>
        <Link
          to={`/photos?view=grid&target_kind=${kind}&target_id=${encodeURIComponent(targetId!)}`}
          className="text-xs text-oe-blue hover:underline"
        >
          {t('photoArchive.strip.open_archive')}
        </Link>
      </div>
      {isLoading ? (
        <div className="flex gap-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-16 w-16 animate-pulse rounded bg-surface-secondary" />
          ))}
        </div>
      ) : isError ? (
        <p className="text-xs text-semantic-error">{t('photoArchive.strip.load_failed')}</p>
      ) : photos.length === 0 ? (
        <p className="text-xs text-content-tertiary">{t('photoArchive.strip.empty')}</p>
      ) : (
        <ul className="flex gap-2 overflow-x-auto pb-1">
          {photos.map((p) => (
            <li key={p.id} className="shrink-0">
              <button
                type="button"
                onClick={() => setOpen(p)}
                className="block h-16 w-16 overflow-hidden rounded border border-border-light focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
                aria-label={p.caption || p.filename}
              >
                <AuthImage src={p.thumb_url} alt={p.caption || p.filename} className="h-full w-full object-cover" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {canUpload && <PhotoUploadDropzone projectId={projectId!} target={{ kind, id: targetId! }} compact />}
      {open && <PhotoLightbox photo={open} photos={photos} onClose={() => setOpen(null)} onNavigate={setOpen} />}
    </section>
  );
}
