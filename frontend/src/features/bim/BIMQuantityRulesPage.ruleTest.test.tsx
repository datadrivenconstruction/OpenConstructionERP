// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "Test this rule" in the rule editor runs the unsaved rule on the server
// (the apply engine as a dry run) and shows what came back. Pins the states a
// person sees: busy while it runs, a plain answer when nothing matched, the
// reason a short result may be the model's fault rather than the filter's,
// and our own sentence when the test fails, never the server's.

import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const mocks = vi.hoisted(() => ({
  listQuantityMaps: vi.fn(),
  fetchBIMModels: vi.fn(),
  fetchBIMElements: vi.fn(),
  fetchSmartViewProperties: vi.fn(),
  fetchBIMDataframeSchema: vi.fn(),
  previewQuantityRule: vi.fn(),
  boqList: vi.fn(),
  boqGet: vi.fn(),
  fetchProjectList: vi.fn(),
  apiGet: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      let d = typeof opts?.defaultValue === 'string' ? opts.defaultValue : key;
      for (const [k, v] of Object.entries(opts ?? {})) d = d.replace(`{{${k}}}`, String(v));
      return d;
    },
    i18n: { language: 'en' },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api')>()),
  listQuantityMaps: (...a: unknown[]) => mocks.listQuantityMaps(...a),
  fetchBIMModels: (...a: unknown[]) => mocks.fetchBIMModels(...a),
  fetchBIMElements: (...a: unknown[]) => mocks.fetchBIMElements(...a),
  fetchSmartViewProperties: (...a: unknown[]) => mocks.fetchSmartViewProperties(...a),
  fetchBIMDataframeSchema: (...a: unknown[]) => mocks.fetchBIMDataframeSchema(...a),
  previewQuantityRule: (...a: unknown[]) => mocks.previewQuantityRule(...a),
}));

vi.mock('@/shared/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/shared/lib/api')>()),
  apiGet: (...a: unknown[]) => mocks.apiGet(...a),
}));

vi.mock('@/features/boq/api', () => ({
  boqApi: { list: (...a: unknown[]) => mocks.boqList(...a), get: (...a: unknown[]) => mocks.boqGet(...a) },
}));

vi.mock('@/shared/lib/projectList', () => ({
  fetchProjectList: (...a: unknown[]) => mocks.fetchProjectList(...a),
}));

vi.mock('@/features/bim_requirements/RulePackLibrary', () => ({
  RulePackLibrary: () => <div data-testid="rule-pack-library" />,
}));
vi.mock('./BIMRequirementsImport', () => ({ default: () => <div data-testid="bim-requirements-import" /> }));

import { BIMQuantityRulesPage } from './BIMQuantityRulesPage';
import type { SandboxRunResult } from './ruleSandbox';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

const PREFILL =
  '/bim/rules?project_id=p-1&model_id=m-2&boq_id=b-2&new=1&element_type=Walls' +
  '&prop_key=Phase%20Created&prop_value=Progetto&qty_source=Area&unit=m%C2%B2';

function renderEditor() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[PREFILL]}>
        <Routes>
          <Route path="/bim/rules" element={<BIMQuantityRulesPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function result(overrides: Partial<SandboxRunResult> = {}): SandboxRunResult {
  return {
    matches: [],
    skips: [],
    matchCount: 0,
    skipCount: 0,
    matchedTypes: [],
    totalAdjusted: 0,
    scanned: 7,
    sidecar: 'full',
    ...overrides,
  };
}

async function runTest() {
  await screen.findByRole('dialog');
  fireEvent.click(await screen.findByTestId('rule-test-run'));
}

beforeEach(() => {
  useProjectContextStore.setState({ activeProjectId: 'p-1', activeProjectName: 'Villa' });
  mocks.listQuantityMaps.mockResolvedValue({ items: [], total: 0 });
  mocks.fetchBIMModels.mockResolvedValue({
    items: [
      { id: 'm-1', name: 'Structure', status: 'ready' },
      { id: 'm-2', name: 'Restauro', status: 'ready' },
    ],
    total: 2,
  });
  mocks.fetchBIMElements.mockResolvedValue({ items: [], total: 0 });
  mocks.fetchSmartViewProperties.mockResolvedValue({ model_id: 'm-2', source_format: 'RVT', element_count: 0, entries: [] });
  mocks.fetchBIMDataframeSchema.mockRejectedValue(new Error('Dataframe schema fetch failed (HTTP 404)'));
  mocks.boqList.mockResolvedValue([{ id: 'b-2', name: 'Computo', is_locked: false }]);
  mocks.boqGet.mockResolvedValue({ id: 'b-2', positions: [] });
  mocks.fetchProjectList.mockResolvedValue([{ id: 'p-1', name: 'Villa' }]);
  mocks.apiGet.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('Test this rule', () => {
  it('sends the unsaved rule to the server for the chosen model and says it is running', async () => {
    let finish: (r: SandboxRunResult) => void = () => {};
    mocks.previewQuantityRule.mockReturnValue(new Promise<SandboxRunResult>((resolve) => (finish = resolve)));
    renderEditor();
    await runTest();

    expect(await screen.findByTestId('rule-test-running')).toBeTruthy();
    expect((screen.getByTestId('rule-test-run') as HTMLButtonElement).disabled).toBe(true);
    expect(mocks.previewQuantityRule).toHaveBeenCalledWith(
      'm-2',
      expect.objectContaining({
        element_type_filter: 'Walls',
        property_filter: { 'Phase Created': 'Progetto' },
        quantity_source: 'Area',
      }),
    );

    finish(result({ matchCount: 3, matches: [], totalAdjusted: 30 }));
    await waitFor(() => expect(screen.queryByTestId('rule-test-running')).toBeNull());
    expect((screen.getByTestId('rule-test-run') as HTMLButtonElement).disabled).toBe(false);
  });

  it('says in plain words that nothing matched and what to try', async () => {
    mocks.previewQuantityRule.mockResolvedValue(result());
    renderEditor();
    await runTest();

    const empty = await screen.findByTestId('rule-test-no-match');
    expect(empty.textContent).toBe('No elements matched in the 7 scanned. Loosen the element type or property filter.');
    expect(screen.queryByTestId('rule-test-capped-properties')).toBeNull();
  });

  it('says a re-import brings the properties back when the model lost them', async () => {
    mocks.previewQuantityRule.mockResolvedValue(result({ sidecar: 'rebuilt' }));
    renderEditor();
    await runTest();

    await screen.findByTestId('rule-test-no-match');
    expect(screen.getByTestId('rule-test-capped-properties').textContent).toContain('Re-import the model');
  });

  it('counts every match the server found, not just the rows it listed', async () => {
    const row = { element_id: 'e1', stable_id: 's1', element_type: 'Walls', name: 'Muro', raw_quantity: 10, adjusted_quantity: 10 };
    mocks.previewQuantityRule.mockResolvedValue(
      result({ matches: [row, { ...row, element_id: 'e2' }], matchCount: 640, totalAdjusted: 6400 }),
    );
    renderEditor();
    await runTest();

    expect((await screen.findByTestId('rule-test-matched')).textContent).toBe('640 matched');
  });

  it('shows its own sentence when the test fails, not the server message', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mocks.previewQuantityRule.mockRejectedValue(new Error('Model not found'));
    renderEditor();
    await runTest();

    const error = await screen.findByTestId('rule-test-error');
    expect(error.textContent).toBe('The test could not run. Check that you can open this model, then try again.');
    expect(screen.queryByTestId('rule-test-running')).toBeNull();
    warn.mockRestore();
  });
});
