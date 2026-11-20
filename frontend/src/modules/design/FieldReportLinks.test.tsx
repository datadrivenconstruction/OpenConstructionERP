import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN } from './testStrings';
import type { FieldReportRow, ReportElements } from './linksApi';

const h = vi.hoisted(() => ({
  hits: [] as unknown[], all: [] as unknown[], elements: null as unknown, put: vi.fn(), hitFails: false,
}));

vi.mock('react-i18next', async () => await vi.importActual('react-i18next'));
vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path.includes('/elements')) return h.elements;
    if (path.includes('keys=')) {
      if (h.hitFails) throw new Error('boom');
      return { items: h.hits };
    }
    return { items: h.all };
  }),
  apiPut: vi.fn(async (...a: unknown[]) => h.put(...a)),
  apiPost: vi.fn(),
  getErrorMessage: (e: unknown) => String(e),
}));
vi.mock('./api', () => ({ LINK_VERSION: '1' }));

import { FieldReportLinks } from './FieldReportLinks';

const ROW = (over: Partial<FieldReportRow> = {}): FieldReportRow => ({
  id: 'r1', report_date: '2027-03-04', report_type: 'daily', status: 'draft', excerpt: 'Wall poured',
  keys: ['k1'], position_ids: ['pos1'], revision_id: 'rev1', ...over,
});

function Where() {
  const l = useLocation();
  return <p data-testid="where">{l.pathname}{l.search}</p>;
}

async function mount(keys = ['k2']) {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({
    lng: 'en', resources: { en: { translation: EN } }, keySeparator: false, nsSeparator: false,
    interpolation: { escapeValue: false },
  });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nextProvider i18n={inst}>
        <MemoryRouter initialEntries={['/design/editor']}>
          <Routes><Route path="*" element={<><FieldReportLinks projectId="p1" keys={keys} /><Where /></>} /></Routes>
        </MemoryRouter>
      </I18nextProvider>
    </QueryClientProvider>,
  );
  return user;
}

beforeEach(() => {
  cleanup();
  h.hits = []; h.all = []; h.hitFails = false; h.put.mockReset(); h.put.mockResolvedValue(ROW());
  h.elements = { report_id: 'r1', model_id: 'm1', keys: ['k1'], element_ids: ['e1', 'e2'], isolate: ['e1', 'e2'], positions: [] } as ReportElements;
});

describe('FieldReportLinks', () => {
  it('lists the reports of the selection and jumps from a report to its elements', async () => {
    h.hits = [ROW()];
    const user = await mount();
    expect(await screen.findByTestId('report-r1')).toBeTruthy();
    await user.click(screen.getByTestId('report-model-r1'));
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/projects/p1/bim/m1?isolate=e1,e2'));
  });

  it('selects the report elements in the editor', async () => {
    h.hits = [ROW()];
    const user = await mount();
    await user.click(await screen.findByTestId('report-editor-r1'));
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/design/editor?select=k1'));
  });

  it('says so when a report points at no element', async () => {
    h.hits = [ROW()];
    h.elements = { report_id: 'r1', model_id: 'm1', keys: [], element_ids: [], isolate: null, positions: [] };
    const user = await mount();
    await user.click(await screen.findByTestId('report-model-r1'));
    expect((await screen.findByRole('alert')).textContent).toContain('no element');
  });

  it('links a chosen report to the selection only after the person confirms, keeping what it already names', async () => {
    h.all = [ROW({ id: 'r1', keys: ['k1'] }), ROW({ id: 'r2', status: 'approved', keys: [] }), ROW({ id: 'r3', keys: ['k2'] })];
    const user = await mount(['k2']);
    await user.click(await screen.findByTestId('report-link-open'));
    const pick = (await screen.findByTestId('report-pick')) as HTMLSelectElement;
    await waitFor(() => expect(pick.options.length).toBe(2)); // placeholder + r1; approved and already-linked ones are not offered
    expect(h.put).not.toHaveBeenCalled();
    await user.selectOptions(pick, 'r1');
    await user.click(screen.getByTestId('report-confirm'));
    await waitFor(() => expect(h.put).toHaveBeenCalled());
    const [path, body] = h.put.mock.calls[0]!;
    expect(path).toBe('/v1/design/projects/p1/field-reports/r1/links');
    expect(body).toEqual({ keys: ['k1', 'k2'], position_ids: ['pos1'] });
  });

  it('shows nothing when the lookup fails', async () => {
    h.hitFails = true;
    await mount();
    await waitFor(() => expect(screen.queryByTestId('field-report-links')).toBeNull());
  });
});
