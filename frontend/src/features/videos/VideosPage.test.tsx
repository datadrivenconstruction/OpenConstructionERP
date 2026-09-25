// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Videos page. It promises that the player is created only when the
// reader presses play, so most checks count iframes: none on
// arrival, none for a shared link until play, none ever for a video that is
// not out yet, and the one that does appear points at the no-cookie host at
// the second the reader asked for.

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
import { VIDEOS, startHereVideo } from './academy';
import { useVideosStore } from './useVideosStore';
import { VideoPlayerDialog } from './VideoPlayerDialog';
import type { AcademyVideo } from './academyTypes';
import type { VideoLabels } from './videoLabels';
import { useVideoHintsStore } from './videoRoutes';

let lastSearch = '';
function LocationProbe() {
  lastSearch = useLocation().search;
  return null;
}

function renderAt(entry = '/videos') {
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
const setup = startHereVideo()!;
// Every catalogue video may be out, so the not-yet-published case is the setup
// lesson with its id taken away: the one field a publication adds.
const soon: AcademyVideo = {
  ...setup,
  id: 'unreleased',
  youtubeId: undefined,
  status: 'coming_soon',
  cover: '/assets/videos/academy/unreleased.webp',
};

beforeEach(() => {
  localStorage.clear();
  useVideosStore.setState({ role: null, market: 'auto', started: {}, watched: {} });
  useVideoHintsStore.setState({ off: false, hidden: [] });
});
afterEach(() => cleanup());

describe('the Videos page', () => {
  it('creates no player until play, then only the no-cookie one', () => {
    renderAt();
    expect(iframes()).toHaveLength(0);
    fireEvent.click(screen.getByTestId('videos-start-here'));
    const [frame] = iframes();
    expect(frame?.getAttribute('src')).toMatch(
      new RegExp(`^https://www\\.youtube-nocookie\\.com/embed/${setup.youtubeId}\\?`),
    );
    expect(frame?.getAttribute('referrerpolicy')).toBe('strict-origin-when-cross-origin');
    expect(lastSearch).toContain(`v=${setup.id}`);
  });

  it('opens a shared link on the poster, and plays from its second only on press', () => {
    renderAt(`/videos?v=${setup.id}&t=61`);
    const dialog = screen.getByTestId('video-player');
    expect(iframes()).toHaveLength(0);
    fireEvent.click(within(dialog).getAllByRole('button', { name: /^Play:/ })[0]!);
    expect(iframes()[0]?.getAttribute('src')).toContain('start=61');
  });

  it('seeks to a chapter by reloading the player at that second', () => {
    renderAt();
    fireEvent.click(screen.getByTestId('videos-start-here'));
    const chapter = setup.chapters[2]!;
    const dialog = screen.getByTestId('video-player');
    fireEvent.click(within(dialog).getByRole('button', { name: new RegExp(chapter.title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }));
    expect(iframes()[0]?.getAttribute('src')).toContain(`start=${chapter.t}`);
    expect(lastSearch).toContain(`t=${chapter.t}`);
  });

  it('shows a video that is not out yet as an outline, never a player', () => {
    const labels = { series: () => '', role: String, stage: String, stageShort: String, result: String, country: String, language: String, example: () => null };
    render(
      <MemoryRouter>
        <VideoPlayerDialog
          video={soon}
          start={0}
          autoplay
          labels={labels as unknown as VideoLabels}
          onClose={() => {}}
          onOpenVideo={() => {}}
        />
      </MemoryRouter>,
    );
    const dialog = screen.getByTestId('video-player');
    expect(within(dialog).getAllByText('Coming soon').length).toBeGreaterThan(0);
    expect(within(dialog).getByText(soon.chapters[0]!.title)).toBeTruthy();
    expect(iframes()).toHaveLength(0);
    expect(within(dialog).queryByRole('button', { name: soon.chapters[0]!.title })).toBeNull();
  });

  it('closes on Escape and drops the video from the URL', () => {
    renderAt(`/videos?v=${setup.id}`);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByTestId('video-player')).toBeNull();
    expect(lastSearch).not.toContain('v=');
  });

  it('finds a chapter by search and opens the video at it', () => {
    const video = VIDEOS.find((v) => v.status === 'published' && v.chapters.length > 3)!;
    const chapter = video.chapters[3]!;
    renderAt();
    fireEvent.change(screen.getByTestId('videos-search'), { target: { value: chapter.title } });
    const library = screen.getByTestId('videos-library');
    const card = within(library)
      .getAllByTestId('video-card')
      .find((c) => c.getAttribute('data-video-id') === video.id)!;
    fireEvent.click(within(card).getByRole('button', { name: new RegExp(chapter.title.slice(0, 20).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }));
    expect(iframes()[0]?.getAttribute('src')).toContain(`start=${chapter.t}`);
  });

  it('reads library filters from the URL and says when nothing matches', () => {
    renderAt('/videos?market=DE');
    const library = screen.getByTestId('videos-library');
    const cards = within(library).getAllByTestId('video-card');
    const de = VIDEOS.filter((v) => v.market === 'DE');
    expect(cards.map((c) => c.getAttribute('data-video-id'))).toEqual(de.map((v) => v.id));
    fireEvent.change(screen.getByTestId('videos-search'), { target: { value: 'zzzz-no-such-thing' } });
    expect(screen.getByTestId('videos-empty')).toBeTruthy();
    fireEvent.click(within(screen.getByTestId('videos-empty')).getByText('Clear filters'));
    expect(within(screen.getByTestId('videos-library')).getAllByTestId('video-card')).toHaveLength(VIDEOS.length);
  });

  it('asks for a role when it knows none, and remembers the pick', () => {
    renderAt();
    const picker = screen.getByTestId('video-role-picker');
    expect(within(picker).getAllByRole('button')).toHaveLength(15);
    fireEvent.click(within(picker).getByRole('button', { name: /Estimator/ }));
    expect(localStorage.getItem('oe_videos_role')).toBe('estimator');
    expect(screen.queryByTestId('video-role-picker')).toBeNull();
    expect(screen.getByTestId('videos-role-button').textContent).toContain('Estimator');
  });

  it('keeps the market choice and narrows the recommendations to it', () => {
    useVideosStore.setState({ role: 'estimator' });
    renderAt();
    fireEvent.change(screen.getByTestId('videos-market-select'), { target: { value: 'CA' } });
    expect(localStorage.getItem('oe_videos_market')).toBe('CA');
    const rec = screen.getByTestId('videos-recommended');
    const ids = within(rec).getAllByTestId('video-card').map((c) => c.getAttribute('data-video-id'));
    expect(ids.length).toBeGreaterThan(0);
    for (const id of ids) {
      const v = VIDEOS.find((x) => x.id === id)!;
      expect(!v.market || v.market === 'CA', id!).toBe(true);
    }
  });

  it('counts a series as watched from the reader’s own marks', () => {
    const first = VIDEOS.filter((v) => v.series === 'landshut-de').sort((a, b) => a.seriesOrder - b.seriesOrder)[0]!;
    renderAt(`/videos?v=${first.id}`);
    const dialog = screen.getByTestId('video-player');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Watched' }));
    expect(JSON.parse(localStorage.getItem('oe_videos_progress')!).watched).toEqual({ [first.id]: true });
    fireEvent.keyDown(document, { key: 'Escape' });
    const shelf = screen
      .getAllByTestId('videos-series')
      .find((s) => s.getAttribute('data-series-id') === 'landshut-de')!;
    expect(shelf.textContent).toContain('1 of 12 watched');
    expect(within(shelf).getByRole('button', { name: /Continue/ })).toBeTruthy();
  });

  it('still works when storage throws', () => {
    const get = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    try {
      renderAt();
      fireEvent.click(within(screen.getByTestId('video-role-picker')).getByRole('button', { name: /Estimator/ }));
      expect(screen.getByTestId('videos-role-button').textContent).toContain('Estimator');
    } finally {
      get.mockRestore();
    }
  });

  it('narrows the library to a screen from a module link, with a way out', () => {
    renderAt('/videos?route=%2Fboq');
    const library = screen.getByTestId('videos-library');
    const n = VIDEOS.filter((v) => v.routes.includes('/boq')).length;
    expect(within(library).getAllByTestId('video-card')).toHaveLength(n);
    fireEvent.click(within(screen.getByTestId('videos-route-chip')).getByRole('button'));
    expect(within(screen.getByTestId('videos-library')).getAllByTestId('video-card')).toHaveLength(VIDEOS.length);
  });

  it('lays out a learning path across all eight stages once the role is known', () => {
    expect(() => renderAt()).not.toThrow();
    expect(screen.queryByTestId('videos-path')).toBeNull();
    cleanup();
    useVideosStore.setState({ role: 'estimator' });
    renderAt();
    expect(screen.getAllByTestId('videos-path-stage')).toHaveLength(8);
  });

  it('offers to bring the module tips back once they were hidden', () => {
    renderAt();
    expect(screen.queryByTestId('videos-hints-restore')).toBeNull();
    cleanup();
    useVideoHintsStore.setState({ off: true, hidden: [] });
    renderAt();
    fireEvent.click(within(screen.getByTestId('videos-hints-restore')).getByRole('button'));
    expect(useVideoHintsStore.getState().off).toBe(false);
    expect(screen.queryByTestId('videos-hints-restore')).toBeNull();
  });
});
