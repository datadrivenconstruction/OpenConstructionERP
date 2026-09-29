// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A deleted project must leave every cached list at once, not after a reload.
//
// `invalidateProjectLists.test.ts` proves the helper marks the right keys. This
// file proves the places that delete, restore or archive a project actually
// reach it: the project card is rendered and driven through its own buttons,
// and the demo endpoints on the modules page and the purge in Settings are
// checked where they are written. Analytics ("Project Comparison", "Budget
// Breakdown") reads ['analytics', 'overview'] and the dashboard reads
// ['portfolio-analytics'], so those two are the keys asserted.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(async () => []),
  apiPatch: vi.fn(async () => ({})),
  apiPost: vi.fn(async () => ({})),
  apiDelete: vi.fn(async () => undefined),
}));

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return {
    ...actual,
    projectsApi: {
      ...actual.projectsApi,
      restore: vi.fn(async () => ({})),
    },
  };
});

// The card's map and weather widgets reach for tiles and a network; neither
// is under test here.
vi.mock('@/shared/ui', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/ui')>();
  return { ...actual, ProjectMap: () => null, ProjectWeather: () => null };
});

import { ProjectCard } from '../ProjectsPage';
import type { Project } from '../api';

const LIST_KEYS = [['analytics', 'overview'], ['portfolio-analytics']] as const;

function project(status: string): Project {
  return {
    id: 'p-1',
    name: 'Tower',
    status,
    description: '',
    classification_standard: 'din276',
    currency: 'EUR',
    region: '',
    metadata: {},
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
  } as unknown as Project;
}

function renderCard(p: Project): QueryClient {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  for (const key of LIST_KEYS) client.setQueryData([...key], {});
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/projects']}>
        <Routes>
          <Route path="/projects" element={<ProjectCard project={p} />} />
          <Route path="/projects/:id" element={<div>opened project page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

async function expectListsStale(client: QueryClient) {
  await waitFor(() => {
    for (const key of LIST_KEYS) {
      expect(client.getQueryState([...key])?.isInvalidated, JSON.stringify(key)).toBe(true);
    }
  });
}

function openMenu() {
  fireEvent.click(screen.getByRole('button', { name: 'Project actions for Tower' }));
}

describe('project card: every path that removes or returns a project', () => {
  it('delete refreshes analytics and the dashboard', async () => {
    const client = renderCard(project('active'));
    openMenu();
    fireEvent.click(screen.getByRole('button', { name: /common\.delete/ }));
    // The confirmation overlay carries its own Delete button.
    fireEvent.click(screen.getByRole('button', { name: /common\.delete/ }));
    await expectListsStale(client);
  });

  it('archive refreshes analytics and the dashboard', async () => {
    const client = renderCard(project('active'));
    openMenu();
    fireEvent.click(screen.getByRole('button', { name: /common\.archive/ }));
    await expectListsStale(client);
  });

  it('restore from a deleted card refreshes analytics and the dashboard', async () => {
    const client = renderCard(project('archived'));
    fireEvent.click(screen.getByTestId('project-card-restore'));
    await expectListsStale(client);
  });

  it('a deleted card does not open the project page, which would answer 404', () => {
    renderCard(project('archived'));
    fireEvent.click(screen.getByTestId('project-card'));
    expect(screen.queryByText('opened project page')).toBeNull();
  });

  it('a live card still opens its project', () => {
    renderCard(project('active'));
    fireEvent.click(screen.getByTestId('project-card'));
    expect(screen.getByText('opened project page')).toBeInTheDocument();
  });
});

// The modules page and Settings are whole admin screens; their demo buttons
// sit behind tabs, dialogs and several queries. The contract checked here is
// the one that regressed: each request that removes or re-creates demo
// projects is followed, in its own success path, by the shared refresh
// rather than a bare ['projects'] invalidation.
const here = dirname(fileURLToPath(import.meta.url));

function successPathAfter(src: string, marker: string): string {
  const at = src.indexOf(marker);
  expect(at, marker).toBeGreaterThan(-1);
  // The success path of that request ends where its failure handling starts:
  // a `catch` in the modules page handlers, `onError` in the Settings mutation.
  const end = src.slice(at).search(/\} catch|onError:/);
  expect(end, `no failure handler after ${marker}`).toBeGreaterThan(0);
  return src.slice(at, at + end);
}

describe('demo endpoints refresh every project list', () => {
  const modules = readFileSync(join(here, '../../modules/ModulesPage.tsx'), 'utf8');
  const settings = readFileSync(join(here, '../../settings/SettingsPage.tsx'), 'utf8');

  it.each([
    ['install', '`/demo/install/${demoId}`'],
    ['uninstall', '`/demo/uninstall/${demoId}`'],
    ['reinstall', '`/demo/install/${demoId}?force=true`'],
    ['clear all', "'/demo/clear-all'"],
  ])('modules page: demo %s', (_label, marker) => {
    const path = successPathAfter(modules, marker);
    expect(path).toContain('invalidateProjectLists(queryClient)');
    expect(path).not.toContain("queryKey: ['projects'] }");
  });

  it('settings: remove demo data', () => {
    const path = successPathAfter(settings, "'/v1/projects/demo-data/purge/'");
    expect(path).toContain('invalidateProjectLists(queryClient)');
  });
});
