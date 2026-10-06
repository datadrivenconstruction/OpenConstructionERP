// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import en from '@/app/locales/en';
import { RegionalPriceListImport } from '../RegionalPriceListImport';

const preview = {
  source: {
    format: 'toscana_xml',
    profile: null,
    title: 'Prezzario dei Lavori Pubblici della Toscana',
    region_code: 'TOS',
    region_name: 'Toscana',
    region_detected_from: 'file_header',
    edition: '2025',
    area: 'Provincia di Firenze',
    publisher: 'Regione Toscana',
    licence: 'CC BY 3.0',
    licence_stated_in: 'file',
    attribution: 'Regione Toscana, Prezzario dei Lavori Pubblici della Toscana, 2025 (Provincia di Firenze), CC BY 3.0',
    suggested_catalog_name: 'Toscana 2025 - Firenze',
  },
  files: [{ name: 'Firenze-2025.xml', size: 1000 }],
  skipped_files: [],
  counts: {
    rows: 9,
    importable: 9,
    duplicates: 0,
    broken_rows: 0,
    with_analysis: 6,
    with_labour_share: 6,
    safety_rows: 2,
    skipped: {},
  },
  chapters: [{ code: '01', title: 'NUOVE COSTRUZIONI EDILI', count: 3 }],
  chapter_count: 4,
  sample_rows: [
    {
      code: 'TOS25_01.A03.001.001',
      description: 'TOTALE O PARZIALE DI EDIFICI',
      unit: 'm3',
      source_unit: 'm³',
      rate: '13.63017',
      labour_share_pct: '40.36',
      chapter: 'NUOVE COSTRUZIONI EDILI',
    },
  ],
  broken_examples: [],
  warnings: [],
  currency: 'EUR',
};

function json(body, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

const BASE = '/api/v1/costs/import/pricelist';

function job(id, status, extra = {}) {
  return json({
    job_id: id,
    kind: 'preview',
    upload_id: 'u1',
    status,
    progress_percent: status === 'success' ? 100 : 0,
    stage: 'reading',
    rows_read: 0,
    imported: 0,
    ...extra,
  });
}

/** The upload is stored and its preview job has finished with ``body``. */
function uploaded(fetchMock, body = preview) {
  fetchMock
    .mockReturnValueOnce(json({ upload_id: 'u1', job_id: 'j1' }, 202))
    .mockReturnValueOnce(job('j1', 'success', { result: body }));
}

function renderIt() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RegionalPriceListImport />
    </QueryClientProvider>,
  );
}

function choose(file = new File(['<xml/>'], 'Firenze-2025.xml', { type: 'application/xml' })) {
  fireEvent.change(screen.getByTestId('regional-price-list-file'), { target: { files: [file] } });
}

