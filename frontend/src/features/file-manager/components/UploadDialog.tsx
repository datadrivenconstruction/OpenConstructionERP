// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Upload dialog — multi-file uploader for the file manager.
 *
 * Routes each upload to the endpoint that owns its kind so files land in
 * the right pipeline instead of all becoming generic documents:
 *   - BIM models (RVT / IFC / …) → POST /api/v1/bim_hub/upload-cad/
 *   - DWG / DXF drawings        → POST /api/v1/dwg_takeoff/drawings/upload/
 *   - everything else           → POST /api/v1/documents/upload/
 * The dedicated BIM/DWG endpoints stream the body server-side, so a large
 * model still uploads safely; only the documents path uses the resumable
 * chunked client (which assembles into the document store). Completed
 * uploads roll up into the same FloatingQueuePanel used everywhere else.
 */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { UploadCloud, X, FileUp } from 'lucide-react';
import clsx from 'clsx';
import { useFileUpload } from '../useFileUpload';
import type { FileKind } from '../types';

interface UploadDialogProps {
  open: boolean;
  projectId: string;
  defaultKind: FileKind | null;
  onClose: () => void;
}

export function UploadDialog({
  open,
  projectId,
  defaultKind,
  onClose,
}: UploadDialogProps) {
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  // The upload routine is shared with the page-level drag-and-drop drop zone
  // (see ``useFileUpload``) so both surfaces hit the exact same pipeline.
  const { doUpload, uploading } = useFileUpload(projectId);

  // Reset the hidden input + close the dialog once the batch is queued.
  const handleFiles = (files: FileList | File[]) => {
    void doUpload(files, defaultKind, () => {
      if (fileInputRef.current) fileInputRef.current.value = '';
      onClose();
    });
  };

  // Lock background scroll when modal is open.
  useEffect(() => {
    if (!open) return;
    const original = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = original;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t('files.upload', { defaultValue: 'Upload files' })}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg mx-4 rounded-xl bg-surface-elevated shadow-2xl border border-border-light overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-border-light">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('files.upload', { defaultValue: 'Upload files' })}
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
          >
            <X size={14} />
          </button>
        </div>

        <div className="p-5">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              if (e.target.files && e.target.files.length > 0) {
                handleFiles(e.target.files);
              }
            }}
          />

          <div
            role="button"
            tabIndex={0}
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                fileInputRef.current?.click();
              }
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={(e) => {
              e.preventDefault();
              setDragOver(false);
            }}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              if (e.dataTransfer.files.length > 0) handleFiles(e.dataTransfer.files);
            }}
            className={clsx(
              'flex flex-col items-center justify-center text-center cursor-pointer',
              'rounded-xl border-2 border-dashed py-10 px-6 transition-all',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-1',
              dragOver
                ? 'border-oe-blue bg-oe-blue/5 scale-[1.005] shadow-md'
                : 'border-border-medium bg-gradient-to-br from-blue-50/60 via-transparent to-violet-50/40 dark:from-blue-950/20 dark:to-violet-950/20 hover:border-oe-blue/50',
            )}
          >
            <div
              className={clsx(
                'mb-3 flex h-14 w-14 items-center justify-center rounded-xl transition-all',
                dragOver
                  ? 'bg-oe-blue/15'
                  : 'bg-gradient-to-br from-oe-blue/10 to-violet-500/10',
              )}
            >
              <UploadCloud size={26} className="text-oe-blue" />
            </div>
            <p className="text-sm font-semibold text-content-primary">
              {dragOver
                ? t('files.upload_drop_here', { defaultValue: 'Drop files to upload' })
                : t('files.upload_drag', { defaultValue: 'Drag & drop files here' })}
            </p>
            <p className="mt-1 text-xs text-content-tertiary">
              {t('files.upload_hint', {
                defaultValue: 'PDF, images, Excel, DWG, IFC - any file type',
              })}
            </p>
            <button
              type="button"
              disabled={uploading}
              onClick={(e) => {
                e.stopPropagation();
                fileInputRef.current?.click();
              }}
              className="mt-4 inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold bg-oe-blue text-white hover:bg-oe-blue-hover shadow-sm transition-colors disabled:opacity-60"
            >
              <FileUp size={14} />
              {t('files.upload_browse', { defaultValue: 'Browse files' })}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
