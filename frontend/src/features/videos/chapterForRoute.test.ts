import { describe, expect, it } from 'vitest';
import { chapterForRoute } from './academy';
import type { AcademyCaseRef, AcademyVideo } from './academyTypes';

const video = {
  id: 'v',
  cases: ['c1'],
  caseStarts: { c1: 230 },
  routes: ['/dwg-takeoff'],
  chapters: [
    { t: 0, title: 'Intro' },
    { t: 120, title: 'Create the project' },
    { t: 222, title: 'Import a DWG drawing' },
    { t: 400, title: 'Export the bill' },
  ],
} as unknown as AcademyVideo;

const cases = { c1: { routes: ['/dwg-takeoff'] } } as unknown as Record<string, AcademyCaseRef>;

describe('chapterForRoute', () => {
  it('prefers the editorial case start on this route', () => {
    expect(chapterForRoute(video, '/dwg-takeoff', [], cases)?.t).toBe(222);
  });

  it('falls back to a chapter title that names the module', () => {
    const v = { ...video, cases: [] } as AcademyVideo;
    expect(chapterForRoute(v, '/dwg-takeoff', ['DWG Takeoff'], {})?.t).toBe(222);
  });

  it('returns nothing when no chapter fits, and never the 0:00 chapter', () => {
    const v = { ...video, cases: [] } as AcademyVideo;
    expect(chapterForRoute(v, '/schedule', ['Schedule'], {})).toBeUndefined();
    expect(chapterForRoute(v, '/intro', ['Intro'], {})).toBeUndefined();
  });
});
