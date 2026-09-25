// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One video as a card: cover, running time, status, what it is for, and
// (from a search) the chapters that matched, each one a way straight into the
// player at that second. A video that is not out yet opens the same dialog,
// which then shows its outline instead of a player.

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { CheckCircle2, Clock, Hourglass, ListOrdered, MapPin, Play } from 'lucide-react';
import type { AcademyVideo, VideoChapter } from './academyTypes';
import { VideoCover } from './VideoCover';
import { formatClock } from './academy';
import { useVideosStore } from './useVideosStore';
import type { VideoLabels } from './videoLabels';

export interface VideoCardProps {
  video: AcademyVideo;
  labels: VideoLabels;
  onOpen: (video: AcademyVideo, start?: number) => void;
  /** Chapters a search matched; shown as jump chips. */
  chapterHits?: VideoChapter[];
  /** Compact cards drop the description, for rows and rails. */
  compact?: boolean;
  className?: string;
}

export function VideoCard({ video, labels, onOpen, chapterHits, compact, className }: VideoCardProps) {
  const { t } = useTranslation();
  const watched = useVideosStore((s) => Boolean(s.watched[video.id]));
  const soon = video.status !== 'published';
  const hits = chapterHits?.slice(0, 4) ?? [];
  const example = labels.example(video);

  return (
    <article
      data-testid="video-card"
      data-video-id={video.id}
      className={clsx(
        'group relative flex flex-col overflow-hidden rounded-xl border border-border-light bg-surface-primary shadow-sm transition-all',
        'hover:-translate-y-0.5 hover:border-oe-blue/40 hover:shadow-md focus-within:border-oe-blue/50',
        className,
      )}
    >
      <button
        type="button"
        onClick={() => onOpen(video)}
        aria-label={
          soon
            ? t('videos.open_outline', { defaultValue: 'Open the outline: {{title}}', title: video.title })
            : t('videos.play', { defaultValue: 'Play: {{title}}', title: video.title })
        }
        className="relative block aspect-video w-full overflow-hidden bg-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-oe-blue"
      >
        <VideoCover
          src={video.cover}
          className={clsx(
            'h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.03]',
            soon && 'opacity-80 saturate-[0.85]',
          )}
        />
        <span
          aria-hidden="true"
          className="absolute inset-0 bg-gradient-to-t from-black/55 via-black/0 to-black/0 opacity-80 transition-opacity group-hover:opacity-100"
        />
        {soon ? (
          <span className="absolute left-2 top-2 inline-flex items-center gap-1 rounded-full bg-black/65 px-2 py-0.5 text-2xs font-semibold uppercase tracking-wide text-amber-200 backdrop-blur-sm">
            <Hourglass size={11} strokeWidth={2.2} aria-hidden />
            {t('videos.coming_soon', { defaultValue: 'Coming soon' })}
          </span>
        ) : (
          <span
            aria-hidden="true"
            className="absolute left-1/2 top-1/2 flex h-11 w-11 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-white/90 text-slate-900 opacity-0 shadow-lg transition-all group-hover:opacity-100 group-focus-within:opacity-100"
          >
            <Play size={18} strokeWidth={2.4} className="translate-x-px" fill="currentColor" />
          </span>
        )}
        {watched && (
          <span className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-full bg-emerald-600/90 px-2 py-0.5 text-2xs font-semibold text-white">
            <CheckCircle2 size={11} strokeWidth={2.4} aria-hidden />
            {t('videos.watched', { defaultValue: 'Watched' })}
          </span>
        )}
        {video.duration ? (
          <span className="absolute bottom-2 right-2 inline-flex items-center gap-1 rounded bg-black/75 px-1.5 py-0.5 font-mono text-2xs tabular-nums text-white">
            <Clock size={10} strokeWidth={2.4} aria-hidden />
            {formatClock(video.duration)}
          </span>
        ) : null}
        <span className="absolute bottom-2 left-2 rounded bg-black/60 px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wide text-white/90">
          {video.language}
          {video.market ? ` · ${video.market}` : ''}
        </span>
      </button>

      <div className="flex min-w-0 flex-1 flex-col gap-1.5 p-3">
        <p className="truncate text-2xs font-medium uppercase tracking-wide text-content-tertiary">
          {labels.series(video.series)}
        </p>
        <h3 lang={video.language} className="line-clamp-2 text-sm font-semibold leading-snug text-content-primary">
          <button type="button" onClick={() => onOpen(video)} className="text-left hover:text-oe-blue focus:outline-none focus-visible:underline">
            {video.title}
          </button>
        </h3>
        {example && (
          <p data-testid="video-example" className="inline-flex items-center gap-1 text-2xs text-content-tertiary">
            <MapPin size={10} className="shrink-0" aria-hidden />
            <span className="truncate">{example}</span>
          </p>
        )}
        {!compact && video.description && (
          <p lang={video.language} className="line-clamp-2 text-xs leading-relaxed text-content-secondary">
            {video.description}
          </p>
        )}
        {hits.length > 0 && (
          <ul
            aria-label={t('videos.matching_chapters', { defaultValue: 'Matching chapters' })}
            className="mt-0.5 flex flex-wrap gap-1"
          >
            {hits.map((c) => (
              <li key={c.t}>
                <button
                  type="button"
                  onClick={() => onOpen(video, c.t)}
                  lang={video.language}
                  className="inline-flex max-w-full items-center gap-1 rounded-md border border-oe-blue/30 bg-oe-blue/[0.06] px-1.5 py-0.5 text-2xs text-oe-blue hover:bg-oe-blue/15"
                >
                  <span className="font-mono tabular-nums">{formatClock(c.t)}</span>
                  <span className="truncate">{c.title}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-auto flex flex-wrap items-center gap-1 pt-1 text-2xs text-content-tertiary">
          <span className="rounded bg-surface-secondary px-1.5 py-0.5">{labels.stageShort(video.stage)}</span>
          {video.result && <span className="rounded bg-surface-secondary px-1.5 py-0.5">{labels.result(video.result)}</span>}
          {video.chapters.length > 0 && (
            <span
              className="ml-auto inline-flex items-center gap-1 tabular-nums"
              title={t('videos.chapters', { defaultValue: 'Chapters' })}
            >
              <ListOrdered size={11} strokeWidth={2.2} aria-hidden />
              <span className="sr-only">{t('videos.chapters', { defaultValue: 'Chapters' })}:</span>
              {video.chapters.length}
            </span>
          )}
        </div>
      </div>
    </article>
  );
}
