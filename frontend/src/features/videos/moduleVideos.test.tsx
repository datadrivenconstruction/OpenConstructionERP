// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The links from the rest of the app into the videos: which screen a path
// belongs to, "Videos for this step" on a module screen (and hiding it), and
// "Videos for this case" on a case page.

import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { ReactNode } from 'react';
import { describe, it, expect, vi, afterEach, beforeAll, beforeEach } from 'vitest';
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

import { ModuleVideosSlot } from './ModuleVideosSlot';
import CaseVideos from './CaseVideos';
import { useVideoHintsStore, videoRouteFor } from './videoRoutes';
import { VIDEO_COUNT_BY_CASE, VIDEO_COUNT_BY_ROUTE } from './academyIndex.generated';
import { VIDEOS, videosForCase, videosForRoute } from './academy';
import { useVideosStore } from './useVideosStore';

function renderAt(path: string, node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

// The panel is a lazy chunk; load it once up front so the first test does not
// spend its wait on a cold transform.
beforeAll(async () => {
  await import('./ModuleVideosPanel');
}, 60_000);

beforeEach(() => {
  localStorage.clear();
  useVideoHintsStore.setState({ off: false, hidden: [] });
  useVideosStore.setState({ role: null, market: 'auto', started: {}, watched: {} });
});
afterEach(() => cleanup());

describe('which screen a path belongs to', () => {
  it('matches the module, its sub-pages and its project-scoped form', () => {
    expect(videoRouteFor('/boq')).toBe('/boq');
    expect(videoRouteFor('/boq/0b6f/')).toBe('/boq');
    expect(videoRouteFor('/projects/7c1d/boq')).toBe('/boq');
    expect(videoRouteFor('/files/transmittals/42')).toBe('/files/transmittals');
    expect(videoRouteFor('/projects/new')).toBe('/projects/new');
    expect(videoRouteFor('/boqx')).toBeNull();
    expect(videoRouteFor('/')).toBeNull();
    expect(videoRouteFor('/videos')).toBeNull();
  });

  it('only names screens the app has, in App.tsx or a plugin module manifest', () => {
    const app = readFileSync(resolve(__dirname, '../../app/App.tsx'), 'utf-8');
    const paths = new Set([...app.matchAll(/path="([^"]+)"/g)].map((m) => m[1]!));
    const modulesDir = resolve(__dirname, '../../modules');
    for (const dir of readdirSync(modulesDir)) {
      const manifest = resolve(modulesDir, dir, 'manifest.ts');
      if (!existsSync(manifest)) continue;
      for (const m of readFileSync(manifest, 'utf-8').matchAll(/path:\s*'([^']+)'/g)) paths.add(m[1]!);
    }
    const missing = Object.keys(VIDEO_COUNT_BY_ROUTE).filter(
      (r) => !paths.has(r) && !paths.has(`/projects/:projectId${r}`),
    );
    expect(missing).toEqual([]);
  });

  it('keeps the light index in step with the catalogue', () => {
    for (const [route, n] of Object.entries(VIDEO_COUNT_BY_ROUTE)) expect(videosForRoute(route), route).toHaveLength(n);
    for (const [id, n] of Object.entries(VIDEO_COUNT_BY_CASE)) expect(videosForCase(id), id).toHaveLength(n);
    const routes = new Set(VIDEOS.flatMap((v) => v.routes));
    expect(new Set(Object.keys(VIDEO_COUNT_BY_ROUTE))).toEqual(routes);
  });
});

describe('Videos for this step', () => {
  it('stays folded until asked, then lists at most three and links to the rest', async () => {
    renderAt('/boq', <ModuleVideosSlot />);
    const toggle = await screen.findByTestId('module-videos-toggle');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(toggle);
    const region = screen.getByRole('region');
    expect(within(region).getAllByRole('listitem').length).toBeLessThanOrEqual(3);
    const all = within(region).getByRole('link', { name: /on the Videos page/ });
    expect(all.getAttribute('href')).toBe(`/videos?route=${encodeURIComponent('/boq')}`);
  });

  it('plays a video in place, without leaving the screen', async () => {
    renderAt('/boq', <ModuleVideosSlot />);
    fireEvent.click(await screen.findByTestId('module-videos-toggle'));
    fireEvent.click(within(screen.getByRole('region')).getAllByRole('listitem')[0]!.querySelector('button')!);
    expect(screen.getByTestId('video-player')).toBeTruthy();
  });

  it('renders nothing on a screen without videos', () => {
    const { container } = renderAt('/dashboard-nowhere', <ModuleVideosSlot />);
    expect(container.innerHTML).toBe('');
  });

  it('hides on this screen only, and remembers it', async () => {
    renderAt('/boq', <ModuleVideosSlot />);
    fireEvent.click(await screen.findByTestId('module-videos-toggle'));
    fireEvent.click(screen.getByRole('button', { name: /Hide on this screen/ }));
    expect(screen.queryByTestId('module-videos')).toBeNull();
    expect(JSON.parse(localStorage.getItem('oe_videos_hints')!)).toEqual({ off: false, hidden: ['/boq'] });
    cleanup();
    renderAt('/contracts', <ModuleVideosSlot />);
    expect(await screen.findByTestId('module-videos-toggle')).toBeTruthy();
  });

  it('hides everywhere, and the Videos page can bring it back', async () => {
    renderAt('/boq', <ModuleVideosSlot />);
    fireEvent.click(await screen.findByTestId('module-videos-toggle'));
    fireEvent.click(screen.getByRole('button', { name: /Hide on every screen/ }));
    expect(useVideoHintsStore.getState().off).toBe(true);
    cleanup();
    const { container } = renderAt('/contracts', <ModuleVideosSlot />);
    expect(container.innerHTML).toBe('');
    useVideoHintsStore.getState().showAgain();
    expect(localStorage.getItem('oe_videos_hints')).toBeNull();
  });
});

describe('Videos for this case', () => {
  it('shows the videos linked to the case, playable ones first', () => {
    renderAt('/cases/set-up-a-new-project', <CaseVideos caseId="set-up-a-new-project" />);
    const ids = within(screen.getByTestId('case-videos'))
      .getAllByTestId('video-card')
      .map((c) => c.getAttribute('data-video-id'));
    expect(ids).toContain('Setup_EN');
    const status = ids.map((id) => VIDEOS.find((v) => v.id === id)!.status);
    expect(status.indexOf('coming_soon') === -1 || status.lastIndexOf('published') < status.indexOf('coming_soon')).toBe(true);
  });

  it('renders nothing for a case without videos', () => {
    const { container } = renderAt('/cases/x', <CaseVideos caseId="no-such-case" />);
    expect(container.innerHTML).toBe('');
  });
});
