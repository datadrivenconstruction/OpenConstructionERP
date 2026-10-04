// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Exporting a bill to Excel from the toolbar produced a file with no project
 * name, no classification standard, no region, no currency and no company
 * letterhead, while asking the server for the same export produced all of
 * them.
 *
 * Two separate causes, and the tests below separate them.
 *
 * The letterhead was never in the browser at all: the browser's own Excel
 * builder wrote the product name into row two and had no letterhead and no
 * logo, so the file the button produced could not have carried one however
 * the page was wired. The fix is that Excel is asked of the server, which is
 * where the one letterhead lives, and the browser builder has since been
 * deleted, so there is no second assembly of it to drift.
 *
 * The project name, standard, region and currency were absent for a different
 * reason: `doExport` closed over `project` while `project` was not in its
 * dependency list, and the project query is gated on the bill having arrived,
 * so it always resolves after the callback was last built. The PDF was the
 * last export still drawn in the browser and so the last one exposed to that;
 * it is asked of the server now too, and the PDF tests below drive it with a
 * project that arrives after mount to show the page no longer needs it.
 *
 * Reproducing the staleness needs every other dependency to be stable across
 * the project arriving, which is why the fixtures below are module-level
 * constants and why this file pins its own `t`. The shared mock in
 * src/test/setup.ts returns a fresh `t` from every `useTranslation()` call, and
 * `t` is a dependency of `doExport`, so under that mock the callback is rebuilt
 * on every render and no stale closure can survive long enough to be caught.
 *
 * Run:  npx vitest run src/features/boq/__tests__/excelExportCarriesTheLetterhead.test.tsx
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

// The `act` calls below drive state outside `render`, which needs the flag
// testing-library only sets around its own calls.
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/* ── The page's dependencies, pinned ───────────────────────────────────── */

// A stable `t`, unlike the shared mock's. See the header: `t` is a dependency
// of the callback under test, so a fresh one per render hides the defect.
vi.mock('react-i18next', () => {
  const t = (key: string, opts?: Record<string, unknown>) => {
    const fallback = opts?.defaultValue;
    return typeof fallback === 'string' ? fallback : key;
  };
  const value = { t, i18n: { language: 'en', changeLanguage: () => {} } };
  return {
    useTranslation: () => value,
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
    I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
  };
});

// AG Grid measures a box jsdom does not have, and the page hands it a ref.
vi.mock('../BOQGrid', () => ({
  __esModule: true,
  default: React.forwardRef<unknown, Record<string, unknown>>(function BOQGridStub(_props, _ref) {
    return <div data-testid="boq-grid-stub" />;
  }),
}));

vi.mock('@/features/bim/api', () => ({ fetchBIMModels: vi.fn().mockResolvedValue({ items: [] }) }));

vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/api')>();
  return { ...actual, triggerDownload: vi.fn() };
});

/* ── Fixtures, module level so their identity survives a re-render ─────── */

const BOQ_ID = 'boq-1';
const PROJECT_ID = 'proj-1';

const POSITION = {
  id: 'p1',
  boq_id: BOQ_ID,
  parent_id: null,
  ordinal: '01.001',
  description: 'Reinforced concrete wall C30/37',
  unit: 'm2',
  quantity: 10,
  unit_rate: 50,
  total: 500,
  classification: {},
  source: 'manual',
  confidence: null,
  validation_status: 'pending',
  sort_order: 0,
  metadata: {},
};

const BOQ = {
  id: BOQ_ID,
  project_id: PROJECT_ID,
  name: 'Riverside HQ Bill',
  status: 'draft',
  positions: [POSITION],
};

// No markups and no FX on purpose. Both are read by the money memos that the
// callback does depend on, and a change in either would rebuild the callback
// when the project lands and hide exactly what is being measured here.
const MARKUPS = { markups: [] };

const PROJECT = {
  id: PROJECT_ID,
  name: 'Riverside HQ',
  currency: 'EUR (€) - Euro',
  classification_standard: 'DIN 276',
  region: 'DACH (Germany, Austria, Switzerland)',
  fx_rates: [],
};

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return {
    ...actual,
    boqApi: {
      get: vi.fn(async () => BOQ),
      getMarkups: vi.fn(async () => MARKUPS),
      getCostBreakdown: vi.fn(async () => ({
        boq_id: BOQ_ID,
        grand_total: 500,
        direct_cost: 500,
        categories: [],
        markups: [],
        top_resources: [],
      })),
      getLimits: vi.fn(async () => ({ max_nesting_depth: 5 })),
      getActivity: vi.fn(async () => []),
    },
  };
});

