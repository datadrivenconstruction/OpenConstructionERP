// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Videos page and the list behind it. The page promises that nothing is
// requested from the video host before the reader presses play, so the first
// thing checked is that no iframe exists until then, and that the one created
// afterwards points at the no-cookie host the backend CSP allows.

import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import type { ReactNode } from 'react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: unknown }) =>
      typeof opts?.defaultValue === 'string' ? opts.defaultValue : key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

import { VideosPage } from './VideosPage';
import { TUTORIAL_VIDEOS, VIDEO_CATEGORIES, embedUrl, videosInCategory } from './videoCatalog';

function renderAt(entry = '/videos') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <VideosPage />
    </MemoryRouter>,
  );
}

afterEach(() => cleanup());

describe('the video list', () => {
  it('names each video once, by a well-formed id, in a known topic', () => {
    const ids = TUTORIAL_VIDEOS.map((v) => v.id);
    const hosted = TUTORIAL_VIDEOS.map((v) => v.youtubeId);
    expect(new Set(ids).size).toBe(ids.length);
    expect(new Set(hosted).size).toBe(hosted.length);
    const topics = new Set(VIDEO_CATEGORIES.map((c) => c.id));
    for (const video of TUTORIAL_VIDEOS) {
      expect(video.youtubeId).toMatch(/^[A-Za-z0-9_-]{11}$/);
      expect(topics.has(video.category)).toBe(true);
    }
  });

  it('ships a local poster for every video', () => {
    // Resolved from the working directory, as navCatalog.test.ts does:
    // `import.meta.url` is rewritten to a bare drive root on Windows.
    const publicDir = [resolve(process.cwd(), 'public'), resolve(process.cwd(), 'frontend/public')].find((dir) =>
      existsSync(dir),
    );
    expect(publicDir).toBeDefined();
    for (const video of TUTORIAL_VIDEOS) {
      expect(video.thumbnail.startsWith('/assets/videos/')).toBe(true);
      expect(existsSync(resolve(publicDir!, `.${video.thumbnail}`))).toBe(true);
    }
  });

  it('plays from the no-cookie host only', () => {
    expect(new URL(embedUrl('X06cIaroAeI')).host).toBe('www.youtube-nocookie.com');
  });
});

describe('VideosPage', () => {
  it('draws a poster per video and loads no player until play is pressed', () => {
    renderAt();
    for (const video of TUTORIAL_VIDEOS) {
      expect(screen.getByTestId(`video-card-${video.id}`)).toBeTruthy();
    }
    expect(document.querySelector('iframe')).toBeNull();
  });

  it('starts one player on play, and a second play replaces it', () => {
    renderAt();
    const [first, second] = TUTORIAL_VIDEOS;

    fireEvent.click(within(screen.getByTestId(`video-card-${first!.id}`)).getAllByRole('button')[0]!);
    let frames = document.querySelectorAll('iframe');
    expect(frames).toHaveLength(1);
    expect(frames[0]!.getAttribute('src')).toBe(embedUrl(first!.youtubeId));
    // The app's own Referrer-Policy would strip the referrer the player needs.
    expect(frames[0]!.getAttribute('referrerpolicy')).toBe('strict-origin-when-cross-origin');

    fireEvent.click(within(screen.getByTestId(`video-card-${second!.id}`)).getAllByRole('button')[0]!);
    frames = document.querySelectorAll('iframe');
    expect(frames).toHaveLength(1);
    expect(frames[0]!.getAttribute('src')).toBe(embedUrl(second!.youtubeId));
  });

  it('shows topics without a video yet as coming soon, not as empty sections', () => {
    renderAt();
    for (const category of VIDEO_CATEGORIES) {
      const upcoming = screen.queryByTestId(`videos-upcoming-${category.id}`);
      if (videosInCategory(category.id).length === 0) expect(upcoming).toBeTruthy();
      else expect(upcoming).toBeNull();
    }
  });

  it('narrows to one topic from the URL', () => {
    renderAt('/videos?topic=talks');
    const talks = videosInCategory('talks');
    for (const video of TUTORIAL_VIDEOS) {
      const card = screen.queryByTestId(`video-card-${video.id}`);
      if (talks.includes(video)) expect(card).toBeTruthy();
      else expect(card).toBeNull();
    }
  });
});
