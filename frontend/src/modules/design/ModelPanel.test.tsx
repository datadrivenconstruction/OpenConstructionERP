import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN, RU } from './testStrings';
import type { ModelView } from './modelApi';

const view = (): ModelView => ({
  typology: 'apartment_section', brief_version: 4, max_units_per_floor: 12, reason: null, source: 'limits.rs',
  params: [
    { id: 'floors', pointer: '/massing/floors_above', kind: 'int', unit: 'storeys', min: 1, max: 40, step: 1, options: null, nullable: false, value: 4, default: null, overridden: false },
    { id: 'floor_height', pointer: '/massing/floor_height_m', kind: 'number', unit: 'm', min: 2.7, max: 6, step: 0.05, options: null, nullable: true, value: 3, default: 3, overridden: false },
    { id: 'grid', pointer: '/structure/grid_m', kind: 'number', unit: 'm', min: 3, max: 12, step: 0.1, options: null, nullable: true, value: null, default: 7.2, overridden: false },
    { id: 'foundation', pointer: '/structure/foundation', kind: 'choice', unit: null, min: null, max: null, step: null, options: ['raft', 'strip', null], nullable: true, value: 'raft', default: null, overridden: false },
  ],
  units: [
    { index: 0, pointer: '/programme/units/0/count', name: '2-Zimmer', value: 8, min: 1, max: 480, per_floor: 2, overridden: false },
    { index: 1, pointer: '/programme/units/1/count', name: '3-Zimmer', value: 8, min: 1, max: 480, per_floor: 2, overridden: false },
  ],
  presets: [{ id: 'floor_up', values: { '/massing/floors_above': 5, '/programme/units/0/count': 10, '/programme/units/1/count': 10 } }],
});

const api = vi.hoisted(() => ({
  can: true,
  rights: { edit: 'members', can_edit: true, can_accept: true } as null | { edit: string; can_edit: boolean; can_accept: boolean },
  lock: null as null | { held_by: string; mine: boolean; expires_at: string },
  brief: { version: 4, provenance: { '/massing/floors_above': { status: 'confirmed' } } } as unknown,
  gen: { enabled: true, reason: null, job: null } as { enabled: boolean; reason: string | null; job: unknown },
  model: null as unknown,
  generate: vi.fn(async () => ({ job_id: 'j1', brief_version: 5, changed: [] })),
  preview: vi.fn(async (_p: string, v: number, values: object) => ({ brief_version: v, brief: { values } })),
  viewer: vi.fn(),
}));

vi.mock('react-i18next', async () => await vi.importActual('react-i18next'));
vi.mock('./api', () => ({
  fetchAccess: vi.fn(async () => ({ can_accept: api.can, currency: null, lock: api.lock })),
  fetchBrief: vi.fn(async () => api.brief),
  fetchGeneration: vi.fn(async () => api.gen),
}));
vi.mock('./draftApi', () => ({
  fetchRights: vi.fn(async () => { if (!api.rights) throw new Error('404'); return api.rights; }),
}));
vi.mock('./modelApi', async () => ({
  ...(await vi.importActual<object>('./modelApi')),
  fetchModel: vi.fn(async () => api.model),
  generateModel: api.generate,
  previewBrief: api.preview,
}));
vi.mock('@/shared/ui/BIMViewer', () => ({
  BIMViewer: (p: { elements: { id: string }[]; geometryUrl: string; portal?: boolean; readOnly?: boolean }) => {
    api.viewer(p);
    return <div data-testid="viewer">{p.elements.length}</div>;
  },
}));
vi.mock('@/shared/ui', async () => {
  const React = await import('react');
  return {
    Card: ({ children }: { children: React.ReactNode }) => <section>{children}</section>,
    CardHeader: ({ title }: { title: string }) => <header>{title}</header>,
    Button: ({ children, disabled, onClick }: { children: React.ReactNode; disabled?: boolean; onClick?: () => void }) => (
      <button type="button" disabled={disabled} onClick={onClick}>{children}</button>
    ),
  };
});

import ModelPanel from './ModelPanel';

