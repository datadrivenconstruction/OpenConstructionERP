// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * ImageSourceSelector — the "Photo / Drawing" source picker for the
 * MatchWizard (step 3).
 *
 * The estimator drops or picks a single site photo, hand sketch or CAD
 * elevation screenshot. The backend's ImageSourceAdapter then asks the
 * configured vision-LLM to enumerate the visible construction elements
 * with rough quantity estimates (MAPPING_PROCESS.md §3.1 / §4.1.4).
 *
 * This component is deliberately presentational + self-validating: it
 * holds no server state, accepts PNG / JPG / WebP up to 10 MB, renders a
 * live preview thumbnail, supports HTML5 drag-and-drop with a fallback
 * file-input picker, and surfaces a clear, inline error on rejection.
 * Selection is lifted to the parent via ``onPick`` so the wizard's
 * single source-of-truth (``Source``) stays canonical.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Image as ImageIcon, Sparkles, UploadCloud, X } from 'lucide-react';
import clsx from 'clsx';
import { fmtFixed } from '@/shared/lib/formatters';

/** Accepted image MIME types — kept in sync with the backend's
 *  ``_detect_image_mime`` magic-byte gate (PNG / JPG / WebP). */
const ACCEPTED_MIME = ['image/jpeg', 'image/png', 'image/webp'] as const;
/** Client-side size cap — mirrors the backend's ``_MAX_IMAGE_BYTES``.
 *  Rejecting here gives an instant, clear message instead of a round-trip
 *  413. */
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${fmtFixed(bytes / (1024 * 1024), 1)} MB`;
}

interface Props {
  /** The currently-selected image file, or null when none is picked. */
  file: File | null;
  /** Lifts the validated selection (or null on clear) to the parent. */
  onPick: (file: File | null) => void;
}

export default function ImageSourceSelector({ file, onPick }: Props) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  // Build (and revoke) an object URL for the live preview. Revoking on
  // change / unmount prevents a memory leak from accumulating blob URLs.
  useEffect(() => {
    if (!file) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const validateAndPick = useCallback(
    (candidate: File | undefined | null) => {
      if (!candidate) return;
      if (!ACCEPTED_MIME.includes(candidate.type as (typeof ACCEPTED_MIME)[number])) {
        setError(
          t('match_wizard.image_err_type', {
            defaultValue: 'Unsupported file. Use a PNG, JPG or WebP image.',
          }),
        );
        onPick(null);
        return;
      }
      if (candidate.size > MAX_IMAGE_BYTES) {
        setError(
          t('match_wizard.image_err_size', {
            defaultValue: 'Image is larger than 10 MB. Downscale it and try again.',
          }),
        );
        onPick(null);
        return;
      }
      setError(null);
      onPick(candidate);
    },
    [onPick, t],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragOver(false);
      validateAndPick(e.dataTransfer.files?.[0]);
    },
    [validateAndPick],
  );

  const clear = useCallback(() => {
    setError(null);
    onPick(null);
    if (inputRef.current) inputRef.current.value = '';
  }, [onPick]);

  return (
    <div>
      <span className="block text-sm text-content-secondary mb-2.5">
        {t('match_wizard.image_label', {
          defaultValue: 'Upload a site photo or drawing snapshot',
        })}
      </span>

      {/* Drop zone — doubles as the empty-state picker and, once a file
          is chosen, the preview surface. */}
      <div
        role="button"
        tabIndex={0}
        aria-label={t('match_wizard.image_dropzone_aria', {
          defaultValue: 'Image upload drop zone',
        })}
        onClick={() => !file && inputRef.current?.click()}
        onKeyDown={(e) => {
          if (!file && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!dragOver) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={clsx(
          'relative rounded-2xl border-2 border-dashed transition-colors p-6 text-center focus:outline-none focus:ring-2 focus:ring-indigo-500/40',
          dragOver
            ? 'border-indigo-500 bg-indigo-50/60 dark:bg-indigo-950/30'
            : 'border-border bg-surface-secondary/40 hover:border-indigo-400 dark:hover:border-indigo-700',
          !file && 'cursor-pointer',
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          onChange={(e) => validateAndPick(e.target.files?.[0])}
          className="sr-only"
        />

        {file && previewUrl ? (
          <div className="flex flex-col sm:flex-row items-center gap-4">
            <img
              src={previewUrl}
              alt={t('match_wizard.image_preview_alt', {
                defaultValue: 'Preview of the uploaded image',
              })}
              className="w-32 h-32 object-cover rounded-xl border border-border-light shadow-sm shrink-0"
            />
            <div className="min-w-0 text-left flex-1">
              <span className="inline-flex items-center gap-1.5 text-emerald-700 dark:text-emerald-300 font-medium text-sm">
                <Check className="w-4 h-4" strokeWidth={3} />
                <span className="truncate">{file.name}</span>
              </span>
              <div className="text-xs text-content-tertiary mt-0.5">
                {file.type.replace('image/', '').toUpperCase()} · {formatBytes(file.size)}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    inputRef.current?.click();
                  }}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-border-light text-content-secondary hover:bg-surface-secondary transition-colors"
                >
                  <UploadCloud className="w-3.5 h-3.5" />
                  {t('match_wizard.image_replace', { defaultValue: 'Replace' })}
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    clear();
                  }}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-border-light text-content-secondary hover:bg-surface-secondary transition-colors"
                >
                  <X className="w-3.5 h-3.5" />
                  {t('match_wizard.image_clear', { defaultValue: 'Clear' })}
                </button>
              </div>
            </div>
          </div>
        ) : (
          <>
            <ImageIcon className="w-8 h-8 mx-auto text-content-tertiary mb-2" />
            <span className="font-medium text-content-primary text-sm">
              {t('match_wizard.image_drop', {
                defaultValue: 'Click or drop an image',
              })}
            </span>
            <div className="text-xs text-content-tertiary mt-0.5">
              {t('match_wizard.image_hint', {
                defaultValue: 'PNG, JPG or WebP up to 10 MB - a site photo, sketch or CAD snapshot',
              })}
            </div>
          </>
        )}
      </div>

      {error && (
        <div className="mt-2 text-xs text-rose-600 dark:text-rose-400">{error}</div>
      )}

      {/* Honest expectation-setting: the AI read is a low-confidence
          suggestion the user reviews, never an auto-applied match. */}
      <div className="mt-3 flex items-start gap-2 rounded-xl border border-indigo-200/60 dark:border-indigo-800/50 bg-indigo-50/50 dark:bg-indigo-950/20 px-3 py-2">
        <Sparkles className="w-3.5 h-3.5 text-indigo-600 dark:text-indigo-300 mt-0.5 shrink-0" />
        <p className="text-[11px] leading-relaxed text-content-secondary">
          {t('match_wizard.image_ai_note', {
            defaultValue:
              'AI reads the image and suggests visible elements with rough quantities. Every suggestion is low-confidence - you review and confirm each one. Needs an AI provider configured in Settings; without one the session opens empty.',
          })}
        </p>
      </div>
    </div>
  );
}
