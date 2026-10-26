// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Photo capture + gallery for a punch item.
 *
 * Wires up the shipped-but-unsurfaced photo endpoints:
 *   - upload  POST   /v1/punchlist/items/{id}/photos/       (uploadPunchPhoto)
 *   - delete  DELETE /v1/punchlist/items/{id}/photos/{index}(deletePunchPhoto)
 *
 * A punch photo is stored as a relative path and cross-linked as a Document
 * (category "photo", name = the stored filename). There is no static route for
 * the raw path, so each thumbnail is resolved to its cross-linked document and
 * streamed through the authenticated documents download endpoint as a blob.
 * When the cross-link is missing (the backend creates it best-effort) the tile
 * falls back to a clear "preview unavailable" state; upload and delete still
 * work because they key off the punch item id and photo index, not the URL.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Camera,
  ImageOff,
  Loader2,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import { Button } from '@/shared/ui';
import { API_BASE, getAuthToken } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { isOnline } from '@/shared/lib/offline/connectivity';
import { isLocalId } from '@/shared/lib/offline/offlineStore';
import { isNetworkError, queuePhoto } from '@/shared/lib/offline/recordSync';
import {
  deletePunchPhoto,
  fetchPunchPhotoDocuments,
  uploadPunchPhoto,
  type PunchItem,
} from './api';

/* ── Authenticated image loader ───────────────────────────────────────── */

interface AuthedImage {
  url: string | null;
  loading: boolean;
  error: boolean;
}

/**
 * Stream a document through the authenticated download endpoint and expose it
 * as an object URL. Revokes the URL on unmount / id change so blobs never leak.
 */
