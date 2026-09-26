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
    <section data-testid="dashboard-videos" aria-labelledby="dashboard-videos-title" className="mt-3">
      <div className="mb-1.5 flex items-center gap-2">
        <span id="dashboard-videos-title" className="flex items-center gap-1 text-2xs font-semibold uppercase tracking-wide text-content-secondary">
          <MonitorPlay size={11} className="text-oe-blue" aria-hidden="true" />
          {t('nav.videos', { defaultValue: 'Video guides' })}
        </span>
        <Link
          to="/videos"
          className="ms-auto inline-flex items-center gap-1 text-2xs font-semibold text-oe-blue hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
        >
          {t('videos.library_title', { defaultValue: 'All videos' })}
          <ArrowRight size={11} aria-hidden="true" />
        </Link>
      </div>
      <ul className={clsx('grid gap-2', count >= 4 ? 'grid-cols-2 sm:grid-cols-4' : count === 3 ? 'grid-cols-2 sm:grid-cols-3' : 'grid-cols-2')}>
        {videos.map((video, i) => (
          // Two on a phone, so the card keeps one row there.
          <li key={video.id} className={clsx(i >= 2 && 'hidden sm:block')}>
            <button
              type="button"
              data-testid="dashboard-video"
              onClick={() => navigate(`/videos?v=${encodeURIComponent(video.id)}`)}
              aria-label={t('videos.play', { defaultValue: 'Play: {{title}}', title: video.title })}
              className="group flex w-full flex-col overflow-hidden rounded-lg border border-border-light bg-surface-primary text-left shadow-xs transition duration-200 hover:-translate-y-0.5 hover:border-oe-blue/40 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 motion-reduce:transition-none motion-reduce:hover:translate-y-0"
            >
              <span className="relative block aspect-video w-full overflow-hidden bg-slate-900">
                <VideoCover src={video.cover} width={320} height={180} className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03] motion-reduce:transition-none" />
                <span aria-hidden="true" className="absolute inset-0 bg-gradient-to-t from-black/45 via-transparent to-transparent" />
                <span
                  aria-hidden="true"
                  className="absolute left-1/2 top-1/2 flex h-9 w-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-white/90 text-oe-blue shadow-md transition-transform group-hover:scale-110 motion-reduce:transition-none"
                >
                  <Play size={16} className="ms-0.5" fill="currentColor" />
                </span>
                {video.startHere && (
                  <span className="absolute left-1.5 top-1.5 rounded-full bg-oe-blue px-1.5 py-0.5 text-[10px] font-semibold text-white shadow-sm">
                    {t('videos.start_here', { defaultValue: 'Start here' })}
                  </span>
                )}
                {video.duration ? (
                  <span className="absolute bottom-1.5 right-1.5 rounded bg-black/75 px-1 py-px font-mono text-[10px] tabular-nums text-white">
                    {formatClock(video.duration)}
                  </span>
                ) : null}
              </span>
              <span lang={video.language} className="line-clamp-2 px-2 py-1.5 text-xs font-semibold leading-snug text-content-primary">
                {video.title}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