let client: QueryClient;
async function mount(lang: 'en' | 'ru' = 'en', fallback: ReactNode = null) {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({
    lng: lang, fallbackLng: 'en', resources: { en: { translation: EN }, ru: { translation: RU } },
    keySeparator: false, nsSeparator: false, interpolation: { escapeValue: false },
  });
  render(
    <MemoryRouter>
      <QueryClientProvider client={client = new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <I18nextProvider i18n={inst}><ModelPanel projectId="p1" fallback={fallback} /></I18nextProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
  return userEvent.setup();
}

beforeEach(() => {
  cleanup();
  api.can = true;
  api.rights = { edit: 'members', can_edit: true, can_accept: true };
  api.lock = null;
  api.brief = { version: 4, provenance: { '/massing/floors_above': { status: 'confirmed' } } };
  api.gen = { enabled: true, reason: null, job: null };
  api.model = view();
  api.generate.mockClear();
  api.preview.mockClear();
  api.viewer.mockClear();
  vi.unstubAllGlobals();
});

/** A GLB with only the JSON chunk the panel reads: node names are element keys, extras the IFC class. */
function tinyGlb(): Uint8Array {
  const nodes = [['b1/s01/wall.1', 'IfcWall'], ['b1/s01/wall.2', 'IfcWall'], ['b1/found/raft', 'IfcFooting']]
    .map(([k, c]) => ({ name: k, extras: { element_key: k, ifc_class: c } }));
  let js = JSON.stringify({ asset: { version: '2.0' }, nodes });
  while (js.length % 4) js += ' ';
  const out = new Uint8Array(20 + js.length);
  const dv = new DataView(out.buffer);
  dv.setUint32(0, 0x46546c67, true); dv.setUint32(4, 2, true); dv.setUint32(8, out.length, true);
  dv.setUint32(12, js.length, true); dv.setUint32(16, 0x4e4f534a, true);
  out.set(new TextEncoder().encode(js), 20);
  return out;
}

/** Stands in for the wasm worker: 'ok' answers like ddc_web.wasm, 'broken' cannot load it. */
function fakeWorker(mode: 'ok' | 'broken', seen: unknown[] = []) {
  return class {
    onmessage: ((e: { data: unknown }) => void) | null = null;
    onerror: (() => void) | null = null;
    postMessage(m: { type: string; id?: number; brief?: string }) {
      seen.push(m);
      const reply = (data: unknown) => setTimeout(() => this.onmessage?.({ data }), 0);
      if (m.type === 'init') reply(mode === 'ok' ? { type: 'ready' } : { type: 'failed', error: 'CompileError' });
      else reply({ type: 'result', id: m.id, result: { ok: true, glb: tinyGlb(), ms: 12.4 } });
    }
    terminate() {}
  };
}

describe('ModelPanel', () => {
  it('shows generator values with unit, range and default', async () => {
    await mount();
    expect(await screen.findByLabelText('Storeys above ground')).toHaveValue(4);
    expect(screen.getByText('1–40 storeys')).toBeInTheDocument();
    expect(screen.getByText('3–12 m · generator default: 7.2')).toBeInTheDocument();
    expect(screen.getByLabelText('Foundation')).toHaveValue('raft');
    expect(screen.getAllByText('2 per floor')).toHaveLength(2);
  });

  it('sends only changed values and links the new revision to acceptance', async () => {
    const user = await mount();
    const floors = await screen.findByLabelText('Storeys above ground');
    await user.clear(floors);
    await user.type(floors, '5');
    expect(screen.getByTestId('model-changed')).toHaveTextContent('1 values changed');
    // the job the click starts is the one the server then reports done
    api.gen = { enabled: true, reason: null, job: { job_id: 'j1', status: 'done', progress: 1, log_tail: [], revision_id: 'r9' } };
    await user.click(screen.getByRole('button', { name: 'Generate revision' }));
    await waitFor(() => expect(api.generate).toHaveBeenCalledWith('p1', 4, { '/massing/floors_above': 5 }));
    const link = await screen.findByRole('link', { name: 'Open acceptance' });
    expect(link).toHaveAttribute('href', '/design/acceptance?revision=r9');
  });

  it('a finished build refreshes the next steps beside the model, not only the revision list', async () => {
    const user = await mount();
    await screen.findByLabelText('Storeys above ground');
    const refresh = vi.spyOn(client, 'invalidateQueries');
    api.gen = { enabled: true, reason: null, job: { job_id: 'j1', status: 'done', progress: 1, log_tail: [], revision_id: 'r9' } };
    await user.click(screen.getByRole('button', { name: 'Generate revision' }));
    await screen.findByRole('link', { name: 'Open acceptance' });
    expect(refresh).toHaveBeenCalledWith({ queryKey: ['design-overview', 'p1'] });
  });

  it('keeps asking until the started job shows up, even when the first answer is the previous job', async () => {
    api.gen = { enabled: true, reason: null, job: { job_id: 'j0', status: 'done', progress: 1, log_tail: [], revision_id: 'r8' } };
    const user = await mount();
    await screen.findByLabelText('Storeys above ground');
    const fetchGeneration = vi.mocked((await import('./api')).fetchGeneration);
    const before = fetchGeneration.mock.calls.length;
    await user.click(screen.getByRole('button', { name: 'Generate revision' }));
    await waitFor(() => expect(fetchGeneration.mock.calls.length).toBeGreaterThan(before));
    expect(screen.queryByRole('link', { name: 'Open acceptance' })).toBeNull();
    api.gen = { enabled: true, reason: null, job: { job_id: 'j1', status: 'done', progress: 1, log_tail: [], revision_id: 'r9' } };
    const link = await screen.findByRole('link', { name: 'Open acceptance' }, { timeout: 5000 });
    expect(link).toHaveAttribute('href', '/design/acceptance?revision=r9');
  });

  it('refetches the brief after a refused start so the retry carries the head version', async () => {
    const user = await mount();
    const floors = await screen.findByLabelText('Storeys above ground');
    await user.clear(floors);
    await user.type(floors, '5');
    const model = api.model as { brief_version: number };
    api.generate.mockImplementationOnce(async () => {
      api.model = { ...model, brief_version: 5 }; // the server wrote version 5 before it refused
      throw new Error('503');
    });
    await user.click(screen.getByRole('button', { name: 'Generate revision' }));
    await waitFor(() => expect(api.generate).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(api.model).toMatchObject({ brief_version: 5 }));
    await user.click(screen.getByRole('button', { name: 'Generate revision' }));
    await waitFor(() => expect(api.generate).toHaveBeenLastCalledWith('p1', 5, expect.anything()));
  });

  it('applies a preset from the brief and refuses a value outside the range', async () => {
    const user = await mount();
    await user.click(await screen.findByRole('button', { name: 'One storey more' }));
    expect(screen.getByLabelText('Storeys above ground')).toHaveValue(5);
    expect(screen.getByLabelText('2-Zimmer')).toHaveValue(10);
    expect(screen.getByTestId('model-changed')).toHaveTextContent('3 values changed');
    const height = screen.getByLabelText('Storey height, m');
    await user.clear(height);
    await user.type(height, '7');
    expect(screen.getByText('Outside the generator range')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Generate revision' })).toBeDisabled();
  });

  it('refuses more dwellings on one floor than the generator places', async () => {
    const user = await mount();
    const a = await screen.findByLabelText('2-Zimmer');
    await user.clear(a);
    await user.type(a, '44');
    expect(screen.getByRole('alert')).toHaveTextContent('13 dwellings on one floor');
    expect(screen.getByRole('button', { name: 'Generate revision' })).toBeDisabled();
  });

  it('is blocked while an editor holds the project and hidden from non-managers', async () => {
    api.lock = { held_by: 'Anna', mine: false, expires_at: '2026-01-01T00:00:00Z' };
    await mount();
    expect(await screen.findByTestId('model-blocked')).toHaveTextContent('Anna');
    expect(screen.getByRole('button', { name: 'Generate revision' })).toBeDisabled();
    cleanup();
    api.lock = null;
    api.can = false;
    api.rights = { edit: 'managers', can_edit: false, can_accept: false };
    await mount();
    await waitFor(() => expect(screen.queryByTestId('model-panel')).toBeNull());
  });

  it('is there for a member with the edit right, not only for the manager', async () => {
    api.can = false;
    api.rights = { edit: 'members', can_edit: true, can_accept: false };
    await mount();
    expect(await screen.findByRole('button', { name: 'Generate revision' })).toBeInTheDocument();
    cleanup();
    api.rights = null; // a server without design rights: managers only, as before
    await mount();
    await waitFor(() => expect(api.model).not.toBeNull());
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole('button', { name: 'Generate revision' })).toBeNull();
  });

  it('stands in for the plain build only where it has nothing to offer', async () => {
    const plain = <p data-testid="plain-build">plain</p>;
    await mount('en', plain);
    expect(await screen.findByRole('button', { name: 'Generate revision' })).toBeInTheDocument();
    expect(screen.queryByTestId('plain-build')).toBeNull();
    cleanup();
    api.rights = { edit: 'managers', can_edit: false, can_accept: true };
    await mount('en', plain);
    expect(await screen.findByTestId('plain-build')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Generate revision' })).toBeNull();
    cleanup();
    api.rights = { edit: 'members', can_edit: true, can_accept: true };
    api.model = { ...view(), typology: null, params: [], units: [], presets: [] };
    await mount('en', plain);
    expect(await screen.findByTestId('plain-build')).toBeInTheDocument();
  });

  it('works as before when the browser has no Web Worker', async () => {
    vi.stubGlobal('Worker', undefined);
    const user = await mount();
    const floors = await screen.findByLabelText('Storeys above ground');
    await user.clear(floors);
    await user.type(floors, '5');
    await user.click(screen.getByRole('button', { name: 'Generate revision' }));
    await waitFor(() => expect(api.generate).toHaveBeenCalledWith('p1', 4, { '/massing/floors_above': 5 }));
    expect(screen.queryByTestId('model-preview')).toBeNull();
    expect(api.preview).not.toHaveBeenCalled();
  });

  it('works as before when the wasm does not load', async () => {
    vi.stubGlobal('Worker', fakeWorker('broken'));
    const user = await mount();
    const floors = await screen.findByLabelText('Storeys above ground');
    await waitFor(() => expect(screen.queryByTestId('model-preview')).toBeNull());
    await user.clear(floors);
    await user.type(floors, '5');
    await user.click(screen.getByRole('button', { name: 'Generate revision' }));
    await waitFor(() => expect(api.generate).toHaveBeenCalledWith('p1', 4, { '/massing/floors_above': 5 }));
    expect(api.preview).not.toHaveBeenCalled();
  });

  it('previews the changed values beside the form, labelled, with counts per class', async () => {
    const seen: { type: string; brief?: string }[] = [];
    vi.stubGlobal('Worker', fakeWorker('ok', seen));
    const user = await mount();
    const floors = await screen.findByLabelText('Storeys above ground');
    expect(await screen.findByTestId('model-preview')).toHaveTextContent('Preview — simplified; the revision is built by the generator');
    await user.clear(floors);
    await user.type(floors, '5');
    // debounced: the dry-run brief for the last value only goes to the worker
    await waitFor(() => expect(api.preview).toHaveBeenLastCalledWith('p1', 4, { '/massing/floors_above': 5 }));
    await waitFor(() => expect(screen.getByTestId('model-preview-counts')).toHaveTextContent('IfcWall 2'));
    expect(screen.getByTestId('model-preview-counts')).toHaveTextContent('IfcFooting 1');
    expect(JSON.parse(seen.filter((m) => m.type === 'gen').at(-1)!.brief!)).toEqual({ values: { '/massing/floors_above': 5 } });
    const props = api.viewer.mock.lastCall![0] as { elements: { id: string; mesh_ref: string }[]; geometryUrl: string };
    expect(props.elements.map((e) => e.mesh_ref)).toContain('b1/found/raft');
    expect(props.geometryUrl).toMatch(/^data:model\/gltf-binary;base64,/);
    // portal+readOnly: a click shows the node's own data and never asks the server for the (unregistered) preview model
    expect(api.viewer.mock.lastCall![0]).toMatchObject({ portal: true, readOnly: true });
    expect(api.generate).not.toHaveBeenCalled(); // the preview never starts a revision
  });

  it('speaks Russian', async () => {
    await mount('ru');
    expect(await screen.findByLabelText('Надземных этажей')).toHaveValue(4);
    expect(screen.getByText('Модель')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'На этаж больше' })).toBeInTheDocument();
  });
});