function useAuthedImageUrl(docId: string | undefined): AuthedImage {
  const [state, setState] = useState<AuthedImage>({
    url: null,
    loading: Boolean(docId),
    error: false,
  });

  useEffect(() => {
    if (!docId) {
      setState({ url: null, loading: false, error: !docId });
      return;
    }
    let cancelled = false;
    let objectUrl: string | null = null;
    setState({ url: null, loading: true, error: false });
    (async () => {
      try {
        const token = getAuthToken();
        const res = await fetch(`${API_BASE}/v1/documents/${docId}/download/`, {
          headers: {
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
            'X-DDC-Client': 'OE/1.0',
          },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const blob = await res.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setState({ url: objectUrl, loading: false, error: false });
      } catch {
        if (!cancelled) setState({ url: null, loading: false, error: true });
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [docId]);

  return state;
}

/* ── Single thumbnail ─────────────────────────────────────────────────── */

function PhotoThumb({
  docId,
  index,
  resolving,
  onOpen,
  onDelete,
  deleting,
}: {
  docId: string | undefined;
  index: number;
  /** True while the photo->document map is still loading. */
  resolving: boolean;
  onOpen: (url: string) => void;
  onDelete: (index: number) => void;
  deleting: boolean;
}) {
  const { t } = useTranslation();
  const { url, loading, error } = useAuthedImageUrl(docId);
  const [confirming, setConfirming] = useState(false);
  const busy = loading || resolving;

  // Auto-disarm the inline delete confirm so a stray click can't leave the
  // tile stuck in the confirming state.
  useEffect(() => {
    if (!confirming) return;
    const timer = window.setTimeout(() => setConfirming(false), 4000);
    return () => window.clearTimeout(timer);
  }, [confirming]);

  return (
    <div className="group relative aspect-square overflow-hidden rounded-lg border border-border-light bg-surface-secondary">
      {busy ? (
        <div className="flex h-full w-full items-center justify-center">
          <Loader2 size={18} className="animate-spin text-content-tertiary" />
        </div>
      ) : url ? (
        <button
          type="button"
          onClick={() => onOpen(url)}
          className="h-full w-full focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
          title={t('punch.photo_view', { defaultValue: 'View photo' })}
        >
          <img
            src={url}
            alt={t('punch.photo_alt', {
              defaultValue: 'Punch item photo {{n}}',
              n: index + 1,
            })}
            className="h-full w-full object-cover transition-transform group-hover:scale-105"
          />
        </button>
      ) : (
        <div className="flex h-full w-full flex-col items-center justify-center gap-1 px-2 text-center">
          <ImageOff size={18} className="text-content-quaternary" />
          <span className="text-2xs text-content-quaternary">
            {error
              ? t('punch.photo_preview_unavailable', { defaultValue: 'Preview unavailable' })
              : t('punch.photo_no_preview', { defaultValue: 'No preview' })}
          </span>
        </div>
      )}

      {/* Delete control - inline two-step confirm so a mis-tap can't wipe a
          site photo. */}
      {confirming ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 bg-black/60 p-2 text-center">
          <span className="text-2xs font-medium text-white">
            {t('punch.photo_delete_confirm', { defaultValue: 'Delete this photo?' })}
          </span>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => onDelete(index)}
              disabled={deleting}
              className="inline-flex items-center gap-1 rounded-md bg-semantic-error px-2 py-1 text-2xs font-semibold text-white hover:bg-red-700 disabled:opacity-60"
            >
              {deleting ? <Loader2 size={11} className="animate-spin" /> : <Trash2 size={11} />}
              {t('common.delete', { defaultValue: 'Delete' })}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              disabled={deleting}
              className="rounded-md bg-white/90 px-2 py-1 text-2xs font-medium text-gray-800 hover:bg-white disabled:opacity-60"
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          aria-label={t('punch.photo_delete', { defaultValue: 'Delete photo' })}
          title={t('punch.photo_delete', { defaultValue: 'Delete photo' })}
          className="absolute right-1 top-1 inline-flex h-6 w-6 items-center justify-center rounded-md bg-black/45 text-white opacity-0 transition-opacity hover:bg-black/70 focus:opacity-100 focus:outline-none group-hover:opacity-100"
        >
          <Trash2 size={12} />
        </button>
      )}
    </div>
  );
}

/* ── Lightbox ─────────────────────────────────────────────────────────── */

function Lightbox({ url, onClose }: { url: string; onClose: () => void }) {
  const { t } = useTranslation();
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', handler, { capture: true });
    return () => document.removeEventListener('keydown', handler, { capture: true });
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <button
        type="button"
        onClick={onClose}
        aria-label={t('common.close', { defaultValue: 'Close' })}
        className="absolute right-4 top-4 inline-flex h-9 w-9 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20"
      >
        <X size={18} />
      </button>
      {/* Stop propagation so clicking the image itself does not close. */}
      <img
        src={url}
        alt={t('punch.photo_full_alt', { defaultValue: 'Punch item photo' })}
        onClick={(e) => e.stopPropagation()}
        className="max-h-full max-w-full rounded-lg object-contain shadow-2xl"
      />
    </div>
  );
}

/* ── Gallery ──────────────────────────────────────────────────────────── */

export function PunchPhotoGallery({
  item,
  projectId,
  onChanged,
}: {
  item: PunchItem;
  projectId: string;
  /** Called after a successful upload/delete so the parent can refetch. */
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const photos = useMemo(() => item.photos ?? [], [item.photos]);
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const [deletingIndex, setDeletingIndex] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);

  // Resolve stored photo paths -> cross-linked document ids so thumbnails can
  // stream through the authenticated documents download endpoint.
  const { data: photoDocs = [], isLoading: docsLoading } = useQuery({
    queryKey: ['punchlist-photo-docs', projectId],
    queryFn: () => fetchPunchPhotoDocuments(projectId),
    enabled: Boolean(projectId) && photos.length > 0,
    staleTime: 30_000,
  });

  const nameToDocId = useMemo(() => {
    const map = new Map<string, string>();
    for (const doc of photoDocs) {
      if (doc.name) map.set(doc.name, doc.id);
    }
    return map;
  }, [photoDocs]);

  const resolveDocId = useCallback(
    (path: string): string | undefined => {
      const basename = path.split('/').pop() ?? path;
      return nameToDocId.get(basename);
    },
    [nameToDocId],
  );

  const uploadMut = useMutation({
    mutationFn: async (file: File) => {
      // Offline (or an item that only exists on this device): keep the photo in
      // IndexedDB; it uploads after the item is on the server.
      const keepOnDevice = async () => {
        await queuePhoto('punch', item.id, file);
        addToast({
          type: 'info',
          title: t('offline_sync.photo_saved_on_device', { defaultValue: 'Photo saved on this device' }),
          message: t('offline_sync.photo_uploads_later', {
            defaultValue: 'It uploads when you are back online.',
          }),
        });
        return item;
      };
      if (!isOnline() || isLocalId(item.id)) return keepOnDevice();
      try {
        return await uploadPunchPhoto(item.id, file);
      } catch (err) {
        if (isNetworkError(err)) return keepOnDevice();
        throw err;
      }
    },
    onSuccess: () => {
      // A new photo cross-links a fresh Document; refresh the resolver map so
      // the thumbnail resolves instead of falling back to "preview unavailable".
      qc.invalidateQueries({ queryKey: ['punchlist-photo-docs', projectId] });
      onChanged();
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('punch.photo_upload_failed', { defaultValue: 'Photo upload failed' }),
        message: e.message,
      }),
  });

  const delMut = useMutation({
    mutationFn: (index: number) => deletePunchPhoto(item.id, index),
    onSuccess: () => {
      onChanged();
      addToast({
        type: 'success',
        title: t('punch.photo_deleted', { defaultValue: 'Photo removed' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
    onSettled: () => setDeletingIndex(null),
  });

  const handleFiles = useCallback(
    async (files: FileList | null) => {
      if (!files || files.length === 0) return;
      // Upload sequentially: the backend appends to the photos array, so
      // parallel writes could race on the same row.
      let uploaded = 0;
      for (const file of Array.from(files)) {
        try {
          await uploadMut.mutateAsync(file);
          uploaded += 1;
        } catch {
          // Per-file error already toasted by the mutation; keep going so one
          // bad file does not abort the rest of the batch.
        }
      }
      if (uploaded > 0) {
        addToast({
          type: 'success',
          title: t('punch.photo_uploaded', {
            defaultValue: '{{count}} photo(s) added',
            count: uploaded,
          }),
        });
      }
    },
    [uploadMut, addToast, t],
  );

  const onFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      void handleFiles(e.target.files);
      // Reset so selecting the same file again re-triggers change.
      e.target.value = '';
    },
    [handleFiles],
  );

  const handleDelete = useCallback(
    (index: number) => {
      setDeletingIndex(index);
      delMut.mutate(index);
    },
    [delMut],
  );

  const uploading = uploadMut.isPending;

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
          {t('punch.photos_section', { defaultValue: 'Photos' })}
          {photos.length > 0 && (
            <span className="ml-1.5 text-content-quaternary">({photos.length})</span>
          )}
        </h4>
        <div className="flex items-center gap-1.5">
          {/* Camera capture - opens the device camera on mobile, a file
              picker on desktop (the capture hint is ignored there). */}
          <input
            ref={cameraInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            className="sr-only"
            onChange={onFileChange}
          />
          <Button
            variant="secondary"
            size="sm"
            onClick={() => cameraInputRef.current?.click()}
            disabled={uploading}
            icon={<Camera size={14} />}
          >
            {t('punch.photo_take', { defaultValue: 'Camera' })}
          </Button>
          {/* Multi-select file upload. */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            className="sr-only"
            onChange={onFileChange}
          />
          <Button
            variant="secondary"
            size="sm"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            icon={uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
          >
            {uploading
              ? t('punch.photo_uploading', { defaultValue: 'Uploading...' })
              : t('punch.photo_upload', { defaultValue: 'Upload' })}
          </Button>
        </div>
      </div>

      {photos.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border-light px-4 py-6 text-center">
          <Camera size={22} className="mx-auto mb-2 text-content-quaternary" strokeWidth={1.5} />
          <p className="text-xs text-content-tertiary">
            {t('punch.photos_empty', {
              defaultValue: 'No photos yet. Add a photo of the issue so the fixer knows exactly what to look for.',
            })}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
          {photos.map((path, index) => (
            <PhotoThumb
              key={`${path}-${index}`}
              docId={resolveDocId(path)}
              index={index}
              resolving={docsLoading}
              onOpen={(url) => setLightboxUrl(url)}
              onDelete={handleDelete}
              deleting={deletingIndex === index}
            />
          ))}
        </div>
      )}

      {lightboxUrl && <Lightbox url={lightboxUrl} onClose={() => setLightboxUrl(null)} />}
    </div>
  );
}
