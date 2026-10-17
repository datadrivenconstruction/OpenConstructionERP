// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The video half of the dashboard's "Start here" card: the videos picked for
// the reader's role and country, as thumbnails on the same grid as the case
// tiles above them. The dashboard loads this lazily, so the catalogue arrives
// only with the card, and nothing plays here: a tile opens the video on the
// Videos page, where the no-cookie player loads on play.

import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { ArrowRight, Clock, MonitorPlay, Play } from 'lucide-react';
import type { AcademyVideo } from './academyTypes';
import { VIDEOS, formatClock, recommend, type RecommendationContext } from './academy';
import { VideoCover } from './VideoCover';
import { useVideoContext } from './useVideoContext';
import { languageTag, preferLanguage } from '@/features/dashboard/contentLanguage';
import { ContentLanguageNote } from '@/features/dashboard/ContentLanguageNote';

/**
 * The recommendations for the dashboard, published only, at most `count`.
 * The setup lesson is left out: whoever reads the dashboard has already
 * installed the platform (founder, 17.10.2026). It stays first on the Videos
 * page, where a new reader still finds it. Among the recommendations, videos
 * spoken in the UI language come first, so the tiles a narrow screen keeps
 * are the ones the reader can follow.
 */
export function dashboardVideos(
  ctx: RecommendationContext,
  count: number,
  videos: AcademyVideo[] = VIDEOS,
): AcademyVideo[] {
  const out: AcademyVideo[] = [];
  const ranked = recommend(ctx, videos, count + 4);
  for (const v of ctx.language ? preferLanguage(ranked, (x) => x.language, ctx.language) : ranked) {
    if (out.length >= count) break;
    if (v.status === 'published' && !v.startHere && !out.includes(v)) out.push(v);
  }
  return out;
}

export interface DashboardVideosStripProps {
  /** Video tiles at the widest column count, the same as the case tiles. */
  count: number;
  /** The case gallery's literal column classes, so both rows line up. */
  columns: string;
  /** The case gallery's per-tile visibility, so both rows end at the same cell. */
  tileVisibility: readonly string[];
}

export default function DashboardVideosStrip({ count, columns, tileVisibility }: DashboardVideosStripProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const ctx = useVideoContext();
  const videos = useMemo(
    () => dashboardVideos({ role: ctx.role, market: ctx.market, language: ctx.language }, count),
    [ctx.role, ctx.market, ctx.language, count],
  );
  if (videos.length === 0) return null;
  const tags = videos.map((video) => languageTag(video.language, i18n.language));

  return (
    // The same grid as the case tiles above, tile for tile, ending on a
    // tile that opens the library just as the cases end on "All cases". Each
    // tile reads as a video at a glance: a play disc in the middle, a "Video"
    // mark and the running time large enough to read. Nothing autoplays.
    <section data-testid="dashboard-videos" aria-labelledby="dashboard-videos-title" className="mt-3 border-t border-border-light pt-3">
      <div className="mb-1.5 flex items-center gap-2">
        <span id="dashboard-videos-title" className="flex items-center gap-1 text-2xs font-medium text-content-tertiary">
          <MonitorPlay size={11} aria-hidden="true" />
          {t('nav.videos', { defaultValue: 'Video guides' })}
        </span>
        <ContentLanguageNote tags={tags} className="ms-auto" testId="dashboard-videos-lang-note" />
      </div>
      <ul className={clsx('grid gap-2', columns)} data-testid="dashboard-videos-grid">
        {videos.map((video, i) => (
          <li key={video.id} className={clsx(tileVisibility[i])}>
            <button
              type="button"
              data-testid="dashboard-video"
              onClick={() => navigate(`/videos?v=${encodeURIComponent(video.id)}`)}
              aria-label={t('videos.play', { defaultValue: 'Play: {{title}}', title: video.title })}
              className="group flex h-full w-full flex-col overflow-hidden rounded-lg border border-border-light bg-surface-primary text-start shadow-xs transition-colors hover:border-oe-blue/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
            >
              <span className="relative block aspect-video w-full overflow-hidden bg-slate-900">
                <VideoCover src={video.cover} width={320} height={180} className="h-full w-full object-cover" />
                <span aria-hidden="true" className="absolute inset-0 bg-black/15 transition-colors group-hover:bg-black/30 motion-reduce:transition-none" />
                <span
                  aria-hidden="true"
                  className="absolute left-1/2 top-1/2 flex h-9 w-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-white/90 text-slate-900 shadow-md transition-colors group-hover:bg-white motion-reduce:transition-none"
                >
                  <Play size={15} className="ms-0.5" fill="currentColor" />
                </span>
                <span className="absolute start-1.5 top-1.5 inline-flex items-center gap-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white">
                  <MonitorPlay size={10} aria-hidden="true" />
                  {t('videos.tile_badge', { defaultValue: 'Video' })}
                </span>
                {tags[i] && (
                  <span
                    data-testid="dashboard-video-lang"
                    title={t('dashboard.content_language_fallback', { defaultValue: 'Not yet available in your language' })}
                    className="absolute end-1.5 top-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white"
                  >
                    {tags[i]}
                  </span>
                )}
                {video.duration ? (
                  <span
                    data-testid="dashboard-video-duration"
                    className="absolute bottom-1.5 end-1.5 inline-flex items-center gap-1 rounded-md bg-black/80 px-1.5 py-0.5 text-xs font-semibold tabular-nums text-white"
                  >
                    <Clock size={11} aria-hidden="true" />
                    {formatClock(video.duration)}
                  </span>
                ) : null}
              </span>
              <span lang={video.language} className="line-clamp-2 px-2 py-1.5 text-xs font-medium leading-snug text-content-primary group-hover:text-oe-blue-text">
                {video.title}
              </span>
            </button>
          </li>
        ))}
        <li>
          <button
            type="button"
            onClick={() => navigate('/videos')}
            data-testid="dashboard-videos-all"
            className="group flex h-full w-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-oe-blue/40 bg-oe-blue/[0.05] px-2 py-3 text-center transition-colors hover:border-oe-blue/60 hover:bg-oe-blue/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-oe-blue/10 text-oe-blue ring-1 ring-inset ring-oe-blue/20">
              <ArrowRight size={18} strokeWidth={2} className="rtl:rotate-180" aria-hidden="true" />
            </span>
            <span className="text-xs font-semibold leading-snug text-oe-blue-text">
              {t('videos.library_title', { defaultValue: 'All videos' })}
            </span>
          </button>
        </li>
      </ul>
    </section>
  );
}
