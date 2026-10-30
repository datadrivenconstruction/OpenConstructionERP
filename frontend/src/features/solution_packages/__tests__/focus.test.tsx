// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { buildFirstSteps, findDemoProjectId, groupModules } from '../focus';
import type { FocusPreview } from '../api';

const setModuleEnabled = vi.fn().mockResolvedValue({});
const showAllModules = vi.fn().mockResolvedValue({});
vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  setModuleEnabled: (...a: unknown[]) => setModuleEnabled(...a),
  showAllModules: () => showAllModules(),
}));
const listProjects = vi.fn().mockResolvedValue([]);
vi.mock('@/features/projects/api', () => ({ projectsApi: { list: () => listProjects() } }));
vi.mock('@/app/layout/Sidebar', () => ({
  ROUTE_BACKEND_MODULE: { '/boq': 'sidebar-nav-boq', '/tendering': 'oe_tendering', '/daily-diary': 'oe_daily_diary' },
}));

import { PackFocusSummary } from '../PackFocusPage';

const ROUTES = { '/tendering': 'oe_tendering', '/daily-diary': 'oe_daily_diary' };

const preview: FocusPreview = {
  slug: 'germany-de', name: 'Germany Construction Pack', name_key: null, type: 'country', source: 'fallback',
  modules: ['boq', 'validation', 'tendering', 'reporting'], hidden: ['takeoff', 'safety'],
  demo_template_ids: ['residential-berlin'], rule_sets: ['din276', 'gaeb'], standard: 'din276',
  cwicr_regions: ['cwicr-de-berlin'], currency: 'EUR', menu: [],
};

describe('pack focus rules', () => {
  it('groups modules by wizard group and keeps unknown ones under platform', () => {
    const groups = groupModules(['boq', 'tendering', 'no_such_thing']);
    expect(groups.map((g) => g.id)).toContain('estimation');
    expect(groups.at(-1)?.id).toBe('platform');
    expect(groups.flatMap((g) => g.modules.map((m) => m.key)).sort()).toEqual(['boq', 'no_such_thing', 'tendering']);
  });

  it('derives demo, BOQ with the standard, validation, GAEB export and costs for a German pack', () => {
    const steps = buildFirstSteps(preview, ROUTES);
    expect(steps.map((s) => s.id)).toEqual(['demo', 'boq', 'validation', 'export_gaeb', 'costs']);
    expect(steps[1]).toMatchObject({ to: '/boq', param: 'din276' });
  });

  it('opens the installed demo project of the pack, newest first, and the list otherwise', () => {
    const projects = [
      { id: 'other', metadata: { demo_id: 'office-london' }, created_at: '2026-10-03' },
      { id: 'old', metadata: { demo_id: 'residential-berlin' }, created_at: '2026-10-01' },
      { id: 'new', metadata: { demo_id: 'residential-berlin' }, created_at: '2026-10-02' },
      { id: 'mine', metadata: {}, created_at: '2026-10-04' },
    ];
    expect(findDemoProjectId(projects, ['residential-berlin'])).toBe('new');
    expect(findDemoProjectId(projects, ['school-paris'])).toBeNull();
    expect(buildFirstSteps(preview, ROUTES, 'new')[0]).toMatchObject({ id: 'demo', to: '/projects/new' });
    expect(buildFirstSteps(preview, ROUTES, null)[0]).toMatchObject({ id: 'demo', to: '/projects' });
  });

  it('fills a pack without BOQ from its own module routes, at least three steps', () => {
    const steps = buildFirstSteps(
      { ...preview, modules: ['daily_diary', 'tendering'], demo_template_ids: [], rule_sets: [], standard: null, cwicr_regions: [] },
      ROUTES,
    );
    expect(steps.length).toBe(2);
    expect(steps.every((s) => s.id === 'open_module')).toBe(true);
    expect(steps.map((s) => s.to).sort()).toEqual(['/daily-diary', '/tendering']);
  });
});

function renderSummary(modules: Record<string, boolean>) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <PackFocusSummary preview={preview} modules={modules} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('PackFocusSummary', () => {
  const modules = { boq: true, validation: true, tendering: true, takeoff: false, safety: false };

  it('says how many modules are on and hidden, and links the first steps to real routes', () => {
    renderSummary(modules);
    expect(screen.getByTestId('pack-focus-headline').textContent).toMatch(/3.*Germany Construction Pack.*2|packs.focus_headline/);
    const links = within(screen.getByTestId('pack-focus-steps')).getAllByRole('link');
    expect(links.map((a) => a.getAttribute('href'))).toEqual(['/projects', '/boq', '/validation', '/boq', '/costs']);
  });

  it('links the demo step to the seeded demo project and names standards readably', async () => {
    listProjects.mockResolvedValueOnce([{ id: 'p-berlin', metadata: { demo_id: 'residential-berlin' }, created_at: '2026-10-01' }]);
    renderSummary(modules);
    await waitFor(() => {
      const first = within(screen.getByTestId('pack-focus-steps')).getAllByRole('link')[0];
      expect(first?.getAttribute('href')).toBe('/projects/p-berlin');
    });
    const text = screen.getByTestId('pack-focus-steps').textContent ?? '';
    expect(text).not.toMatch(/din276|DIN276/);
  });

  it('shows a hidden module with one click and shows everything on "Show all modules"', async () => {
    renderSummary(modules);
    const picker = screen.getByTestId('pack-focus-hidden');
    expect(within(picker).getByTestId('focus-module-takeoff')).toBeTruthy();
    expect(within(picker).queryByTestId('focus-module-boq')).toBeNull();
    fireEvent.click(within(picker).getByTestId('focus-show-takeoff'));
    await waitFor(() => expect(setModuleEnabled).toHaveBeenCalledWith('takeoff', true));
    fireEvent.click(screen.getByTestId('pack-focus-show-all'));
    await waitFor(() => expect(showAllModules).toHaveBeenCalled());
  });
});
