// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Quantity Rules page opened with context: from the 3D viewer's right-click
// "Create quantity rule" (a new rule pre-filled from the element), from the
// BIM page header and from the BOQ editor (project, model and BOQ preselected).
// Also the rule editor's property pickers, fed by the model's property catalog:
// the tester could not tell which property names the model carries.

import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

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
import { useProjectContextStore } from '@/stores/useProjectContextStore';

const CATALOG = {
  model_id: 'm-2',
  source_format: 'RVT',
  element_count: 3,
  entries: [
    { field: 'element_type', label: 'element type', group: 'identity', data_type: 'enum', source_formats: [], sample_values: ['Walls'], distinct_count: 1, truncated: false },
    { field: 'properties.Phase Created', label: 'Phase Created', group: 'properties', data_type: 'enum', source_formats: [], sample_values: ['Existing', 'New Construction'], distinct_count: 2, truncated: false },
    { field: 'properties.Pset_WallCommon.FireRating', label: 'FireRating', group: 'properties', data_type: 'enum', source_formats: [], sample_values: ['REI 60'], distinct_count: 1, truncated: false },
    { field: 'properties.layers', label: 'layers', group: 'properties', data_type: 'enum', source_formats: [], sample_values: ['<complex>'], distinct_count: 1, truncated: false },
    { field: 'quantities.Area', label: 'Area', group: 'quantities', data_type: 'number', source_formats: [], sample_values: ['12.5'], distinct_count: 1, truncated: false },
  ],
};

let lastLocation = '';
function LocationProbe() {
  const loc = useLocation();
  lastLocation = `${loc.pathname}${loc.search}`;
  return null;
}

