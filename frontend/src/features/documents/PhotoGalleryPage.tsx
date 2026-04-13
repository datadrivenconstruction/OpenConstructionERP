/**
 * Photo Gallery / Documentation page.
 *
 * Provides upload, gallery grid, lightbox, timeline view,
 * and filtering for project site photos.
 */

import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Camera,
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
} from 'lucide-react';
import { Card, Button, Badge, EmptyState, Breadcrumb } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchPhotos,
  fetchPhotoTimeline,
  uploadPhoto,
  updatePhoto,
  deletePhoto,
  getPhotoFileUrl,
  type PhotoItem,
  type PhotoCategory,
  type PhotoFilters,
  type PhotoTimelineGroup as _PhotoTimelineGroup,
  type PhotoUpdatePayload,
} from './api';

/* ── Constants ────────────────────────────────────────────────────────── */

const PHOTO_CATEGORIES: PhotoCategory[] = [
  'site', 'progress', 'defect', 'delivery', 'safety', 'other',
];

const MAX_PHOTO_SIZE_BYTES = 50 * 1024 * 1024; // 50 MB

const CATEGORY_COLORS: Record<PhotoCategory, string> = {
  site: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  progress: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  defect: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  delivery: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  safety: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300',
  other: 'bg-gray-100 text-gray-700 dark:bg-gray-800/60 dark:text-gray-300',
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
}: {
  photos: PhotoItem[];
  currentIndex: number;
  onClose: () => void;
  onNavigate: (index: number) => void;
  onEdit: (photo: PhotoItem) => void;
  onDelete: (photo: PhotoItem) => void;
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
        <img
          src={getPhotoFileUrl(photo.id)}
          alt={photo.caption || photo.filename}
          className="max-w-full max-h-[70vh] object-contain rounded-lg"
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in"
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
            className="flex h-7 w-7 items-center justify-center rounded-lg text-content-secondary hover:bg-surface-secondary transition-colors"
          >
            <X size={14} />
          </button>
        </div>

        {/* Form */}
        <div className="p-5 space-y-4">
          {/* Thumbnail */}
          <div className="flex justify-center">
            <img
              src={getPhotoFileUrl(photo.id)}
              alt={photo.filename}
              className="h-32 w-auto rounded-lg object-cover"
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
}: {
  photo: PhotoItem;
  onClick: () => void;
  selected?: boolean;
  onToggleSelect?: () => void;
  selectMode?: boolean;
}) {
  const { t } = useTranslation();

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
      <img
        src={getPhotoFileUrl(photo.id)}
        alt={photo.caption || photo.filename}
        className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
        loading="lazy"
        onError={(e) => {
          const target = e.currentTarget;
          target.style.display = 'none';
          const parent = target.parentElement;
          if (parent && !parent.querySelector('.photo-fallback')) {
            const fallback = document.createElement('div');
            fallback.className = 'photo-fallback absolute inset-0 flex items-center justify-center bg-surface-secondary';
            fallback.innerHTML = '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="text-content-quaternary"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>';
            parent.appendChild(fallback);
          }
        }}
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

      {/* Category badge */}
      <div className="absolute top-2 left-2">
        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-2xs font-medium backdrop-blur-sm ${CATEGORY_COLORS[photo.category]}`}>
          {t(`photos.cat_${photo.category}`, { defaultValue: photo.category })}
        </span>
      </div>

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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in"
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

    const oversized = fileArray.filter((f) => f.size > MAX_PHOTO_SIZE_BYTES);
    if (oversized.length > 0) {
      addToast({
        type: 'warning',
        title: t('photos.files_too_large', { defaultValue: 'Files too large' }),
        message: t('photos.max_size_warning', {
          defaultValue: '{{count}} file(s) exceed the 50 MB limit.',
          count: oversized.length,
        }),
      });
    }

    const validFiles = fileArray.filter((f) => f.size <= MAX_PHOTO_SIZE_BYTES);
    if (validFiles.length === 0) return;

    setUploading(true);
    let successCount = 0;
    let failCount = 0;

    for (let i = 0; i < validFiles.length; i++) {
      const file = validFiles[i]!;
      setProgress({ current: i + 1, total: validFiles.length });

      try {
        // Extract EXIF data
        const exif = await extractExifData(file);

        await uploadPhoto(projectId, file, {
          category: 'site',
          taken_at: exif.taken_at,
          gps_lat: exif.gps_lat,
          gps_lon: exif.gps_lon,
        });
        successCount++;
      } catch (err) {
        failCount++;
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
  }, [projectId, addToast, t, onUploaded]);

  return (
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
            {t('photos.supported_formats', { defaultValue: 'JPEG, PNG, WebP, HEIC. Max 50 MB per file.' })}
          </p>
        </div>
      )}
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
                  ? 'bg-oe-blue-subtle/30 text-oe-blue font-medium'
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
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);


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
  }, [selectedIds, addToast, t, queryClient, exitSelectMode]);

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
      <div className="space-y-6 p-6 max-w-7xl mx-auto">
        <EmptyState
          icon={<Camera size={28} strokeWidth={1.5} />}
          title={t('photos.no_project', { defaultValue: 'No project selected' })}
          description={t('photos.select_project', {
            defaultValue: 'Select a project from the header to view its photo documentation.',
          })}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6 max-w-7xl mx-auto animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          { label: t('photos.title', { defaultValue: 'Project Photos' }) },
        ]}
      />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle">
            <Camera size={20} className="text-oe-blue" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-content-primary">
              {t('photos.title', { defaultValue: 'Project Photos' })}
            </h1>
            <p className="text-xs text-content-tertiary">
              {t('photos.subtitle', {
                defaultValue: '{{count}} photos',
                count: photoList.length,
              })}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0 flex-nowrap">
          {/* Project selector */}
          {projects.length > 0 && (
            <select
              value={projectId}
              onChange={(e) => {
                const p = projects.find((pr) => pr.id === e.target.value);
                if (p) useProjectContextStore.getState().setActiveProject(p.id, p.name);
              }}
              className="h-8 rounded-lg border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-colors pr-7 appearance-none cursor-pointer max-w-[180px]"
            >
              <option value="" disabled>{t('photos.select_project', { defaultValue: 'Select project...' })}</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          )}
          {/* Select mode toggle */}
          {photoList.length > 0 && !selectMode && (
            <Button variant="ghost" size="sm" onClick={() => setSelectMode(true)} className="shrink-0 whitespace-nowrap">
              <CheckSquare size={14} className="mr-1.5 shrink-0" />
              <span className="whitespace-nowrap">{t('photos.select', { defaultValue: 'Select' })}</span>
            </Button>
          )}
          <Button onClick={() => setShowUpload(!showUpload)} size="sm" disabled={!projectId} className="shrink-0 whitespace-nowrap">
            <Upload size={14} className="mr-1.5 shrink-0" />
            <span className="whitespace-nowrap">{t('photos.upload_photos', { defaultValue: 'Upload Photos' })}</span>
          </Button>
        </div>
      </div>

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
                  ? 'bg-oe-blue-subtle text-oe-blue'
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
                  ? 'bg-oe-blue-subtle text-oe-blue'
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
        <div className="flex items-center justify-center py-20">
          <Loader2 size={32} className="text-oe-blue animate-spin" />
        </div>
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
                  // Find the global index for lightbox navigation
                  const globalIdx = photoList.findIndex((p) => p.id === photo.id);
                  return (
                    <PhotoCard
                      key={photo.id}
                      photo={photo}
                      onClick={() => setLightboxIndex(globalIdx >= 0 ? globalIdx : 0)}
                      selectMode={selectMode}
                      selected={selectedIds.has(photo.id)}
                      onToggleSelect={() => toggleSelect(photo.id)}
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
      {lightboxIndex !== null && photoList.length > 0 && (
        <Lightbox
          photos={photoList}
          currentIndex={lightboxIndex}
          onClose={() => setLightboxIndex(null)}
          onNavigate={setLightboxIndex}
          onEdit={(photo) => { setLightboxIndex(null); setEditPhoto(photo); }}
          onDelete={(photo) => { setLightboxIndex(null); setDeleteTarget(photo); }}
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
    </div>
  );
}
