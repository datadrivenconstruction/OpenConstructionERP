// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Videos and cases, linked both ways. A case page lists the videos to watch
// and starts each one at the chapter about that case where there is one; a
// video card in the library lists the cases it is used in, each one a link.
// Every link has to land: no case id the hub does not have, no video id the
// catalogue does not have, and no start second that is not a chapter.

import type { ReactNode } from 'react';
import { describe, it, expect, vi, afterEach, beforeAll } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const template = typeof opts?.defaultValue === 'string' ? opts.defaultValue : key;
      return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(opts?.[name] ?? ''));
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

import { PLAYBOOKS } from '@/features/cases/playbooks';
import { VIDEOS, caseRef, caseStart, formatClock, videosForCase } from './academy';
import { VIDEO_COUNT_BY_CASE } from './academyIndex.generated';
import { VideoCard } from './VideoCard';
import CaseVideos from './CaseVideos';
import type { VideoLabels } from './videoLabels';

const labels = {
  role: (r: string) => r,
  stage: (s: string) => s,
  stageShort: (s: string) => s,
  result: (r: string) => r,
  country: (c: string) => c,
  language: (l: string) => l,
  series: (s: string) => s,
  example: () => null,
} as unknown as VideoLabels;

const CASE_IDS = new Set(PLAYBOOKS.map((p) => p.id));

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeAll(async () => {
  await import('./VideoPlayerDialog');
});
afterEach(() => cleanup());

describe('every link lands', () => {
  it('names only cases the hub has, and the hub index agrees with the videos', () => {
    for (const v of VIDEOS) {
      for (const c of v.cases) {
        expect(CASE_IDS.has(c), `${v.id} -> ${c}`).toBe(true);
        expect(caseRef(c), `${v.id} -> ${c} has no title`).toBeDefined();
      }
    }
    for (const [caseId, n] of Object.entries(VIDEO_COUNT_BY_CASE)) {
      expect(CASE_IDS.has(caseId), caseId).toBe(true);
      expect(videosForCase(caseId)).toHaveLength(n);
    }
  });

  it('starts a case at a chapter the video has, and only for a case it is linked to', () => {
    let starts = 0;
    for (const v of VIDEOS) {
      for (const [caseId, t] of Object.entries(v.caseStarts ?? {})) {
        starts++;
        expect(v.cases, `${v.id} starts ${caseId} but is not linked to it`).toContain(caseId);
        expect(v.chapters.some((c) => c.t === t), `${v.id} -> ${caseId}: ${t}s`).toBe(true);
      }
    }
    expect(starts).toBeGreaterThan(0);
  });
});

describe('on a case page', () => {
  const video = VIDEOS.find((v) => Object.values(v.caseStarts ?? {}).some((t) => t > 0))!;
  const [caseId, start] = Object.entries(video.caseStarts!).find(([, t]) => t > 0)!;
  const chapter = video.chapters.find((c) => c.t === start)!;

  it('offers the chapter about the case and plays from it', () => {
    wrap(<CaseVideos caseId={caseId} />);
    const card = screen
      .getAllByTestId('video-card')
      .find((c) => c.getAttribute('data-video-id') === video.id)!;
    const jump = within(card).getByTestId('video-card-jump');
    expect(jump.textContent).toContain(`From ${formatClock(start)}: ${chapter.title}`);
    fireEvent.click(jump);
    expect(document.querySelector('iframe')?.getAttribute('src')).toContain(`start=${start}`);
  });

  it('starts there on a plain click too', () => {
    wrap(<CaseVideos caseId={caseId} />);
    const card = screen
      .getAllByTestId('video-card')
      .find((c) => c.getAttribute('data-video-id') === video.id)!;
    fireEvent.click(within(card).getAllByRole('button')[0]!);
    expect(caseStart(video, caseId)).toBe(start);
    expect(document.querySelector('iframe')?.getAttribute('src')).toContain(`start=${start}`);
  });

  it('does not list the cases again on the case page', () => {
    wrap(<CaseVideos caseId={caseId} />);
    expect(screen.queryByTestId('video-card-cases')).toBeNull();
  });
});

describe('on a video card in the library', () => {
  it('names the cases it is used in, each a link to that case', () => {
    const video = VIDEOS.find((v) => v.cases.length === 2)!;
    wrap(<VideoCard video={video} labels={labels} onOpen={() => {}} showCases />);
    const block = screen.getByTestId('video-card-cases');
    expect(block.textContent).toContain('Used in these cases');
    const links = within(block).getAllByRole('link');
    expect(links.map((a) => a.getAttribute('href'))).toEqual(video.cases.map((c) => `/cases/${c}`));
    expect(links.map((a) => a.textContent)).toEqual(video.cases.map((c) => caseRef(c)!.titleDefault));
  });

  it('shows two and counts the rest, which opens the full list in the player', () => {
    const video = VIDEOS.find((v) => v.cases.length > 2)!;
    const onOpen = vi.fn();
    wrap(<VideoCard video={video} labels={labels} onOpen={onOpen} showCases />);
    const block = screen.getByTestId('video-card-cases');
    expect(within(block).getAllByRole('link')).toHaveLength(2);
    fireEvent.click(within(block).getByRole('button', { name: `+${video.cases.length - 2} more` }));
    expect(onOpen).toHaveBeenCalledWith(video);
  });
});
