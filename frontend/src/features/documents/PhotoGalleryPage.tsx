/**
 * Photo Gallery / Documentation page.
 *
 * Provides upload, gallery grid, lightbox, timeline view,
 * and filtering for project site photos.
 */

import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Upload,
  Search,
  X,
  Loader2,
  ChevronLeft,
  ChevronRight,
  Trash2,
  Pencil,
  MapPin,
  Calendar,
  Tag,
  Grid3X3,
  Clock,
  ChevronDown,
  Image as ImageIcon,
  CheckSquare,
  Sparkles,
  Check,
  ClipboardList,
  AlertTriangle,
  ShieldAlert,
  BookOpen,
} from 'lucide-react';
import { Card, Button, Badge, ConfirmDialog, EmptyState, Breadcrumb, AuthImage, SkeletonGrid } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DismissibleInfo } from '@/shared/ui/DismissibleInfo';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { apiGet } from '@/shared/lib/api';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchPhotos,
  fetchPhotoTimeline,
  uploadPhoto,
  updatePhoto,
  deletePhoto,
  getPhotoFileUrl,
  getPhotoThumbUrl,
  getCategorySuggestion,
  isGpsFromExif,
  isDateFromExif,
  type PhotoItem,
  type PhotoCategory,
  type DefectSeverity,
  type PhotoFilters,
  type PhotoTimelineGroup as _PhotoTimelineGroup,
  type PhotoUpdatePayload,
} from './api';

/* ── Constants ────────────────────────────────────────────────────────── */

const PHOTO_CATEGORIES: PhotoCategory[] = [
  'site', 'progress', 'defect', 'delivery', 'safety', 'other',
];

const CATEGORY_COLORS: Record<PhotoCategory, string> = {
  site: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  progress: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  defect: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  delivery: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  safety: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300',
  other: 'bg-gray-100 text-gray-700 dark:bg-gray-800/60 dark:text-gray-300',
};

const SEVERITY_COLORS: Record<DefectSeverity, string> = {
  low: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300',
  medium: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300',
  high: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
};

type ViewMode = 'grid' | 'timeline';

/* ── Helpers ──────────────────────────────────────────────────────────── */

function useDebounce<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '';
  try {
    return new Date(dateStr).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return dateStr;
  }
}

function formatDateFull(dateStr: string | null): string {
  if (!dateStr) return '';
  try {
    return new Date(dateStr).toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

/** Attempt to extract EXIF data from image file client-side. */
function extractExifData(file: File): Promise<{
  taken_at?: string;
  gps_lat?: number;
  gps_lon?: number;
}> {
  return new Promise((resolve) => {
    // Basic EXIF extraction from JPEG files
    if (!file.type.includes('jpeg') && !file.type.includes('jpg')) {
      resolve({});
      return;
    }
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const view = new DataView(e.target?.result as ArrayBuffer);
        // Check for JPEG SOI marker
        if (view.getUint16(0) !== 0xFFD8) { resolve({}); return; }

        let offset = 2;
        const len = view.byteLength;
        while (offset < len) {
          if (view.getUint16(offset) === 0xFFE1) {
            // APP1 marker (EXIF)
            const exifStr = String.fromCharCode(
              view.getUint8(offset + 4),
              view.getUint8(offset + 5),
              view.getUint8(offset + 6),
              view.getUint8(offset + 7),
            );
            if (exifStr === 'Exif') {
              // EXIF found but full parsing is complex;
              // use the file's lastModified as fallback date
              resolve({
                taken_at: new Date(file.lastModified).toISOString(),
              });
              return;
            }
            break;
          }
          offset += 2 + view.getUint16(offset + 2);
        }
        resolve({ taken_at: new Date(file.lastModified).toISOString() });
      } catch {
        resolve({});
      }
    };
    reader.onerror = () => resolve({});
    // Only read first 128KB for EXIF header
    reader.readAsArrayBuffer(file.slice(0, 131072));
  });
}

/* ── Lightbox ─────────────────────────────────────────────────────────── */

