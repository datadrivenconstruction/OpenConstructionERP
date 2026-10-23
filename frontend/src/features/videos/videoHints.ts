// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "Watch how" next to one section of a screen: which chapter of which video
// shows that section, per market and language. Light on purpose (no catalogue
// import), so a page that places a hint does not pull the catalogue in.

import type { AcademyVideo } from './academyTypes';

export type VideoHintTopic =
  | 'retention'
  | 'payment-application'
  | 'bid-leveling'
  | 'daily-diary'
  | 'cost-report'
  | 'change-order'
  | 'payment-notice'
  | 'punch-list';

export interface VideoHintSpot {
  /** The app route the hinted section lives on. */
  route: string;
  /** [video id, second a chapter starts at], in editorial order. */
  chapters: readonly (readonly [string, number])[];
}

export const VIDEO_HINTS: Record<VideoHintTopic, VideoHintSpot> = {
  retention: {
    route: '/finance',
    chapters: [['UK03', 193], ['US08', 150], ['QC05', 135], ['IT08', 192], ['BG07', 83]],
  },
  'payment-application': {
    route: '/finance',
    chapters: [
      ['CA04', 182], ['UK03', 193], ['US08', 123], ['QC04', 133], ['ES01', 100],
      ['IT06', 139], ['BG01', 62], ['HR04', 137], ['CN04', 83], ['DIN07', 119],
    ],
  },
  'bid-leveling': {
    route: '/tendering',
    chapters: [
      ['US05', 74], ['UK02', 137], ['CA03', 145], ['QC03', 133], ['ES03', 52],
      ['IT03', 77], ['BG05', 47], ['CN03', 92], ['DIN05', 67],
    ],
  },
  'daily-diary': {
    route: '/daily-diary',
    chapters: [['US09', 0], ['IT04', 61], ['ES08', 0], ['BG09', 30], ['DIN06', 93]],
  },
  'cost-report': {
    route: '/finance',
    chapters: [['US06', 129], ['ES05', 38], ['IT07', 140], ['CN07', 135], ['BG08', 29], ['HR05', 29]],
  },
  'change-order': {
    route: '/changeorders',
    chapters: [
      ['CA06', 112], ['UK06', 134], ['US08', 89], ['ES04', 21], ['BG06', 24], ['CN05', 194], ['DIN07', 39],
    ],
  },
  'payment-notice': {
    route: '/payment-clock',
    chapters: [['UK04', 157], ['CA05', 124]],
  },
  'punch-list': {
    route: '/punchlist',
    chapters: [['US09', 119], ['QC05', 79], ['ES06', 35], ['DIN08', 45]],
  },
};

export interface HintReader {
  market: string | null;
  /** Interface language base code. */
  language: string;
}

/**
 * The chapter to offer a reader: their market first, then their language, then
 * a video that applies anywhere, then English. A video in neither the reader's
 * language nor English is offered only when it teaches the reader's market;
 * otherwise there is no hint at all rather than a lesson they cannot follow.
 */
export function pickVideoHint(
  topic: VideoHintTopic,
  reader: HintReader,
  videos: readonly AcademyVideo[],
): { video: AcademyVideo; start: number } | null {
  const byId = new Map(videos.map((v) => [v.id, v]));
  let best: { video: AcademyVideo; start: number; score: number } | null = null;
  for (const [id, start] of VIDEO_HINTS[topic].chapters) {
    const video = byId.get(id);
    if (!video || video.status !== 'published' || !video.youtubeId) continue;
    const ownMarket = !!reader.market && video.market === reader.market;
    if (!ownMarket && video.language !== reader.language && video.language !== 'en') continue;
    let score = 0;
    if (ownMarket) score += 8;
    if (video.language === reader.language) score += 4;
    if (!video.market) score += 2;
    if (video.language === 'en') score += 1;
    if (!best || score > best.score) best = { video, start, score };
  }
  return best ? { video: best.video, start: best.start } : null;
}
