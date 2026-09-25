// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The library's other two views. Moments: chapters along each video, lit by a
// search, each one a way into the player at its second. Coverage map: roles or
// countries against the stages, counted the way the filters count, and each
// cell a way back to the list it stands for.

import type { ReactNode } from 'react';
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
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

import { VideosPage } from './VideosPage';
import { VIDEOS, searchVideos, NO_FILTERS } from './academy';
import { chapterOffset } from './MomentsView';
import { ANY_MARKET, roleRowsOf } from './MatrixView';
import { useVideosStore } from './useVideosStore';
import { useVideoHintsStore } from './videoRoutes';

let lastSearch = '';
function LocationProbe() {
  lastSearch = useLocation().search;
  return null;
}

function renderAt(entry: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <VideosPage />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const iframes = () => Array.from(document.querySelectorAll('iframe'));

beforeEach(() => {
  localStorage.clear();
  useVideosStore.setState({ role: 'estimator', market: 'auto', started: {}, watched: {} });
  useVideoHintsStore.setState({ off: false, hidden: [] });
});
afterEach(() => cleanup());

describe('moments', () => {
  it('places a chapter along the running time', () => {
    const v = VIDEOS.find((x) => x.duration && x.chapters.length > 2)!;
    expect(chapterOffset(v.chapters[0]!, v)).toBeCloseTo(v.chapters[0]!.t / v.duration!);
    expect(chapterOffset({ t: v.duration! * 2, title: '' }, v)).toBe(1);
  });

  it('switches the library to moments in the URL, one row per video', () => {
    renderAt('/videos');
    fireEvent.click(screen.getByTestId('videos-view-moments'));
    expect(lastSearch).toContain('view=moments');
    expect(screen.getAllByTestId('videos-moment-row')).toHaveLength(VIDEOS.length);
  });

  it('folds a long chapter list after four and unfolds it on request', () => {
    const video = VIDEOS.find((v) => v.chapters.length > 5)!;
    renderAt('/videos?view=moments');
    const row = screen
      .getAllByTestId('videos-moment-row')
      .find((r) => r.getAttribute('data-video-id') === video.id)!;
    expect(within(row).getAllByRole('listitem')).toHaveLength(4);
    fireEvent.click(within(row).getByText(`${video.chapters.length - 4} more moments`));
    expect(within(row).getAllByRole('listitem')).toHaveLength(video.chapters.length);
  });

  it('lists only the matching moments during a search, and plays from one', () => {
    const video = VIDEOS.find((v) => v.chapters.length > 5)!;
    const chapter = video.chapters[5]!;
    renderAt(`/videos?view=moments&q=${encodeURIComponent(chapter.title)}`);
    const row = screen
      .getAllByTestId('videos-moment-row')
      .find((r) => r.getAttribute('data-video-id') === video.id)!;
    const expected = searchVideos({ ...NO_FILTERS, query: chapter.title }).find((h) => h.video.id === video.id)!;
    expect(within(row).getAllByRole('listitem').length).toBe(expected.chapters.length > 5 ? 4 : expected.chapters.length);
    fireEvent.click(within(row).getAllByRole('button', { name: new RegExp(chapter.title.slice(0, 15).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) })[0]!);
    expect(iframes()[0]?.getAttribute('src')).toContain(`start=${chapter.t}`);
  });
});

describe('coverage map', () => {
  it('counts each role at each stage the way the role filter does', () => {
    renderAt('/videos?view=matrix');
    const cell = screen
      .getAllByTestId('videos-matrix-cell')
      .find((c) => c.getAttribute('data-row') === 'estimator' && c.getAttribute('data-stage') === 'estimate')!;
    const n = VIDEOS.filter((v) => v.stage === 'estimate' && roleRowsOf(v).includes('estimator')).length;
    expect(n).toBeGreaterThan(0);
    expect(cell.textContent).toBe(String(n));
    expect(n).toBe(searchVideos({ ...NO_FILTERS, role: 'estimator', stage: 'estimate' }).length);
  });

  it('turns a cell into the list it stands for', () => {
    renderAt('/videos?view=matrix');
    const cell = screen
      .getAllByTestId('videos-matrix-cell')
      .find((c) => c.getAttribute('data-row') === 'estimator' && c.getAttribute('data-stage') === 'estimate')!;
    fireEvent.click(cell);
    expect(lastSearch).toContain('role=estimator');
    expect(lastSearch).toContain('stage=estimate');
    expect(lastSearch).not.toContain('view=');
    const n = searchVideos({ ...NO_FILTERS, role: 'estimator', stage: 'estimate' }).length;
    expect(within(screen.getByTestId('videos-library')).getAllByTestId('video-card')).toHaveLength(n);
  });

  it('can count by country, with a row for videos that apply anywhere', () => {
    renderAt('/videos?view=matrix');
    fireEvent.click(screen.getByRole('button', { name: 'Country', pressed: false }));
    expect(lastSearch).toContain('rows=markets');
    const rows = new Set(screen.getAllByTestId('videos-matrix-cell').map((c) => c.getAttribute('data-row')));
    expect(rows.has(ANY_MARKET)).toBe(true);
    expect(rows.has('CA')).toBe(true);
    const total = screen
      .getAllByTestId('videos-matrix-cell')
      .reduce((sum, c) => sum + (Number(c.textContent) || 0), 0);
    expect(total).toBe(VIDEOS.length);
  });

  it('leaves an empty cell inert', () => {
    renderAt('/videos?view=matrix&rows=markets');
    const empty = screen.getAllByTestId('videos-matrix-cell').filter((c) => c.textContent === '·');
    expect(empty.length).toBeGreaterThan(0);
    expect(empty.every((c) => (c as HTMLButtonElement).disabled)).toBe(true);
  });
});
