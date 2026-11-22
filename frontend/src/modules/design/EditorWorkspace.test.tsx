import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN } from './testStrings';
import type { ModelView } from './modelApi';

const view = (): ModelView => ({
  typology: 'apartment_section', brief_version: 4, max_units_per_floor: 12, reason: null, source: 'limits.rs',
  params: [{ id: 'floors', pointer: '/massing/floors_above', kind: 'int', unit: 'storeys', min: 1, max: 40, step: 1, options: null, nullable: false, value: 4, default: null, overridden: false }],
  units: [], presets: [],
});

const api = vi.hoisted(() => ({
  can: true,
  brief: { version: 4, provenance: { '/massing/floors_above': { status: 'confirmed' } } } as unknown,
  generate: vi.fn(async () => ({ job_id: 'j1', brief_version: 5, changed: [] })),
  extract: vi.fn(),
  save: vi.fn(async (_p: string, doc: unknown) => ({ ...(doc as object), version: 5 })),
  confirm: vi.fn(async (_p: string, _ptrs: string[], v: number) => ({ version: v, provenance: {} })),
  offer: vi.fn(),
  rights: { edit: 'members', can_edit: true, can_accept: true } as { edit: string; can_edit: boolean; can_accept: boolean },
  draft: null as unknown,
  saveDraft: vi.fn(),
  makeRevision: vi.fn(),
  payload: { kind: 'engine', version: 'ddc_web', assets: [{ url: 'x', bytes: 635678 }] } as unknown,
  revs: [] as unknown[],
  demo: false,
}));
const BRIEF = api.brief;

vi.mock('react-i18next', async () => await vi.importActual('react-i18next'));
vi.mock('@/stores/useProjectContextStore', () => ({
  useProjectContextStore: (sel: (s: { activeProjectId: string }) => unknown) => sel({ activeProjectId: 'p1' }),
}));
vi.mock('@/features/projects/api', () => ({ projectsApi: { get: vi.fn(async () => ({ id: 'p1', name: 'Haus Linde' })) } }));
vi.mock('./api', () => ({
  LINK_VERSION: '1',
  fetchAccess: vi.fn(async () => ({ can_accept: api.can, currency: null, lock: null })),
  fetchBrief: vi.fn(async () => api.brief),
  fetchGeneration: vi.fn(async () => ({ enabled: true, reason: null, job: null })),
  fetchRevisions: vi.fn(async () => api.revs),
  fetchEstimate: vi.fn(async () => ({ estimate: false })),
  fetchAiSettings: vi.fn(async () => ({ x_api_key_set: true })),
  extractBrief: api.extract,
  saveBrief: api.save,
  confirmBrief: api.confirm,
}));
vi.mock('./modelApi', async () => ({
  ...(await vi.importActual<object>('./modelApi')),
  fetchModel: vi.fn(async () => view()),
  generateModel: api.generate,
  previewBrief: vi.fn(async () => ({ brief_version: 4, brief: {} })),
}));
vi.mock('./editorPayload', () => ({
  currentPayload: vi.fn(async () => api.payload),
  startBackgroundLoad: vi.fn(() => null),
}));
vi.mock('./draftApi', () => ({
  fetchRights: vi.fn(async () => api.rights),
  fetchDraft: vi.fn(async () => api.draft),
  saveDraft: api.saveDraft,
  makeRevision: api.makeRevision,
  readDraftPackage: vi.fn(),
  readRevisionFile: vi.fn(),
  fetchAiChoice: vi.fn(async () => ({ same_as_erp: true, preferred_model: null, model: null })),
  putAiChoice: vi.fn(),
  putRights: vi.fn(),
}));
vi.mock('@/shared/lib/useDemoModules', () => ({ useDemoServer: () => api.demo }));
vi.mock('@/shared/ui/BIMViewer', () => ({ BIMViewer: () => <div data-testid="viewer" /> }));
vi.mock('@/features/bim/useModelViewerData', () => ({
  useModelViewerData: () => ({ elements: [], geometryUrl: null, isLoadingElements: false, activeModel: null }),
}));
vi.mock('@/shared/ui', async () => {
  type ReactNodeT = import('react').ReactNode;
  return {
    EmptyState: ({ title }: { title: string }) => <p>{title}</p>,
    Card: ({ children }: { children: ReactNodeT }) => <section>{children}</section>,
    CardHeader: ({ title }: { title: string }) => <header>{title}</header>,
    Button: ({ children, disabled, onClick, ...rest }: { children: ReactNodeT; disabled?: boolean; onClick?: () => void; 'data-testid'?: string }) => (
      <button type="button" disabled={disabled} onClick={onClick} data-testid={rest['data-testid']}>{children}</button>
    ),
  };
});

