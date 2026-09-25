// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The shape of the generated video catalogue (academyCatalog.generated.ts).
// Written by hand: the generator emits data, this file says what it means.
//
// Stage and role ids are the ones the Cases hub uses (LifecycleStage,
// ProfessionalRole), so a video and a case can be matched without a mapping
// table. The links from a video to roles, stage and cases are editorial
// proposals, not a guarantee, and the page does not present them as one.

import type { LifecycleStage, ProfessionalRole } from '@/features/cases/types';

/** What a video leaves you holding at the end: the family of result it teaches. */
export type ResultFamily =
  | 'gaeb'
  | 'bill'
  | 'rate'
  | 'cost'
  | 'qty'
  | 'award'
  | 'invoice'
  | 'programme'
  | 'change'
  | 'site'
  | 'handover'
  | 'order';

export type VideoStatus = 'published' | 'coming_soon';

/** `academy` is the OpenConstruction Academy channel; `ddc` the older
 *  DataDrivenConstruction channel that carries the first walkthroughs. */
export type VideoChannel = 'academy' | 'ddc';

export interface VideoChapter {
  /** Start, in whole seconds. */
  t: number;
  /** Chapter title, in the video's own language. */
  title: string;
}

export interface AcademyVideo {
  id: string;
  /** Null until the video is published; adding it is the only edit a
   *  publication needs, and the status follows from it. */
  youtubeId?: string;
  status: VideoStatus;
  channel: VideoChannel;
  /** ISO 639-1 language the video is spoken in. */
  language: string;
  /** ISO 3166-1 alpha-2 market whose rules the video teaches; absent when the
   *  topic applies in any market. */
  market?: string;
  series: string;
  seriesOrder: number;
  /** The entry point for somebody new. */
  startHere?: boolean;
  stage: LifecycleStage;
  /** Empty means the video is for every role. */
  roles: ProfessionalRole[];
  /** Case ids that exist in the Cases hub. */
  cases: string[];
  /** Module routes those cases walk through, unscoped and query-less. */
  routes: string[];
  result?: ResultFamily;
  /** Title and description are data in the video's own language. */
  title: string;
  /** English working title, where the source has one (the German series). */
  titleEn?: string;
  description: string;
  /** What the video produces, in English, where the source states it. */
  produces?: string;
  /** Release the recording shows, when known. */
  recordedOn?: string;
  /** Running time in seconds, when known. */
  duration?: number;
  /** The channel thumbnail (i.ytimg.com) for a published video, or the
   *  public path of the local WebP for one that is not out yet. */
  cover: string;
  chapters: VideoChapter[];
}

export interface AcademySeries {
  id: string;
  /** Source title, in the series' own language. */
  title: string;
  /** i18n key for a title we wrote ourselves rather than took from a source. */
  titleKey?: string;
  language: string;
  market: string | null;
  channel: VideoChannel;
}

/** A case a video links to, carried with its title so the Videos page never
 *  has to load the playbook data to name it. */
export interface AcademyCaseRef {
  titleKey: string;
  titleDefault: string;
  region: string | null;
  stage: LifecycleStage;
  routes: string[];
}

export interface AcademyCatalog {
  channelId: string;
  channelName: string;
  series: AcademySeries[];
  videos: AcademyVideo[];
  cases: Record<string, AcademyCaseRef>;
}
