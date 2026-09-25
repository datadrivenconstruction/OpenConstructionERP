// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Filters, search to the chapter, recommendations and links, over a small
// fixture catalogue so each rule is read on its own, plus a few checks on the
// real catalogue that pin memberships the page relies on.

import { describe, expect, it } from 'vitest';
import type { AcademyVideo } from './academyTypes';
import {
  NO_FILTERS,
  VIDEOS,
  activeFilterCount,
  embedUrl,
  fold,
  formatClock,
  pathForRole,
  playlist,
  recommend,
  searchVideos,
  startHereVideo,
  videosForCase,
  videosForRoute,
  watchUrl,
} from './academy';

function video(partial: Partial<AcademyVideo> & { id: string }): AcademyVideo {
  return {
    status: partial.youtubeId ? 'published' : 'coming_soon',
    channel: 'academy',
    language: 'en',
    series: 's',
    seriesOrder: 1,
    stage: 'estimate',
    roles: [],
    cases: [],
    routes: [],
    title: partial.id,
    description: '',
    cover: '/assets/videos/academy/x.webp',
    chapters: [],
    ...partial,
  };
}

const FIXTURE: AcademyVideo[] = [
  video({ id: 'ca-est', youtubeId: 'aaaaaaaaaaa', market: 'CA', roles: ['estimator'], title: 'Price a Toronto job' }),
  video({ id: 'de-lv', youtubeId: 'bbbbbbbbbbb', market: 'DE', language: 'de', roles: ['estimator'], title: 'Leistungsverzeichnis' }),
  video({
    id: 'any-site',
    stage: 'build',
    roles: ['site-manager'],
    title: 'Site hours',
    chapters: [
      { t: 0, title: 'Why' },
      { t: 95, title: 'Approve the timesheet' },
    ],
  }),
  video({ id: 'all', youtubeId: 'ccccccccccc', stage: 'define', title: 'Install', series: 'g', seriesOrder: 1 }),
  video({ id: 'qc', market: 'CA', language: 'fr', roles: ['estimator'], title: 'Estimation à Montréal', series: 'q', seriesOrder: 2 }),
  video({ id: 'qc1', market: 'CA', language: 'fr', title: 'Démarrer', series: 'q', seriesOrder: 1 }),
];

const ids = (list: { id: string }[]) => list.map((v) => v.id);
const hitIds = (hits: { video: AcademyVideo }[]) => hits.map((h) => h.video.id);

describe('filters', () => {
  it('treats a video that names no role as for every role', () => {
    const hits = searchVideos({ ...NO_FILTERS, role: 'site-manager' }, FIXTURE);
    expect(hitIds(hits)).toEqual(['any-site', 'all', 'qc1']);
  });

  it('narrows to a market, or to videos that apply anywhere', () => {
    expect(hitIds(searchVideos({ ...NO_FILTERS, market: 'CA' }, FIXTURE))).toEqual(['ca-est', 'qc', 'qc1']);
    expect(hitIds(searchVideos({ ...NO_FILTERS, market: 'universal' }, FIXTURE))).toEqual(['any-site', 'all']);
  });

  it('combines stage, language and series', () => {
    expect(hitIds(searchVideos({ ...NO_FILTERS, language: 'fr', series: 'q' }, FIXTURE))).toEqual(['qc', 'qc1']);
    expect(hitIds(searchVideos({ ...NO_FILTERS, stage: 'build' }, FIXTURE))).toEqual(['any-site']);
  });

  it('counts what is set', () => {
    expect(activeFilterCount(NO_FILTERS)).toBe(0);
    expect(activeFilterCount({ ...NO_FILTERS, role: 'estimator', query: ' x ' })).toBe(2);
  });
});

describe('search', () => {
  it('finds a chapter and reports it, so the player can open at that second', () => {
    const [hit] = searchVideos({ ...NO_FILTERS, query: 'timesheet' }, FIXTURE);
    expect(hit?.video.id).toBe('any-site');
    expect(hit?.chapters).toEqual([{ t: 95, title: 'Approve the timesheet' }]);
  });

  it('ignores accents and case', () => {
    expect(fold('Québec MONTRÉAL')).toBe('quebec montreal');
    expect(hitIds(searchVideos({ ...NO_FILTERS, query: 'montreal' }, FIXTURE))).toEqual(['qc']);
  });

  it('needs every word somewhere in the video', () => {
    expect(hitIds(searchVideos({ ...NO_FILTERS, query: 'site approve' }, FIXTURE))).toEqual(['any-site']);
    expect(hitIds(searchVideos({ ...NO_FILTERS, query: 'site toronto' }, FIXTURE))).toEqual([]);
  });

  it('finds real chapters in the German series', () => {
    const hits = searchVideos({ ...NO_FILTERS, query: 'Lernprojekt' });
    expect(hits.some((h) => h.chapters.length > 0)).toBe(true);
  });
});

