// @ts-nocheck
/**
 * RegionalExchangePage — Wave 5 Epic I.
 *
 * The polymorphic page renders one of 20 country packs from the registry.
 * These tests cover:
 *   1. Registry-pickup — the Spanish template renders the flag, the
 *      native label, the BC3 format hint, and a downloadable sample.
 *   2. Per-country differentiation — switching `template` to the US
 *      MasterFormat pack flips the header without re-mounting the
 *      whole page tree, and the validator-pack list reflects the new
 *      country.
 *   3. Back-compat slug lookup — `/modules/es-pbc-exchange` resolves
 *      to the same registry entry (deep-link compat shim).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

// Stub the read side of the API layer — the project and BOQ pickers would
// otherwise leave React Query hanging on a real fetch promise. The import
// itself is NOT routed through this mock: it posts multipart through raw
// `fetch`, and the tests below assert on that request directly. Stubbing the
// api helper there would only re-prove that the helper was called.
vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/api')>();
  return {
    ...actual,
    apiGet: vi.fn(async () => []),
    triggerDownload: vi.fn(),
  };
});

// Toast store would otherwise touch zustand internals during the
// import-success path. Mocking it keeps the test side-effect free.
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: () => vi.fn(),
}));

import { apiGet } from '@/shared/lib/api';
import RegionalExchangePage from './RegionalExchangePage';
import {
  COUNTRY_TEMPLATES,
  getRegionalTemplate,
  getRegionalTemplateBySlug,
} from './regionalRegistry';

function renderWithProviders(template: ReturnType<typeof getRegionalTemplate>) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/${template!.routeSlug}`]}>
        <RegionalExchangePage template={template!} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('RegionalExchangePage - registry pickup', () => {
  it('renders the Spanish PBC template with flag, native label, and BC3 hint', () => {
    const es = getRegionalTemplate('es-pbc');
    expect(es).toBeDefined();

    renderWithProviders(es);

    // Header label is the native template label
    expect(screen.getByTestId('regional-label').textContent).toMatch(
      /Spanish PBC/i,
    );
    // Flag is rendered (the emoji shows up as text content)
    expect(screen.getByTestId('regional-flag').textContent).toContain('🇪🇸');
    // Format hint mentions BC3 (the Spanish native format)
    expect(screen.getByTestId('regional-format-hint').textContent).toMatch(/BC3/i);
    // Sample-file link points to the design-mandated BC3 sample
    const sampleLink = screen.getByTestId('regional-sample-link');
    expect(sampleLink.getAttribute('href')).toBe('/templates/es-pbc-sample.bc3');
  });

  it('renders the US MasterFormat template with the US flag and MasterFormat hint', () => {
    const us = getRegionalTemplate('us-masterformat');
    expect(us).toBeDefined();

    renderWithProviders(us);

    expect(screen.getByTestId('regional-label').textContent).toMatch(/MasterFormat/i);
    expect(screen.getByTestId('regional-flag').textContent).toContain('🇺🇸');
    expect(screen.getByTestId('regional-format-hint').textContent).toMatch(/MasterFormat/i);
    const sampleLink = screen.getByTestId('regional-sample-link');
    expect(sampleLink.getAttribute('href')).toBe('/templates/masterformat-sample.csv');
  });

  it('renders the page container with the active template id as a data attribute', () => {
    const de = getRegionalTemplate('de-din276');
    expect(de).toBeDefined();

    renderWithProviders(de);
    const root = screen.getByTestId('regional-exchange-page');
    expect(root.getAttribute('data-template-id')).toBe('de-din276');
  });
});

describe('RegionalExchangePage - deep-link compat shim', () => {
  it('deep-link slug /es-pbc-exchange resolves to the same template', () => {
    const direct = getRegionalTemplate('es-pbc');
    const viaSlug = getRegionalTemplateBySlug('es-pbc-exchange');
    expect(viaSlug).toBe(direct);

    // And rendering with the slug-resolved template gives the same UI as
    // rendering with the id-resolved template — the polymorphic page
    // does not care whether the parent route was the new id-based one
    // or the old country-slug back-compat one.
    renderWithProviders(viaSlug);
    expect(screen.getByTestId('regional-label').textContent).toMatch(/Spanish PBC/i);
  });

  it('deep-link slug for every registry entry mounts the polymorphic page', () => {
    for (const tpl of COUNTRY_TEMPLATES) {
      const resolved = getRegionalTemplateBySlug(tpl.routeSlug);
      expect(resolved).toBeDefined();
      expect(resolved!.id).toBe(tpl.id);
    }
  });
});

describe('RegionalExchangePage - sample link visibility', () => {
  it('hides the sample link for countries without a sample file', () => {
    // Australia is one of the templates that does NOT ship a sample
    // file as part of Epic I scope (only es-pbc / it-computo / uk-nrm /
    // us-masterformat have native sample files). The polymorphic page
    // simply omits the link when sampleFile is undefined.
    const au = getRegionalTemplate('au-acmm');
    expect(au?.sampleFile).toBeUndefined();

    renderWithProviders(au);
    expect(screen.queryByTestId('regional-sample-link')).toBeNull();
  });
});

/* ── Import request shape ───────────────────────────────────────────── */

