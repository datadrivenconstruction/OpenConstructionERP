import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN, RU, DE } from './testStrings';
import type { RevisionView } from './data/revisions';

const state = vi.hoisted(() => ({
  project: 'p1' as string | null,
  revisions: [] as unknown[],
  elements: {} as Record<string, unknown[]>,
  fail: false,
  imported: [] as unknown[],
  importedAdd: [] as string[],
  lastViewer: null as null | { modelId: string; glbUpAxis?: string; overlay: Map<string, string> | null },
}));

vi.mock('react-i18next', async () => await vi.importActual('react-i18next'));
vi.mock('@/stores/useProjectContextStore', () => ({
  useProjectContextStore: (sel: (s: { activeProjectId: string | null }) => unknown) => sel({ activeProjectId: state.project }),
}));
vi.mock('./api', () => ({
  LINK_VERSION: '1',
  fetchRevisions: vi.fn(async () => {
    if (state.fail) throw new Error('boom');
    return state.revisions;
  }),
  fetchAccess: vi.fn(async () => ({ can_accept: false, currency: null, lock: null })),
  fetchBrief: vi.fn(async () => null),
  fetchGeneration: vi.fn(async () => ({ enabled: false, reason: 'off', job: null })),
  startGeneration: vi.fn(),
  fetchImportedModels: vi.fn(async () => state.imported),
  importModel: vi.fn(async (_p: string, id: string) => {
    state.importedAdd.push(id);
    state.imported = [];
    state.revisions = [{ revision_id: 'ri', project_id: 'p1', number: 1, parent_revision_id: null, status: 'shared',
      source_kind: 'imported', depth_level: null, message: 'Haus.ifc', bim_model_id: id, decided_by: null, decided_at: null,
      decision_comment: null, created_at: '2026-01-05T10:00:00Z', manifest: { schema: 'ddc-import/1' } }];
    return state.revisions[0];
  }),
  cancelGeneration: vi.fn(),
}));
vi.mock('@/features/bim/api', () => ({
  fetchBIMElements: vi.fn(async (id: string) => ({ items: state.elements[id] ?? [], total: (state.elements[id] ?? []).length })),
}));
vi.mock('@/features/bim/useModelViewerData', () => ({
  useModelViewerData: (_p: string, id: string | null) => ({
    activeModel: id ? { id, metadata: {} } : null, elements: [], geometryUrl: id ? `/g/${id}` : null,
    isLoadingElements: false, isLoadingModels: false, models: [],
  }),
}));
vi.mock('@/shared/ui/BIMViewer', () => ({
  BIMViewer: (p: { modelId: string; glbUpAxis?: string; diffChangeByStableId: Map<string, string> | null;
    onSelectionChange: (ids: string[], els: unknown[]) => void }) => {
    state.lastViewer = { modelId: p.modelId, glbUpAxis: p.glbUpAxis, overlay: p.diffChangeByStableId };
    return (
      <button type="button" data-testid="viewer" onClick={() => p.onSelectionChange(['e1'], [{
        id: 'e1', stable_id: 'b1/s00/w1', name: 'Wall A', element_type: 'Wall', storey: 'EG', discipline: 'architecture',
        quantities: { area_m2: 82.5 },
      }])}>viewer {p.modelId}</button>
    );
  },
}));
vi.mock('@/shared/ui', async () => {
  const React = await import('react');
  const div = (name: string) => ({ children, title, description, hint, action }: Record<string, unknown>) =>
    React.createElement('div', { 'data-ui': name, role: name === 'ErrorState' ? 'alert' : undefined },
      React.createElement('p', null, title as string), React.createElement('p', null, description as string),
      React.createElement('p', null, hint as string), action as never, children as never);
  return {
    Badge: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
    Button: ({ children, onClick, disabled }: { children: React.ReactNode; onClick?: () => void; disabled?: boolean }) =>
      <button type="button" onClick={onClick} disabled={disabled}>{children}</button>,
    Card: ({ children }: { children: React.ReactNode }) => <section>{children}</section>,
    CardHeader: ({ title, subtitle }: { title: string; subtitle?: string }) => <header>{title}{subtitle}</header>,
    EmptyState: div('EmptyState'), ErrorState: div('ErrorState'), PageHeader: ({ srTitle, subtitle }: { srTitle?: string; subtitle?: string }) => <header><h1>{srTitle}</h1><p>{subtitle}</p></header>,
    Skeleton: () => <span data-testid="skeleton" />,
  };
});

import RevisionsPage from './RevisionsPage';

const rev = (n: number, over: Partial<RevisionView> = {}): RevisionView => ({
  revision_id: `r${n}`, project_id: 'p1', number: n, parent_revision_id: null, status: 'shared', source_kind: 'editor',
  depth_level: 'D2', message: `message ${n}`, bim_model_id: `m${n}`, decided_by: null, decided_at: null,
  decision_comment: null, created_at: '2026-01-0' + n + 'T10:00:00Z', ...over,
});
const el = (key: string, hash = 'h') => ({ stable_id: key, name: key, element_type: 'Wall', storey: 'EG',
  geometry_hash: hash, quantities: { area_m2: 10 } });

