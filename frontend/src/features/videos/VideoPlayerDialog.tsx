// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The player: a modal with the video on the left and its chapters on the
// right. Clicking a chapter reloads the privacy-enhanced embed at that second;
// a plain embed has no API channel back to the page, so the seek is a new
// `start=` rather than a message to a running player, and the page never
// learns how far the reader got.
//
// The frame is created only on a gesture. A card click is one, so the video
// starts at once; a shared link (`?v=`) is not, so it opens on the poster and
// waits for play. A video that is not out yet opens here too and shows its
// outline, so a card never leads to a broken player.

import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  ArrowRight,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Circle,
  ExternalLink,
  Hourglass,
  Play,
  Route,
  X,
} from 'lucide-react';
import { useFocusTrap } from '@/shared/hooks/useFocusTrap';
import type { AcademyVideo } from './academyTypes';
import { caseRef, channelUrl, embedUrl, formatClock, playlist, watchUrl } from './academy';
import { useVideosStore } from './useVideosStore';
import { VideoCover } from './VideoCover';
import type { VideoLabels } from './videoLabels';

/** Render with `key={video.id}`: the start second and play state are read
 *  once, when the dialog opens on a video. */
export interface VideoPlayerDialogProps {
  video: AcademyVideo;
  /** Second to open at. */
  start: number;
  /** Start playing at once (the dialog was opened by a click). */
  autoplay: boolean;
  labels: VideoLabels;
  onClose: () => void;
  onOpenVideo: (video: AcademyVideo, start?: number) => void;
  /** Called when the reader moves to another chapter, to keep the URL in step. */
  onSeek?: (start: number) => void;
}