describe('recommendations', () => {
  it('leaves out other markets and other roles once they are known, and ranks the exact fit first', () => {
    const list = recommend({ role: 'estimator', market: 'CA', language: 'en' }, FIXTURE);
    expect(ids(list)).not.toContain('de-lv');
    expect(ids(list)).not.toContain('any-site');
    expect(list[0]?.id).toBe('ca-est');
  });

  it('puts a close fit that plays now first, and a close fit coming soon above a loose one', () => {
    const list = recommend({ role: 'estimator', market: 'CA', language: 'fr' }, FIXTURE);
    expect(ids(list)).toEqual(['ca-est', 'qc', 'qc1', 'all']);
  });

  it('among videos that play, prefers the reader language', () => {
    const both = [
      video({ id: 'en', youtubeId: 'ddddddddddd', market: 'CA' }),
      video({ id: 'fr', youtubeId: 'eeeeeeeeeee', market: 'CA', language: 'fr' }),
    ];
    expect(ids(recommend({ role: null, market: 'CA', language: 'fr' }, both))).toEqual(['fr', 'en']);
    expect(ids(recommend({ role: null, market: 'CA', language: 'en' }, both))).toEqual(['en', 'fr']);
  });

  it('with nothing known, offers published videos first', () => {
    const list = recommend({ role: null, market: null, language: null }, FIXTURE);
    expect(list.slice(0, 3).every((v) => v.status === 'published')).toBe(true);
  });

  it('recommends the Canadian series to a Canadian estimator in the real catalogue', () => {
    const list = recommend({ role: 'estimator', market: 'CA', language: 'en' });
    expect(list.length).toBeGreaterThan(0);
    expect(list.every((v) => !v.market || v.market === 'CA')).toBe(true);
    expect(list[0]?.market).toBe('CA');
  });
});

describe('links and URLs', () => {
  it('opens the player at a chapter', () => {
    expect(embedUrl('WjDK-uk9b1w', 95.6)).toBe(
      'https://www.youtube-nocookie.com/embed/WjDK-uk9b1w?autoplay=1&rel=0&modestbranding=1&playsinline=1&start=95',
    );
    expect(embedUrl('WjDK-uk9b1w')).not.toContain('start=');
    expect(watchUrl('WjDK-uk9b1w', 61)).toBe('https://www.youtube.com/watch?v=WjDK-uk9b1w&t=61s');
  });

  it('formats a running time', () => {
    expect(formatClock(281)).toBe('4:41');
    expect(formatClock(3725)).toBe('1:02:05');
  });

  it('plays a series in order', () => {
    expect(ids(playlist('q', FIXTURE))).toEqual(['qc1', 'qc']);
    const landshut = playlist('landshut-de');
    expect(landshut).toHaveLength(12);
    expect(landshut.map((v) => v.seriesOrder)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
  });

  it('finds the videos for a module screen and for a case', () => {
    expect(ids(videosForRoute('/boq?tab=x'))).toEqual(ids(VIDEOS.filter((v) => v.routes.includes('/boq'))));
    expect(videosForRoute('/boq').length).toBeGreaterThan(0);
    expect(ids(videosForCase('set-up-a-new-project'))).toContain('Setup_EN');
  });

  it('starts somebody new at the setup lesson', () => {
    expect(startHereVideo()?.id).toBe('Setup_EN');
  });
});

describe('learning path', () => {
  const STAGES = ['define', 'design', 'estimate', 'procure', 'plan', 'build', 'handover', 'operate'] as const;

  it('lays a role out across every stage, named-for-the-role and playable first', () => {
    const path = pathForRole('estimator', 'CA', STAGES, FIXTURE);
    expect([...path.keys()]).toEqual([...STAGES]);
    expect(ids(path.get('estimate')!)).toEqual(['ca-est', 'qc', 'qc1']);
    expect(ids(path.get('define')!)).toEqual(['all']);
    expect(path.get('build')).toEqual([]);
  });

  it('leaves out another market once the market is known', () => {
    expect(ids(pathForRole('estimator', null, STAGES, FIXTURE).get('estimate')!)).toContain('de-lv');
    expect(ids(pathForRole('estimator', 'CA', STAGES, FIXTURE).get('estimate')!)).not.toContain('de-lv');
  });
});

describe('the screen filter', () => {
  it('keeps the videos whose cases walk through a screen', () => {
    const hits = searchVideos({ ...NO_FILTERS, route: '/boq' });
    expect(hits.map((h) => h.video.id)).toEqual(ids(videosForRoute('/boq')));
    expect(activeFilterCount({ ...NO_FILTERS, route: '/boq' })).toBe(1);
  });
});