async function mount(lang: 'en' | 'ru' | 'de' = 'en', route = '/') {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({
    lng: lang, fallbackLng: 'en', resources: { en: { translation: EN }, ru: { translation: RU }, de: { translation: DE } },
    keySeparator: false, nsSeparator: false, interpolation: { escapeValue: false },
  });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nextProvider i18n={inst}><MemoryRouter initialEntries={[route]}><RevisionsPage /></MemoryRouter></I18nextProvider>
    </QueryClientProvider>,
  );
  return user;
}

beforeEach(() => {
  cleanup();
  state.project = 'p1';
  state.fail = false;
  state.lastViewer = null;
  state.revisions = [];
  state.imported = [];
  state.importedAdd = [];
  state.elements = {
    m1: [el('k/a'), el('k/b'), el('k/c')],
    m2: [el('k/a'), el('k/b', 'new'), el('k/d')],
    m3: [el('k/a'), el('k/b'), el('k/c')],
  };
});

describe('RevisionsPage imported models (R16)', () => {
  it('lists unwrapped imports, adds one as a revision and shows it imported, without a level, Z-up', async () => {
    state.imported = [{ bim_model_id: 'mi', name: 'Haus.ifc', model_format: 'ifc', element_count: 1840, created_at: null }];
    const user = await mount();
    const panel = await screen.findByTestId('imported-models');
    expect(within(panel).getByText('Haus.ifc')).toBeTruthy();
    expect(within(panel).getByText('1840 elements')).toBeTruthy();
    await user.click(within(panel).getByRole('button', { name: 'Add as revision' }));
    expect(state.importedAdd).toEqual(['mi']);
    const list = await screen.findByTestId('revision-list');
    await waitFor(() => expect(screen.queryByTestId('imported-models')).toBeNull());
    const item = within(list).getByRole('listitem');
    expect(within(item).getByText('imported')).toBeTruthy();
    expect(item.textContent).not.toMatch(/D[1-5]/);
    await user.click(within(list).getByRole('button', { name: /Revision 1/ }));
    expect(state.lastViewer?.modelId).toBe('mi');
    expect(state.lastViewer?.glbUpAxis).toBe('z');
  });

  it('shows no panel without candidates and no imported badge on editor revisions (ru)', async () => {
    state.revisions = [rev(1)];
    await mount('ru');
    const list = await screen.findByTestId('revision-list');
    expect(screen.queryByTestId('imported-models')).toBeNull();
    expect(within(list).queryByText('импорт')).toBeNull();
    expect(within(list).getByText('D2')).toBeTruthy();
  });
});

describe('RevisionsPage states', () => {
  it('asks for a project when none is active', async () => {
    state.project = null;
    await mount();
    expect(screen.getByText('Select a project')).toBeTruthy();
  });

  it('shows the empty state with no revisions', async () => {
    await mount();
    expect(await screen.findByText('No revisions yet')).toBeTruthy();
    expect(screen.queryByTestId('revision-list')).toBeNull();
    // The empty list is not a dead end: it leads to where a revision comes from.
    expect(screen.getByRole('link', { name: 'Open in design editor' }).getAttribute('href')).toBe('/design/editor');
  });

  it('shows an error with the server message when the list fails', async () => {
    state.fail = true;
    await mount();
    expect(await screen.findByText('The revisions could not be loaded')).toBeTruthy();
    expect(screen.getByRole('alert')).toBeTruthy();
  });

  it('lists one revision, newest first for many, and opens one in the viewer with Y-up geometry', async () => {
    state.revisions = [rev(3), rev(2), rev(1)];
    const user = await mount();
    const list = await screen.findByTestId('revision-list');
    expect(within(list).getAllByRole('listitem').map((li) => li.textContent?.match(/Revision (\d)/)?.[1])).toEqual(['3', '2', '1']);
    expect(screen.queryByTestId('viewer')).toBeNull();
    await user.click(within(list).getByRole('button', { name: /Revision 2/ }));
    expect(await screen.findByTestId('viewer')).toBeTruthy();
    expect(state.lastViewer?.modelId).toBe('m2');
    expect(state.lastViewer?.glbUpAxis).toBe('y');
    expect(state.lastViewer?.overlay).toBeNull();
  });

  it('opens and highlights the revision named by ?rev=', async () => {
    state.revisions = [rev(3), rev(2), rev(1)];
    await mount('en', '/design/revisions?rev=r2');
    expect((await screen.findByTestId('viewer')).textContent).toContain('m2');
    const items = within(screen.getByTestId('revision-list')).getAllByRole('listitem');
    expect(items.filter((li) => li.getAttribute('aria-current') === 'true').map((li) => li.textContent?.match(/Revision (\d)/)?.[1])).toEqual(['2']);
  });

  it('ignores a ?rev= that names no revision of the project', async () => {
    state.revisions = [rev(2), rev(1)];
    await mount('en', '/design/revisions?rev=nope');
    await screen.findByTestId('revision-list');
    expect(screen.queryByTestId('viewer')).toBeNull();
  });

  it('a single revision can be opened and shows its message and status', async () => {
    state.revisions = [rev(1)];
    const user = await mount();
    expect(await screen.findByText('Awaiting decision')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /Revision 1/ }));
    expect((await screen.findByTestId('viewer')).textContent).toContain('m1');
  });

  it('a revision without a model is listed but cannot be opened or compared', async () => {
    state.revisions = [rev(2, { bim_model_id: null }), rev(1)];
    await mount();
    await screen.findByTestId('revision-list');
    expect((screen.getByRole('button', { name: /Revision 2/ }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText('Compare revision 2') as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText(/no model/)).toBeTruthy();
  });

  it('picking an element shows its table row', async () => {
    state.revisions = [rev(1)];
    const user = await mount();
    await user.click(await screen.findByRole('button', { name: /Revision 1/ }));
    await user.click(await screen.findByTestId('viewer'));
    const row = await screen.findByTestId('element-row');
    expect(row.textContent).toContain('Wall A');
    expect(row.textContent).toContain('EG');
    expect(row.textContent).toContain('Area, m²');
  });
});

