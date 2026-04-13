/**
 * BIMConverterStatusBanner — dismissible amber banner that surfaces the
 * install status of every DDC converter needed to drag-and-drop native
 * CAD formats (.rvt / .dwg / .dgn) onto the BIM Hub page.
 *
 * Rendered at the top of BIMPage content.  Self-contained: runs its
 * own `fetchBIMConverters` query against the shared `['bim-converters']`
 * cache key so the Install button and upload-time preflight guard
 * always see the same state.
 *
 * Guidelines:
 *  - Renders nothing while loading or when every installable converter
 *    is already present on the VPS — no noise for the happy path.
 *  - Uses `useMutation` for the install action + refetches on success.
 *  - Every user-visible string goes through i18next (`t()`) with a
 *    sensible `defaultValue`.  No hardcoded English.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { AlertTriangle, Check, Download, Loader2, X } from 'lucide-react';

import {
  fetchBIMConverters,
  installBIMConverter,
  type BIMConverterInfo,
  type BIMConvertersResponse,
} from './api';
import { useToastStore } from '@/stores/useToastStore';

/** Ids of converters we proactively surface in the banner.  Kept in
 *  sync with the set of file extensions accepted by the BIM drop zone. */
const BANNER_CONVERTER_IDS = ['rvt', 'dwg', 'dgn'] as const;

interface BIMConverterStatusBannerProps {
  className?: string;
}

export function BIMConverterStatusBanner({
  className,
}: BIMConverterStatusBannerProps): JSX.Element | null {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [dismissed, setDismissed] = useState(false);
  const [installingId, setInstallingId] = useState<string | null>(null);

  const { data, isLoading } = useQuery<BIMConvertersResponse>({
    queryKey: ['bim-converters'],
    queryFn: fetchBIMConverters,
    staleTime: 30_000,
  });

  const installMutation = useMutation({
    mutationFn: (converterId: string) => installBIMConverter(converterId),
    onSuccess: (_result, converterId) => {
      const conv = data?.converters.find((c) => c.id === converterId);
      const sizeMb = conv?.size_mb ?? 0;
      addToast({
        type: 'success',
        title: t('bim.converter_install_success_title', {
          defaultValue: 'Converter installed',
        }),
        message: t('bim.converter_install_success_msg', {
          defaultValue: 'Installed {{name}} ({{size}} MB)',
          name: conv?.name ?? converterId.toUpperCase(),
          size: sizeMb,
        }),
      });
      queryClient.invalidateQueries({ queryKey: ['bim-converters'] });
      queryClient.invalidateQueries({ queryKey: ['takeoff', 'converters'] });
    },
    onError: (err, converterId) => {
      const conv = data?.converters.find((c) => c.id === converterId);
      addToast({
        type: 'error',
        title: t('bim.converter_install_error_title', {
          defaultValue: 'Install failed',
        }),
        message:
          err instanceof Error
            ? err.message
            : t('bim.converter_install_error_msg', {
                defaultValue: 'Could not install {{name}}',
                name: conv?.name ?? converterId.toUpperCase(),
              }),
      });
    },
    onSettled: () => setInstallingId(null),
  });

  if (isLoading || dismissed || !data) return null;

  const relevant = data.converters.filter((c) =>
    (BANNER_CONVERTER_IDS as readonly string[]).includes(c.id),
  );
  if (relevant.length === 0) return null;

  const missing = relevant.filter((c) => !c.installed);
  if (missing.length === 0) return null;

  const handleInstall = (converter: BIMConverterInfo): void => {
    setInstallingId(converter.id);
    installMutation.mutate(converter.id);
  };

  return (
    <div
      className={clsx(
        'rounded-xl border bg-amber-50 dark:bg-amber-950/20 border-amber-200 dark:border-amber-800 p-3',
        className,
      )}
      role="status"
    >
      <div className="flex items-start gap-3">
        <div className="shrink-0 mt-0.5">
          <AlertTriangle
            size={16}
            className="text-amber-600 dark:text-amber-400"
          />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-amber-900 dark:text-amber-200">
            {t('bim.converter_banner_title', {
              defaultValue: 'Some BIM formats need a converter',
            })}
          </p>
          <p className="text-[11px] text-amber-800/90 dark:text-amber-300/90 mt-0.5">
            {t('bim.converter_banner_subtitle', {
              defaultValue:
                'Without these, drag-and-drop of .rvt / .dwg / .dgn files will fail. One-time install from GitHub releases.',
            })}
          </p>
          <ul className="mt-2 space-y-1.5">
            {relevant.map((conv) => {
              const busy = installingId === conv.id && installMutation.isPending;
              return (
                <li
                  key={conv.id}
                  className="flex items-center gap-2 text-[11px]"
                >
                  <span className="shrink-0">
                    {conv.installed ? (
                      <Check
                        size={13}
                        className="text-emerald-600 dark:text-emerald-400"
                      />
                    ) : (
                      <Download
                        size={13}
                        className="text-amber-600 dark:text-amber-400"
                      />
                    )}
                  </span>
                  <span className="font-medium text-amber-900 dark:text-amber-200">
                    {conv.name}
                  </span>
                  <span className="text-amber-700/80 dark:text-amber-300/80 tabular-nums">
                    {t('bim.converter_banner_size', {
                      defaultValue: '{{size}} MB',
                      size: conv.size_mb,
                    })}
                  </span>
                  <span className="ms-auto">
                    {conv.installed ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
                        <Check size={10} />
                        {t('bim.converter_banner_installed', {
                          defaultValue: 'Installed',
                        })}
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => handleInstall(conv)}
                        disabled={busy || installMutation.isPending}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-semibold bg-amber-600 hover:bg-amber-700 disabled:opacity-60 disabled:cursor-not-allowed text-white transition-colors"
                      >
                        {busy ? (
                          <>
                            <Loader2 size={11} className="animate-spin" />
                            {t('bim.converter_install_in_progress', {
                              defaultValue: 'Installing…',
                            })}
                          </>
                        ) : (
                          <>
                            <Download size={11} />
                            {t('bim.converter_install_btn', {
                              defaultValue: 'Install',
                            })}
                          </>
                        )}
                      </button>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
        <button
          type="button"
          onClick={() => setDismissed(true)}
          className="shrink-0 p-1 rounded-md text-amber-700 dark:text-amber-400 hover:bg-amber-100 dark:hover:bg-amber-900/40 transition-colors"
          aria-label={t('bim.converter_banner_dismiss', {
            defaultValue: 'Dismiss',
          })}
          title={t('bim.converter_banner_dismiss', {
            defaultValue: 'Dismiss',
          })}
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}

export default BIMConverterStatusBanner;