vi.mock('@/features/projects/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/projects/api')>();
  return { ...actual, projectsApi: { ...actual.projectsApi, get: vi.fn() } };
});

import { triggerDownload } from '@/shared/lib/api';
import { projectsApi } from '@/features/projects/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { useToastStore } from '@/stores/useToastStore';
import { BOQEditorPage } from '../BOQEditorPage';

/* ── Harness ───────────────────────────────────────────────────────────── */

const SERVER_FILE = new Blob(['server workbook with the letterhead']);

let releaseProject: (() => void) | null = null;
let fetchSpy: ReturnType<typeof vi.fn>;
let client: QueryClient;

function serverExportCalls(): string[] {
  return fetchSpy.mock.calls
    .map((call) => String(call[0]))
    .filter((url) => url.includes('/export/'));
}

/** Renders the editor with the project query still in flight. */
async function renderWithProjectPending() {
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity, gcTime: Infinity } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/boq/${BOQ_ID}`]}>
        <Routes>
          <Route path="/boq/:boqId" element={<BOQEditorPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByTestId('boq-toolbar', {}, { timeout: 10_000 });
  // The bill is on screen and the project is not: this is the state the
  // callback is built in, and the state the reporter's browser was in.
  expect(client.getQueryData(['project', PROJECT_ID])).toBeUndefined();
}

/** Lets the project land, and waits until the page is showing it. */
async function letTheProjectArrive() {
  await act(async () => {
    releaseProject?.();
    await Promise.resolve();
  });
  await waitFor(() => expect(client.getQueryData(['project', PROJECT_ID])).toBeTruthy());
  // The breadcrumb, not the cache. The point of these tests is that the page
  // is holding the project and printing it where a person can see it at the
  // moment the export runs, so a failure below cannot be read as the fixture
  // simply not having arrived.
  await screen.findByRole('link', { name: PROJECT.name });
}

async function chooseExport(label: string) {
  fireEvent.click(screen.getByRole('button', { name: 'boq.export' }));
  await act(async () => {
    fireEvent.click(await screen.findByRole('menuitem', { name: label }));
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  Element.prototype.scrollIntoView = vi.fn();
  releaseProject = null;
  (projectsApi.get as ReturnType<typeof vi.fn>).mockImplementation(
    () =>
      new Promise((resolve) => {
        releaseProject = () => resolve(PROJECT);
      }),
  );
  fetchSpy = vi.fn(async () => ({
    ok: true,
    status: 200,
    blob: async () => SERVER_FILE,
    json: async () => ({}),
    text: async () => '',
    headers: new Headers(),
  }));
  vi.stubGlobal('fetch', fetchSpy);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/* ── The defect ────────────────────────────────────────────────────────── */

describe('exporting a bill of quantities to Excel', () => {
  it('asks the server for the workbook, which is where the letterhead is', async () => {
    await renderWithProjectPending();
    await letTheProjectArrive();

    await chooseExport('Excel (.xlsx)');

    await waitFor(() =>
      expect(serverExportCalls()).toContain(`/api/v1/boq/boqs/${BOQ_ID}/export/excel/`),
    );
    await waitFor(() =>
      expect(triggerDownload).toHaveBeenCalledWith(SERVER_FILE, 'Riverside HQ Bill.xlsx'),
    );
  });

  it('asks the server even when the project was loaded well before the click', async () => {
    await renderWithProjectPending();
    await letTheProjectArrive();
    // A second settled frame, so this is not the pending-project case passing
    // again under another name: the page has had the project for a while.
    await act(async () => {
      await Promise.resolve();
    });

    await chooseExport('Excel (.xlsx)');

    await waitFor(() =>
      expect(serverExportCalls()).toContain(`/api/v1/boq/boqs/${BOQ_ID}/export/excel/`),
    );
  });
});

describe('exporting a bill of quantities to PDF', () => {
  const PDF_URL = `/api/v1/boq/boqs/${BOQ_ID}/export/pdf/`;

  function pdfCall(): [string, RequestInit | undefined] | undefined {
    const call = fetchSpy.mock.calls.find((c) => String(c[0]).startsWith(PDF_URL));
    return call ? [String(call[0]), call[1] as RequestInit | undefined] : undefined;
  }

  function errorToasts(): { title: string; message?: string }[] {
    return useToastStore.getState().toasts.filter((toast) => toast.type === 'error');
  }

  beforeEach(() => {
    useToastStore.setState({ toasts: [] });
    useAuthStore.setState({ accessToken: 'token-123' });
    usePreferencesStore.setState({ measurementSystem: 'metric' });
  });

  afterEach(() => {
    useAuthStore.setState({ accessToken: null });
    usePreferencesStore.setState({ measurementSystem: 'metric' });
  });

  it('downloads the server PDF with the token, never drawing one in the browser', async () => {
    await renderWithProjectPending();
    await letTheProjectArrive();

    await chooseExport('PDF');

    await waitFor(() => expect(pdfCall()).toBeDefined());
    const [url, init] = pdfCall()!;
    const query = new URL(url, 'http://test').searchParams;
    // The reader's measurement system, and the resources under each line,
    // as the browser PDF printed them.
    expect(query.get('measurement_system')).toBe('metric');
    expect(query.get('include_resources')).toBe('true');
    expect(init?.headers).toEqual({ Authorization: 'Bearer token-123' });
    await waitFor(() =>
      expect(triggerDownload).toHaveBeenCalledWith(SERVER_FILE, 'Riverside HQ Bill.pdf'),
    );
    expect(errorToasts()).toEqual([]);
  });

  it('does not wait for the project: the server reads it for itself', async () => {
    await renderWithProjectPending();

    await chooseExport('PDF');

    await waitFor(() => expect(pdfCall()).toBeDefined());
    await waitFor(() => expect(triggerDownload).toHaveBeenCalledWith(SERVER_FILE, 'Riverside HQ Bill.pdf'));
  });

  it('asks for imperial quantities when the reader works in imperial', async () => {
    usePreferencesStore.setState({ measurementSystem: 'imperial' });
    await renderWithProjectPending();
    await letTheProjectArrive();

    await chooseExport('PDF');

    await waitFor(() => expect(pdfCall()).toBeDefined());
    expect(new URL(pdfCall()![0], 'http://test').searchParams.get('measurement_system')).toBe('imperial');
  });

  it('shows the server reason when the PDF cannot be built, and downloads nothing', async () => {
    const reason = 'PDF generation failed. The BOQ may be too large or contain invalid data.';
    fetchSpy.mockImplementation(async () => ({
      ok: false,
      status: 500,
      blob: async () => new Blob([]),
      json: async () => ({ detail: reason }),
      text: async () => '',
      headers: new Headers(),
    }));
    await renderWithProjectPending();

    await chooseExport('PDF');

    await waitFor(() => expect(errorToasts().map((toast) => toast.title)).toContain(reason));
    expect(triggerDownload).not.toHaveBeenCalled();
  });

  it('does not show a validation error list as the title', async () => {
    fetchSpy.mockImplementation(async () => ({
      ok: false,
      status: 422,
      blob: async () => new Blob([]),
      json: async () => ({ detail: [{ loc: ['query', 'measurement_system'], msg: 'bad' }] }),
      text: async () => '',
      headers: new Headers(),
    }));
    await renderWithProjectPending();

    await chooseExport('PDF');

    await waitFor(() => expect(errorToasts().map((toast) => toast.title)).toContain('Export failed'));
  });

  it('says the server could not be reached when there is no response at all', async () => {
    fetchSpy.mockImplementation(async () => {
      throw new TypeError('Failed to fetch');
    });
    await renderWithProjectPending();

    await chooseExport('PDF');

    await waitFor(() => expect(errorToasts()).toHaveLength(1));
    expect(errorToasts()[0]).toMatchObject({
      title: 'Export failed',
      message: 'The server could not be reached. Check your connection and try again.',
    });
    expect(triggerDownload).not.toHaveBeenCalled();
  });
});
