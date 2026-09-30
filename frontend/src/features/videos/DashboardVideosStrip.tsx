// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The video half of the dashboard's "Start here" card: the setup lesson first,
// then the videos picked for the reader's role and country, as thumbnails. The
// dashboard loads this lazily, so the catalogue arrives only with the card,
// and nothing plays here: a tile opens the video on the Videos page, where the
// no-cookie player loads on play.

import { useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { ArrowRight, MonitorPlay, Play } from 'lucide-react';
import type { AcademyVideo } from './academyTypes';
import { VIDEOS, formatClock, recommend, startHereVideo, type RecommendationContext } from './academy';
import { VideoCover } from './VideoCover';
import { useVideoContext } from './useVideoContext';

/** Start here, then the recommendations, published only, at most `count`. */
export function dashboardVideos(
  ctx: RecommendationContext,
  count: number,
  videos: AcademyVideo[] = VIDEOS,
): AcademyVideo[] {
  const out: AcademyVideo[] = [];
  const start = startHereVideo(videos);
  if (start?.status === 'published') out.push(start);
  for (const v of recommend(ctx, videos, count + 4)) {
    if (out.length >= count) break;
    if (v.status === 'published' && !out.includes(v)) out.push(v);
  }
  return out.slice(0, count);
}

/** Columns per video count. Static strings, because a computed
 *  `sm:grid-cols-${n}` would be purged from the build. Three on a phone. */
export const STRIP_COLUMNS: Record<number, string> = {
  2: 'grid-cols-2',
  3: 'grid-cols-3',
  4: 'grid-cols-3 sm:grid-cols-4',
  5: 'grid-cols-3 sm:grid-cols-5',
};

export default function DashboardVideosStrip({ count }: { count: number }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const ctx = useVideoContext();
  const videos = useMemo(
    () => dashboardVideos({ role: ctx.role, market: ctx.market, language: ctx.language }, count),
    [ctx.role, ctx.market, ctx.language, count],
  );
  if (videos.length === 0) return null;

  return (
    // Deliberately quiet. The strip sits under the cases it supports, so it
    // is a neutral row rather than a second hero: grey eyebrow, no hover lift,
    // a small dark play mark instead of a white disc, and a caption in the
    // secondary colour. The card asks for one more video than it used to at
    // each width (see VIDEOS_BY_SPAN), so every thumbnail is about a fifth
    // smaller while the row still ends flush. Nothing autoplays.
    <section data-testid="dashboard-videos" aria-labelledby="dashboard-videos-title" className="mt-3 border-t border-border-light pt-3">
      <div className="mb-1.5 flex items-center gap-2">
        <span id="dashboard-videos-title" className="flex items-center gap-1 text-2xs font-medium text-content-tertiary">
          <MonitorPlay size={11} aria-hidden="true" />
          {t('nav.videos', { defaultValue: 'Video guides' })}
        </span>
        <Link
          to="/videos"
          className="ms-auto inline-flex items-center gap-1 rounded text-2xs font-medium text-content-tertiary hover:text-oe-blue focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
        >
          {t('videos.library_title', { defaultValue: 'All videos' })}
          <ArrowRight size={11} className="rtl:rotate-180" aria-hidden="true" />
        </Link>
      </div>
      <ul className={clsx('grid gap-2', STRIP_COLUMNS[count] ?? STRIP_COLUMNS[5])} data-testid="dashboard-videos-grid">
        {videos.map((video, i) => (
          // Three on a phone, so the row stays one line there too.
          <li key={video.id} className={clsx(i >= 3 && 'hidden sm:block')}>
            <button
              type="button"
              data-testid="dashboard-video"
              onClick={() => navigate(`/videos?v=${encodeURIComponent(video.id)}`)}
              aria-label={t('videos.play', { defaultValue: 'Play: {{title}}', title: video.title })}
              className="group flex w-full flex-col overflow-hidden rounded-md text-start focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
            >
              <span className="relative block aspect-video w-full overflow-hidden rounded-md border border-border-light bg-slate-900">
                <VideoCover src={video.cover} width={320} height={180} className="h-full w-full object-cover opacity-95 transition-opacity group-hover:opacity-100 motion-reduce:transition-none" />
                <span
                  aria-hidden="true"
                  className="absolute bottom-1 start-1 flex h-5 w-5 items-center justify-center rounded-full bg-black/60 text-white"
                >
                  <Play size={9} className="ms-px" fill="currentColor" />
                </span>
                {video.startHere && (
                  <span className="absolute start-1 top-1 rounded bg-black/60 px-1 py-px text-[10px] font-medium text-white">
                    {t('videos.start_here', { defaultValue: 'Start here' })}
                  </span>
                )}
                {video.duration ? (
                  <span className="absolute bottom-1 end-1 rounded bg-black/60 px-1 py-px font-mono text-[10px] tabular-nums text-white">
                    {formatClock(video.duration)}
                  </span>
                ) : null}
              </span>
              <span lang={video.language} className="line-clamp-2 pt-1 text-2xs font-medium leading-snug text-content-secondary group-hover:text-content-primary">
                {video.title}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