/**
 * The dispatcher endpoint takes a file, not a row list. These tests drive
 * the whole drop-parse-import flow against a stubbed `fetch` so the request
 * that leaves the page is asserted on directly. Mocking `apiPost` instead
 * is what let a JSON body sit in front of a multipart route unnoticed.
 */

const CSV_FIXTURE =
  'Ordinal,Description,Unit,Qty,Rate,Total,Code\n' +
  '01.01,Concrete C25/30,m3,10,100,1000,03 30 00\n';

/**
 * A real FIEBDC budget, in the record layout the backend reader and the BC3
 * exporter both use. The browser-side parser cannot read it, and that is the
 * point: it is a native container, not a delimited sheet.
 */
const BC3_FIXTURE =
  '~V|sample.bc3|FIEBDC-3/2020|OpenConstructionERP|26052026|Sample|ISO-8859-1|2||EUR|\r\n' +
  '~C|01#||01 Movimiento de tierras|0|||1|\r\n' +
  '~C|01.01|m3|Excavacion en zanja|18.50|||0|\r\n' +
  '~D|01#|01.01\\1\\120|\r\n' +
  '~M|01#\\01.01|1|120.000||\r\n';

async function driveImportFlow(
  template: ReturnType<typeof getRegionalTemplate>,
  fetchImpl: typeof fetch,
  upload: File = new File([CSV_FIXTURE], 'positions.csv', { type: 'text/csv' }),
  buttonMatcher: RegExp = /Import \d+ positions/,
) {
  vi.mocked(apiGet).mockImplementation(async (path: string) => {
    if (path.startsWith('/v1/projects/')) return [{ id: 'p-1', name: 'Harbour works' }];
    if (path.startsWith('/v1/boq/boqs/?project_id=')) {
      return [{ id: 'boq-9', name: 'Structure', project_id: 'p-1' }];
    }
    return [];
  });
  globalThis.fetch = fetchImpl;

  const { container } = renderWithProviders(template);

  const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
  const file = upload;
  await act(async () => {
    fireEvent.change(fileInput, { target: { files: [file] } });
  });

  const [projectSelect, boqSelect] = Array.from(
    container.querySelectorAll('select'),
  ) as HTMLSelectElement[];
  // Wait for the project list before choosing from it. Setting a value an
  // option list does not carry yet is a no-op that leaves the state empty, and
  // the CSV path only ever got away with it because awaiting its parse happened
  // to give the query time to settle.
  await waitFor(() => expect(projectSelect!.querySelectorAll('option').length).toBe(2));
  await act(async () => {
    fireEvent.change(projectSelect!, { target: { value: 'p-1' } });
  });
  await waitFor(() => expect(boqSelect!.querySelectorAll('option').length).toBe(2));
  await act(async () => {
    fireEvent.change(boqSelect!, { target: { value: 'boq-9' } });
  });

  const importButton = screen
    .getAllByRole('button')
    .find((b) => buttonMatcher.test(b.textContent ?? ''));
  await act(async () => {
    fireEvent.click(importButton!);
  });

  return { file, container, importButton };
}