function renderAt(url: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/bim/rules" element={<><BIMQuantityRulesPage /><LocationProbe /></>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  lastLocation = '';
  useProjectContextStore.setState({ activeProjectId: 'p-1', activeProjectName: 'Villa' });
  mocks.listQuantityMaps.mockResolvedValue({ items: [], total: 0 });
  mocks.fetchBIMModels.mockResolvedValue({
    items: [
      { id: 'm-1', name: 'Structure', status: 'ready' },
      { id: 'm-2', name: 'Architecture', status: 'ready' },
    ],
    total: 2,
  });
  mocks.fetchBIMElements.mockResolvedValue({ items: [], total: 0 });
  mocks.fetchSmartViewProperties.mockResolvedValue(CATALOG);
  mocks.boqList.mockResolvedValue([
    { id: 'b-1', name: 'Shell', is_locked: false },
    { id: 'b-2', name: 'Finishes', is_locked: false },
  ]);
  mocks.boqGet.mockResolvedValue({ id: 'b-2', positions: [] });
  mocks.fetchProjectList.mockResolvedValue([{ id: 'p-1', name: 'Villa' }, { id: 'p-2', name: 'Palazzo' }]);
  mocks.apiGet.mockResolvedValue([]);
  // No dataframe sidecar unless a test gives one: keys show alone.
  mocks.fetchBIMDataframeSchema.mockRejectedValue(new Error('Dataframe schema fetch failed (HTTP 404)'));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const PREFILL =
  '/bim/rules?project_id=p-1&model_id=m-2&boq_id=b-2&new=1&element_type=Walls' +
  '&prop_key=Phase%20Created&prop_value=New%20Construction&qty_source=Area&unit=m%C2%B2';

describe('BIMQuantityRulesPage opened with context', () => {
  it('opens the editor with a new rule pre-filled from the URL', async () => {
    renderAt(PREFILL);
    const dialog = await screen.findByRole('dialog');
    expect((dialog.querySelector('#rule-element-type') as HTMLInputElement).value).toBe('Walls');
    expect((dialog.querySelector('#rule-name') as HTMLInputElement).value).toBe('Walls - quantity');
    expect((dialog.querySelector('#rule-qsrc') as HTMLSelectElement).value).toBe('custom');
    expect((dialog.querySelector('#rule-custom-src') as HTMLInputElement).value).toBe('Area');
    expect((dialog.querySelector('#rule-unit') as HTMLInputElement).value).toBe('m²');
    const keyInput = screen.getByTestId('rule-prop-key-0') as HTMLInputElement;
    const valueInput = screen.getByTestId('rule-prop-value-0') as HTMLInputElement;
    expect(keyInput.value).toBe('Phase Created');
    expect(valueInput.value).toBe('New Construction');
  });

  it('preselects the model and the BOQ, and lands on quantity rules, not requirements', async () => {
    renderAt('/bim/rules?project_id=p-1&model_id=m-2&boq_id=b-2');
    await waitFor(() => expect((document.getElementById('model-picker') as HTMLSelectElement).value).toBe('m-2'));
    await waitFor(() => expect((document.getElementById('apply-boq-picker') as HTMLSelectElement).value).toBe('b-2'));
    expect(screen.queryByRole('dialog')).toBeNull();
    // "New rule" lives only on the Quantity Rules tab.
    expect(screen.getByRole('button', { name: 'New rule' })).toBeTruthy();
    expect(screen.queryByText('BIM Rules (Compliance)')).toBeNull();
  });

  it('strips the hand-over parameters so a refresh does not reopen the editor', async () => {
    renderAt(PREFILL);
    await screen.findByRole('dialog');
    await waitFor(() => expect(lastLocation).toBe('/bim/rules'));
  });

  it('switches the active project to the one the link names', async () => {
    renderAt('/bim/rules?project_id=p-2');
    await waitFor(() => expect(useProjectContextStore.getState().activeProjectId).toBe('p-2'));
    expect(useProjectContextStore.getState().activeProjectName).toBe('Palazzo');
  });

  it('falls back to the first model when the link names one the project does not have', async () => {
    renderAt('/bim/rules?model_id=m-gone');
    await waitFor(() => expect((document.getElementById('model-picker') as HTMLSelectElement).value).toBe('m-1'));
  });
});

describe('the rule editor property pickers', () => {
  // Rule values are patterns: * and ? match any text, on the server and in
  // the preview alike, and there is no escape for them. A value the model
  // really carries with a * or ? in it is offered as is, so the editor says
  // what it will do rather than let the rule pick more than the user meant.
  it('warns when a value picked from the model contains * or ?', async () => {
    mocks.fetchSmartViewProperties.mockResolvedValue({
      ...CATALOG,
      entries: CATALOG.entries.map((e) =>
        e.field === 'properties.Phase Created' ? { ...e, sample_values: ['Existing', 'Phase 2*'] } : e,
      ),
    });
    renderAt(PREFILL);
    await screen.findByRole('dialog');
    const valueInput = screen.getByTestId('rule-prop-value-0') as HTMLInputElement;
    await waitFor(() =>
      expect(document.getElementById(valueInput.getAttribute('list') ?? '')?.querySelectorAll('option').length).toBe(2),
    );
    expect(screen.queryByTestId('rule-prop-wildcard-hint-0')).toBeNull();

    fireEvent.change(valueInput, { target: { value: 'Phase 2*' } });
    expect(screen.getByTestId('rule-prop-wildcard-hint-0').textContent).toContain('match any text');

    // Typed on purpose, not offered by the model: a wildcard the user meant.
    fireEvent.change(valueInput, { target: { value: 'Phase*' } });
    expect(screen.queryByTestId('rule-prop-wildcard-hint-0')).toBeNull();
  });

  it('suggests the model property names and the values seen for the chosen one', async () => {
    renderAt(PREFILL);
    await screen.findByRole('dialog');
    const keyInput = screen.getByTestId('rule-prop-key-0') as HTMLInputElement;
    await waitFor(() => {
      const list = document.getElementById(keyInput.getAttribute('list') ?? '');
      expect(list).not.toBeNull();
      const keys = Array.from(list!.querySelectorAll('option')).map((o) => o.getAttribute('value'));
      // Original names, prefix cut by length (dots inside a name survive);
      // nested-only properties and identity fields are not offered.
      expect(keys).toEqual(['Phase Created', 'Pset_WallCommon.FireRating']);
    });
    expect(mocks.fetchSmartViewProperties).toHaveBeenCalledWith('m-2');

    const valueInput = screen.getByTestId('rule-prop-value-0') as HTMLInputElement;
    const values = () =>
      Array.from(document.getElementById(valueInput.getAttribute('list') ?? '')?.querySelectorAll('option') ?? []).map(
        (o) => o.getAttribute('value'),
      );
    expect(values()).toEqual(['Existing', 'New Construction']);

    // Free typing still allowed, and the value list follows the key.
    fireEvent.change(keyInput, { target: { value: 'Pset_WallCommon.FireRating' } });
    expect((screen.getByTestId('rule-prop-key-0') as HTMLInputElement).value).toBe('Pset_WallCommon.FireRating');
    expect(values()).toEqual(['REI 60']);
    fireEvent.change(keyInput, { target: { value: 'Not In Model' } });
    expect((screen.getByTestId('rule-prop-key-0') as HTMLInputElement).value).toBe('Not In Model');
    expect(values()).toEqual([]);
  });

  it('shows the header the model was exported with beside a DDC lowercase key', async () => {
    mocks.fetchSmartViewProperties.mockResolvedValue({
      ...CATALOG,
      entries: [
        { field: 'properties.phase created', label: 'phase created', group: 'properties', data_type: 'enum', source_formats: [], sample_values: ['Existing'], distinct_count: 1, truncated: false },
        { field: 'properties.mark', label: 'mark', group: 'properties', data_type: 'string', source_formats: [], sample_values: ['W1'], distinct_count: 1, truncated: false },
      ],
    });
    mocks.fetchBIMDataframeSchema.mockResolvedValue([
      { name: 'phase created', type: 'string', label: 'Phase Created' },
      { name: 'mark', type: 'string' },
    ]);
    renderAt(PREFILL);
    await screen.findByRole('dialog');
    const keyInput = screen.getByTestId('rule-prop-key-0') as HTMLInputElement;
    await waitFor(() => {
      const options = Array.from(document.getElementById(keyInput.getAttribute('list') ?? '')?.querySelectorAll('option') ?? []);
      // The key the rule saves stays the value; the header is its label, the
      // same one the property search shows. A key with no stored header has
      // no separate label.
      expect(options.map((o) => [o.getAttribute('value'), o.getAttribute('label')])).toEqual([
        ['mark', null],
        ['phase created', 'Phase Created'],
      ]);
    });
    expect(mocks.fetchBIMDataframeSchema).toHaveBeenCalledWith('m-2', expect.anything());
  });

  it('keeps focus in the key field while typing (the row is not remounted)', async () => {
    renderAt(PREFILL);
    await screen.findByRole('dialog');
    const keyInput = screen.getByTestId('rule-prop-key-0') as HTMLInputElement;
    keyInput.focus();
    fireEvent.change(keyInput, { target: { value: 'Phase' } });
    expect(screen.getByTestId('rule-prop-key-0')).toBe(keyInput);
  });
});

// The page draws data from three modules: quantity rules (BIM Hub), the
// requirements (oe_requirements) and the IDS/COBie import plus the Rule Library
// (oe_bim_requirements). No tab or block may call an API whose module is off.
const modulesOff = (...names: string[]) =>
  mocks.apiGet.mockImplementation((path: string) =>
    Promise.resolve(path === '/v1/modules/' ? names.map((name) => ({ name, enabled: false, is_core: false })) : []),
  );
const reqTab = () => screen.queryByRole('button', { name: 'Requirements' });
const libraryTab = () => screen.queryByTestId('bim-rules-tab-rule-library');
const importBlock = () => screen.queryByTestId('bim-requirements-import');

describe('the page with both requirement modules on', () => {
  it('shows all three tabs and the import block on the requirements tab', async () => {
    renderAt('/bim/rules?tab=requirements');
    await waitFor(() => expect(importBlock()).toBeTruthy());
    expect(reqTab()).toBeTruthy();
    expect(libraryTab()).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Quantity Rules' })).toBeTruthy();
  });
});

describe('the page with oe_requirements off', () => {
  beforeEach(() => modulesOff('oe_requirements'));

  it('drops the requirements tab and keeps the rule library', async () => {
    renderAt('/bim/rules?tab=requirements');
    await waitFor(() => expect(reqTab()).toBeNull());
    expect(libraryTab()).toBeTruthy();
    expect(importBlock()).toBeNull();
    await waitFor(() => expect(lastLocation).toBe('/bim/rules'));
    expect(screen.getByRole('button', { name: 'New rule' })).toBeTruthy();
  });

  it('answers the compliance link with the rule library', async () => {
    renderAt('/bim/rules?mode=requirements');
    await waitFor(() => expect(reqTab()).toBeNull());
    expect(screen.getByTestId('rule-pack-library')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Quantity Rules' })).toBeNull();
    expect(importBlock()).toBeNull();
  });
});

describe('the page with oe_bim_requirements off', () => {
  beforeEach(() => modulesOff('oe_bim_requirements'));

  it('keeps the requirements tab without the import block, and drops the rule library', async () => {
    renderAt('/bim/rules?tab=requirements');
    await waitFor(() => expect(libraryTab()).toBeNull());
    expect(reqTab()).toBeTruthy();
    expect(importBlock()).toBeNull();
    expect(lastLocation).toBe('/bim/rules?tab=requirements');
  });

  it('moves a rule library link to a tab that exists', async () => {
    renderAt('/bim/rules?mode=requirements&tab=rule_library');
    await waitFor(() => expect(lastLocation).toBe('/bim/rules?mode=requirements'));
    expect(screen.queryByTestId('rule-pack-library')).toBeNull();
    expect(reqTab()).toBeTruthy();
  });
});

describe('the page with both requirement modules off', () => {
  beforeEach(() => modulesOff('oe_requirements', 'oe_bim_requirements'));

  it('keeps the quantity rules and drops the requirements and rule library tabs', async () => {
    renderAt('/bim/rules');
    await waitFor(() => expect(libraryTab()).toBeNull());
    expect(screen.getByRole('button', { name: 'New rule' })).toBeTruthy();
    expect(reqTab()).toBeNull();
  });

  it('answers the compliance link with the quantity rules rather than a dead tab', async () => {
    renderAt('/bim/rules?mode=requirements');
    await waitFor(() => expect(screen.getByRole('button', { name: 'New rule' })).toBeTruthy());
    expect(screen.queryByText('BIM Rules (Compliance)')).toBeNull();
    expect(importBlock()).toBeNull();
  });

  it('drops the compliance mode and tab from the URL, so the top bar names the quantity rules too', async () => {
    renderAt('/bim/rules?mode=requirements&tab=rule_library');
    await waitFor(() => expect(lastLocation).toBe('/bim/rules'));
  });
});

describe('the breadcrumb', () => {
  it('names the quantity rules on the quantity tab', async () => {
    renderAt('/bim/rules');
    const crumbs = await screen.findByRole('navigation', { name: 'Breadcrumb' });
    expect(crumbs.textContent).toContain('Quantity Rules');
    expect(crumbs.textContent).not.toContain('BIM Rules');
  });

  it('keeps BIM Rules on the compliance half', async () => {
    renderAt('/bim/rules?mode=requirements');
    const crumbs = await screen.findByRole('navigation', { name: 'Breadcrumb' });
    await waitFor(() => expect(crumbs.textContent).toContain('BIM Rules'));
  });
});

describe('the tab bar', () => {
  it('writes the tab into the URL, so the top bar, the crumb and the tab agree', async () => {
    renderAt('/bim/rules');
    fireEvent.click(await screen.findByRole('button', { name: 'Requirements' }));
    await waitFor(() => expect(lastLocation).toBe('/bim/rules?tab=requirements'));
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(crumbs.textContent).toContain('BIM Rules');
    expect(screen.queryByRole('button', { name: 'New rule' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Quantity Rules' }));
    await waitFor(() => expect(lastLocation).toBe('/bim/rules'));
    expect(screen.getByRole('button', { name: 'New rule' })).toBeTruthy();
  });

  it('does not lock the page on the requirements half (all three tabs stay)', async () => {
    renderAt('/bim/rules?tab=requirements');
    await screen.findByRole('button', { name: 'Requirements' });
    expect(screen.getByRole('button', { name: 'Quantity Rules' })).toBeTruthy();
    expect(screen.getByTestId('bim-rules-tab-rule-library')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'New rule' })).toBeNull();
  });
});
