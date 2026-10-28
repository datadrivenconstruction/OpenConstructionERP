// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// InlinePdfPreviewModal - open a referenced PDF in a focused overlay without
// leaving the screen you are on (#246). Reuses the same authenticated-blob
// approach as the File Manager preview: the document download endpoints are
// bearer-protected, so a raw <iframe src> navigation 401s. We fetch the bytes
// with the Authorization header and point the iframe at the resulting blob
// URL instead. Used wherever a file is referenced from another record
// (transmittals today; inspections / NCRs as those surfaces grow a linked
// files list).

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, ExternalLink, Loader2, X } from 'lucide-react';

import {
  fetchProtectedObjectUrl,
  downloadProtectedFile,
} from '@/features/file-manager/api';

export interface InlinePdfPreviewModalProps {
  open: boolean;
  /** Bearer-protected download URL of the PDF. Null renders nothing. */
  downloadUrl: string | null;
  /** File name shown in the header and used for the download fallback. */
  title: string;
  onClose: () => void;
}

export function InlinePdfPreviewModal({
  open,
  downloadUrl,
  title,
  onClose,
}: InlinePdfPreviewModalProps) {
  const { t } = useTranslation();
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [downloading, setDownloading] = useState(false);

  // Fetch the protected bytes into a blob URL whenever the modal opens for a
  // new URL. Revoke the previous blob on cleanup so we never leak object URLs.
  useEffect(() => {
    if (!open || !downloadUrl) {
      setObjectUrl(null);
      setFailed(false);
      return;
    }
    let cancelled = false;
    let created: string | null = null;
    setObjectUrl(null);
    setFailed(false);
    void fetchProtectedObjectUrl(downloadUrl).then((url) => {
      if (cancelled) {
        if (url) URL.revokeObjectURL(url);
        return;
      }
      if (!url) {
        setFailed(true);
        return;
      }
      created = url;
      setObjectUrl(url);
    });
    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [open, downloadUrl]);

  // Close on Escape for keyboard parity with the other drawers.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const handleDownload = useCallback(async () => {
    if (!downloadUrl) return;
    setDownloading(true);
    try {
      await downloadProtectedFile(downloadUrl, title);
    } catch {
      // Best-effort - the inline viewer already shows an error state and the
      // user can retry. No toast dependency so the modal stays light.
    } finally {
      setDownloading(false);
    }
  }, [downloadUrl, title]);

  if (!open || !downloadUrl) return null;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      data-testid="inline-pdf-preview"
      onClick={onClose}
    >
      <div
        className="flex h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-lg bg-surface-elevated shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between gap-2 border-b border-border-light px-4 py-2.5">
          <span
            className="truncate text-sm font-semibold text-content-primary"
            title={title}
          >
            {title}
          </span>
          <div className="flex shrink-0 items-center gap-1">
            {objectUrl && (
              <a
                href={objectUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex h-7 items-center gap-1 rounded-md border border-border-light px-2 text-[11px] font-medium text-content-secondary hover:bg-surface-secondary"
                title={t('files.preview.open_new_tab', {
                  defaultValue: 'Open in a new tab',
                })}
              >
                <ExternalLink size={12} />
                {t('files.preview.open_new_tab_short', { defaultValue: 'New tab' })}
              </a>
            )}
            <button
              type="button"
              onClick={handleDownload}
              disabled={downloading}
              data-testid="inline-pdf-download"
              className="inline-flex h-7 items-center gap-1 rounded-md border border-border-light px-2 text-[11px] font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {downloading ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Download size={12} />
              )}
              {t('files.actions.download', { defaultValue: 'Download' })}
            </button>
            <button
              type="button"
              onClick={onClose}
              aria-label={t('common.close', { defaultValue: 'Close' })}
              data-testid="inline-pdf-close"
              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
            >
              <X size={15} />
            </button>
          </div>
        </header>

        <div className="flex-1 bg-surface-secondary/40">
          {objectUrl ? (
            <iframe
              src={objectUrl}
              title={title}
              data-testid="inline-pdf-frame"
              className="h-full w-full border-0"
            />
          ) : failed ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
              <p className="text-sm text-content-secondary">
                {t('files.preview.failed', {
                  defaultValue: 'This file could not be previewed.',
                })}
              </p>
              <button
                type="button"
                onClick={handleDownload}
                className="inline-flex items-center gap-1.5 rounded-md border border-border-light px-3 py-1.5 text-xs font-medium text-content-primary hover:bg-surface-secondary"
              >
                <Download size={13} />
                {t('files.actions.download', { defaultValue: 'Download' })}
              </button>
            </div>
          ) : (
            <div className="flex h-full items-center justify-center">
              <Loader2 size={28} className="animate-spin text-content-tertiary" />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
