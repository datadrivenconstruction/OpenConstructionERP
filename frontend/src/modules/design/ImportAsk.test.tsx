import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN } from './testStrings';

const state = vi.hoisted(() => ({
  enabled: true,
  canEdit: true,
  jobs: new Map<string, unknown>(),
  imported: [] as unknown[],
  added: [] as string[],
}));

vi.mock('react-i18next', async () => await vi.importActual('react-i18next'));
vi.mock('@/stores/useModuleStore', () => ({
  useModuleStore: (sel: (s: unknown) => unknown) => sel({ enabledModules: { design: state.enabled } }),
}));
vi.mock('@/stores/useBIMUploadStore', () => ({
  useBIMUploadStore: (sel: (s: unknown) => unknown) => sel({ jobs: state.jobs }),
}));
vi.mock('./api', () => ({
  fetchImportedModels: vi.fn(async () => state.imported),
  importModel: vi.fn(async (_p: string, id: string) => { state.added.push(id); return {}; }),
}));
vi.mock('./draftApi', () => ({
  fetchRights: vi.fn(async () => ({ edit: 'members', can_edit: state.canEdit, can_accept: false })),
}));

import { ImportAsk } from './ImportAsk';

const job = (status: string) => ({ id: 'j1', projectId: 'p1', status, modelId: status === 'ready' ? 'm1' : null });
const model = { bim_model_id: 'm1', name: 'House', model_format: 'ifc', element_count: 5, created_at: null };

function mount() {
  const i = i18n.createInstance();
  void i.use(initReactI18next).init({ lng: 'en', resources: { en: { translation: EN } }, interpolation: { escapeValue: false } });
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nextProvider i18n={i}><MemoryRouter><ImportAsk projectId="p1" /></MemoryRouter></I18nextProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  cleanup();
  state.enabled = true; state.canEdit = true; state.imported = [model]; state.added = [];
  state.jobs = new Map([['j1', job('ready')]]);
});

describe('ImportAsk', () => {
  it('asks once the upload is ready and wraps only on the click', async () => {
    mount();
    await screen.findByText(EN['design.import_ask.question']!);
    expect(state.added).toEqual([]);
    await userEvent.click(screen.getByRole('button', { name: EN['design.import_ask.yes']! }));
    await screen.findByTestId('import-ask-done');
    expect(state.added).toEqual(['m1']);
  });

  it('dismiss wraps nothing', async () => {
    mount();
    await userEvent.click(await screen.findByRole('button', { name: EN['design.import_ask.no']! }));
    await waitFor(() => expect(screen.queryByTestId('import-ask')).toBeNull());
    expect(state.added).toEqual([]);
  });

  it('does not ask while converting', async () => {
    state.jobs = new Map([['j1', job('converting')]]);
    mount();
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByTestId('import-ask')).toBeNull();
  });

  it('does not ask without design rights, with the module off, or for a model that cannot be wrapped', async () => {
    state.canEdit = false;
    mount();
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByTestId('import-ask')).toBeNull();
    cleanup(); state.canEdit = true; state.enabled = false;
    mount();
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByTestId('import-ask')).toBeNull();
    cleanup(); state.enabled = true; state.imported = [];
    mount();
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByTestId('import-ask')).toBeNull();
  });
});