describe('RegionalPriceListImport', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('previews the list with its edition, licence and attribution before importing', async () => {
    uploaded(fetchMock);
    renderIt();
    choose();

    await waitFor(() => expect(screen.getByTestId('regional-price-list-preview')).toBeInTheDocument());
    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE}/uploads/`);
    expect(fetchMock.mock.calls[0][1].body.get('file').name).toBe('Firenze-2025.xml');
    expect(fetchMock.mock.calls[1][0]).toBe(`${BASE}/jobs/j1`);
    expect(screen.getByText(/Toscana, edition 2025/)).toBeInTheDocument();
    expect(screen.getByText(/CC BY 3.0 \(stated in the file\)/)).toBeInTheDocument();
    expect(screen.getByText(/Source: Regione Toscana/)).toBeInTheDocument();
    expect(screen.getByText('TOS25_01.A03.001.001')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Toscana 2025 - Firenze')).toBeInTheDocument();
    // Only the upload and its preview: nothing is imported until the user confirms.
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('shows how many rows it has read while a large list is previewed', async () => {
    fetchMock
      .mockReturnValueOnce(json({ upload_id: 'u1', job_id: 'j1' }, 202))
      .mockReturnValueOnce(job('j1', 'started', { rows_read: 12500 }))
      .mockReturnValueOnce(job('j1', 'success', { result: preview }));
    renderIt();
    choose();

    expect(await screen.findByTestId('regional-price-list-progress')).toHaveTextContent(/12,500 rows read/);
    await waitFor(() => expect(screen.getByTestId('regional-price-list-preview')).toBeInTheDocument(), {
      timeout: 3000,
    });
  });

  it('imports the stored upload into the named catalogue once confirmed, showing progress', async () => {
    uploaded(fetchMock);
    fetchMock
      .mockReturnValueOnce(json({ upload_id: 'u1', job_id: 'j2' }, 202))
      .mockReturnValueOnce(job('j2', 'started', { kind: 'import', stage: 'writing', progress_percent: 40, imported: 4 }))
      .mockReturnValueOnce(
        job('j2', 'success', {
          kind: 'import',
          result: {
            imported: 9,
            rows: 9,
            duplicates: 0,
            skipped: {},
            catalog: 'Toscana 2025 - Firenze',
            catalog_id: 'c1',
            catalog_currency: 'EUR',
            source: preview.source,
          },
        }),
      );
    renderIt();
    choose();
    const button = await screen.findByRole('button', { name: /Import 9 items/ });
    fireEvent.click(button);

    expect(await screen.findByTestId('regional-price-list-import-progress')).toHaveTextContent(/40%, 4 items written/);
    const [url, init] = fetchMock.mock.calls[2];
    expect(url).toBe(`${BASE}/uploads/u1/import/`);
    expect(init.body.get('catalog_name')).toBe('Toscana 2025 - Firenze');
    expect(init.body.get('expected_rows')).toBe('9');
    expect(init.body.get('file')).toBeNull();
    expect(await screen.findByText(/9 items imported into "Toscana 2025 - Firenze"/, {}, { timeout: 3000 })).toBeInTheDocument();
  });

  it('names a refused import by its reason and keeps the upload for another try', async () => {
    uploaded(fetchMock);
    fetchMock
      .mockReturnValueOnce(json({ upload_id: 'u1', job_id: 'j2' }, 202))
      .mockReturnValueOnce(
        job('j2', 'failed', {
          kind: 'import',
          error: { code: 'catalog_name_unavailable', message: 'x', params: { suggestion: 'Toscana 2025 - Firenze (2)' } },
        }),
      );
    renderIt();
    choose();
    fireEvent.click(await screen.findByRole('button', { name: /Import 9 items/ }));

    // Neutral: it does not say that a catalogue of that name exists, and offers a free one.
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/cannot be used for a new catalogue.*"Toscana 2025 - Firenze \(2\)"/);
    expect(alert).not.toHaveTextContent(/already exists/);
    // The preview stays, so the user can rename and import the same upload again.
    expect(screen.getByTestId('regional-price-list-preview')).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false);
  });

  it('asks for the region when the file does not name it and blocks the import until chosen', async () => {
    uploaded(fetchMock, {
      ...preview,
      source: { ...preview.source, region_code: null, region_name: null, licence: null, licence_stated_in: null },
      warnings: ['region_not_detected', 'licence_not_stated'],
    });
    renderIt();
    choose();

    expect(await screen.findByText(/does not say which region/)).toBeInTheDocument();
    expect(screen.getByText(/Licence: not stated/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Import 9 items/ })).toBeDisabled();
  });

  it('names a refused archive by its reason and drops the upload', async () => {
    fetchMock
      .mockReturnValueOnce(json({ upload_id: 'u1', job_id: 'j1' }, 202))
      .mockReturnValueOnce(job('j1', 'failed', { error: { code: 'zip_ratio_suspicious', message: 'x', params: {} } }))
      .mockReturnValueOnce(Promise.resolve(new Response(null, { status: 204 })));
    renderIt();
    choose(new File(['PK'], 'bomb.zip', { type: 'application/zip' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/compressed far more than any price list/);
    expect(fetchMock.mock.calls[2][0]).toBe(`${BASE}/uploads/u1/`);
    expect(fetchMock.mock.calls[2][1].method).toBe('DELETE');
  });

  it('says which encoding a file was saved in when it cannot be read', async () => {
    fetchMock
      .mockReturnValueOnce(json({ upload_id: 'u1', job_id: 'j1' }, 202))
      .mockReturnValueOnce(
        job('j1', 'failed', {
          error: { code: 'text_encoding_unreadable', message: 'x', params: { encoding: 'UTF-16', member: 'p.csv' } },
        }),
      )
      .mockReturnValueOnce(Promise.resolve(new Response(null, { status: 204 })));
    renderIt();
    choose(new File(['x'], 'p.csv', { type: 'text/csv' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/saved as UTF-16 text, but its contents are not valid UTF-16/);
  });

  it('words a broken XPWE list the way the bill import does, naming where it breaks', async () => {
    // The test i18n mock answers with the defaultValue, so the server's message
    // is the en.ts wording itself: only the coded path fills in its values.
    const wording = (en.translation as Record<string, string>)['boq.import_error.xpwe_not_well_formed'];
    expect(wording).toBeTruthy();
    fetchMock
      .mockReturnValueOnce(json({ upload_id: 'u1', job_id: 'j1' }, 202))
      .mockReturnValueOnce(
        job('j1', 'failed', {
          error: { code: 'xpwe_not_well_formed', message: wording, params: { line: 66, column: 127 } },
        }),
      )
      .mockReturnValueOnce(Promise.resolve(new Response(null, { status: 204 })));
    renderIt();
    choose(new File(['<PweDocumento>'], 'elenco.xpwe', { type: 'application/xml' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/not well-formed XML: it breaks off at line 66, column 127/);
  });

  it('names a refusal the server answers at once', async () => {
    fetchMock.mockReturnValueOnce(json({ detail: { code: 'file_too_large', message: 'x', limit_mb: 200 } }, 400));
    renderIt();
    choose();

    expect(await screen.findByRole('alert')).toHaveTextContent(/larger than 200 MB/);
  });
});