describe('RevisionsPage compare', () => {
  it('colours added, removed and changed; removed elements are listed, base side shows them as deleted', async () => {
    state.revisions = [rev(2), rev(1)];
    const user = await mount();
    await user.click(await screen.findByLabelText('Compare revision 1'));
    expect(screen.queryByTestId('compare-bar')).toBeNull();
    await user.click(screen.getByLabelText('Compare revision 2'));
    const bar = await screen.findByTestId('compare-bar');
    await waitFor(() => expect(bar.textContent).toContain('1 added'));
    expect(bar.textContent).toContain('1 removed');
    expect(bar.textContent).toContain('1 changed');
    expect(bar.textContent).toContain('1 unchanged');
    expect(state.lastViewer?.modelId).toBe('m2');
    expect([...(state.lastViewer?.overlay ?? [])]).toEqual([['k/b', 'modified'], ['k/d', 'added']]);
    expect(within(screen.getByTestId('change-list')).getByText('k/c')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: /Revision 1 \(removed\)/ }));
    await waitFor(() => expect(state.lastViewer?.modelId).toBe('m1'));
    expect([...(state.lastViewer?.overlay ?? [])]).toEqual([['k/b', 'modified'], ['k/c', 'deleted']]);
  });

  it('comparing a revision with itself is impossible: the second click unselects', async () => {
    state.revisions = [rev(2), rev(1)];
    const user = await mount();
    const one = await screen.findByLabelText('Compare revision 1');
    await user.click(one);
    await user.click(one);
    expect((one as HTMLInputElement).checked).toBe(false);
    expect(screen.queryByTestId('compare-bar')).toBeNull();
  });

  it('two revisions with the same content report no differences', async () => {
    state.revisions = [rev(3), rev(1)];
    const user = await mount();
    await user.click(await screen.findByLabelText('Compare revision 1'));
    await user.click(screen.getByLabelText('Compare revision 3'));
    expect(await screen.findByTestId('no-differences')).toBeTruthy();
    expect((state.lastViewer?.overlay ?? new Map()).size).toBe(0);
  });

  it('a third pick replaces the older of the two', async () => {
    state.revisions = [rev(3), rev(2), rev(1)];
    const user = await mount();
    await user.click(await screen.findByLabelText('Compare revision 1'));
    await user.click(screen.getByLabelText('Compare revision 2'));
    await user.click(screen.getByLabelText('Compare revision 3'));
    expect((screen.getByLabelText('Compare revision 1') as HTMLInputElement).checked).toBe(false);
    expect(screen.getByTestId('compare-bar').textContent).toContain('Revision 2 to revision 3');
  });

  it('works from the keyboard: tab to a checkbox, space toggles, enter opens', async () => {
    state.revisions = [rev(2), rev(1)];
    const user = await mount();
    await screen.findByTestId('revision-list');
    await user.tab();
    expect(document.activeElement).toBe(screen.getByLabelText('Compare revision 2'));
    await user.keyboard(' ');
    expect((document.activeElement as HTMLInputElement).checked).toBe(true);
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: /Revision 2/ }));
    await user.keyboard('{Enter}');
    expect((await screen.findByTestId('viewer')).textContent).toContain('m2');
  });
});

describe('RevisionsPage languages', () => {
  it.each([
    ['ru', 'Ревизии', 'Ждёт решения'],
    ['de', 'Revisionen', 'Wartet auf Entscheidung'],
  ] as const)('renders %s', async (lang, title, status) => {
    state.revisions = [rev(1)];
    await mount(lang);
    expect(await screen.findByText(status)).toBeTruthy();
    expect(screen.getAllByText(title).length).toBeGreaterThan(0);
  });
});