function Lightbox({
  photos,
  currentIndex,
  onClose,
  onNavigate,
  onEdit,
  onDelete,
  onRaise,
  onOpenDayDiary,
}: {
  photos: PhotoItem[];
  currentIndex: number;
  onClose: () => void;
  onNavigate: (index: number) => void;
  onEdit: (photo: PhotoItem) => void;
  onDelete: (photo: PhotoItem) => void;
  /** Raise a punch item / NCR / safety incident from this photo (CONN-66). */
  onRaise: (photo: PhotoItem, target: 'punch' | 'ncr' | 'safety') => void;
  /** Open the daily diary on the photo's capture day (CONN-68). */
  onOpenDayDiary: (photo: PhotoItem) => void;
}) {
  const { t } = useTranslation();
  const photo = photos[currentIndex];
  if (!photo) return null;

  const hasPrev = currentIndex > 0;
  const hasNext = currentIndex < photos.length - 1;

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowLeft' && hasPrev) onNavigate(currentIndex - 1);
      if (e.key === 'ArrowRight' && hasNext) onNavigate(currentIndex + 1);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose, onNavigate, currentIndex, hasPrev, hasNext]);

  // Prevent body scroll
  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm animate-fade-in"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={t('photos.lightbox', { defaultValue: 'Photo viewer' })}
    >
      {/* Close button */}
      <button
        onClick={onClose}
        className="absolute top-4 right-4 z-10 flex h-10 w-10 items-center justify-center rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors"
        aria-label={t('common.close', { defaultValue: 'Close' })}
      >
        <X size={20} />
      </button>

      {/* Navigation arrows */}
      {hasPrev && (
        <button
          onClick={(e) => { e.stopPropagation(); onNavigate(currentIndex - 1); }}
          className="absolute left-4 top-1/2 -translate-y-1/2 z-10 flex h-12 w-12 items-center justify-center rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors"
          aria-label={t('photos.previous', { defaultValue: 'Previous photo' })}
        >
          <ChevronLeft size={24} />
        </button>
      )}
      {hasNext && (
        <button
          onClick={(e) => { e.stopPropagation(); onNavigate(currentIndex + 1); }}
          className="absolute right-4 top-1/2 -translate-y-1/2 z-10 flex h-12 w-12 items-center justify-center rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors"
          aria-label={t('photos.next', { defaultValue: 'Next photo' })}
        >
          <ChevronRight size={24} />
        </button>
      )}

      {/* Main image */}
      <div
        className="relative max-w-[90vw] max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <AuthImage
          src={getPhotoFileUrl(photo.id)}
          alt={photo.caption || photo.filename}
          className="max-w-full max-h-[70vh] object-contain rounded-lg"
          placeholder={
            <div className="flex h-64 w-64 items-center justify-center">
              <Loader2 size={28} className="animate-spin text-white/70" />
            </div>
          }
          fallback={
            <div className="flex h-64 w-64 flex-col items-center justify-center gap-2 text-white/70">
              <ImageIcon size={40} />
              <span className="text-xs">{photo.filename}</span>
            </div>
          }
        />

        {/* Info panel */}
        <div className="mt-3 rounded-lg bg-black/60 px-5 py-3 text-white">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              {photo.caption && (
                <p className="text-sm font-medium mb-1">{photo.caption}</p>
              )}
              <p className="text-xs text-white/70">{photo.filename}</p>
              <div className="flex flex-wrap items-center gap-3 mt-2 text-xs text-white/60">
                {photo.taken_at && (
                  <span className="flex items-center gap-1">
                    <Calendar size={12} />
                    {formatDateFull(photo.taken_at)}
                  </span>
                )}
                {photo.gps_lat != null && photo.gps_lon != null && (
                  <span className="flex items-center gap-1">
                    <MapPin size={12} />
                    {photo.gps_lat.toFixed(5)}, {photo.gps_lon.toFixed(5)}
                    {isGpsFromExif(photo) && (
                      <span className="ml-1 text-white/40">
                        {t('photos.gps_auto_paren', { defaultValue: '(auto, EXIF)' })}
                      </span>
                    )}
                  </span>
                )}
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-2xs font-medium ${CATEGORY_COLORS[photo.category]}`}>
                  {t(`photos.cat_${photo.category}`, { defaultValue: photo.category })}
                </span>
              </div>
              {photo.tags.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {photo.tags.map((tag) => (
                    <span key={tag} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-white/15 text-2xs text-white/80">
                      <Tag size={10} />
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => onEdit(photo)}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-white/70 hover:bg-white/15 hover:text-white transition-colors"
                aria-label={t('common.edit', { defaultValue: 'Edit' })}
              >
                <Pencil size={16} />
              </button>
              <button
                onClick={() => onDelete(photo)}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-white/70 hover:bg-red-500/30 hover:text-red-300 transition-colors"
                aria-label={t('common.delete', { defaultValue: 'Delete' })}
              >
                <Trash2 size={16} />
              </button>
            </div>
          </div>

          {/* Turn a photo into the record it documents — a defect into a
              punch item or NCR, a safety shot into an incident, or jump to
              the diary for the day it was taken (CONN-66 / CONN-68). The
              photo id rides along so the target can attach the evidence. */}
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-white/15 pt-3">
            <span className="text-2xs uppercase tracking-wide text-white/50">
              {t('photos.raise_from', { defaultValue: 'Create from this photo' })}
            </span>
            <button
              type="button"
              onClick={() => onRaise(photo, 'punch')}
              className="inline-flex items-center gap-1.5 rounded-lg bg-white/15 px-2.5 py-1 text-xs font-medium text-white hover:bg-white/25 transition-colors"
              title={t('photos.raise_punch_hint', {
                defaultValue: 'Open a punch item prefilled from this photo',
              })}
            >
              <ClipboardList size={13} />
              {t('photos.raise_punch', { defaultValue: 'Punch item' })}
            </button>
            <button
              type="button"
              onClick={() => onRaise(photo, 'ncr')}
              className="inline-flex items-center gap-1.5 rounded-lg bg-white/15 px-2.5 py-1 text-xs font-medium text-white hover:bg-white/25 transition-colors"
              title={t('photos.raise_ncr_hint', {
                defaultValue: 'Open an NCR prefilled from this photo',
              })}
            >
              <AlertTriangle size={13} />
              {t('photos.raise_ncr', { defaultValue: 'NCR' })}
            </button>
            <button
              type="button"
              onClick={() => onRaise(photo, 'safety')}
              className="inline-flex items-center gap-1.5 rounded-lg bg-white/15 px-2.5 py-1 text-xs font-medium text-white hover:bg-white/25 transition-colors"
              title={t('photos.raise_safety_hint', {
                defaultValue: 'Open a safety incident prefilled from this photo',
              })}
            >
              <ShieldAlert size={13} />
              {t('photos.raise_safety', { defaultValue: 'Safety incident' })}
            </button>
            {(photo.taken_at || photo.created_at) && (
              <button
                type="button"
                onClick={() => onOpenDayDiary(photo)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-white/15 px-2.5 py-1 text-xs font-medium text-white hover:bg-white/25 transition-colors"
                title={t('photos.open_day_diary_hint', {
                  defaultValue: "Open the daily diary for this photo's capture day",
                })}
              >
                <BookOpen size={13} />
                {t('photos.open_day_diary', { defaultValue: 'Day diary' })}
              </button>
            )}
          </div>
        </div>

        {/* Counter */}
        <div className="text-center mt-2 text-xs text-white/50">
          {currentIndex + 1} / {photos.length}
        </div>
      </div>
    </div>
  );
}

/* ── Edit Modal ───────────────────────────────────────────────────────── */

function EditPhotoModal({
  photo,
  onClose,
  onSave,
}: {
  photo: PhotoItem;
  onClose: () => void;
  onSave: (id: string, data: PhotoUpdatePayload) => void;
}) {
  const { t } = useTranslation();
  const [caption, setCaption] = useState(photo.caption || '');
  const [category, setCategory] = useState<PhotoCategory>(photo.category);
  const [tagInput, setTagInput] = useState('');
  const [tags, setTags] = useState<string[]>([...photo.tags]);

  const handleAddTag = useCallback(() => {
    const tag = tagInput.trim();
    if (tag && !tags.includes(tag)) {
      setTags([...tags, tag]);
    }
    setTagInput('');
  }, [tagInput, tags]);

  const handleRemoveTag = useCallback((tag: string) => {
    setTags(tags.filter((t) => t !== tag));
  }, [tags]);

  const handleSubmit = useCallback(() => {
    onSave(photo.id, {
      caption: caption || undefined,
      category,
      tags,
    });
  }, [photo.id, caption, category, tags, onSave]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={t('photos.edit_photo', { defaultValue: 'Edit photo' })}
    >
      <div
        className="w-full max-w-md mx-4 rounded-xl bg-surface-elevated shadow-xl border border-border-light overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border-light">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('photos.edit_photo', { defaultValue: 'Edit photo' })}
          </h3>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-content-secondary hover:bg-surface-secondary transition-colors"
          >
            <X size={14} />
          </button>
        </div>

        {/* Form */}
        <div className="p-5 space-y-4">
          {/* Thumbnail */}
          <div className="flex justify-center">
            <AuthImage
              src={getPhotoThumbUrl(photo.id)}
              alt={photo.filename}
              className="h-32 w-auto rounded-lg object-cover"
              placeholder={
                <div className="flex h-32 w-32 items-center justify-center rounded-lg bg-surface-secondary">
                  <Loader2 size={20} className="animate-spin text-content-quaternary" />
                </div>
              }
              fallback={
                <div className="flex h-32 w-32 items-center justify-center rounded-lg bg-surface-secondary">
                  <ImageIcon size={28} className="text-content-quaternary" />
                </div>
              }
            />
          </div>

          {/* Caption */}
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">
              {t('photos.caption', { defaultValue: 'Caption' })}
            </label>
            <textarea
              value={caption}
              onChange={(e) => setCaption(e.target.value)}
              placeholder={t('photos.caption_placeholder', { defaultValue: 'Add a description...' })}
              rows={2}
              className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder-content-quaternary focus:border-oe-blue focus:ring-1 focus:ring-oe-blue/30 outline-none resize-none"
            />
          </div>

          {/* Category */}
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">
              {t('photos.category', { defaultValue: 'Category' })}
            </label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as PhotoCategory)}
              className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:border-oe-blue focus:ring-1 focus:ring-oe-blue/30 outline-none"
            >
              {PHOTO_CATEGORIES.map((cat) => (
                <option key={cat} value={cat}>
                  {t(`photos.cat_${cat}`, { defaultValue: cat })}
                </option>
              ))}
            </select>
          </div>

          {/* Tags */}
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1">
              {t('photos.tags', { defaultValue: 'Tags' })}
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleAddTag(); } }}
                placeholder={t('photos.add_tag', { defaultValue: 'Add tag...' })}
                className="flex-1 rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder-content-quaternary focus:border-oe-blue focus:ring-1 focus:ring-oe-blue/30 outline-none"
              />
              <Button size="sm" variant="secondary" onClick={handleAddTag}>
                {t('common.add', { defaultValue: 'Add' })}
              </Button>
            </div>
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {tags.map((tag) => (
                  <span key={tag} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-surface-secondary text-2xs text-content-secondary">
                    {tag}
                    <button onClick={() => handleRemoveTag(tag)} className="hover:text-red-500">
                      <X size={10} />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-border-light bg-surface-primary">
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button size="sm" onClick={handleSubmit}>
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Photo Card ───────────────────────────────────────────────────────── */

function PhotoCard({
  photo,
  onClick,
  selected,
  onToggleSelect,
  selectMode,
  onAcceptSuggestion,
}: {
  photo: PhotoItem;
  onClick: () => void;
  selected?: boolean;
  onToggleSelect?: () => void;
  selectMode?: boolean;
  onAcceptSuggestion?: (
    photo: PhotoItem,
    suggestion: ReturnType<typeof getCategorySuggestion>,
  ) => void;
}) {
  const { t } = useTranslation();

  // AI / heuristic suggestion — only surfaced when it differs from the
  // category the user already chose (no point suggesting what's set). The
  // suggestion is advisory: applying it is an explicit click.
  const suggestion = getCategorySuggestion(photo);
  const showSuggestion =
    !selectMode && suggestion !== null && suggestion.suggested_category !== photo.category;
  const confidencePct =
    suggestion?.confidence != null ? Math.round(suggestion.confidence * 100) : null;
  // Defect severity is only meaningful for a defect suggestion.
  const severity =
    suggestion?.suggested_category === 'defect' ? suggestion.defect_severity : null;
  const suggestedTags = suggestion?.suggested_tags ?? [];

  return (
    <div
      className={`group relative aspect-square rounded-xl overflow-hidden cursor-pointer border bg-surface-secondary transition-all shadow-sm hover:shadow-md ${
        selected
          ? 'border-oe-blue ring-2 ring-oe-blue/40'
          : 'border-border-light hover:border-oe-blue/30'
      }`}
      onClick={selectMode ? onToggleSelect : onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectMode ? onToggleSelect?.() : onClick(); } }}
      aria-label={photo.caption || photo.filename}
    >
      <AuthImage
        src={getPhotoThumbUrl(photo.id)}
        alt={photo.caption || photo.filename}
        className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
        loading="lazy"
        placeholder={
          <div className="absolute inset-0 flex items-center justify-center bg-surface-secondary">
            <Loader2 size={20} className="animate-spin text-content-quaternary" />
          </div>
        }
        fallback={
          <div className="absolute inset-0 flex items-center justify-center bg-surface-secondary">
            <ImageIcon size={32} className="text-content-quaternary" />
          </div>
        }
      />

      {/* Selection checkbox */}
      {(selectMode || selected) && (
        <div className="absolute top-2 right-2 z-10">
          <div
            className={`h-5 w-5 rounded-md border-2 flex items-center justify-center transition-colors ${
              selected
                ? 'bg-oe-blue border-oe-blue text-white'
                : 'bg-white/80 border-white/60 backdrop-blur-sm'
            }`}
            onClick={(e) => { e.stopPropagation(); onToggleSelect?.(); }}
          >
            {selected && (
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M2 6L5 9L10 3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
          </div>
        </div>
      )}

      {/* Category badge + EXIF GPS cue */}
      <div className="absolute top-2 left-2 flex items-center gap-1">
        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-2xs font-medium backdrop-blur-sm ${CATEGORY_COLORS[photo.category]}`}>
          {t(`photos.cat_${photo.category}`, { defaultValue: photo.category })}
        </span>
        {isGpsFromExif(photo) && photo.gps_lat != null && photo.gps_lon != null && (
          <span
            className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-2xs font-medium bg-black/50 text-white/90 backdrop-blur-sm"
            title={t('photos.gps_exif_hint', {
              defaultValue: 'Location read from photo EXIF: {{lat}}, {{lon}}',
              lat: photo.gps_lat.toFixed(5),
              lon: photo.gps_lon.toFixed(5),
            })}
          >
            <MapPin size={10} />
            {t('photos.gps_auto', { defaultValue: 'GPS' })}
          </span>
        )}
        {isDateFromExif(photo) && photo.taken_at && (
          <span
            className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-2xs font-medium bg-black/50 text-white/90 backdrop-blur-sm"
            title={t('photos.date_exif_hint', {
              defaultValue: 'Capture date read from photo EXIF: {{date}}',
              date: formatDateFull(photo.taken_at),
            })}
          >
            <Calendar size={10} />
            {t('photos.date_auto', { defaultValue: 'EXIF date' })}
          </span>
        )}
      </div>

      {/* AI-suggested category badge — user-confirmable, never auto-applied.
          Stacks the category-apply button with an advisory severity chip
          (defect only) and the first auto-tags the model saw. */}
      {showSuggestion && suggestion && (
        <div className="absolute top-2 right-2 z-10 flex flex-col items-end gap-1">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onAcceptSuggestion?.(photo, suggestion);
            }}
            title={t('photos.suggestion_apply_hint', {
              defaultValue: 'Apply suggested category "{{cat}}"',
              cat: t(`photos.cat_${suggestion.suggested_category}`, {
                defaultValue: suggestion.suggested_category,
              }),
            })}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-2xs font-medium bg-violet-600/90 text-white backdrop-blur-sm shadow-sm hover:bg-violet-500 transition-colors"
          >
            <Sparkles size={10} />
            {confidencePct != null
              ? t('photos.suggested_with_conf', {
                  defaultValue: 'AI: {{cat}} ({{pct}}%)',
                  cat: t(`photos.cat_${suggestion.suggested_category}`, {
                    defaultValue: suggestion.suggested_category,
                  }),
                  pct: confidencePct,
                })
              : t('photos.suggested', {
                  defaultValue: 'Suggest: {{cat}}',
                  cat: t(`photos.cat_${suggestion.suggested_category}`, {
                    defaultValue: suggestion.suggested_category,
                  }),
                })}
            <Check size={10} />
          </button>
          {severity && (
            <span
              className={`inline-flex items-center px-2 py-0.5 rounded-full text-2xs font-medium backdrop-blur-sm ${SEVERITY_COLORS[severity]}`}
              title={t('photos.severity_hint', {
                defaultValue: 'AI-rated defect severity: {{sev}}',
                sev: t(`photos.severity_${severity}`, { defaultValue: severity }),
              })}
            >
              {t('photos.severity_label', {
                defaultValue: 'Severity: {{sev}}',
                sev: t(`photos.severity_${severity}`, { defaultValue: severity }),
              })}
            </span>
          )}
          {suggestedTags.length > 0 && (
            <div className="flex flex-wrap justify-end gap-1 max-w-[90%]">
              {suggestedTags.slice(0, 3).map((tag) => (
                <span
                  key={tag}
                  className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-2xs font-medium bg-violet-500/70 text-white backdrop-blur-sm"
                >
                  <Tag size={9} />
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Bottom overlay */}
      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 via-black/30 to-transparent p-3 pt-8 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
        {photo.caption && (
          <p className="text-xs text-white font-medium truncate mb-1">{photo.caption}</p>
        )}
        <p className="text-2xs text-white/70">
          {formatDate(photo.taken_at || photo.created_at)}
        </p>
      </div>
    </div>
  );
}

/* ── Confirm Delete Dialog ────────────────────────────────────────────── */

function ConfirmDeleteDialog({
  photo,
  onConfirm,
  onCancel,
}: {
  photo: PhotoItem;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in"
      onClick={onCancel}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-sm mx-4 rounded-xl bg-surface-elevated shadow-xl border border-border-light p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-sm font-semibold text-content-primary mb-2">
          {t('photos.delete_confirm_title', { defaultValue: 'Delete photo?' })}
        </h3>
        <p className="text-xs text-content-secondary mb-4">
          {t('photos.delete_confirm_message', {
            defaultValue: 'Are you sure you want to delete "{{name}}"? This action cannot be undone.',
            name: photo.caption || photo.filename,
          })}
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onCancel}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button size="sm" variant="danger" onClick={onConfirm}>
            {t('common.delete', { defaultValue: 'Delete' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Upload Zone ──────────────────────────────────────────────────────── */

function UploadZone({
  projectId,
  onUploaded,
}: {
  projectId: string;
  onUploaded: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState<{ current: number; total: number } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Batch metadata — applied to every photo in this upload so the user
  // classifies once instead of editing each photo afterwards. Category
  // is the fixed taxonomy; tags are the free-form "type" labels
  // (e.g. "foundation", "rebar", "ground-floor"). Both reuse the
  // existing photo fields, so no backend change is needed.
  const [category, setCategory] = useState<PhotoCategory>('site');
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState('');

  const addTag = useCallback(() => {
    const tag = tagInput.trim();
    if (tag && !tags.includes(tag)) setTags((prev) => [...prev, tag]);
    setTagInput('');
  }, [tagInput, tags]);

  const removeTag = useCallback(
    (tag: string) => setTags((prev) => prev.filter((x) => x !== tag)),
    [],
  );

  const handleFiles = useCallback(async (files: FileList | File[]) => {
    const fileArray = Array.from(files).filter((f) => f.type.startsWith('image/'));
    if (fileArray.length === 0) {
      addToast({
        type: 'warning',
        title: t('photos.no_images', { defaultValue: 'No images found' }),
        message: t('photos.only_images', { defaultValue: 'Only image files are accepted.' }),
      });
      return;
    }

    const validFiles = fileArray;
    if (validFiles.length === 0) return;

    setUploading(true);
    let successCount = 0;

    for (let i = 0; i < validFiles.length; i++) {
      const file = validFiles[i]!;
      setProgress({ current: i + 1, total: validFiles.length });

      try {
        // Extract EXIF data
        const exif = await extractExifData(file);

        await uploadPhoto(projectId, file, {
          category,
          tags: tags.length > 0 ? tags : undefined,
          taken_at: exif.taken_at,
          gps_lat: exif.gps_lat,
          gps_lon: exif.gps_lon,
        });
        successCount++;
      } catch {
        addToast({
          type: 'error',
          title: t('photos.upload_failed', { defaultValue: 'Upload failed' }),
          message: file.name,
        });
      }
    }

    if (successCount > 0) {
      addToast({
        type: 'success',
        title: t('photos.uploaded', { defaultValue: 'Photos uploaded' }),
        message: t('photos.upload_count', {
          defaultValue: '{{count}} photo(s) uploaded successfully.',
          count: successCount,
        }),
      });
    }

    setUploading(false);
    setProgress(null);
    onUploaded();
    if (inputRef.current) inputRef.current.value = '';
  }, [projectId, addToast, t, onUploaded, category, tags]);

  return (
    <div className="space-y-3">
      {/* Batch metadata — chosen once, applied to every file in this
          upload. Lives OUTSIDE the click-to-browse drop area so using
          the controls never triggers the file dialog. */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-content-secondary mb-1">
            {t('photos.category', { defaultValue: 'Category' })}
          </label>
          <select
            value={category}
            disabled={uploading}
            onChange={(e) => setCategory(e.target.value as PhotoCategory)}
            className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:border-oe-blue focus:ring-1 focus:ring-oe-blue/30 outline-none disabled:opacity-60"
          >
            {PHOTO_CATEGORIES.map((cat) => (
              <option key={cat} value={cat}>
                {t(`photos.cat_${cat}`, { defaultValue: cat })}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-content-secondary mb-1">
            {t('photos.upload_type_tags', { defaultValue: 'Type / tags' })}
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              value={tagInput}
              disabled={uploading}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addTag(); } }}
              placeholder={t('photos.add_type_tag', { defaultValue: 'e.g. foundation, rebar...' })}
              className="flex-1 rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder-content-quaternary focus:border-oe-blue focus:ring-1 focus:ring-oe-blue/30 outline-none disabled:opacity-60"
            />
            <Button size="sm" variant="secondary" disabled={uploading} onClick={addTag}>
              {t('common.add', { defaultValue: 'Add' })}
            </Button>
          </div>
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {tags.map((tag) => (
                <span key={tag} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-surface-secondary text-2xs text-content-secondary">
                  {tag}
                  <button
                    type="button"
                    onClick={() => removeTag(tag)}
                    aria-label={t('photos.remove_tag', { defaultValue: 'Remove tag' })}
                    className="hover:text-red-500"
                  >
                    <X size={10} />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
      <p className="text-2xs text-content-quaternary">
        {t('photos.batch_meta_hint', {
          defaultValue: 'Category and tags apply to every photo in this upload - you can refine each one afterwards.',
        })}
      </p>
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
      onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files); }}
      onClick={() => inputRef.current?.click()}
      className={`relative border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all
        ${dragOver
          ? 'border-oe-blue bg-oe-blue-subtle/20 scale-[1.01]'
          : 'border-border-light hover:border-oe-blue/40 hover:bg-surface-secondary/50'}
        ${uploading ? 'pointer-events-none opacity-60' : ''}`}
      role="button"
      tabIndex={0}
      aria-label={t('photos.upload_area', { defaultValue: 'Drop photos here or click to upload' })}
    >
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        multiple
        onChange={(e) => e.target.files && handleFiles(e.target.files)}
        className="hidden"
      />
      {uploading ? (
        <div className="flex flex-col items-center gap-2">
          <Loader2 size={32} className="text-oe-blue animate-spin" />
          <p className="text-sm text-content-secondary">
            {t('photos.uploading', { defaultValue: 'Uploading...' })}
            {progress && ` (${progress.current}/${progress.total})`}
          </p>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-2">
          <Upload size={32} className="text-content-tertiary" />
          <p className="text-sm text-content-secondary">
            {t('photos.drop_or_click', { defaultValue: 'Drop photos here or click to upload' })}
          </p>
          <p className="text-2xs text-content-quaternary">
            {t('photos.supported_formats', { defaultValue: 'JPEG, PNG, WebP, HEIC.' })}
          </p>
        </div>
      )}
      </div>
    </div>
  );
}

/* ── Category Filter Dropdown ─────────────────────────────────────────── */

function CategoryFilter({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const labels: Record<string, string> = {
    all: t('photos.all_categories', { defaultValue: 'All categories' }),
    ...Object.fromEntries(
      PHOTO_CATEGORIES.map((cat) => [cat, t(`photos.cat_${cat}`, { defaultValue: cat })])
    ),
  };

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex items-center gap-1.5 h-10 px-3 text-xs font-medium rounded-lg border border-border-light text-content-secondary hover:bg-surface-secondary transition-colors"
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        {labels[value] || labels.all}
        <ChevronDown size={14} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div
          className="absolute left-0 top-full mt-1 w-44 rounded-lg border border-border-light bg-surface-elevated shadow-lg z-10 overflow-hidden"
          role="listbox"
        >
          {['all', ...PHOTO_CATEGORIES].map((cat) => (
            <button
              key={cat}
              role="option"
              aria-selected={value === cat}
              onClick={() => { onChange(cat); setOpen(false); }}
              className={`w-full text-left px-3 py-2 text-xs transition-colors ${
                value === cat
                  ? 'bg-oe-blue-subtle/30 text-oe-blue-text font-medium'
                  : 'text-content-secondary hover:bg-surface-secondary'
              }`}
            >
              {labels[cat]}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Main Component ───────────────────────────────────────────────────── */

export function PhotoGalleryPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const { confirm, ...confirmProps } = useConfirm();


  const [searchQuery, setSearchQuery] = useState('');
  const debouncedSearch = useDebounce(searchQuery, 300);
  const [category, setCategory] = useState('all');
  const [viewMode, setViewMode] = useState<ViewMode>('grid');
  const [showUpload, setShowUpload] = useState(false);

  // Lightbox state
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);

  // Edit state
  const [editPhoto, setEditPhoto] = useState<PhotoItem | null>(null);

  // Delete state
  const [deleteTarget, setDeleteTarget] = useState<PhotoItem | null>(null);

  // Batch selection state
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchDeleting, setBatchDeleting] = useState(false);

  // Projects list for selector
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<{ id: string; name: string }[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const projectId = activeProjectId || projects[0]?.id || '';

  /* ── Data fetching ──────────────────────────────────────────────────── */

  const filters: PhotoFilters = useMemo(() => ({
    category: category !== 'all' ? (category as PhotoCategory) : undefined,
    search: debouncedSearch || undefined,
  }), [category, debouncedSearch]);

  const { data: photos, isLoading: photosLoading } = useQuery({
    queryKey: ['photos', projectId, filters],
    queryFn: () => fetchPhotos(projectId!, filters),
    enabled: !!projectId,
  });

  const { data: timeline, isLoading: timelineLoading } = useQuery({
    queryKey: ['photos-timeline', projectId],
    queryFn: () => fetchPhotoTimeline(projectId!),
    enabled: !!projectId && viewMode === 'timeline',
  });

  const photoList = photos ?? [];
  const isLoading = viewMode === 'grid' ? photosLoading : timelineLoading;

  // Flattened, date-ordered photo list backing the timeline view. The
  // lightbox must page through THESE photos when timeline is active —
  // previously it always used ``photoList`` (the category/search-filtered
  // grid query), so opening a timeline photo that wasn't in the grid
  // result jumped to the wrong image (or index 0).
  const timelinePhotos = useMemo(
    () => (timeline ?? []).flatMap((g) => g.photos),
    [timeline],
  );
  const lightboxPhotos = viewMode === 'timeline' ? timelinePhotos : photoList;

  // Deep-link: `?photo={id}` (set by /files → "Open in Site Photos")
  // opens the lightbox on that photo as soon as the gallery loads. We
  // strip the param afterwards so refreshing/back-button doesn't keep
  // re-opening it. One-shot effect keyed on photoList loading.
  const [searchParams, setSearchParams] = useSearchParams();
  const deepLinkPhotoId = searchParams.get('photo');
  useEffect(() => {
    if (!deepLinkPhotoId || photoList.length === 0) return;
    const idx = photoList.findIndex((p) => p.id === deepLinkPhotoId);
    if (idx >= 0) setLightboxIndex(idx);
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('photo');
        return next;
      },
      { replace: true },
    );
  }, [deepLinkPhotoId, photoList, setSearchParams]);

  /* ── Mutations ──────────────────────────────────────────────────────── */

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: PhotoUpdatePayload }) =>
      updatePhoto(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['photos'] });
      queryClient.invalidateQueries({ queryKey: ['photos-timeline'] });
      addToast({
        type: 'success',
        title: t('photos.updated', { defaultValue: 'Photo updated' }),
      });
      setEditPhoto(null);
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('photos.update_failed', { defaultValue: 'Update failed' }),
        message: err.message,
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deletePhoto(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['photos'] });
      queryClient.invalidateQueries({ queryKey: ['photos-timeline'] });
      addToast({
        type: 'success',
        title: t('photos.deleted', { defaultValue: 'Photo deleted' }),
      });
      setDeleteTarget(null);
      setLightboxIndex(null);
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('photos.delete_failed', { defaultValue: 'Delete failed' }),
        message: err.message,
      });
    },
  });

  const handleUploaded = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['photos'] });
    queryClient.invalidateQueries({ queryKey: ['photos-timeline'] });
    setShowUpload(false);
  }, [queryClient]);

  const handleEditSave = useCallback((id: string, data: PhotoUpdatePayload) => {
    updateMutation.mutate({ id, data });
  }, [updateMutation]);

  // Field-evidence to record (CONN-66): a defect / safety photo becomes the
  // starting point for a punch item, NCR or safety incident. We open the
  // target module's create flow with ``?create=true`` (the established
  // convention used by Submittals / Transmittals) and carry the photo id +
  // a seeded caption so the new record can attach the evidence. The create
  // consumers on /punchlist, /ncr and /safety land with their own batches;
  // until then these links open the page with the params on the URL.
  const handleRaiseFromPhoto = useCallback(
    (photo: PhotoItem, target: 'punch' | 'ncr' | 'safety') => {
      const params = new URLSearchParams();
      params.set('create', 'true');
      params.set('photo_id', photo.id);
      const seed = photo.caption || photo.filename;
      if (seed) params.set('title', seed);
      const route =
        target === 'punch' ? '/punchlist' : target === 'ncr' ? '/ncr' : '/safety';
      navigate(`${route}?${params.toString()}`);
    },
    [navigate],
  );

  // Photo timeline to diary (CONN-68): jump to the daily diary for the day
  // the photo was captured. Daily Diary reads ``?date=YYYY-MM-DD`` (consumer
  // lands with the diary batch); the link is already useful as it opens the
  // diary scoped to the active project.
  const handleOpenDayDiary = useCallback(
    (photo: PhotoItem) => {
      const stamp = photo.taken_at || photo.created_at;
      const day = stamp ? stamp.slice(0, 10) : '';
      const params = new URLSearchParams();
      if (day) params.set('date', day);
      const qs = params.toString();
      navigate(`/daily-diary${qs ? `?${qs}` : ''}`);
    },
    [navigate],
  );

  // Accept an AI / heuristic category suggestion. This is the explicit
  // human-confirm step — it PATCHes the category to the suggested value and
  // merges any auto-tags the model saw into the photo's existing tags. The
  // manual fields stay authoritative until the user clicks.
  const handleAcceptSuggestion = useCallback(
    (photo: PhotoItem, suggestion: ReturnType<typeof getCategorySuggestion>) => {
      if (!suggestion) return;
      const data: PhotoUpdatePayload = { category: suggestion.suggested_category };
      if (suggestion.suggested_tags.length > 0) {
        const merged = [...photo.tags];
        for (const tag of suggestion.suggested_tags) {
          if (!merged.includes(tag)) merged.push(tag);
        }
        data.tags = merged;
      }
      updateMutation.mutate({ id: photo.id, data });
    },
    [updateMutation],
  );

  // Batch selection helpers
  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(photoList.map((p) => p.id)));
  }, [photoList]);

  const deselectAll = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const exitSelectMode = useCallback(() => {
    setSelectMode(false);
    setSelectedIds(new Set());
  }, []);

  const handleBatchDelete = useCallback(async () => {
    if (selectedIds.size === 0) return;
    const confirmed = await confirm({
      title: t('photos.batch_delete_title', {
        defaultValue: 'Delete photos?',
      }),
      message: t('photos.batch_delete_confirm', {
        defaultValue: 'Delete {{count}} photo(s)? This cannot be undone.',
        count: selectedIds.size,
      }),
      confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
      variant: 'danger',
    });
    if (!confirmed) return;
    setBatchDeleting(true);
    let ok = 0;
    let fail = 0;
    for (const id of selectedIds) {
      try {
        await deletePhoto(id);
        ok++;
      } catch {
        fail++;
      }
    }
    setBatchDeleting(false);
    if (ok > 0) {
      addToast({
        type: 'success',
        title: t('photos.batch_deleted', { defaultValue: '{{count}} photo(s) deleted', count: ok }),
      });
    }
    if (fail > 0) {
      addToast({
        type: 'error',
        title: t('photos.batch_delete_failed', { defaultValue: '{{count}} photo(s) failed to delete', count: fail }),
      });
    }
    queryClient.invalidateQueries({ queryKey: ['photos'] });
    queryClient.invalidateQueries({ queryKey: ['photos-timeline'] });
    exitSelectMode();
  }, [selectedIds, confirm, addToast, t, queryClient, exitSelectMode]);

  // Stats
  const categoryStats = useMemo(() => {
    const stats: Record<string, number> = {};
    for (const p of photoList) {
      stats[p.category] = (stats[p.category] || 0) + 1;
    }
    return stats;
  }, [photoList]);

  /* ── Render ─────────────────────────────────────────────────────────── */

  if (!projectId) {
    return (
      <div className="space-y-6">
        <RequiresProject
          emptyHint={t('photos.select_project', {
            defaultValue: 'Select a project from the header to view its photo documentation.',
          })}
        >{null}</RequiresProject>
      </div>
    );
  }

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Breadcrumb — single item auto-hides; the Home icon IS the dashboard
          link, so no literal "Dashboard" item. */}
      <Breadcrumb
        items={[
          { label: t('photos.title', { defaultValue: 'Project Photos' }) },
        ]}
      />

      {/* Canonical header: subtitle + actions, srTitle for screen readers.
          The module name lives in the top app bar; project selection is
          global (we read the shared project context only). */}
      <PageHeader
        srTitle={t('photos.title', { defaultValue: 'Project Photos' })}
        subtitle={t('photos.subtitle', {
          defaultValue: '{{count}} photos',
          count: photoList.length,
        })}
        actions={
          <>
            {photoList.length > 0 && !selectMode && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setSelectMode(true)}
                className="shrink-0 whitespace-nowrap"
              >
                <CheckSquare size={14} className="mr-1.5 shrink-0" />
                <span className="whitespace-nowrap">{t('photos.select', { defaultValue: 'Select' })}</span>
              </Button>
            )}
            <Button
              onClick={() => setShowUpload(!showUpload)}
              size="sm"
              disabled={!projectId}
              className="shrink-0 whitespace-nowrap"
            >
              <Upload size={14} className="mr-1.5 shrink-0" />
              <span className="whitespace-nowrap">{t('photos.upload_photos', { defaultValue: 'Upload Photos' })}</span>
            </Button>
          </>
        }
      />

      {/* Info card (canonical, pain-named copy from MODULE_INTRO_COPY) */}
      <DismissibleInfo
        storageKey="photos"
        title={t('photos.intro_title', {
          defaultValue: 'Prove what the site looked like, when',
        })}
        links={[
          {
            label: t('nav.project_files', { defaultValue: 'Files' }),
            onClick: () => navigate('/files'),
          },
          {
            label: t('photos.intro_link_punch', { defaultValue: 'Punch list' }),
            onClick: () => navigate('/punchlist'),
          },
          {
            label: t('photos.intro_link_diary', { defaultValue: 'Daily diary' }),
            onClick: () => navigate('/daily-diary'),
          },
        ]}
      >
        {t('photos.intro_body', {
          defaultValue:
            'Upload site photos and the gallery reads EXIF capture date and GPS on the way in, so progress, defects, deliveries and safety shots sort chronologically and on a timeline. Tag and caption in batches, and accept the suggested category when it spots a likely defect. The photos sit beside the rest of the project files in the File Manager.',
        })}
      </DismissibleInfo>

      {/* Batch selection bar */}
      {selectMode && (
        <div className="flex items-center gap-3 px-4 py-2.5 rounded-xl bg-oe-blue-subtle/30 border border-oe-blue/20">
          <span className="text-sm font-medium text-content-primary">
            {selectedIds.size > 0
              ? t('photos.selected_count', { defaultValue: '{{count}} selected', count: selectedIds.size })
              : t('photos.select_photos', { defaultValue: 'Click photos to select' })}
          </span>
          <div className="flex items-center gap-1.5 ml-auto">
            <Button variant="ghost" size="sm" onClick={selectedIds.size === photoList.length ? deselectAll : selectAll}>
              {selectedIds.size === photoList.length
                ? t('photos.deselect_all', { defaultValue: 'Deselect All' })
                : t('photos.select_all', { defaultValue: 'Select All' })}
            </Button>
            {selectedIds.size > 0 && (
              <Button variant="danger" size="sm" onClick={handleBatchDelete} loading={batchDeleting} className="shrink-0 whitespace-nowrap">
                <Trash2 size={14} className="mr-1 shrink-0" />
                <span className="whitespace-nowrap">{t('photos.delete_selected', { defaultValue: 'Delete ({{count}})', count: selectedIds.size })}</span>
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={exitSelectMode} className="shrink-0 whitespace-nowrap">
              <X size={14} className="mr-1 shrink-0" />
              <span className="whitespace-nowrap">{t('common.cancel', { defaultValue: 'Cancel' })}</span>
            </Button>
          </div>
        </div>
      )}

      {/* Stats summary (only when there are photos) */}
      {photoList.length > 0 && Object.keys(categoryStats).length > 0 && !selectMode && (
        <div className="flex items-center gap-2 flex-wrap text-xs">
          <span className="font-semibold text-content-primary bg-surface-secondary px-2 py-1 rounded-md">
            {t('photos.total', { defaultValue: 'Total' })}: {photoList.length}
          </span>
          <span className="text-border-light select-none">|</span>
          {Object.entries(categoryStats).map(([cat, count]) => (
            <span
              key={cat}
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-2xs font-medium ${CATEGORY_COLORS[cat as PhotoCategory] || 'bg-gray-100 text-gray-600'}`}
            >
              {t(`photos.cat_${cat}`, { defaultValue: cat })}
              <span className="font-bold">{count}</span>
            </span>
          ))}
        </div>
      )}

      {/* Upload zone */}
      {showUpload && (
        <UploadZone projectId={projectId} onUploaded={handleUploaded} />
      )}

      {/* Filters bar */}
      <Card className="p-3">
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
          {/* Search */}
          <div className="relative flex-1">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-content-quaternary" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('photos.search_placeholder', { defaultValue: 'Search captions, filenames...' })}
              className="w-full rounded-lg border border-border-light bg-surface-primary pl-9 pr-8 py-2 text-sm text-content-primary placeholder-content-quaternary focus:border-oe-blue focus:ring-1 focus:ring-oe-blue/30 outline-none"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-content-quaternary hover:text-content-secondary"
              >
                <X size={14} />
              </button>
            )}
          </div>

          {/* Category filter */}
          <CategoryFilter value={category} onChange={setCategory} />

          {/* View toggle */}
          <div className="flex items-center rounded-lg border border-border-light overflow-hidden">
            <button
              onClick={() => setViewMode('grid')}
              className={`flex items-center gap-1.5 h-10 px-3 text-xs font-medium transition-colors ${
                viewMode === 'grid'
                  ? 'bg-oe-blue-subtle text-oe-blue-text'
                  : 'text-content-secondary hover:bg-surface-secondary'
              }`}
              aria-label={t('photos.grid_view', { defaultValue: 'Grid view' })}
            >
              <Grid3X3 size={14} />
              {t('photos.grid', { defaultValue: 'Grid' })}
            </button>
            <button
              onClick={() => setViewMode('timeline')}
              className={`flex items-center gap-1.5 h-10 px-3 text-xs font-medium transition-colors ${
                viewMode === 'timeline'
                  ? 'bg-oe-blue-subtle text-oe-blue-text'
                  : 'text-content-secondary hover:bg-surface-secondary'
              }`}
              aria-label={t('photos.timeline_view', { defaultValue: 'Timeline view' })}
            >
              <Clock size={14} />
              {t('photos.timeline', { defaultValue: 'Timeline' })}
            </button>
          </div>
        </div>
      </Card>

      {/* Content */}
      {isLoading ? (
        <SkeletonGrid items={8} gridCols="grid-cols-2 sm:grid-cols-3 lg:grid-cols-4" />
      ) : photoList.length === 0 && viewMode === 'grid' ? (
        <EmptyState
          icon={<ImageIcon size={28} strokeWidth={1.5} />}
          title={
            searchQuery || category !== 'all'
              ? t('photos.no_match_title', { defaultValue: 'No matching photos' })
              : t('photos.empty_title', { defaultValue: 'No photos yet' })
          }
          description={
            searchQuery || category !== 'all'
              ? t('photos.no_match_description', {
                  defaultValue: 'Try adjusting your search or category filter.',
                })
              : t('photos.empty_description', {
                  defaultValue: 'Upload photos to document your project progress, site conditions, and more.',
                })
          }
          action={
            searchQuery || category !== 'all'
              ? undefined
              : (
                <Button onClick={() => setShowUpload(true)} size="sm" variant="secondary">
                  <Upload size={16} className="mr-2 shrink-0" />
                  <span>{t('photos.upload_first', { defaultValue: 'Upload your first photo' })}</span>
                </Button>
              )
          }
        />
      ) : viewMode === 'grid' ? (
        /* Grid view */
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
          {photoList.map((photo, idx) => (
            <PhotoCard
              key={photo.id}
              photo={photo}
              onClick={() => setLightboxIndex(idx)}
              selectMode={selectMode}
              selected={selectedIds.has(photo.id)}
              onToggleSelect={() => toggleSelect(photo.id)}
              onAcceptSuggestion={handleAcceptSuggestion}
            />
          ))}
        </div>
      ) : (
        /* Timeline view */
        <div className="space-y-8">
          {(timeline ?? []).map((group) => (
            <div key={group.date}>
              <div className="flex items-center gap-3 mb-4">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-secondary">
                  <Calendar size={14} className="text-content-tertiary" />
                </div>
                <h3 className="text-sm font-semibold text-content-primary">
                  {formatDate(group.date)}
                </h3>
                <Badge variant="neutral">
                  {group.photos.length}
                </Badge>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3 ml-11">
                {group.photos.map((photo) => {
                  // Index into the flattened timeline list (the lightbox
                  // source while timeline view is active).
                  const globalIdx = timelinePhotos.findIndex((p) => p.id === photo.id);
                  return (
                    <PhotoCard
                      key={photo.id}
                      photo={photo}
                      onClick={() => setLightboxIndex(globalIdx >= 0 ? globalIdx : 0)}
                      selectMode={selectMode}
                      selected={selectedIds.has(photo.id)}
                      onToggleSelect={() => toggleSelect(photo.id)}
                      onAcceptSuggestion={handleAcceptSuggestion}
                    />
                  );
                })}
              </div>
            </div>
          ))}
          {(!timeline || timeline.length === 0) && (
            <EmptyState
              icon={<ImageIcon size={28} strokeWidth={1.5} />}
              title={t('photos.empty_title', { defaultValue: 'No photos yet' })}
              description={t('photos.empty_description', {
                defaultValue: 'Upload photos to document your project progress, site conditions, and more.',
              })}
              action={
                <Button onClick={() => setShowUpload(true)} size="sm" variant="secondary">
                  <Upload size={16} className="mr-2 shrink-0" />
                  <span>{t('photos.upload_first', { defaultValue: 'Upload your first photo' })}</span>
                </Button>
              }
            />
          )}
        </div>
      )}

      {/* Lightbox */}
      {lightboxIndex !== null && lightboxPhotos.length > 0 && (
        <Lightbox
          photos={lightboxPhotos}
          currentIndex={lightboxIndex}
          onClose={() => setLightboxIndex(null)}
          onNavigate={setLightboxIndex}
          onEdit={(photo) => { setLightboxIndex(null); setEditPhoto(photo); }}
          onDelete={(photo) => { setLightboxIndex(null); setDeleteTarget(photo); }}
          onRaise={(photo, target) => { setLightboxIndex(null); handleRaiseFromPhoto(photo, target); }}
          onOpenDayDiary={(photo) => { setLightboxIndex(null); handleOpenDayDiary(photo); }}
        />
      )}

      {/* Edit modal */}
      {editPhoto && (
        <EditPhotoModal
          photo={editPhoto}
          onClose={() => setEditPhoto(null)}
          onSave={handleEditSave}
        />
      )}

      {/* Delete confirmation */}
      {deleteTarget && (
        <ConfirmDeleteDialog
          photo={deleteTarget}
          onConfirm={() => deleteMutation.mutate(deleteTarget.id)}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      {/* Mobile PWA — Slice 1. Bottom-anchored quick-action FAB visible
          only on viewports ≤640px; opens the upload sheet for fast
          site capture from a phone. ≥44×44 tap target. */}
      <button
        type="button"
        onClick={() => setShowUpload(true)}
        disabled={!projectId}
        aria-label={t('photos.upload', { defaultValue: 'Upload Photos' })}
        className="fixed bottom-5 right-5 z-40 inline-flex h-14 w-14 min-h-[44px] min-w-[44px] items-center justify-center rounded-full bg-oe-blue text-white shadow-lg ring-1 ring-black/5 transition-transform hover:scale-105 active:scale-95 disabled:opacity-50 disabled:hover:scale-100 sm:hidden"
      >
        <Upload size={22} />
      </button>
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