import EditorWorkspacePage from './EditorWorkspace';

async function mount() {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({
    lng: 'en', resources: { en: { translation: EN } }, keySeparator: false, nsSeparator: false, interpolation: { escapeValue: false },
  });
  render(
    <MemoryRouter>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <I18nextProvider i18n={inst}><EditorWorkspacePage /></I18nextProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
  return userEvent.setup();
}

beforeEach(() => {
  cleanup();
  localStorage.clear();
  localStorage.setItem('ddc-design-workspace-form-open', '1');
  api.can = true;
  api.rights = { edit: 'members', can_edit: true, can_accept: true };
  api.draft = null;
  api.revs = [];
  api.brief = BRIEF;
  api.demo = false;
  api.payload = { kind: 'engine', version: 'ddc_web', assets: [{ url: 'x', bytes: 635678 }] };
  api.saveDraft.mockReset();
  api.makeRevision.mockReset();
  api.generate.mockClear();
  api.save.mockClear();
  api.confirm.mockClear();
  api.extract.mockReset();
});

describe('editor workspace (generator in the module)', () => {
  it('is a workspace: values, canvas, selection panel, Create revision and the desktop editor', async () => {
    const user = await mount();
    expect(await screen.findByTestId('create-revision')).toBeTruthy();
    expect(screen.getByTestId('engine-label').textContent).toBe(EN['design.workspace.engine_simple_short']!);
    expect(screen.getByTestId('engine-label').getAttribute('title')).toBe(EN['design.workspace.engine_simple']!);
    expect(screen.getByTestId('workspace-canvas')).toBeTruthy();
    expect(screen.getByTestId('selection-panel').textContent).toContain(EN['design.workspace.side.none']!);
    expect(screen.getByTestId('open-desktop').getAttribute('href')).toBe('/design/editor/desktop');
    // with today's engine, Create revision = the server build through the same intake
    await user.click(screen.getByTestId('create-revision'));
    await waitFor(() => expect(api.generate).toHaveBeenCalledWith('p1', 4, {}));
  });

  it('shows the newest revision real model until a value changes, then the simplified preview', async () => {
    api.revs = [
      { revision_id: 'r1', number: 1, status: 'accepted', bim_model_id: 'm1', manifest: null },
      { revision_id: 'r2', number: 2, status: 'shared', bim_model_id: 'm2', manifest: null },
    ];
    const user = await mount();
    expect((await screen.findByTestId('tip-label')).textContent).toBe(
      `${EN['design.revisions.number']!.replace('{{number}}', '2')} · ${EN['design.revisions.status.shared']!}`);
    const floors = await screen.findByLabelText(EN['design.model.param.floors']!);
    await user.clear(floors);
    await user.type(floors, '5');
    await waitFor(() => expect(screen.queryByTestId('tip-model')).toBeNull());
  });

  it('the model is the hero: the parameters panel folds away and the choice is kept', async () => {
    localStorage.removeItem('ddc-design-workspace-form-open'); // jsdom is 1024 px wide: starts folded
    const user = await mount();
    const open = await screen.findByTestId('form-open');
    expect(screen.queryByTestId('workspace-left')).toBeNull();
    await user.click(open);
    expect(screen.getByTestId('workspace-left')).toBeTruthy();
    expect(localStorage.getItem('ddc-design-workspace-form-open')).toBe('1');
    await user.click(screen.getByTestId('form-close'));
    expect(screen.queryByTestId('workspace-left')).toBeNull();
    expect(document.activeElement).toBe(screen.getByTestId('form-open'));
  });

  it('no brief and no revision: says so and links to the brief, no preview that never starts', async () => {
    api.brief = null;
    await mount();
    const empty = await screen.findByTestId('no-design');
    expect(empty.textContent).toContain(EN['design.workspace.no_design']!);
    expect(screen.getByTestId('no-design-brief').getAttribute('href')).toBe('/design/brief');
    expect(screen.queryByText(EN['design.model.preview.building']!)).toBeNull();
  });

  it('on the read-only public demo the view-only notice names the demo, not the role', async () => {
    api.demo = true;
    api.rights = { edit: 'members', can_edit: false, can_accept: false };
    await mount();
    expect((await screen.findByTestId('view-why')).textContent).toBe(EN['design.workspace.view_demo']!);
  });

  it('without the edit right: look and select only, and it says why', async () => {
    api.rights = { edit: 'managers', can_edit: false, can_accept: false };
    await mount();
    expect((await screen.findByTestId('view-why')).textContent).toBe(EN['design.workspace.view_rights']!);
    expect(screen.getByTestId('editor-workspace').dataset.mode).toBe('view');
    expect(screen.queryByTestId('create-revision')).toBeNull();
    expect(screen.queryByTestId('workspace-left')).toBeNull();
    expect(screen.getByTestId('selection-panel')).toBeTruthy();
  });

  it('AI: each value comes with its quote, nothing is ticked, only ticked values are saved and confirmed', async () => {
    api.extract.mockResolvedValue({
      brief: {
        schema: 'ddc-brief/1', brief_id: 'b', project_id: 'p1', version: 4,
        massing: { floors_above: 5, floor_height_m: 3.1 },
        provenance: {
          '/massing/floors_above': { status: 'proposed', sources: [{ kind: 'text', quote: 'five storeys' }] },
          '/massing/floor_height_m': { status: 'proposed', sources: [{ kind: 'text', quote: '3.1 m' }] },
        },
      },
      rejected: [], notes: [], used_model: 'm', tokens: 10,
      summary: { proposed: ['/massing/floor_height_m', '/massing/floors_above'], defaults: [], questions: [], rejected: 0 },
    });
    const user = await mount();
    await user.type(await screen.findByRole('textbox', { name: EN['design.workspace.ai.title']! }), 'five storeys, 3.1 m');
    await user.click(screen.getByRole('button', { name: EN['design.workspace.ai.read']! }));
    const list = await screen.findByTestId('ai-proposals');
    expect(api.extract).toHaveBeenCalledWith('p1', 'five storeys, 3.1 m', api.brief);
    expect(list.textContent).toContain('five storeys');
    const boxes = screen.getAllByRole('checkbox').filter((c) => list.contains(c));
    expect(boxes.every((b) => !(b as HTMLInputElement).checked)).toBe(true);
    await user.click(boxes[1]!); // floors_above (list order follows the proposal order)
    await user.click(screen.getByRole('button', { name: 'Save confirmed values (1)' }));
    await waitFor(() => expect(api.confirm).toHaveBeenCalledWith('p1', ['/massing/floors_above'], 5));
    const saved = api.save.mock.calls[0]![1] as { massing: Record<string, number> };
    expect(saved.massing).toEqual({ floors_above: 5 });
    expect(await screen.findByText('Brief saved as version 5; the model follows it.')).toBeTruthy();
  });
});

describe('editor workspace (browser editor over the bridge)', () => {
  const PID = '746402cb-14a8-430c-b3b9-9c6908fa75d7';
  const DRAFT = {
    project_id: PID, revision_id: '5b0c7e21-9d3f-4a8e-b6c1-2f4d8a9e0c13', parent_revision_id: null, package_sha256: 'a'.repeat(64),
    package_bytes: 22, element_count: 2, updated_at: '2026-11-15T10:42:00Z',
    estimate: { estimate: true, model_total: '0', lines: [{ rule: 'wall_ext', unit: 'm2', elements: 1, element_keys: ['b1/w1'],
      quantity: '88.1', current_quantity: '82.5', unit_rate: '0', total: null, current_total: '0', position_id: 'p', description: 'Exterior walls', flags: ['rate_missing'] }] },
  };
  const PKG = new Uint8Array([0x50, 0x4b, 0x05, 0x06, ...new Array(18).fill(0)]);

  it('autosaves the draft, shows its lines beside the selection, makes one revision', async () => {
    api.payload = { kind: 'editor', version: '0.4.0', entryUrl: '/editor/index.html', assets: [], bundle: {} };
    api.saveDraft.mockResolvedValue(DRAFT);
    api.makeRevision.mockResolvedValue({ revision_id: '9c1d2e3f-4a5b-4c6d-8e7f-0a1b2c3d4e5f', number: 3, status: 'shared' });
    const user = await mount();
    const frame = await waitFor(() => {
      const f = screen.getByTestId('editor-host').querySelector('iframe');
      if (!f) throw new Error('no frame');
      return f;
    });
    expect(frame.getAttribute('sandbox')).toBe('allow-scripts');
    const toHost: unknown[] = [];
    vi.spyOn(frame.contentWindow!, 'postMessage').mockImplementation((m: unknown) => { toHost.push(m); });
    const emit = (data: unknown) => act(() => { window.dispatchEvent(new MessageEvent('message', { data, source: frame.contentWindow })); });
    emit({ bridge: 1, type: 'ready', versions: [1], editor: { name: 'editor', version: '0.4.0' } });
    await waitFor(() => expect(toHost).toHaveLength(1));
    expect(toHost[0]).toMatchObject({ type: 'open', mode: 'edit', draft: null, permissions: { can_edit: true, can_accept: true } });
    expect((screen.getByTestId('create-revision') as HTMLButtonElement).disabled).toBe(true); // nothing to make yet

    const sha = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', PKG))).map((b) => b.toString(16).padStart(2, '0')).join('');
    emit({ bridge: 1, type: 'save', request_id: 's1', package: PKG, package_bytes: 22, package_sha256: sha });
    await waitFor(() => expect(toHost).toHaveLength(2));
    expect(toHost[1]).toMatchObject({ type: 'save_result', ok: true, draft: { element_count: 2 } });
    expect(api.saveDraft).toHaveBeenCalledWith('p1', PKG);
    await waitFor(() => expect(screen.getByTestId('draft-status').textContent).toContain('Draft saved'));
    expect(screen.getByTestId('draft-impact').textContent).toContain('Exterior walls');

    emit({ bridge: 1, type: 'select', elements: [{ element_key: 'b1/w1', ifc_class: 'IfcWall' }] });
    expect(screen.getByTestId('selection-lines').textContent).toMatch(/82\.5.*88\.1/);
    await user.keyboard('{Escape}');
    expect(screen.getByTestId('selection-panel').textContent).toContain(EN['design.workspace.side.none']!);

    await user.click(screen.getByTestId('create-revision'));
    expect((await screen.findByTestId('revision-created')).textContent).toContain('Revision 3 created');
    expect(api.makeRevision).toHaveBeenCalledWith('p1');
    await waitFor(() => expect(toHost.filter((m) => (m as { type: string }).type === 'open')).toHaveLength(2)); // the editor reopens
  });
});
