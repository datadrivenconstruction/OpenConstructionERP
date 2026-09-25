// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The tutorial videos the Videos page lists, and the topics it groups them by.
//
// Every entry is a video DataDrivenConstruction has published on its own
// channel. The ids were taken from the places the project already links them
// (README, docs/docs.html, the marketing site's release notes and talk page),
// never typed from memory: a wrong id plays somebody else's video inside the
// product. Adding one is a new entry here plus its title and description keys
// in the locales; the page picks it up with no other edit.
//
// Thumbnails are local stills under `public/assets/videos/`, cut from the
// posters the marketing site already uses for the same videos. Nothing is
// requested from the video host until the reader presses play, the same
// promise the marketing site makes.

import type { LucideIcon } from 'lucide-react';
import { Rocket, Calculator, Boxes, CalendarRange, Wallet, Presentation } from 'lucide-react';

export type VideoCategoryId =
  | 'getting_started'
  | 'estimating'
  | 'cad_bim'
  | 'scheduling'
  | 'finance'
  | 'talks';

export interface VideoCategory {
  id: VideoCategoryId;
  icon: LucideIcon;
  labelKey: string;
  defaultLabel: string;
  descriptionKey: string;
  defaultDescription: string;
}

export interface TutorialVideo {
  /** Stable id for React keys and deep links (`/videos?v=<id>`). */
  id: string;
  /** The 11-character id of the published video. */
  youtubeId: string;
  category: VideoCategoryId;
  titleKey: string;
  defaultTitle: string;
  descriptionKey: string;
  defaultDescription: string;
  /** Running time in whole minutes, when the source states it. Left out
   *  rather than guessed when it does not. */
  minutes?: number;
  /** The release the recording shows, when known. Older walkthroughs still
   *  teach the workflow, but the screens have moved on since. */
  recordedOn?: string;
  /** Path under `public/`. */
  thumbnail: string;
}

/** Topics in reading order. A topic with no video yet still renders, as a
 *  "coming soon" card, so the page shows where the library is going. */
export const VIDEO_CATEGORIES: VideoCategory[] = [
  {
    id: 'getting_started',
    icon: Rocket,
    labelKey: 'videos.category.getting_started',
    defaultLabel: 'Getting started',
    descriptionKey: 'videos.category.getting_started_desc',
    defaultDescription: 'Walkthroughs of the whole platform, from the first project to a priced bill.',
  },
  {
    id: 'estimating',
    icon: Calculator,
    labelKey: 'videos.category.estimating',
    defaultLabel: 'Estimating & BOQ',
    descriptionKey: 'videos.category.estimating_desc',
    defaultDescription: 'Building a bill of quantities, pricing it from cost databases and applying markups.',
  },
  {
    id: 'cad_bim',
    icon: Boxes,
    labelKey: 'videos.category.cad_bim',
    defaultLabel: 'CAD, BIM & takeoff',
    descriptionKey: 'videos.category.cad_bim_desc',
    defaultDescription: 'Turning drawings and models into quantities and linking them to the bill.',
  },
  {
    id: 'scheduling',
    icon: CalendarRange,
    labelKey: 'videos.category.scheduling',
    defaultLabel: 'Scheduling',
    descriptionKey: 'videos.category.scheduling_desc',
    defaultDescription: 'Schedules, resource loading and 4D planning.',
  },
  {
    id: 'finance',
    icon: Wallet,
    labelKey: 'videos.category.finance',
    defaultLabel: 'Contracts & finance',
    descriptionKey: 'videos.category.finance_desc',
    defaultDescription: 'Contracts, change orders, payment applications and cost control.',
  },
  {
    id: 'talks',
    icon: Presentation,
    labelKey: 'videos.category.talks',
    defaultLabel: 'Talks & ideas',
    descriptionKey: 'videos.category.talks_desc',
    defaultDescription: 'The thinking behind the platform: open data, open formats and where estimating is heading.',
  },
];

export const TUTORIAL_VIDEOS: TutorialVideo[] = [
  {
    // marketing-site/news/v15-0-0.html and the homepage lead video.
    id: 'walkthrough-v15',
    youtubeId: 'vENnh7bBVVM',
    category: 'getting_started',
    titleKey: 'videos.item.walkthrough_v15.title',
    defaultTitle: 'From a drawing to a priced tender',
    descriptionKey: 'videos.item.walkthrough_v15.description',
    defaultDescription:
      'The whole chain in one take: a drawing becomes a takeoff, the takeoff becomes a bill, the bill carries its markups and the job is inspected on site. One data model underneath all of it.',
    recordedOn: '15.0',
    thumbnail: '/assets/videos/walkthrough-v15.webp',
  },
  {
    // README.md and docs/docs.html, "the 12-min walkthrough".
    id: 'walkthrough-full',
    youtubeId: 'X06cIaroAeI',
    category: 'getting_started',
    titleKey: 'videos.item.walkthrough_full.title',
    defaultTitle: 'Full product walkthrough',
    descriptionKey: 'videos.item.walkthrough_full.description',
    defaultDescription:
      'Onboarding, a new project, the bill of quantities, BIM linking, DWG and PDF takeoff, the AI estimate and the portfolio dashboard, in the order you would use them.',
    minutes: 12,
    recordedOn: '2.0',
    thumbnail: '/assets/videos/walkthrough-12min.webp',
  },
  {
    // marketing-site/uberization/, the ETH Zurich talk (PT14M22S).
    id: 'eth-zurich-talk',
    youtubeId: 'R_PQQHXY-rQ',
    category: 'talks',
    titleKey: 'videos.item.eth_talk.title',
    defaultTitle: 'The uberization of construction',
    descriptionKey: 'videos.item.eth_talk.description',
    defaultDescription:
      'A talk at ETH Zurich on how drawings and models turn into quantities, why cost data stays locked up, and what open formats and AI agents change.',
    minutes: 14,
    thumbnail: '/assets/videos/eth-zurich-talk.webp',
  },
];

/** The channel every video above is published on. */
export const VIDEO_CHANNEL_URL = 'https://www.youtube.com/@datadrivenconstruction';

/** The privacy-enhanced player URL, requested only after the reader presses
 *  play. The backend CSP allows exactly this host on `frame-src`. */
export function embedUrl(youtubeId: string): string {
  return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(youtubeId)}?autoplay=1&rel=0&modestbranding=1&playsinline=1`;
}

/** The public watch page, for "open in a new tab". */
export function watchUrl(youtubeId: string): string {
  return `https://www.youtube.com/watch?v=${encodeURIComponent(youtubeId)}`;
}

export function videosInCategory(category: VideoCategoryId): TutorialVideo[] {
  return TUTORIAL_VIDEOS.filter((video) => video.category === category);
}
