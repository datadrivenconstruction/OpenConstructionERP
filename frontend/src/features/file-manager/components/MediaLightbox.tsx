// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// MediaLightbox - view an image or play a video in a focused full-screen
// overlay without leaving the screen you are on (#284 follow-up, ITEM 10).
//
// Generic uploads land as kind="document" with an image/video extension and
// used to fall through to PDF Takeoff (the document kind's default module),
// which cannot render them. This gives them a proper viewer: an authenticated
// <img> for images (via the shared AuthImage) and an authenticated
// <video controls> for clips. Both download endpoints are bearer-protected,
// so a raw <video src> / <img src> navigation 401s - we reuse the same
// authed-blob approach the InlinePdfPreviewModal uses (fetchProtectedObjectUrl)
// for the video element, and AuthImage already handles the image case.
//
// Optional prev/next lets the File Manager step through every visible media
// row without closing the overlay; single-file callers pass a one-item list
// and the arrows hide themselves.

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ChevronLeft,
  ChevronRight,
  Download,
  Loader2,
  X,
} from 'lucide-react';

import { AuthImage } from '@/shared/ui';
import { downloadProtectedFile, mintEmailLink } from '../api';
import { isVideoRow, type MediaRowLike } from '../kindModule';

/** One viewable media file. A trimmed FileRow is assignable to this. */
export interface MediaLightboxItem extends MediaRowLike {
  id: string;
  name: string;
}

export interface MediaLightboxProps {
  open: boolean;
  /** The media rows available to page through. Empty renders nothing. */
  items: MediaLightboxItem[];
  /** Index into ``items`` of the file currently shown. */
  index: number;
  onClose: () => void;
  /** Optional - omit to disable prev/next (single-file callers). */
  onIndexChange?: (nextIndex: number) => void;
}

