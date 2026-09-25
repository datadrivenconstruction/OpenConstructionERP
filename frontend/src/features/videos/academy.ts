// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pure selectors over the video catalogue: filtering, search to the chapter,
// recommendations by role and market, series playlists and the links back to
// cases and module screens. No React and no storage here, so every rule the
// page applies can be tested on its own.

import { ACADEMY_CATALOG } from './academyCatalog.generated';
import type {
  AcademyCaseRef,
  AcademySeries,
  AcademyVideo,
  ResultFamily,
  VideoChapter,
} from './academyTypes';
import type { LifecycleStage, ProfessionalRole } from '@/features/cases/types';

export const CATALOG = ACADEMY_CATALOG;
export const VIDEOS: AcademyVideo[] = ACADEMY_CATALOG.videos;
export const SERIES: AcademySeries[] = ACADEMY_CATALOG.series;

/** Result families in the order the page shows them. */
export const RESULT_FAMILIES: ResultFamily[] = [
  'cost',
  'qty',
  'bill',
  'rate',
  'gaeb',
  'award',
  'order',
  'programme',
  'site',
  'change',
  'invoice',
  'handover',
];

// ── URLs ─────────────────────────────────────────────────────────────────────

/** The privacy-enhanced player, requested only after the reader presses play.
 *  `start` opens the video at a chapter. The backend CSP allows this host. */
export function embedUrl(youtubeId: string, start = 0): string {
  const params = new URLSearchParams({ autoplay: '1', rel: '0', modestbranding: '1', playsinline: '1' });
  if (start > 0) params.set('start', String(Math.floor(start)));
  return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(youtubeId)}?${params.toString()}`;
}

/** The public watch page, for "open in a new tab". */
export function watchUrl(youtubeId: string, start = 0): string {
  const base = `https://www.youtube.com/watch?v=${encodeURIComponent(youtubeId)}`;
  return start > 0 ? `${base}&t=${Math.floor(start)}s` : base;
}

/** The channel page, built from the channel id the publishing package records. */
export function channelUrl(channelId: string = ACADEMY_CATALOG.channelId): string {
  return `https://www.youtube.com/channel/${encodeURIComponent(channelId)}`;
}

/** `m:ss` or `h:mm:ss`. Digits and colons only, the same in every language. */
export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, '0');
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
}

// ── Lookups ──────────────────────────────────────────────────────────────────

export function videoById(id: string | null | undefined): AcademyVideo | undefined {
  return id ? VIDEOS.find((v) => v.id === id) : undefined;
}

export function seriesById(id: string): AcademySeries | undefined {
  return SERIES.find((s) => s.id === id);
}

export function caseRef(id: string): AcademyCaseRef | undefined {
  return ACADEMY_CATALOG.cases[id];
}

/** A series' videos in playing order. */
export function playlist(seriesId: string, videos: AcademyVideo[] = VIDEOS): AcademyVideo[] {
  return videos.filter((v) => v.series === seriesId).sort((a, b) => a.seriesOrder - b.seriesOrder);
}

/** Markets that at least one video teaches, sorted. */
export function catalogMarkets(videos: AcademyVideo[] = VIDEOS): string[] {
  return [...new Set(videos.map((v) => v.market).filter((m): m is string => Boolean(m)))].sort();
}

/** Languages the videos are spoken in, sorted. */
export function catalogLanguages(videos: AcademyVideo[] = VIDEOS): string[] {
  return [...new Set(videos.map((v) => v.language))].sort();
}

/** Videos whose cases walk through `route` (unscoped, query-less base). */
export function videosForRoute(route: string, videos: AcademyVideo[] = VIDEOS): AcademyVideo[] {
  const base = route.split('?')[0] ?? route;
  return videos.filter((v) => v.routes.includes(base));
}

/** Videos linked to a case. */
export function videosForCase(caseId: string, videos: AcademyVideo[] = VIDEOS): AcademyVideo[] {
  return videos.filter((v) => v.cases.includes(caseId));
}

/** A video is for a role when it names the role or names no role at all. */
export function isForRole(video: AcademyVideo, role: ProfessionalRole | null): boolean {
  return !role || video.roles.length === 0 || video.roles.includes(role);
}

// ── Filters and search ───────────────────────────────────────────────────────

export interface VideoFilters {
  role: ProfessionalRole | null;
  stage: LifecycleStage | null;
  /** A market code, `universal` for videos that apply anywhere, or null. */
  market: string | null;
  language: string | null;
  series: string | null;
  result: ResultFamily | null;
  query: string;
}

export const NO_FILTERS: VideoFilters = {
  role: null,
  stage: null,
  market: null,
  language: null,
  series: null,
  result: null,
  query: '',
};

