// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "Videos for this step": a small pill above a module screen that opens a
// short list of the videos whose cases walk through this screen, best fit for
// the reader first. The video plays in place; nothing leaves the screen.
//
// It stays out of the way. It starts folded, it can be hidden on this screen
// or on every screen with an undo, and the Videos page can bring it back.
// Loaded lazily by ModuleVideosSlot, so the catalogue is fetched only here.

import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { ChevronDown, EyeOff, Hourglass, MonitorPlay, X } from 'lucide-react';
import { navGroups } from '@/app/layout/navCatalog';
import { useToastStore } from '@/stores/useToastStore';
import type { AcademyVideo } from './academyTypes';
import { formatClock, recommend, videosForRoute } from './academy';
import { useVideoContext } from './useVideoContext';
import { useVideoLabels } from './videoLabels';
import { useVideoHintsStore } from './videoRoutes';
import { VideoCover } from './VideoCover';
import { VideoPlayerDialog } from './VideoPlayerDialog';

const SHOWN = 3;

function moduleLabel(route: string): { key: string; fallback: string } | null {
  for (const group of navGroups) {
    for (const item of group.items) {
      if (item.to === route) return { key: item.labelKey, fallback: item.defaultLabel ?? route };
    }
  }
  return null;
}

/** The videos for a screen, best fit first, falling back to the published
 *  ones when the reader's role and country rule every one of them out. */
export function videosForScreen(
  route: string,
  ctx: { role: Parameters<typeof recommend>[0]['role']; market: string | null; language: string },
): AcademyVideo[] {
  const all = videosForRoute(route);
  const ranked = recommend(ctx, all, all.length);
  if (ranked.length > 0) return ranked;
  return [...all].sort((a, b) => Number(b.status === 'published') - Number(a.status === 'published'));
}