export function VideoPlayerDialog({
  video,
  start: initialStart,
  autoplay,
  labels,
  onClose,
  onOpenVideo,
  onSeek,
}: VideoPlayerDialogProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const [start, setStart] = useState(initialStart);
  const [playing, setPlaying] = useState(autoplay && video.status === 'published');
  // Bumped on every seek, so clicking the chapter you are already in replays it.
  const [nonce, setNonce] = useState(0);
  const watched = useVideosStore((s) => Boolean(s.watched[video.id]));
  const toggleWatched = useVideosStore((s) => s.toggleWatched);
  const markStarted = useVideosStore((s) => s.markStarted);

  useFocusTrap(panelRef, true);

  useEffect(() => {
    if (playing) markStarted(video.id);
  }, [playing, video.id, markStarted]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  const published = video.status === 'published' && !!video.youtubeId;
  const seek = (t0: number) => {
    setStart(t0);
    setNonce((n) => n + 1);
    onSeek?.(t0);
    if (published) setPlaying(true);
  };
  // The chapter the player is in: the last one that starts at or before `start`.
  const current = video.chapters.reduce((acc, c, i) => (c.t <= start ? i : acc), -1);

  const list = playlist(video.series);
  const index = list.findIndex((v) => v.id === video.id);
  const prev = index > 0 ? list[index - 1] : undefined;
  const next = index >= 0 && index < list.length - 1 ? list[index + 1] : undefined;
  const cases = video.cases.map((id) => ({ id, ref: caseRef(id) })).filter((c) => c.ref);

  return createPortal(
    <div
      className="fixed inset-0 z-[80] flex items-end justify-center bg-slate-950/70 p-0 backdrop-blur-sm sm:items-center sm:p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="video-player"
        className="flex max-h-[100dvh] w-full max-w-6xl flex-col overflow-hidden rounded-t-2xl border border-border-light bg-surface-primary shadow-2xl sm:max-h-[92vh] sm:rounded-2xl"
      >
        <div className="flex items-start gap-3 border-b border-border-light px-4 py-3">
          <div className="min-w-0 flex-1">
            <p className="truncate text-2xs font-medium uppercase tracking-wide text-content-tertiary">
              {labels.series(video.series)}
              {index >= 0 && list.length > 1 ? ` · ${index + 1}/${list.length}` : ''}
            </p>
            <h2 id={titleId} lang={video.language} className="text-base font-semibold leading-snug text-content-primary">
              {video.title}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="shrink-0 rounded-lg p-1.5 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
          >
            <X size={18} />
          </button>
        </div>

        <div className="grid min-h-0 flex-1 overflow-y-auto lg:grid-cols-[minmax(0,1fr)_320px] lg:overflow-hidden">
          {/* ── Player and details ─────────────────────────────────────── */}
          <div className="min-w-0 lg:overflow-y-auto">
            <div className="relative aspect-video w-full bg-black">
              {published && playing ? (
                <iframe
                  key={`${video.youtubeId}-${start}-${nonce}`}
                  src={embedUrl(video.youtubeId!, start)}
                  title={video.title}
                  className="absolute inset-0 h-full w-full"
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                  referrerPolicy="strict-origin-when-cross-origin"
                  allowFullScreen
                />
              ) : (
                <>
                  <VideoCover src={video.cover} eager className="h-full w-full object-cover opacity-90" />
                  {published ? (
                    <button
                      type="button"
                      onClick={() => setPlaying(true)}
                      className="absolute inset-0 flex items-center justify-center bg-black/25 transition-colors hover:bg-black/35 focus:outline-none focus-visible:ring-4 focus-visible:ring-inset focus-visible:ring-oe-blue"
                      aria-label={t('videos.play', { defaultValue: 'Play: {{title}}', title: video.title })}
                    >
                      <span className="flex h-16 w-16 items-center justify-center rounded-full bg-white/95 text-slate-900 shadow-xl">
                        <Play size={26} strokeWidth={2.4} className="translate-x-0.5" fill="currentColor" />
                      </span>
                      {start > 0 && (
                        <span className="absolute bottom-3 left-3 rounded bg-black/75 px-2 py-0.5 font-mono text-xs text-white">
                          {formatClock(start)}
                        </span>
                      )}
                    </button>
                  ) : (
                    <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-slate-950/70 p-4 text-center text-white">
                      <Hourglass size={26} strokeWidth={1.8} className="text-amber-300" aria-hidden />
                      <p className="text-sm font-semibold">{t('videos.coming_soon', { defaultValue: 'Coming soon' })}</p>
                      <p className="max-w-sm text-xs text-white/75">
                        {t('videos.coming_soon_body', {
                          defaultValue:
                            'This video is finished and waiting for its release. The outline is here already, and it will play on this page the day it is out.',
                        })}
                      </p>
                    </div>
                  )}
                </>
              )}
            </div>

            <div className="space-y-4 p-4">
              <div className="flex flex-wrap items-center gap-2">
                {published && (
                  <a
                    href={watchUrl(video.youtubeId!, start)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-lg border border-border-light px-2.5 py-1.5 text-xs font-medium text-content-secondary hover:border-oe-blue/40 hover:text-oe-blue"
                  >
                    {t('videos.open_external', { defaultValue: 'Open on YouTube' })}
                    <ExternalLink size={12} aria-hidden />
                  </a>
                )}
                {!published && (
                  <a
                    href={channelUrl()}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-lg border border-border-light px-2.5 py-1.5 text-xs font-medium text-content-secondary hover:border-oe-blue/40 hover:text-oe-blue"
                  >
                    {t('videos.follow_channel', { defaultValue: 'Follow the channel' })}
                    <ExternalLink size={12} aria-hidden />
                  </a>
                )}
                <button
                  type="button"
                  aria-pressed={watched}
                  onClick={() => toggleWatched(video.id)}
                  className={clsx(
                    'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors',
                    watched
                      ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                      : 'border-border-light text-content-secondary hover:border-emerald-500/40 hover:text-emerald-700 dark:hover:text-emerald-300',
                  )}
                >
                  {watched ? <CheckCircle2 size={13} aria-hidden /> : <Circle size={13} aria-hidden />}
                  {t('videos.watched', { defaultValue: 'Watched' })}
                </button>
                <span className="ml-auto flex flex-wrap items-center gap-1 text-2xs text-content-tertiary">
                  <span className="rounded bg-surface-secondary px-1.5 py-0.5">{labels.stage(video.stage)}</span>
                  <span className="rounded bg-surface-secondary px-1.5 py-0.5">{labels.language(video.language)}</span>
                  {video.market && (
                    <span className="rounded bg-surface-secondary px-1.5 py-0.5">{labels.country(video.market)}</span>
                  )}
                  {labels.example(video) && (
                    <span className="rounded bg-surface-secondary px-1.5 py-0.5">{labels.example(video)}</span>
                  )}
                  {video.duration ? (
                    <span className="rounded bg-surface-secondary px-1.5 py-0.5 font-mono tabular-nums">
                      {formatClock(video.duration)}
                    </span>
                  ) : null}
                </span>
              </div>

              {video.description && (
                <p lang={video.language} className="whitespace-pre-line text-sm leading-relaxed text-content-secondary">
                  {video.description}
                </p>
              )}
              {video.produces && (
                <p className="text-xs text-content-secondary">
                  <span className="font-semibold text-content-primary">
                    {t('videos.you_end_with', { defaultValue: 'You end with' })}:
                  </span>{' '}
                  <span lang="en">{video.produces}</span>
                </p>
              )}
              {(video.roles.length > 0 || video.result) && (
                <div className="flex flex-wrap items-center gap-1 text-2xs">
                  {video.roles.map((r) => (
                    <span key={r} className="rounded-full border border-border-light px-2 py-0.5 text-content-secondary">
                      {labels.role(r)}
                    </span>
                  ))}
                  {video.result && (
                    <span className="rounded-full border border-oe-blue/30 bg-oe-blue/[0.06] px-2 py-0.5 text-oe-blue">
                      {labels.result(video.result)}
                    </span>
                  )}
                </div>
              )}

              {cases.length > 0 && (
                <section aria-labelledby={`${titleId}-cases`} className="rounded-xl border border-border-light bg-surface-secondary/40 p-3">
                  <h3 id={`${titleId}-cases`} className="flex items-center gap-1.5 text-xs font-semibold text-content-primary">
                    <Route size={13} className="text-oe-blue" aria-hidden />
                    {t('videos.try_in_app', { defaultValue: 'Try it in the app' })}
                  </h3>
                  <p className="mt-0.5 text-2xs text-content-tertiary">
                    {t('videos.related_cases_note', {
                      defaultValue: 'Cases that cover similar ground, suggested by our editors. The video and a case may not match step for step.',
                    })}
                  </p>
                  <ul className="mt-2 grid gap-1 sm:grid-cols-2">
                    {cases.map(({ id, ref }) => (
                      <li key={id}>
                        <Link
                          to={`/cases/${id}`}
                          onClick={onClose}
                          className="group/case flex items-center gap-2 rounded-lg border border-border-light bg-surface-primary px-2.5 py-1.5 text-xs text-content-primary hover:border-oe-blue/40 hover:text-oe-blue"
                        >
                          <span className="min-w-0 flex-1 truncate">{t(ref!.titleKey, { defaultValue: ref!.titleDefault })}</span>
                          {ref!.region && <span className="shrink-0 text-2xs text-content-tertiary">{ref!.region}</span>}
                          <ArrowRight size={12} className="shrink-0 opacity-50 group-hover/case:opacity-100" aria-hidden />
                        </Link>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {(prev || next) && (
                <div className="flex items-stretch gap-2">
                  {prev ? (
                    <button
                      type="button"
                      onClick={() => onOpenVideo(prev)}
                      className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-border-light px-2.5 py-2 text-left text-xs hover:border-oe-blue/40"
                    >
                      <ChevronLeft size={14} className="shrink-0 text-content-tertiary" aria-hidden />
                      <span className="min-w-0">
                        <span className="block text-2xs text-content-tertiary">{t('videos.previous', { defaultValue: 'Previous' })}</span>
                        <span lang={prev.language} className="block truncate text-content-primary">{prev.title}</span>
                      </span>
                    </button>
                  ) : (
                    <span className="flex-1" />
                  )}
                  {next ? (
                    <button
                      type="button"
                      onClick={() => onOpenVideo(next)}
                      className="flex min-w-0 flex-1 items-center justify-end gap-2 rounded-lg border border-border-light px-2.5 py-2 text-right text-xs hover:border-oe-blue/40"
                    >
                      <span className="min-w-0">
                        <span className="block text-2xs text-content-tertiary">{t('videos.next', { defaultValue: 'Next' })}</span>
                        <span lang={next.language} className="block truncate text-content-primary">{next.title}</span>
                      </span>
                      <ChevronRight size={14} className="shrink-0 text-content-tertiary" aria-hidden />
                    </button>
                  ) : (
                    <span className="flex-1" />
                  )}
                </div>
              )}
            </div>
          </div>

          {/* ── Chapters ───────────────────────────────────────────────── */}
          <aside
            aria-labelledby={`${titleId}-chapters`}
            className="border-t border-border-light bg-surface-secondary/30 lg:overflow-y-auto lg:border-l lg:border-t-0"
          >
            <h3 id={`${titleId}-chapters`} className="sticky top-0 z-10 border-b border-border-light bg-surface-primary/95 px-4 py-2.5 text-xs font-semibold text-content-primary backdrop-blur">
              {t('videos.chapters', { defaultValue: 'Chapters' })}
              <span className="ml-1.5 font-normal tabular-nums text-content-tertiary">{video.chapters.length}</span>
            </h3>
            {video.chapters.length === 0 ? (
              <p className="px-4 py-3 text-xs text-content-tertiary">
                {t('videos.no_chapters', { defaultValue: 'This video has no chapters.' })}
              </p>
            ) : (
              <ol className="p-2">
                {video.chapters.map((c, i) => {
                  const active = i === current && (playing || start > 0);
                  const body = (
                    <>
                      <span className="w-12 shrink-0 font-mono text-2xs tabular-nums text-content-tertiary">{formatClock(c.t)}</span>
                      <span lang={video.language} className="min-w-0 flex-1 leading-snug">{c.title}</span>
                    </>
                  );
                  return (
                    <li key={`${c.t}-${i}`}>
                      {published ? (
                        <button
                          type="button"
                          onClick={() => seek(c.t)}
                          aria-current={active ? 'true' : undefined}
                          className={clsx(
                            'flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-xs transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
                            active
                              ? 'bg-oe-blue/10 font-medium text-oe-blue'
                              : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
                          )}
                        >
                          {body}
                        </button>
                      ) : (
                        <div className="flex items-start gap-2 px-2 py-1.5 text-xs text-content-secondary">{body}</div>
                      )}
                    </li>
                  );
                })}
              </ol>
            )}
          </aside>
        </div>
      </div>
    </div>,
    document.body,
  );
}
