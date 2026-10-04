// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Progress is a step in the middle of the workflow: a reading is recorded
// against a BOQ position, it is billed through a payment application, and it
// is judged against the programme. The page linked only to the bare BOQ list
// and the 5D page. What is pinned: each tracked position opens its own row in
// its bill (resolved from the position id alone), and the page offers the
// payment applications of the active project and the schedule.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => {
  type Opts = Record<string, unknown>;
  const fill = (template: string, opts?: Opts): string => {
    if (!opts) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_m, name: string) =>
      opts[name] === undefined ? `{{${name}}}` : String(opts[name]),
    );
  };
  return {
    useTranslation: () => ({
      t: (key: string, second?: string | Opts, third?: Opts) => {
        if (typeof second === 'string') return fill(second, third);
        const dflt = second?.defaultValue;
        return fill(typeof dflt === 'string' ? dflt : key, second);
      },
      i18n: { language: 'en', changeLanguage: vi.fn() },
    }),
    Trans: ({ children }: { children?: unknown }) => children ?? null,
    initReactI18next: { type: '3rdParty', init: () => undefined },
    I18nextProvider: ({ children }: { children?: unknown }) => children ?? null,
  };
});

vi.mock('@/shared/lib/projectList', () => ({
  fetchProjectList: () => Promise.resolve([{ id: 'proj-1' }]),
}));

const store = vi.hoisted(() => ({ activeProjectId: 'proj-1' as string | null, activeProjectName: 'Riverside' }));

vi.mock('@/stores/useProjectContextStore', () => ({
  useProjectContextStore: (selector?: (s: typeof store) => unknown) => (selector ? selector(store) : store),
}));

vi.mock('./RecordProgressDialog', () => ({ RecordProgressDialog: () => null }));

vi.mock('./api', () => ({
  getProgressCumulative: () =>
    Promise.resolve({ project_id: 'proj-1', boq_position_id: null, periods: [], current_cumulative_pct: 40 }),
  getProgressSCurve: () => Promise.resolve({ project_id: 'proj-1', points: [] }),
  getQuantityVariance: () =>
    Promise.resolve({
      project_id: 'proj-1',
      positions: [
        {
          boq_position_id: 'pos-17',
          ordinal: '01.020',
          description: 'Reinforced concrete slab',
          unit: 'm3',
          design_quantity: '120',
          earned_quantity: '48',
          percent_complete: '40',
          variance: '-72',
          variance_percent: '-60',
          status: 'under_run',
          is_over_run: false,
          is_under_run: true,
        },
      ],
      rollup: {
        position_count: 1,
        over_run_count: 0,
        under_run_count: 1,
        on_target_count: 0,
        design_quantity_total: '120',
        earned_quantity_total: '48',
        variance_total: '-72',
        variance_percent: '-60',
      },
    }),
}));

import { ProgressPage } from './ProgressPage';

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/progress']}>
        <ProgressPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => cleanup());

describe('the progress page leads on', () => {
  it('opens a tracked position on its own row in its bill', async () => {
    renderPage();

    const link = await screen.findByRole('link', { name: '01.020' });
    expect(link.getAttribute('href')).toBe('/boq?positionId=pos-17');
  });

  it("offers the active project's payment applications and the schedule", async () => {
    renderPage();

    const strip = within(await screen.findByTestId('progress-next'));
    expect(strip.getByRole('link', { name: /Payment applications/ }).getAttribute('href')).toBe(
      '/projects/proj-1/contracts?tab=claims',
    );
    expect(strip.getByRole('link', { name: /Schedule/ }).getAttribute('href')).toBe('/schedule');
  });
});