/** Lower-case and strip accents, so "Quebec" finds "Québec" and "aufmass"
 *  still needs its own spelling but "Aufmaß" finds "aufmaß". */
export function fold(text: string): string {
  return text.normalize('NFD').replace(/\p{M}+/gu, '').toLowerCase();
}

export interface VideoHit {
  video: AcademyVideo;
  /** Chapters whose title matches the query, in order. Empty when the match
   *  is in the title or description, or when there is no query. */
  chapters: VideoChapter[];
}

function matchesQuery(video: AcademyVideo, terms: string[]): VideoHit | null {
  if (terms.length === 0) return { video, chapters: [] };
  const seriesTitle = seriesById(video.series)?.title ?? '';
  const all = fold(
    [video.title, video.titleEn, video.description, video.produces, seriesTitle, ...video.chapters.map((c) => c.title)].join(
      ' \n ',
    ),
  );
  // Every term has to appear somewhere in the video; a chapter is reported
  // when its own title carries at least one of them.
  if (!terms.every((term) => all.includes(term))) return null;
  const chapters = video.chapters.filter((c) => {
    const text = fold(c.title);
    return terms.some((term) => text.includes(term));
  });
  return { video, chapters };
}

/** Apply every filter; the query also reports which chapters it matched. */
export function searchVideos(filters: VideoFilters, videos: AcademyVideo[] = VIDEOS): VideoHit[] {
  const terms = fold(filters.query).split(/\s+/).filter(Boolean);
  const hits: VideoHit[] = [];
  for (const video of videos) {
    if (!isForRole(video, filters.role)) continue;
    if (filters.stage && video.stage !== filters.stage) continue;
    if (filters.market === 'universal' && video.market) continue;
    if (filters.market && filters.market !== 'universal' && video.market !== filters.market) continue;
    if (filters.language && video.language !== filters.language) continue;
    if (filters.series && video.series !== filters.series) continue;
    if (filters.result && video.result !== filters.result) continue;
    const hit = matchesQuery(video, terms);
    if (hit) hits.push(hit);
  }
  return hits;
}

export function activeFilterCount(filters: VideoFilters): number {
  return (Object.keys(filters) as (keyof VideoFilters)[]).filter((k) =>
    k === 'query' ? filters.query.trim() !== '' : filters[k] !== null,
  ).length;
}

// ── Recommendations ──────────────────────────────────────────────────────────

export interface RecommendationContext {
  role: ProfessionalRole | null;
  market: string | null;
  /** The UI language's base code (`de`, `fr`). */
  language: string | null;
}

/**
 * Videos for this reader, best first.
 *
 * A video for another market is left out once the reader has a market; one
 * for another role is left out once they have a role. What remains is ranked
 * by whether it can be played now, then by how exactly it fits: named for the
 * role over "every role", the reader's own market over "any market", spoken in
 * their language, then the series order so a course reads in sequence.
 */
export function recommend(
  ctx: RecommendationContext,
  videos: AcademyVideo[] = VIDEOS,
  limit = 8,
): AcademyVideo[] {
  const scored: { video: AcademyVideo; score: number; index: number }[] = [];
  videos.forEach((video, index) => {
    if (!isForRole(video, ctx.role)) return;
    if (ctx.market && video.market && video.market !== ctx.market) return;
    let score = 0;
    if (ctx.role && video.roles.includes(ctx.role)) score += 4;
    if (ctx.market && video.market === ctx.market) score += 4;
    if (ctx.language && video.language === ctx.language) score += 3;
    // A video the reader can play now outranks a closer fit they cannot.
    if (video.status === 'published') score += 5;
    if (video.channel === 'academy') score += 1;
    scored.push({ video, score, index });
  });
  return scored
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .slice(0, limit)
    .map((s) => s.video);
}

/** The entry point for somebody new: the setup lesson. */
export function startHereVideo(videos: AcademyVideo[] = VIDEOS): AcademyVideo | undefined {
  return videos.find((v) => v.startHere);
}

// ── Coverage ─────────────────────────────────────────────────────────────────

/** How many videos sit at each (row, stage) cell, for the coverage matrix. */
export function coverage<K extends string>(
  rows: readonly K[],
  rowOf: (video: AcademyVideo) => readonly K[],
  stages: readonly LifecycleStage[],
  videos: AcademyVideo[] = VIDEOS,
): Map<K, Map<LifecycleStage, AcademyVideo[]>> {
  const out = new Map<K, Map<LifecycleStage, AcademyVideo[]>>();
  for (const row of rows) out.set(row, new Map(stages.map((s) => [s, []])));
  for (const video of videos) {
    for (const row of rowOf(video)) out.get(row)?.get(video.stage)?.push(video);
  }
  return out;
}