export function MediaLightbox({
  open,
  items,
  index,
  onClose,
  onIndexChange,
}: MediaLightboxProps) {
  const { t } = useTranslation();
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoFailed, setVideoFailed] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);

  // Guard the index against an out-of-range value (the list can shrink while
  // the overlay is open) so we never read ``undefined`` under
  // noUncheckedIndexedAccess.
  const safeIndex = Math.min(Math.max(index, 0), Math.max(items.length - 1, 0));
  const current: MediaLightboxItem | undefined = items[safeIndex];
  const isVideo = current ? isVideoRow(current) : false;
  const downloadUrl = current?.download_url ?? null;
  const currentId = current?.id ?? null;
  const canPage = Boolean(onIndexChange) && items.length > 1;

  const goPrev = useCallback(() => {
    if (!onIndexChange || items.length < 2) return;
    onIndexChange((safeIndex - 1 + items.length) % items.length);
  }, [onIndexChange, items.length, safeIndex]);

  const goNext = useCallback(() => {
    if (!onIndexChange || items.length < 2) return;
    onIndexChange((safeIndex + 1) % items.length);
  }, [onIndexChange, items.length, safeIndex]);

  // For a VIDEO, mint a short-lived signed URL and let the native <video>
  // element stream it with HTTP Range requests, instead of pre-downloading the
  // entire clip into a blob first (which left a large site video stuck on the
  // spinner and risked running the tab out of memory). The bearer-only download
  // route can't be a media ``src`` directly - a media subresource can't carry
  // the auth header - so we exchange the session for a short-lived HMAC share
  // link the browser streams anonymously (the share endpoint now serves via a
  // Range-capable FileResponse). Images still go through AuthImage, which owns
  // its own blob lifecycle.
  useEffect(() => {
    if (!open || !isVideo || !currentId) {
      setVideoUrl(null);
      setVideoFailed(false);
      return;
    }
    let cancelled = false;
    setVideoUrl(null);
    setVideoFailed(false);
    void mintEmailLink(currentId, 1)
      .then((link) => {
        if (cancelled) return;
        if (link?.url) {
          setVideoUrl(link.url);
        } else {
          setVideoFailed(true);
        }
      })
      .catch(() => {
        if (!cancelled) setVideoFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [open, isVideo, currentId]);

  // Lock background scroll and give the overlay initial focus while open, so
  // it behaves like a real modal: the page underneath does not scroll behind
  // the backdrop, and Escape / Tab work without a prior click.
  useEffect(() => {
    if (!open) return undefined;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialogRef.current?.focus();
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, [open]);

  // Keyboard parity with the other overlays: Escape closes, arrows page, and
  // Tab is trapped inside the dialog. Arrow keys are NOT intercepted while the
  // <video> is focused so its native controls can seek.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === 'Tab') {
        const node = dialogRef.current;
        if (!node) return;
        const focusable = node.querySelectorAll<HTMLElement>(
          'button, [href], video, [tabindex]:not([tabindex="-1"])',
        );
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (!first || !last) return;
        const active = document.activeElement;
        if (e.shiftKey && (active === first || active === node)) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
        return;
      }
      // Let a focused <video> handle arrows as seek; only page when focus is
      // elsewhere (the backdrop, a button, the image).
      if ((e.target as HTMLElement | null)?.tagName === 'VIDEO') return;
      if (e.key === 'ArrowLeft') {
        goPrev();
      } else if (e.key === 'ArrowRight') {
        goNext();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose, goPrev, goNext]);

  const handleDownload = useCallback(async () => {
    if (!downloadUrl || !current) return;
    setDownloading(true);
    try {
      await downloadProtectedFile(downloadUrl, current.name);
    } catch {
      // Best-effort - the overlay already shows an error state for failed
      // video loads and the user can retry. Kept toast-free so the overlay
      // stays light (mirrors InlinePdfPreviewModal).
    } finally {
      setDownloading(false);
    }
  }, [downloadUrl, current]);

  if (!open || !current || !downloadUrl) return null;

  return (
    <div
      ref={dialogRef}
      tabIndex={-1}
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 p-4 outline-none"
      role="dialog"
      aria-modal="true"
      aria-label={current.name}
      data-testid="media-lightbox"
      onClick={onClose}
    >
      {/* Header bar - file name + download + close. Sits above the media. */}
      <div
        className="absolute inset-x-0 top-0 z-10 flex items-center justify-between gap-2 bg-gradient-to-b from-black/60 to-transparent px-4 py-3"
        onClick={(e) => e.stopPropagation()}
      >
        <span
          className="truncate text-sm font-semibold text-white"
          title={current.name}
        >
          {current.name}
          {canPage && (
            <span className="ms-2 text-xs font-normal text-white/70 tabular-nums">
              {safeIndex + 1} / {items.length}
            </span>
          )}
        </span>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={handleDownload}
            disabled={downloading}
            data-testid="media-lightbox-download"
            className="inline-flex h-8 items-center gap-1 rounded-md border border-white/30 px-2 text-[11px] font-medium text-white hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {downloading ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <Download size={13} />
            )}
            {t('files.actions.download', { defaultValue: 'Download' })}
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            data-testid="media-lightbox-close"
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-white/80 hover:bg-white/10 hover:text-white"
          >
            <X size={18} />
          </button>
        </div>
      </div>

      {/* Prev / next arrows - hidden for a single-file view. */}
      {canPage && (
        <>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              goPrev();
            }}
            aria-label={t('common.previous', { defaultValue: 'Previous' })}
            data-testid="media-lightbox-prev"
            className="absolute left-2 top-1/2 z-10 inline-flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-black/40 text-white hover:bg-black/60"
          >
            <ChevronLeft size={22} />
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              goNext();
            }}
            aria-label={t('common.next', { defaultValue: 'Next' })}
            data-testid="media-lightbox-next"
            className="absolute right-2 top-1/2 z-10 inline-flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-black/40 text-white hover:bg-black/60"
          >
            <ChevronRight size={22} />
          </button>
        </>
      )}

      {/* Media stage. Stop propagation so a click on the media itself does
          not close the overlay (only the surrounding backdrop does). */}
      <div
        className="flex max-h-full max-w-full items-center justify-center"
        onClick={(e) => e.stopPropagation()}
      >
        {isVideo ? (
          videoUrl ? (
            <video
              src={videoUrl}
              controls
              autoPlay
              playsInline
              onError={() => setVideoFailed(true)}
              data-testid="media-lightbox-video"
              className="max-h-[85vh] max-w-[90vw] rounded-lg shadow-2xl"
            />
          ) : videoFailed ? (
            <MediaError onDownload={handleDownload} />
          ) : (
            <Loader2 size={32} className="animate-spin text-white/80" />
          )
        ) : (
          <AuthImage
            // Key by id so switching items re-mounts AuthImage and it
            // re-fetches the new file's bytes instead of showing the prior one.
            key={current.id}
            src={downloadUrl}
            alt={current.name}
            data-testid="media-lightbox-image"
            className="max-h-[85vh] max-w-[90vw] rounded-lg object-contain shadow-2xl"
            placeholder={
              <Loader2 size={32} className="animate-spin text-white/80" />
            }
            fallback={<MediaError onDownload={handleDownload} />}
          />
        )}
      </div>
    </div>
  );
}

function MediaError({ onDownload }: { onDownload: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 text-center">
      <p className="text-sm text-white/80">
        {t('files.preview.media_failed', {
          defaultValue: 'This file could not be displayed here.',
        })}
      </p>
      <button
        type="button"
        onClick={onDownload}
        className="inline-flex items-center gap-1.5 rounded-md border border-white/30 px-3 py-1.5 text-xs font-medium text-white hover:bg-white/10"
      >
        <Download size={13} />
        {t('files.actions.download', { defaultValue: 'Download' })}
      </button>
    </div>
  );
}
