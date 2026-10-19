// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ConverterInstallProgressBar — small, reusable progress strip rendered
 * while a DDC converter is being installed.
 *
 * Polls ``GET /v1/takeoff/converters/{id}/install-progress/`` every 500 ms
 * while ``installing=true`` and renders:
 *   * A determinate ``<div>``-based progress bar driven by the
 *     file-count ratio reported by the backend (most reliable signal we
 *     have during a 175-file install), or an indeterminate pulsing
 *     placeholder while the backend is still listing files.
 *   * A microcopy line showing the current stage
 *     (``Fetching file list… / Downloading · 42/175 / Running smoke test…``),
 *     the in-flight filename (when present) and a ``MB done / MB expected``
 *     counter so the user can eyeball download speed.
 *
 * The progress query is disabled when ``installing=false`` so there is
 * zero network traffic at rest. Shared by:
 *   * ``BIMConverterStatusBanner`` (per-row install button)  → existing
 *   * ``InstallConverterPrompt``     (file-upload guard modal)  → new
 *   * ``DwgTakeoffPage`` offline-readiness hint                  → new
 *
 * Why a shared component: the previous inline copy in the banner had
 * the only progress bar in the app, but the two highest-impact install
 * triggers (the upload-time modal on /bim and the "Install converter"
 * button on /dwg-takeoff) showed only a generic spinner — so the user
 * had no signal that a 470 MB download was actually making progress.
 */

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';

import {
  fetchBIMConverterInstallProgress,
  type BIMConverterInstallProgress,
} from './api';
import { fmtFixed } from '@/shared/lib/formatters';

interface ConverterInstallProgressBarProps {
  /** Converter id (``rvt`` / ``ifc`` / ``dwg``). */
  converterId: string;
  /** Whether the parent's install mutation is in flight. The poll is
   *  disabled when ``false`` so nothing is fetched at rest. */
  installing: boolean;
  /** Optional expected size in megabytes — surfaced in the "X / Y MB"
   *  counter so the user has a sense of how much is left. */
  sizeMb?: number;
  /** Optional className applied to the outer wrapper for layout fit. */
  className?: string;
  /** Visual variant.
   *   * ``light`` — default; bar uses ``bg-slate-200`` track suitable
   *     for the light-on-light banner row backgrounds.
   *   * ``dark``  — for the DWG-takeoff hint popover and the install
   *     prompt modal, both of which sit on darker surfaces. */
  variant?: 'light' | 'dark';
}

export function ConverterInstallProgressBar({
  converterId,
  installing,
  sizeMb,
  className,
  variant = 'light',
}: ConverterInstallProgressBarProps): JSX.Element | null {
  const { t } = useTranslation();

  const progressQuery = useQuery<BIMConverterInstallProgress>({
    queryKey: ['bim-converter-install-progress', converterId],
    queryFn: () => fetchBIMConverterInstallProgress(converterId),
    enabled: installing,
    refetchInterval: (query) => {
      if (!installing) return false;
      const s = query.state.data?.stage;
      // Stop polling once the background install reaches a terminal stage -
      // installBIMConverter's own poll resolves the mutation at that point.
      return s === 'done' || s === 'error' ? false : 500;
    },
    refetchIntervalInBackground: false,
    staleTime: 0,
    gcTime: 0,
  });

  if (!installing) return null;

  // While the very first poll is in flight the backend may not yet have
  // recorded the started_at row — fall back to an indeterminate bar so
  // the user immediately sees "something is happening" instead of an
  // empty space until the first 500 ms tick lands.
  const progress = progressQuery.data;
  const active = progress?.active ?? true;
  const stage = progress?.stage ?? 'listing';
  const current = progress?.current ?? 0;
  const total = progress?.total ?? 0;
  const bytesDone = progress?.bytes_done ?? 0;
  const mbDone = bytesDone / (1024 * 1024);
  const expectedMb = sizeMb && sizeMb > 0 ? sizeMb : 0;

  // File-count ratio when the backend has finished listing; null until
  // then so the bar shows its indeterminate state.
  const percent =
    total > 0 ? Math.min(100, Math.round((current / total) * 100)) : null;

  const stageLabel =
    stage === 'listing'
      ? t('bim.converter_progress_listing', {
          defaultValue: 'Fetching file list…',
        })
      : stage === 'extracting'
        ? t('bim.converter_progress_extracting', {
            defaultValue: 'Extracting…',
          })
        : stage === 'verifying'
          ? t('bim.converter_progress_verifying', {
              defaultValue: 'Running smoke test…',
            })
          : t('bim.converter_progress_downloading', {
              defaultValue: 'Downloading',
            });

  const trackBg =
    variant === 'dark'
      ? 'bg-white/10'
      : 'bg-slate-200 dark:bg-slate-700';
  const fillBg = 'bg-sky-500 dark:bg-sky-400';
  const microTone =
    variant === 'dark'
      ? 'text-white/70'
      : 'text-content-secondary';

  return (
    <div
      className={clsx('w-full space-y-1', className)}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent ?? undefined}
      aria-label={t('bim.converter_progress_aria', {
        defaultValue: 'Converter install progress',
      })}
      data-testid={`converter-install-progress-${converterId}`}
    >
      <div
        className={clsx(
          'relative h-1.5 w-full overflow-hidden rounded-full',
          trackBg,
        )}
      >
        {percent === null || !active ? (
          <div
            className={clsx(
              'absolute inset-y-0 left-0 w-1/3 animate-pulse',
              fillBg,
            )}
          />
        ) : (
          <div
            className={clsx('h-full transition-all duration-300', fillBg)}
            style={{ width: `${percent}%` }}
          />
        )}
      </div>
      <div
        className={clsx(
          'flex items-center justify-between gap-2 text-[10px] tabular-nums',
          microTone,
        )}
      >
        <span className="truncate">
          {stageLabel}
          {total > 0 &&
            (stage === 'downloading' || stage === 'extracting') &&
            ` · ${current}/${total}`}
          {progress?.file && ` · ${progress.file}`}
        </span>
        <span className="shrink-0 font-mono">
          {expectedMb > 0
            ? `${fmtFixed(mbDone, 1)} / ${expectedMb} MB`
            : `${fmtFixed(mbDone, 1)} MB`}
        </span>
      </div>
    </div>
  );
}

export default ConverterInstallProgressBar;
