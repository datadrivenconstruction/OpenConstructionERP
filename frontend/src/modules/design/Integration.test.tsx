import type { ReactNode, ButtonHTMLAttributes } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN, RU } from './testStrings';
import type { ElementLinks, Overview, PositionElements } from './linksApi';

const api = vi.hoisted(() => ({
  calls: [] as string[],
  links: null as unknown,
  overview: null as unknown,
  elements: null as unknown,
  canAccept: true,
  zeroEstimate: false,
}));

vi.mock('react-i18next', async () => await vi.importActual('react-i18next'));
vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(async (path: string) => {
    api.calls.push(`GET ${path}`);
    if (path.includes('/links?')) return api.links;
    if (path.endsWith('/overview')) return api.overview;
    if (path.includes('/elements')) return api.elements;
    throw new Error(`unexpected ${path}`);
  }),
  apiPost: vi.fn(async (path: string) => {
    api.calls.push(`POST ${path}`);
    return { positions: 2, element_links: 7, activities: 2 };
  }),
  getErrorMessage: (e: unknown) => String(e),
}));
vi.mock('./api', () => ({
  LINK_VERSION: '1',
  fetchAccess: vi.fn(async () => ({ can_accept: api.canAccept, currency: null, lock: null })),
  fetchEstimate: vi.fn(async () => {
    const f = (await import('./data/fixtures/estimate.de-residential.json')).default;
    return api.zeroEstimate ? { ...f, total: '0', range: { ...f.range, total: { low: '0', mid: '0', high: '0', complete: false } } } : f;
  }),
}));
vi.mock('@/shared/ui', () => {
  return {
    Button: ({ children, onClick, loading: _l, variant: _v, size: _s, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & Record<string, unknown>) => (
      <button type="button" onClick={onClick} {...(rest as object)}>{children}</button>),
    PageHeader: ({ subtitle }: { subtitle: string }) => <p>{subtitle}</p>,
    EmptyState: ({ title }: { title: string }) => <p>{title}</p>,
    ErrorState: ({ title }: { title: string }) => <p role="alert">{title}</p>,
    Skeleton: () => <div aria-busy="true" />,
    KpiBand: ({ items }: { items: { key: string; label: string; value: string; sub?: string }[] }) => (
      <ul>{items.map((i) => <li key={i.key} data-testid={`kpi-${i.key}`}>{i.label}|{i.value}|{i.sub ?? ''}</li>)}</ul>),
  };
});
vi.mock('@/stores/useProjectContextStore', () => {
  const state = { activeProjectId: 'p1', setActiveProject: vi.fn() };
  return { useProjectContextStore: (sel: (s: typeof state) => unknown) => sel(state) };
});

import { ProjectOverview, stepState } from './OverviewPage';
import { LinkedInErp } from './SelectionPanel';
import { PositionLinks } from './PositionLinks';
import { boqUrl, editorUrl, packageUrl, scheduleUrl, selectionFromUrl, viewerUrl } from './linksApi';

const LINKS: ElementLinks = {
  keys: ['b1/s01/wall/0'],
  positions: [
    { position_id: 'pos1', boq_id: 'boq1', source: 'estimate', ordinal: '01.002', description: 'Exterior wall', quantity: '82.5', unit: 'm2', elements: ['b1/s01/wall/0'] },
    { position_id: 'pos9', boq_id: 'boq2', source: 'takeoff', ordinal: '03.001', description: 'wall/ext-365', quantity: '82.5', unit: 'm2', elements: ['b1/s01/wall/0'] },
  ],
  activities: [{ activity_id: 'a1', schedule_id: 's1', name: 'Exterior wall · 1.OG', start_date: '2027-03-04', end_date: '2027-03-08', storey: '1.OG', elements: ['b1/s01/wall/0'] }],
  packages: [{ package_id: 'k1', name: 'Design take-off: IfcWall', status: 'draft', ifc_class: 'IfcWall', elements: ['b1/s01/wall/0'] }],
};

const OVERVIEW = (over: Partial<Record<string, object>> = {}): Overview => ({
  project_id: 'p1', waiting_revision_id: null,
  steps: [
    { id: 'brief', done: true, count: null, url: '/design/brief' },
    { id: 'model', done: true, count: 2, waiting: 0, drafts: 1, current: 2, url: '/design/revisions' },
    { id: 'estimate', done: true, count: 14, url: '/boq/boq1' },
    { id: 'schedule', done: false, count: 0, url: '/design/acceptance' },
    { id: 'procurement', done: false, count: 0, url: '/design/acceptance' },
    { id: 'documents', done: true, count: 3, url: '/projects/p1/files' },
    { id: 'bim', done: true, count: 40, url: '/projects/p1/bim/m2' },
    { id: 'change_orders', done: false, count: 0, url: '/changeorders' },
    { id: 'tasks', done: true, count: 0, url: '/projects/p1/tasks' },
  ].map((s) => ({ ...s, ...(over[s.id] ?? {}) })) as Overview['steps'],
});

let lastPath = '';
function Where() {
  const loc = useLocation();
  lastPath = loc.pathname + loc.search;
  return null;
}

async function mount(ui: ReactNode, lang = 'en') {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({
    lng: lang, fallbackLng: 'en', resources: { en: { translation: EN }, ru: { translation: RU } },
    keySeparator: false, nsSeparator: false, interpolation: { escapeValue: false },
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <I18nextProvider i18n={inst}>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/design/estimate']}>
          <Routes><Route path="*" element={<>{ui}<Where /></>} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  );
}

beforeEach(() => {
  cleanup();
  api.calls = [];
  api.zeroEstimate = false;
  api.links = LINKS;
  api.overview = OVERVIEW();
  api.canAccept = true;
  lastPath = '';
});

describe('ERP addresses', () => {
  it('open each thing where the ERP shows it', () => {
    expect(boqUrl({ boq_id: 'b', position_id: 'p' })).toBe('/boq/b?highlight=p');
    expect(scheduleUrl({ schedule_id: 's' })).toBe('/schedule/s/cpm');
    expect(packageUrl({ package_id: 'k' })).toBe('/tendering?package=k');
    const e: PositionElements = { position_id: 'p', boq_id: 'b', model_id: 'm', keys: ['a'], element_ids: ['u1', 'u2'], isolate: ['u1', 'u2'] };
    expect(viewerUrl('p1', e)).toBe('/projects/p1/bim/m?isolate=u1,u2');
    expect(viewerUrl('p1', { ...e, isolate: null })).toBe('/projects/p1/bim/m'); // too many to filter: the whole model
    expect(viewerUrl('p1', { ...e, model_id: null })).toBeNull();
    expect(editorUrl(['b1/s00/wall/0', 'x:1'])).toBe('/design/editor?select=b1%2Fs00%2Fwall%2F0%2Cx%3A1');
  });

  it('a deep link selects only well-formed element keys, at most 50', () => {
    expect(selectionFromUrl('a/1,,a/1, b:2 ,<script>')).toEqual([{ element_key: 'a/1' }, { element_key: 'b:2' }]);
    expect(selectionFromUrl(Array.from({ length: 80 }, (_, i) => `k${i}`).join(','))).toHaveLength(50);
    expect(selectionFromUrl(null)).toEqual([]);
  });
});

describe('selection: linked in the ERP', () => {
  it('lists positions, activities and packages, each a link into its module', async () => {
    await mount(<LinkedInErp projectId="p1" keys={['b1/s01/wall/0']} />);
    const pos = await screen.findByTestId('link-position-pos1');
    expect(pos).toHaveAttribute('href', '/boq/boq1?highlight=pos1');
    expect(pos).toHaveTextContent('01.002 Exterior wall');
    expect(screen.getByTestId('link-position-pos9')).toHaveTextContent('Take-off');
    expect(screen.getByTestId('link-activity-a1')).toHaveAttribute('href', '/schedule/s1/cpm');
    expect(screen.getByTestId('link-package-k1')).toHaveAttribute('href', '/tendering?package=k1');
    expect(api.calls.sort()).toEqual(['GET /v1/design/projects/p1/field-reports?keys=b1%2Fs01%2Fwall%2F0',
      'GET /v1/design/projects/p1/links?keys=b1%2Fs01%2Fwall%2F0']);
  });

  it('says so when nothing uses the selection, and asks nothing without one', async () => {
    api.links = { keys: ['x'], positions: [], activities: [], packages: [] };
    await mount(<LinkedInErp projectId="p1" keys={['x']} />);
    expect(await screen.findByText(EN['design.links.none']!)).toBeInTheDocument();
    cleanup();
    api.calls = [];
    await mount(<LinkedInErp projectId="p1" keys={[]} />);
    expect(screen.queryByTestId('linked-in-erp')).toBeNull();
    expect(api.calls).toEqual([]);
  });
});

describe('estimate position: where it lives', () => {
  it('opens the elements isolated in the ERP viewer, the BOQ row, the editor selection', async () => {
    api.elements = { position_id: 'pos1', boq_id: 'boq1', model_id: 'm2', keys: ['w/0', 'w/1'], element_ids: ['u0', 'u1'], isolate: ['u0', 'u1'] };
    const user = userEvent.setup();
    await mount(<PositionLinks projectId="p1" positionId="pos1" rule="wall_ext" />);
    await user.click(screen.getByTestId('show-model-wall_ext'));
    await waitFor(() => expect(lastPath).toBe('/projects/p1/bim/m2?isolate=u0,u1'));
    await user.click(screen.getByTestId('show-boq-wall_ext'));
    await waitFor(() => expect(lastPath).toBe('/boq/boq1?highlight=pos1'));
    await user.click(screen.getByTestId('show-editor-wall_ext'));
    await waitFor(() => expect(lastPath).toBe('/design/editor?select=w%2F0%2Cw%2F1'));
  });

  it('stays and says why when the model has no elements behind the position', async () => {
    api.elements = { position_id: 'pos1', boq_id: 'boq1', model_id: 'm2', keys: [], element_ids: [], isolate: null };
    const user = userEvent.setup();
    await mount(<PositionLinks projectId="p1" positionId="pos1" rule="slab" />);
    await user.click(screen.getByTestId('show-model-slab'));
    expect(await screen.findByRole('alert')).toHaveTextContent(EN['design.links.no_elements']!);
    expect(lastPath).toBe('/design/estimate');
  });
});

describe('project overview', () => {
  it('shows every module with its state and points to the next step', async () => {
    await mount(<ProjectOverview projectId="p1" />);
    const steps = await screen.findByTestId('overview-steps');
    expect(steps.querySelectorAll('li')).toHaveLength(9);
    expect(screen.getByText('Steps linked: 3 of 5')).toBeInTheDocument();
    expect(screen.getByTestId('step-estimate')).toHaveAttribute('data-state', 'done');
    expect(screen.getByTestId('step-estimate').querySelector('a')).toHaveAttribute('href', '/boq/boq1');
    expect(screen.getByTestId('step-estimate')).toHaveTextContent('Positions following the model: 14');
    expect(screen.getByTestId('step-model')).toHaveTextContent('Current: R2; revisions: 2 · drafts: 1');
    expect(screen.getByTestId('step-schedule')).toHaveAttribute('data-state', 'todo');
    expect(screen.getByTestId('overview-next')).toHaveAttribute('href', '/design/acceptance');
    expect(screen.getByTestId('overview-next')).toHaveTextContent('Set up the schedule');
    // headline figures: from the overview and the estimate, nothing guessed for what is not set up
    expect(screen.getByTestId('kpi-revision')).toHaveTextContent('Revision 2');
    // the estimate arrives after the overview: wait for it rather than the first paint
    await waitFor(() => expect(screen.getByTestId('kpi-priced')).toHaveTextContent('3 / 14'));
    expect(screen.getByTestId('kpi-priced')).toHaveTextContent('Without a rate: 11');
    expect(screen.getByTestId('kpi-estimate')).toHaveTextContent(/132/);
    expect(screen.getByTestId('kpi-linked')).toHaveTextContent('40');
  });

  it('shows no range tile figure when nothing is priced', async () => {
    api.zeroEstimate = true;
    api.overview = OVERVIEW();
    await mount(<ProjectOverview projectId="p1" />);
    await waitFor(() => expect(screen.getByTestId('kpi-priced')).toHaveTextContent('3 / 14'));
    expect(screen.getByTestId('kpi-estimate')).not.toHaveTextContent(/€|0/);
  });

  it('puts a waiting revision first, and lets only the manager relink', async () => {
    api.overview = { ...OVERVIEW({ model: { waiting: 1 }, tasks: { count: 1, done: false } }), waiting_revision_id: 'r3' };
    const user = userEvent.setup();
    await mount(<ProjectOverview projectId="p1" />);
    expect(await screen.findByTestId('overview-review')).toHaveAttribute('href', '/design/acceptance?revision=r3');
    expect(screen.queryByTestId('overview-next')).toBeNull();
    expect(screen.getByTestId('step-model')).toHaveAttribute('data-state', 'waiting');
    expect(screen.getByTestId('step-tasks')).toHaveTextContent('Reviews open: 1');
    await user.click(await screen.findByTestId('overview-relink'));
    expect(await screen.findByRole('status')).toHaveTextContent('Element links written: 7');
    expect(api.calls).toContain('POST /v1/design/projects/p1/links/sync');
    cleanup();
    api.canAccept = false;
    await mount(<ProjectOverview projectId="p1" />);
    await screen.findByTestId('overview-steps');
    expect(screen.queryByTestId('overview-relink')).toBeNull();
  });

  it('state rules', () => {
    expect(stepState({ id: 'model', done: true, count: 3, waiting: 1, url: '' })).toBe('waiting');
    expect(stepState({ id: 'tasks', done: true, count: 0, url: '' })).toBe('done');
    expect(stepState({ id: 'estimate', done: false, count: 0, url: '' })).toBe('todo');
    expect(stepState({ id: 'bim', done: true, count: 0, url: '' })).toBe('todo');
    expect(stepState({ id: 'bim', done: true, count: 5, url: '' })).toBe('done');
  });

  it('speaks Russian', async () => {
    await mount(<ProjectOverview projectId="p1" />, 'ru');
    expect(await screen.findByText('Связано шагов: 3 из 5')).toBeInTheDocument();
    expect(screen.getByTestId('step-estimate')).toHaveTextContent('Позиций по модели: 14');
  });
});
