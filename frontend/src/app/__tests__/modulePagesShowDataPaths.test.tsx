// Every module page that renders the shared PageHeader shows one "Data paths"
// button, whether or not the page puts a "How it works" button in its actions.
// The button is route-derived, so the proof walks every route the sidebar maps
// to a backend module; a page no module owns and the data-paths page itself
// stay without it.

import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

vi.mock('@/features/cases/ModuleCasesButton', () => ({ ModuleCasesButton: () => null }));

import { PageHeader } from '@/shared/ui/PageHeader';
import { ModuleGuideButton } from '@/shared/ui/ModuleGuideButton';
import { ROUTE_BACKEND_MODULE } from '@/app/layout/Sidebar';

const GUIDE = { titleKey: 'x.title', titleDefault: 'Guide', sections: [] };

function mount(path: string, withGuide = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <PageHeader subtitle="page" actions={withGuide ? <ModuleGuideButton content={GUIDE} /> : undefined} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// Core modules (always installed) are absent from the sidebar map but own pages too.
const CORE_ROUTES = ['/boq', '/boq/some-boq-id', '/costs', '/assemblies'];
const MODULE_ROUTES = [
  ...CORE_ROUTES,
  ...Object.keys(ROUTE_BACKEND_MODULE).filter((r) => r !== '/' && !r.includes(':') && !r.includes('?')),
];

afterEach(cleanup);

describe('module pages show the Data paths button', () => {
  it('maps a real set of module routes', () => {
    expect(MODULE_ROUTES.length).toBeGreaterThan(40);
  });

  it('shows exactly one button on every module route', async () => {
    for (const route of MODULE_ROUTES) {
      mount(route);
      await waitFor(() => expect(screen.getAllByTestId('data-paths-button')).toHaveLength(1), { timeout: 5000 }).catch(
        () => {
          throw new Error(`no Data paths button on ${route}`);
        },
      );
      cleanup();
    }
  }, 300_000);

  // Plugin pages (the survey group) are owned through the module registry, not the sidebar map.
  it('shows the button on every survey page', async () => {
    const survey = [
      '/survey',
      '/survey/points',
      '/survey/parcels',
      '/survey/monitoring',
      '/survey/setting-out',
      '/survey/mine',
      '/survey/stockpiles',
      '/survey/volumes',
    ];
    for (const route of survey) {
      mount(route);
      await waitFor(() => expect(screen.getAllByTestId('data-paths-button')).toHaveLength(1), { timeout: 5000 }).catch(
        () => {
          throw new Error(`no Data paths button on ${route}`);
        },
      );
      cleanup();
    }
  }, 120_000);

  // Project-scoped pages (/projects/<id>/<page>) belong to the module of the plain route.
  it('shows the button on project-scoped module pages', async () => {
    for (const route of ['/projects/p1/finance', '/projects/p1/geo', '/projects/p1/cde', '/inbound', '/files', '/dashboards']) {
      mount(route);
      await waitFor(() => expect(screen.getAllByTestId('data-paths-button')).toHaveLength(1), { timeout: 5000 }).catch(
        () => {
          throw new Error(`no Data paths button on ${route}`);
        },
      );
      cleanup();
    }
    mount('/projects/p1/settings');
    await new Promise((r) => setTimeout(r, 300));
    expect(screen.queryAllByTestId('data-paths-button')).toHaveLength(0);
  }, 60_000);

  it('keeps one button when the page also has How it works', async () => {
    for (const route of ['/boq', '/tendering', '/finance']) {
      mount(route, true);
      await waitFor(() => expect(screen.getAllByTestId('data-paths-button')).toHaveLength(1), { timeout: 5000 });
      expect(screen.getByTestId('module-guide-button')).toBeTruthy();
      cleanup();
    }
  }, 60_000);

  it('stays off the data-paths page and off pages no module owns', async () => {
    mount('/data-paths/boq');
    mount('/no-such-module-page');
    // Give the lazy route resolver time to settle before asserting absence.
    await new Promise((r) => setTimeout(r, 300));
    expect(screen.queryAllByTestId('data-paths-button')).toHaveLength(0);
  });

  it('keeps the button wired into the shared header and the learning group', () => {
    const ui = resolve(__dirname, '../../shared/ui');
    expect(readFileSync(resolve(ui, 'PageHeader.tsx'), 'utf8')).toMatch(/<DataPathsButton\b/);
    expect(readFileSync(resolve(ui, 'ModuleGuideButton.tsx'), 'utf8')).toMatch(/<DataPathsButton\s*\/>/);
  });
});