export default function ModuleVideosPanel({ route }: { route: string }) {
  const { t } = useTranslation();
  const labels = useVideoLabels();
  const ctx = useVideoContext();
  const addToast = useToastStore((s) => s.addToast);
  const hideOn = useVideoHintsStore((s) => s.hideOn);
  const unhideOn = useVideoHintsStore((s) => s.unhideOn);
  const setOff = useVideoHintsStore((s) => s.setOff);
  const [open, setOpen] = useState(false);
  const [playing, setPlaying] = useState<{ video: AcademyVideo; start: number } | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const panelId = useId();

  const videos = useMemo(
    () => videosForScreen(route, { role: ctx.role, market: ctx.market, language: ctx.language }),
    [route, ctx.role, ctx.market, ctx.language],
  );
  const label = moduleLabel(route);
  const moduleName = label ? t(label.key, { defaultValue: label.fallback }) : '';

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  if (videos.length === 0) return null;

  const hideHere = () => {
    hideOn(route);
    addToast(
      {
        type: 'info',
        title: t('videos.hint_hidden_here', { defaultValue: 'Video tips hidden on this screen' }),
        message: t('videos.hint_hidden_body', {
          defaultValue: 'Turn them back on at any time from the Videos page.',
        }),
        action: { label: t('common.undo', { defaultValue: 'Undo' }), onClick: () => unhideOn(route) },
      },
      { duration: 8000 },
    );
  };
  const hideEverywhere = () => {
    setOff(true);
    addToast(
      {
        type: 'info',
        title: t('videos.hint_hidden_all', { defaultValue: 'Video tips hidden on every screen' }),
        message: t('videos.hint_hidden_body', {
          defaultValue: 'Turn them back on at any time from the Videos page.',
        }),
        action: { label: t('common.undo', { defaultValue: 'Undo' }), onClick: () => setOff(false) },
      },
      { duration: 8000 },
    );
  };

  return (
    <div className="relative z-30 mb-2 flex justify-end" data-testid="module-videos">
      <div ref={boxRef} className="relative">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls={panelId}
          data-testid="module-videos-toggle"
          className={clsx(
            'inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium shadow-sm transition-colors',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
            open
              ? 'border-oe-blue/50 bg-oe-blue/10 text-oe-blue'
              : 'border-border-light bg-surface-primary/90 text-content-secondary backdrop-blur hover:border-oe-blue/40 hover:text-oe-blue',
          )}
        >
          <MonitorPlay size={13} aria-hidden />
          {t('videos.for_this_step', { defaultValue: 'Videos for this step' })}
          <span className="rounded-full bg-oe-blue/10 px-1.5 text-2xs font-semibold tabular-nums text-oe-blue">
            {videos.length}
          </span>
          <ChevronDown size={12} className={clsx('transition-transform', open && 'rotate-180')} aria-hidden />
        </button>

        {open && (
          <div
            id={panelId}
            role="region"
            aria-label={t('videos.for_this_step', { defaultValue: 'Videos for this step' })}
            className="absolute right-0 top-full mt-1.5 w-[min(23rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-border-light bg-surface-primary shadow-xl"
          >
            <div className="flex items-start gap-2 border-b border-border-light px-3 py-2">
              <p className="min-w-0 flex-1 text-xs font-semibold text-content-primary">
                {moduleName
                  ? t('videos.for_module', { defaultValue: 'Videos about {{module}}', module: moduleName })
                  : t('videos.for_this_step', { defaultValue: 'Videos for this step' })}
                <span className="mt-0.5 block text-2xs font-normal text-content-tertiary">
                  {t('videos.for_step_note', {
                    defaultValue: 'Suggested by our editors from the cases that use this screen.',
                  })}
                </span>
              </p>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label={t('common.close', { defaultValue: 'Close' })}
                className="rounded p-0.5 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
              >
                <X size={14} />
              </button>
            </div>
            <ul className="divide-y divide-border-light">
              {videos.slice(0, SHOWN).map((video) => (
                <li key={video.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setPlaying({ video, start: 0 });
                      setOpen(false);
                    }}
                    className="flex w-full items-center gap-2.5 px-3 py-2 text-left hover:bg-surface-secondary focus:bg-surface-secondary focus:outline-none"
                  >
                    <span className="relative block h-[54px] w-24 shrink-0 overflow-hidden rounded-md bg-slate-900">
                      <VideoCover src={video.cover} width={96} height={54} className="h-full w-full object-cover" />
                      {video.duration ? (
                        <span className="absolute bottom-0.5 right-0.5 rounded bg-black/75 px-1 font-mono text-[9px] text-white">
                          {formatClock(video.duration)}
                        </span>
                      ) : null}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span lang={video.language} className="line-clamp-2 text-xs font-medium leading-snug text-content-primary">
                        {video.title}
                      </span>
                      <span className="mt-0.5 flex items-center gap-1 text-2xs text-content-tertiary">
                        {video.status !== 'published' && (
                          <span className="inline-flex items-center gap-0.5 text-amber-700 dark:text-amber-300">
                            <Hourglass size={10} aria-hidden />
                            {t('videos.coming_soon', { defaultValue: 'Coming soon' })}
                          </span>
                        )}
                        <span className="truncate">{labels.series(video.series)}</span>
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            <div className="space-y-1.5 border-t border-border-light bg-surface-secondary/40 px-3 py-2">
              <Link
                to={`/videos?route=${encodeURIComponent(route)}`}
                className="block text-xs font-medium text-oe-blue hover:underline"
              >
                {t('videos.see_all_for_step', {
                  defaultValue: 'All {{total}} on the Videos page',
                  total: videos.length,
                })}
              </Link>
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-2xs text-content-tertiary">
                <button type="button" onClick={hideHere} className="inline-flex items-center gap-1 hover:text-content-primary">
                  <EyeOff size={11} aria-hidden />
                  {t('videos.hide_here', { defaultValue: 'Hide on this screen' })}
                </button>
                <button type="button" onClick={hideEverywhere} className="inline-flex items-center gap-1 hover:text-content-primary">
                  <EyeOff size={11} aria-hidden />
                  {t('videos.hide_everywhere', { defaultValue: 'Hide on every screen' })}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {playing && (
        <VideoPlayerDialog
          key={playing.video.id}
          video={playing.video}
          start={playing.start}
          autoplay
          labels={labels}
          onClose={() => setPlaying(null)}
          onOpenVideo={(v, s = 0) => setPlaying({ video: v, start: s })}
        />
      )}
    </div>
  );
}
