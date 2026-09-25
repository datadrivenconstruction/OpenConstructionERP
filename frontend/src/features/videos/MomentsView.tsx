// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The library as moments: one line per video, its chapters laid out along
// the running time, so the reader can see where in a video a topic sits and
// start right there. With a search, the matching chapters are lit and listed;
// without one, every chapter is listed under its video, folded after a few.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import type { AcademyVideo, VideoChapter } from './academyTypes';
import { formatClock, type VideoHit } from './academy';
import { VideoCover } from './VideoCover';
import type { VideoLabels } from './videoLabels';

// Fold after four, but never to hide a single line behind a link.
const FOLDED = 4;

export interface MomentsViewProps {
  hits: VideoHit[];
  searching: boolean;
  labels: VideoLabels;
  onOpen: (video: AcademyVideo, start?: number) => void;
}

/** Where a chapter sits along the video, as a share of its running time. */
export function chapterOffset(chapter: VideoChapter, video: AcademyVideo): number {
  const end = video.duration ?? (video.chapters.at(-1)?.t ?? 0) + 60;
  return end > 0 ? Math.min(1, Math.max(0, chapter.t / end)) : 0;
}

export function MomentsView({ hits, searching, labels, onOpen }: MomentsViewProps) {
  return (
    <ul data-testid="videos-moments" className="space-y-3">
      {hits.map((hit) => (
        <MomentRow key={hit.video.id} hit={hit} searching={searching} labels={labels} onOpen={onOpen} />
      ))}
    </ul>
  );
}

function MomentRow({
  hit,
  searching,
  labels,
  onOpen,
}: {
  hit: VideoHit;
  searching: boolean;
  labels: VideoLabels;
  onOpen: (video: AcademyVideo, start?: number) => void;
}) {
  const { t } = useTranslation();
  const [unfolded, setUnfolded] = useState(false);
  const { video } = hit;
  const lit = new Set(hit.chapters.map((c) => c.t));
  const listed = searching && hit.chapters.length > 0 ? hit.chapters : video.chapters;
  const folds = listed.length > FOLDED + 1;
  const shown = unfolded || !folds ? listed : listed.slice(0, FOLDED);

  return (
    <li
      data-testid="videos-moment-row"
      data-video-id={video.id}
      className="rounded-xl border border-border-light bg-surface-primary p-3 shadow-sm"
    >
      <div className="flex items-start gap-3">
        <button
          type="button"
          onClick={() => onOpen(video)}
          aria-label={t('videos.play', { defaultValue: 'Play: {{title}}', title: video.title })}
          className="relative block h-12 w-20 shrink-0 overflow-hidden rounded-md bg-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue sm:h-14 sm:w-24"
        >
          <VideoCover src={video.cover} width={96} height={54} className="h-full w-full object-cover" />
        </button>
        <div className="min-w-0 flex-1">
          <p className="truncate text-2xs text-content-tertiary">{labels.series(video.series)}</p>
          <p lang={video.language} className="line-clamp-2 text-sm font-semibold leading-snug text-content-primary">
            {video.title}
          </p>
          {video.duration ? (
            <p className="font-mono text-2xs tabular-nums text-content-tertiary">{formatClock(video.duration)}</p>
          ) : null}
        </div>
      </div>

      {video.chapters.length > 0 && (
        <div className="relative mt-3 h-6" aria-hidden="true">
          <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-surface-secondary" />
          {video.chapters.map((c, i) => (
            <button
              key={`${c.t}-${i}`}
              type="button"
              tabIndex={-1}
              title={`${formatClock(c.t)} ${c.title}`}
              onClick={() => onOpen(video, c.t)}
              style={{ left: `${chapterOffset(c, video) * 100}%` }}
              className={clsx(
                'absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-surface-primary transition-transform hover:scale-125',
                lit.has(c.t) ? 'bg-oe-blue' : 'bg-content-quaternary/60 hover:bg-oe-blue/70',
              )}
            />
          ))}
        </div>
      )}

      <ol className="mt-2 grid gap-1 sm:grid-cols-2">
        {shown.map((c, i) => (
          <li key={`${c.t}-${i}`}>
            <button
              type="button"
              onClick={() => onOpen(video, c.t)}
              className={clsx(
                'flex w-full items-start gap-2 rounded-md px-1.5 py-1 text-left text-xs transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
                lit.has(c.t) ? 'bg-oe-blue/10 text-oe-blue' : 'text-content-secondary hover:bg-surface-secondary',
              )}
            >
              <span className="w-11 shrink-0 font-mono text-2xs tabular-nums text-content-tertiary">{formatClock(c.t)}</span>
              <span lang={video.language} className="min-w-0 flex-1 leading-snug">
                {c.title}
              </span>
            </button>
          </li>
        ))}
      </ol>
      {folds && (
        <button
          type="button"
          onClick={() => setUnfolded((u) => !u)}
          aria-expanded={unfolded}
          className="mt-1 text-2xs font-medium text-oe-blue hover:underline"
        >
          {unfolded
            ? t('common.show_less', { defaultValue: 'Show less' })
            : t('videos.more_moments', { defaultValue: '{{more}} more moments', more: listed.length - FOLDED })}
        </button>
      )}
    </li>
  );
}