describe('RegionalExchangePage - import request', () => {
  const realFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = realFetch;
    vi.mocked(apiGet).mockImplementation(async () => []);
  });

  it('sends the dropped file as multipart form data, not a JSON row list', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ imported: 1, errors: [], source_format: 'csv' }),
    })) as unknown as typeof fetch;

    const { file } = await driveImportFlow(getRegionalTemplate('es-pbc'), fetchMock);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = vi.mocked(fetchMock).mock.calls[0]!;
    expect(url).toBe('/api/v1/boq/boqs/boq-9/import/auto/');
    expect(init!.method).toBe('POST');
    expect(init!.body).toBeInstanceOf(FormData);
    expect((init!.body as FormData).get('file')).toBe(file);
    // A multipart body must not carry a JSON content type: the browser has
    // to set the boundary itself.
    expect(JSON.stringify(init!.headers ?? {})).not.toMatch(/application\/json/);
  });

  it('reports the format the backend says read the file', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ imported: 1, errors: [], source_format: 'bc3' }),
    })) as unknown as typeof fetch;

    await driveImportFlow(getRegionalTemplate('es-pbc'), fetchMock);

    expect(screen.getByText(/read by bc3/i)).toBeTruthy();
  });

  it('says the count is unknown when the response carries no imported field', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ errors: [], source_format: 'csv' }),
    })) as unknown as typeof fetch;

    await driveImportFlow(getRegionalTemplate('es-pbc'), fetchMock);

    expect(
      screen.getByText(/did not report how many positions were imported/i),
    ).toBeTruthy();
    // The parsed preview held one row. That number is the client's, not the
    // server's, and must never be presented as the server's answer.
    expect(screen.queryByText(/^1 positions imported$/)).toBeNull();
  });

  it('renders a backend error entry as its message rather than [object Object]', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        imported: 0,
        errors: [{ ordinal: '01.01', error: 'quantity is not a number' }],
        source_format: 'csv',
      }),
    })) as unknown as typeof fetch;

    await driveImportFlow(getRegionalTemplate('es-pbc'), fetchMock);

    expect(screen.getByText(/01\.01: quantity is not a number/)).toBeTruthy();
    expect(screen.queryByText(/\[object Object\]/)).toBeNull();
  });
});

/* ── Native containers the browser cannot preview ───────────────────── */

/**
 * The client-side preview is a delimited-text reader. Handed a BC3 it used to
 * split it on commas anyway and announce the rows it made up: two, cut out of
 * the file's long-text records, while the server read the same file as nine
 * positions. The button then said "Import 2 positions" and the result said 9.
 *
 * The same reader also read an HTML error page saved under a .bc3 name as three
 * positions, which is how a broken download looked like a working one.
 */
describe('RegionalExchangePage - a format the browser cannot read', () => {
  const realFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = realFetch;
    vi.mocked(apiGet).mockImplementation(async () => []);
  });

  const okFetch = () =>
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ imported: 9, errors: [], source_format: 'bc3' }),
    })) as unknown as typeof fetch;

  it('offers no invented preview for a BC3 and says why', async () => {
    const bc3 = new File([BC3_FIXTURE], 'es-pbc-sample.bc3', { type: 'text/plain' });
    await driveImportFlow(getRegionalTemplate('es-pbc'), okFetch(), bc3, /Import es-pbc-sample\.bc3/);

    expect(screen.getByTestId('regional-no-browser-preview')).toBeTruthy();
    // Not "0 positions found" and not a made-up count either: no count at all.
    expect(screen.queryByText(/positions found/i)).toBeNull();
    // And not an error. The file is fine; this browser just does not read it.
    expect(screen.queryByText(/Ensure the file matches the expected layout/i)).toBeNull();
  });

  it('still imports it, and posts the file itself', async () => {
    const fetchMock = okFetch();
    const bc3 = new File([BC3_FIXTURE], 'es-pbc-sample.bc3', { type: 'text/plain' });
    const { file } = await driveImportFlow(
      getRegionalTemplate('es-pbc'),
      fetchMock,
      bc3,
      /Import es-pbc-sample\.bc3/,
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = vi.mocked(fetchMock).mock.calls[0]!;
    expect(url).toBe('/api/v1/boq/boqs/boq-9/import/auto/');
    expect((init!.body as FormData).get('file')).toBe(file);
    // The answer on screen is the server's nine, and nothing on the way there
    // ever offered a number of its own.
    expect(screen.getByText(/9 positions imported/i)).toBeTruthy();
  });

  it('leaves the CSV path alone', async () => {
    // The control. Without it, a flag stuck on would pass both tests above and
    // silently take the preview away from every format that has one.
    await driveImportFlow(getRegionalTemplate('us-masterformat'), okFetch());

    expect(screen.queryByTestId('regional-no-browser-preview')).toBeNull();
    expect(screen.getByText(/positions found/i)).toBeTruthy();
  });
});
