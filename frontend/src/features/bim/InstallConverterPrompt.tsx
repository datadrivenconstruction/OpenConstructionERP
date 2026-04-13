/**
 * InstallConverterPrompt — modal shown when the user tries to upload a
 * native CAD file (.rvt / .dwg / .dgn) but the matching DDC converter
 * is not installed on the VPS.
 *
 * Shared with the pre-upload guard in BIMPage AND the backend
 * `converter_required` / `needs_converter` response branches.  On
 * successful install, calls `onInstalledAndRetry()` so the caller can
 * replay the upload with the same file — no second file-picker step.
 *
 * Fetches converter metadata (size, name) from the shared
 * `['bim-converters']` query cache so the "470 MB" figure always
 * matches what the status banner and the /quantities page show.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertCircle, Download, Loader2, X } from 'lucide-react';

import {
  fetchBIMConverters,
  installBIMConverter,
  type BIMConvertersResponse,
} from './api';
import { useToastStore } from '@/stores/useToastStore';

interface InstallConverterPromptProps {
  open: boolean;
  converterId: string;
  fileName: string;
  /** Original file size in bytes — formatted for display. */
  fileSize: number;
  onClose: () => void;
  /** Fired after a successful install.  Caller should replay the
   *  upload with the same file + metadata and then call `onClose()`. */
  onInstalledAndRetry: () => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

export function InstallConverterPrompt({
  open,
  converterId,
  fileName,
  fileSize,
  onClose,
  onInstalledAndRetry,
}: InstallConverterPromptProps): JSX.Element | null {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [localError, setLocalError] = useState<string | null>(null);

  // Re-uses the cached converter list so the displayed size + name
  // match the banner and the /quantities UI.
  const { data } = useQuery<BIMConvertersResponse>({
    queryKey: ['bim-converters'],
    queryFn: fetchBIMConverters,
    staleTime: 30_000,
    enabled: open,
  });

  const converter = data?.converters.find((c) => c.id === converterId);

  const installMutation = useMutation({
    mutationFn: () => installBIMConverter(converterId),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('bim.install_prompt_success_title', {
          defaultValue: 'Converter installed',
        }),
        message: t('bim.install_prompt_success_msg', {
          defaultValue: 'Retrying upload of {{name}}…',
          name: fileName,
        }),
      });
      queryClient.invalidateQueries({ queryKey: ['bim-converters'] });
      queryClient.invalidateQueries({ queryKey: ['takeoff', 'converters'] });
      onInstalledAndRetry();
      onClose();
    },
    onError: (err) => {
      setLocalError(
        err instanceof Error
          ? err.message
          : t('bim.install_prompt_error_generic', {
              defaultValue: 'Install failed. Please try again.',
            }),
      );
    },
  });

  if (!open) return null;

  const formatLabel = converterId.toUpperCase();
  const converterName =
    converter?.name ??
    t('bim.install_prompt_default_converter_name', {
      defaultValue: 'DDC {{format}} Converter',
      format: formatLabel,
    });
  const converterSizeMb = converter?.size_mb ?? 0;
  const sizeFormatted = formatBytes(fileSize);
  const installing = installMutation.isPending;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-in fade-in duration-150"
      role="dialog"
      aria-modal="true"
      aria-labelledby="install-converter-prompt-title"
      onClick={(e) => {
        // Clicking the backdrop dismisses — but not while installing,
        // since we'd leave the user with a half-run download.
        if (e.target === e.currentTarget && !installing) onClose();
      }}
    >
      <div className="w-full max-w-md rounded-2xl bg-surface-primary border border-border-light shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-start justify-between px-5 py-4 border-b border-border-light">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-amber-100 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-800 flex items-center justify-center">
              <Download
                size={18}
                className="text-amber-600 dark:text-amber-400"
              />
            </div>
            <div>
              <h2
                id="install-converter-prompt-title"
                className="text-sm font-bold text-content-primary"
              >
                {t('bim.install_prompt_title', {
                  defaultValue: 'Install {{format}} converter',
                  format: formatLabel,
                })}
              </h2>
              <p className="text-[10px] text-content-quaternary mt-0.5">
                {t('bim.install_prompt_subtitle', {
                  defaultValue: 'One-time download from GitHub releases',
                })}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={installing}
            className="p-1.5 rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            aria-label={t('bim.install_prompt_close', {
              defaultValue: 'Close',
            })}
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-3">
          <p className="text-sm text-content-secondary leading-relaxed">
            {t('bim.install_prompt_body', {
              defaultValue:
                'To process “{{fileName}}” ({{fileSize}}), OpenConstructionERP needs the {{converterName}} ({{converterSize}} MB one-time download).',
              fileName,
              fileSize: sizeFormatted,
              converterName,
              converterSize: converterSizeMb,
            })}
          </p>
          <p className="text-[11px] text-content-quaternary">
            {t('bim.install_prompt_duration_hint', {
              defaultValue:
                'The install typically takes 1–2 minutes. Your file will be retried automatically once the converter is ready.',
            })}
          </p>

          {localError && (
            <div className="flex items-start gap-2 p-2.5 rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800">
              <AlertCircle
                size={14}
                className="text-red-500 mt-0.5 shrink-0"
              />
              <p className="text-[11px] text-red-700 dark:text-red-300">
                {localError}
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-border-light bg-surface-secondary/50">
          <button
            type="button"
            onClick={onClose}
            disabled={installing}
            className="px-3 py-1.5 rounded-lg text-xs font-medium text-content-secondary hover:bg-surface-tertiary transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {t('bim.install_prompt_cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="button"
            onClick={() => {
              setLocalError(null);
              installMutation.mutate();
            }}
            disabled={installing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-oe-blue text-white hover:bg-oe-blue-dark disabled:opacity-60 disabled:cursor-not-allowed transition-colors shadow-sm"
          >
            {installing ? (
              <>
                <Loader2 size={13} className="animate-spin" />
                {t('bim.install_prompt_installing', {
                  defaultValue: 'Installing… (1–2 minutes)',
                })}
              </>
            ) : (
              <>
                <Download size={13} />
                {t('bim.install_prompt_confirm', {
                  defaultValue: 'Install converter & retry upload',
                })}
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

export default InstallConverterPrompt;
