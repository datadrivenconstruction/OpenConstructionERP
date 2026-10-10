// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * PhotosTab — project-detail tab showing all photo uploads as a
 * masonry-style grid with filter, sort, search, upload CTA and a
 * keyboard-driven lightbox.
 *
 * Data: pulls from the file-manager's ``useFileList`` hook with
 * ``{ category: 'photo' }`` so we don't duplicate the API layer.
 * Upload: reuses the existing ``UploadDialog`` with ``defaultKind='photo'``.
 *
 * Every visible string goes through ``t('projects.photos.<key>', …)``
 * with an EN ``defaultValue`` so other locales can fall through to EN
 * until they're translated.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Image as ImageIcon,
  Upload,
  Search,
  X,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { Button, EmptyState, Skeleton, AuthImage } from '@/shared/ui';
import { useFileList } from '@/features/file-manager/hooks';
import { UploadDialog } from '@/features/file-manager/components/UploadDialog';
import type { FileRow } from '@/features/file-manager/types';
import { fmtFixed } from '@/shared/lib/formatters';
import { matchesSearch } from '@/shared/lib/highlightMatch';

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Pretty-print a byte count using the same step sizes as FilePreviewPane. */
export function fmtBytes(bytes: number): string {
  if (!bytes) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${fmtFixed(bytes / 1024, 1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${fmtFixed(bytes / (1024 * 1024), 1)} MB`;
  return `${fmtFixed(bytes / (1024 * 1024 * 1024), 2)} GB`;
}

/** Pick the best "captured at" timestamp:
 *  EXIF date from ``row.extra`` (set by the photo importer when present),
 *  falling back to the file's mtime.
 */
function pickCapturedAt(row: FileRow): string | null {
  const extra = row.extra ?? {};
  const exif =
    (extra as Record<string, unknown>).captured_at ??
    (extra as Record<string, unknown>).exif_date ??
    (extra as Record<string, unknown>).date_taken;
  if (typeof exif === 'string' && exif) return exif;
  return row.modified_at;
}

function fmtDate(iso: string | null, locale = 'en'): string {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleDateString(locale, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return iso;
  }
}

type SortKey = 'newest' | 'oldest' | 'largest';

function sortRows(rows: FileRow[], sort: SortKey): FileRow[] {
  const copy = rows.slice();
  switch (sort) {
    case 'newest':
      return copy.sort((a, b) => {
        const at = pickCapturedAt(a) ?? '';
        const bt = pickCapturedAt(b) ?? '';
        return bt.localeCompare(at);
      });
    case 'oldest':
      return copy.sort((a, b) => {
        const at = pickCapturedAt(a) ?? '';
        const bt = pickCapturedAt(b) ?? '';
        return at.localeCompare(bt);
      });
    case 'largest':
      return copy.sort((a, b) => (b.size_bytes ?? 0) - (a.size_bytes ?? 0));
  }
}

// ── Component ────────────────────────────────────────────────────────────────

export interface PhotosTabProps {
  /** Project being viewed. ``null``/``undefined`` renders an "active project
   *  required" empty state so the tab is mountable even with no context. */
  projectId: string | null | undefined;
}

export function PhotosTab({ projectId }: PhotosTabProps): React.ReactElement {
  const { t, i18n } = useTranslation();
  const locale = i18n?.language ?? 'en';

  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<SortKey>('newest');
  const [uploadOpen, setUploadOpen] = useState(false);
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);

  // Pull every photo for this project. Backend already filters by kind,
  // so we don't need to refilter client-side — but we do want to sort &
  // text-filter locally without paying a round-trip per keystroke.
  const list = useFileList(projectId ?? null, { category: 'photo', limit: 500 });

  const photos: FileRow[] = useMemo(() => list.data?.items ?? [], [list.data]);

  const filtered: FileRow[] = useMemo(() => {
    const matched = search.trim()
      ? photos.filter((r) => matchesSearch(search, r.name))
      : photos;
    return sortRows(matched, sort);
  }, [photos, search, sort]);

  const openLightbox = useCallback((index: number) => {
    setLightboxIndex(index);
  }, []);

  const closeLightbox = useCallback(() => {
    setLightboxIndex(null);
  }, []);

  const stepLightbox = useCallback(
    (delta: number) => {
      setLightboxIndex((current) => {
        if (current === null) return current;
        const next = current + delta;
        if (next < 0 || next >= filtered.length) return current;
        return next;
      });
    },
    [filtered.length],
  );

  // Keyboard handler for the lightbox.
  useEffect(() => {
    if (lightboxIndex === null) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeLightbox();
      else if (e.key === 'ArrowLeft') stepLightbox(-1);
      else if (e.key === 'ArrowRight') stepLightbox(1);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [lightboxIndex, closeLightbox, stepLightbox]);

  // ── No active project ────────────────────────────────────────────────────
  if (!projectId) {
    return (
      <div data-testid="photos-tab-no-project" className="py-10">
        <EmptyState
          icon={<ImageIcon size={28} strokeWidth={1.5} />}
          title={t('projects.photos.no_project', {
            defaultValue: 'No active project',
          })}
          description={t('projects.photos.no_project_desc', {
            defaultValue: 'Open a project to view and upload photos.',
          })}
        />
      </div>
    );
  }

  // ── Loading ──────────────────────────────────────────────────────────────
  if (list.isLoading) {
    return (
      <div
        data-testid="photos-tab-loading"
        className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3"
      >
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} height={180} className="w-full" rounded="lg" />
        ))}
      </div>
    );
  }

  // ── Empty state (no photos in project) ───────────────────────────────────
  if (photos.length === 0) {
    return (
      <>
        <div data-testid="photos-tab-empty" className="py-10">
          <EmptyState
            icon={<ImageIcon size={28} strokeWidth={1.5} />}
            title={t('projects.photos.empty_title', {
              defaultValue: 'No photos yet',
            })}
            description={t('projects.photos.empty_desc', {
              defaultValue:
                'Upload site photos to keep visual records alongside the project.',
            })}
            action={
              <Button
                variant="primary"
                size="md"
                icon={<Upload size={16} />}
                onClick={() => setUploadOpen(true)}
                data-testid="photos-tab-upload-empty"
              >
                {t('projects.photos.upload_cta', { defaultValue: 'Upload photos' })}
              </Button>
            }
          />
        </div>
        <UploadDialog
          open={uploadOpen}
          projectId={projectId}
          defaultKind="photo"
          onClose={() => setUploadOpen(false)}
        />
      </>
    );
  }

  // ── Photos present: filter bar + grid + (optional) lightbox ──────────────
  const activePhoto =
    lightboxIndex !== null && lightboxIndex >= 0 && lightboxIndex < filtered.length
      ? filtered[lightboxIndex]
      : null;

  return (
    <div data-testid="photos-tab" className="space-y-4">
      {/* Filter / sort / upload bar */}
      <div className="flex flex-wrap items-center gap-2 sm:gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search
            size={14}
            className="absolute start-3 top-1/2 -translate-y-1/2 text-content-tertiary pointer-events-none"
          />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('projects.photos.search_placeholder', {
              defaultValue: 'Search filename…',
            })}
            className="w-full h-9 ps-8 pe-3 text-sm rounded-lg bg-surface-secondary/60 border border-border-light text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
            data-testid="photos-tab-search"
            aria-label={t('projects.photos.search_aria', {
              defaultValue: 'Search photos by filename',
            })}
          />
        </div>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          className="h-9 px-3 text-sm rounded-lg bg-surface-secondary/60 border border-border-light text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
          data-testid="photos-tab-sort"
          aria-label={t('projects.photos.sort_aria', { defaultValue: 'Sort photos' })}
        >
          <option value="newest">
            {t('projects.photos.sort_newest', { defaultValue: 'Newest first' })}
          </option>
          <option value="oldest">
            {t('projects.photos.sort_oldest', { defaultValue: 'Oldest first' })}
          </option>
          <option value="largest">
            {t('projects.photos.sort_largest', { defaultValue: 'Largest first' })}
          </option>
        </select>
        <Button
          variant="primary"
          size="sm"
          icon={<Upload size={14} />}
          onClick={() => setUploadOpen(true)}
          data-testid="photos-tab-upload"
        >
          {t('projects.photos.upload_cta', { defaultValue: 'Upload photos' })}
        </Button>
      </div>

      {/* Result count */}
      <div className="text-xs text-content-tertiary tabular-nums">
        {t('projects.photos.count_label', {
          defaultValue: '{{count}} of {{total}} photos',
          count: filtered.length,
          total: photos.length,
        })}
      </div>

      {/* Grid */}
      {filtered.length === 0 ? (
        <div data-testid="photos-tab-no-matches" className="py-10">
          <EmptyState
            icon={<Search size={28} strokeWidth={1.5} />}
            title={t('projects.photos.no_matches', {
              defaultValue: 'No matching photos',
            })}
            description={t('projects.photos.no_matches_desc', {
              defaultValue: 'Try adjusting your search query.',
            })}
          />
        </div>
      ) : (
        <div
          data-testid="photos-tab-grid"
          className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3"
        >
          {filtered.map((row, idx) => {
            const captured = pickCapturedAt(row);
            return (
              <button
                key={row.id}
                type="button"
                onClick={() => openLightbox(idx)}
                data-testid={`photos-tab-tile-${row.id}`}
                className="group relative flex flex-col text-left rounded-lg overflow-hidden bg-surface-secondary border border-border-light hover:border-oe-blue hover:shadow-md focus:outline-none focus:ring-2 focus:ring-oe-blue transition-all"
                aria-label={t('projects.photos.open_photo_aria', {
                  defaultValue: 'Open {{name}}',
                  name: row.name,
                })}
              >
                <div className="relative aspect-square w-full bg-surface-tertiary">
                  {row.thumbnail_url ? (
                    <AuthImage
                      src={row.thumbnail_url}
                      alt={row.name}
                      loading="lazy"
                      className="absolute inset-0 h-full w-full object-cover"
                      placeholder={
                        <div className="absolute inset-0 flex items-center justify-center text-content-tertiary">
                          <ImageIcon size={32} strokeWidth={1.5} />
                        </div>
                      }
                      fallback={
                        <div className="absolute inset-0 flex items-center justify-center text-content-tertiary">
                          <ImageIcon size={32} strokeWidth={1.5} />
                        </div>
                      }
                    />
                  ) : (
                    <div className="absolute inset-0 flex items-center justify-center text-content-tertiary">
                      <ImageIcon size={32} strokeWidth={1.5} />
                    </div>
                  )}
                </div>
                <div className="p-2 space-y-0.5">
                  <div
                    className="text-xs font-medium text-content-primary truncate"
                    title={row.name}
                  >
                    {row.name}
                  </div>
                  <div className="flex items-center justify-between text-[11px] text-content-tertiary">
                    <span>{fmtDate(captured, locale)}</span>
                    <span className="tabular-nums">{fmtBytes(row.size_bytes ?? 0)}</span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* Lightbox */}
      {activePhoto && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={t('projects.photos.lightbox_aria', {
            defaultValue: 'Photo viewer',
          })}
          data-testid="photos-tab-lightbox"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-sm"
          onClick={closeLightbox}
        >
          {/* Close */}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              closeLightbox();
            }}
            className="absolute top-4 right-4 z-10 flex h-10 w-10 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20 focus:outline-none focus:ring-2 focus:ring-white"
            data-testid="photos-tab-lightbox-close"
            aria-label={t('projects.photos.close_aria', { defaultValue: 'Close' })}
          >
            <X size={20} />
          </button>

          {/* Prev */}
          {lightboxIndex !== null && lightboxIndex > 0 && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                stepLightbox(-1);
              }}
              className="absolute left-4 top-1/2 -translate-y-1/2 z-10 flex h-12 w-12 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20 focus:outline-none focus:ring-2 focus:ring-white"
              data-testid="photos-tab-lightbox-prev"
              aria-label={t('projects.photos.prev_aria', { defaultValue: 'Previous' })}
            >
              <ChevronLeft size={22} />
            </button>
          )}

          {/* Next */}
          {lightboxIndex !== null && lightboxIndex < filtered.length - 1 && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                stepLightbox(1);
              }}
              className="absolute right-4 top-1/2 -translate-y-1/2 z-10 flex h-12 w-12 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20 focus:outline-none focus:ring-2 focus:ring-white"
              data-testid="photos-tab-lightbox-next"
              aria-label={t('projects.photos.next_aria', { defaultValue: 'Next' })}
            >
              <ChevronRight size={22} />
            </button>
          )}

          {/* Image */}
          <div
            className="max-w-[90vw] max-h-[85vh] flex flex-col items-center"
            onClick={(e) => e.stopPropagation()}
          >
            {activePhoto.download_url ? (
              <AuthImage
                src={activePhoto.download_url}
                alt={activePhoto.name}
                className="max-w-full max-h-[80vh] object-contain rounded shadow-2xl"
                data-testid="photos-tab-lightbox-image"
                placeholder={
                  <div className="flex h-64 w-64 items-center justify-center rounded bg-white/10 text-white">
                    <ImageIcon size={40} strokeWidth={1.25} className="animate-pulse" />
                  </div>
                }
                fallback={
                  <div className="flex h-64 w-64 items-center justify-center rounded bg-white/10 text-white">
                    <ImageIcon size={40} strokeWidth={1.25} />
                  </div>
                }
              />
            ) : (
              <div className="flex h-64 w-64 items-center justify-center rounded bg-white/10 text-white">
                <ImageIcon size={40} strokeWidth={1.25} />
              </div>
            )}
            <div className="mt-3 text-center text-white">
              <div className="text-sm font-medium truncate max-w-[80vw]">
                {activePhoto.name}
              </div>
              <div className="text-xs text-white/70 mt-0.5">
                {fmtDate(pickCapturedAt(activePhoto), locale)}
                {' · '}
                {fmtBytes(activePhoto.size_bytes ?? 0)}
                {' · '}
                {t('projects.photos.position_label', {
                  defaultValue: '{{current}} / {{total}}',
                  current: (lightboxIndex ?? 0) + 1,
                  total: filtered.length,
                })}
              </div>
            </div>
          </div>
        </div>
      )}

      <UploadDialog
        open={uploadOpen}
        projectId={projectId}
        defaultKind="photo"
        onClose={() => setUploadOpen(false)}
      />
    </div>
  );
}

export default PhotosTab;
