/**
 * The rebar schedule page against the response shapes the backend really sends.
 *
 * The page was written against a contract the backend never had: it read
 * ``GET /imports`` as a bare array and called ``.find`` on it, so the page threw
 * "find is not a function" for every user the moment a project was selected.
 * The fixtures below are copied field by field from
 * ``backend/app/modules/rebar_schedule/schemas.py``, including the Decimal
 * columns, which Pydantic serialises as JSON strings. Only the HTTP layer is
 * mocked, so ``api.ts`` and the page are exercised together.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string } & Record<string, unknown>) => {
      if (typeof opts === 'object' && opts && 'defaultValue' in opts) {
        let dv = String(opts.defaultValue ?? '');
        for (const [k, v] of Object.entries(opts)) {
          if (k === 'defaultValue') continue;
          dv = dv.replaceAll(`{{${k}}}`, String(v));
        }
        return dv;
      }
      return _key;
    },
    i18n: { language: 'en' },
  }),
  initReactI18next: { type: '3rdParty', init: () => undefined },
  I18nextProvider: ({ children }: { children: unknown }) => children,
  Trans: ({ children }: { children?: unknown }) => children ?? null,
}));

const apiMocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiDelete: vi.fn(),
  downloadWithAuth: vi.fn(),
}));
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('@/shared/lib/api');
  return { ...actual, ...apiMocks };
});

import { ApiError } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { RebarSchedulePage } from '../RebarSchedulePage';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';
const IMPORT_ID = '22222222-2222-4222-8222-222222222222';

// RebarImportResponse
const IMPORT_RECORD = {
  id: IMPORT_ID,
  project_id: PROJECT_ID,
  filename: 'wall_B1.abs',
  content_sha256: 'a'.repeat(64),
  encoding: 'ascii',
  record_count: 2,
  total_weight_kg: '1234.500',
  validation_status: 'warnings',
  error_count: 0,
  warning_count: 1,
  created_by: 'user-1',
  created_at: '2026-09-20T10:00:00Z',
};

// RebarImportListResponse
function importList(total = 1) {
  return { items: [IMPORT_RECORD], total, offset: 0, limit: 200 };
}

// RebarShapeResponse
function shape(lineNo: number, position: string, diameter: string, weight: string, checksumOk = true) {
  return {
    id: `33333333-3333-4333-8333-00000000000${lineNo}`,
    import_id: IMPORT_ID,
    project_id: PROJECT_ID,
    line_no: lineNo,
    super_group: 'BF2D',
    project_ref: 'P-1',
    drawing_ref: 'S-101',
    drawing_index: 'a',
    position,
    length_mm: '4250.00',
    quantity: 10,
    weight_kg: weight,
    diameter_mm: diameter,
    steel_grade: 'B500B',
    bending_roller_mm: '48.00',
    mesh_type: null,
    width_mm: null,
    height_mm: null,
    layer: null,
    stagger_group: null,
    geometry: null,
    block_layout: 'BF2D',
    checksum_ok: checksumOk,
    raw: 'BF2D@Hj...@',
  };
}

// RebarShapeListResponse
const SHAPE_LIST = {
  items: [shape(1, 'POS-7', '12.00', '45.300'), shape(2, 'POS-8', '16.00', '80.100', false)],
  total: 2,
  offset: 0,
  limit: 1000,
};

// list[CuttingItem]: diameter_mm is str(Decimal) off Numeric(8,2), weight_kg a float
const CUTTING = [
  { diameter_mm: '12.00', bars: 10, weight_kg: 45.3 },
  { diameter_mm: '16.00', bars: 14, weight_kg: 80.1 },
];

const ERROR_FINDING = {
  rule_id: 'bvbs_abs.checksum_valid',
  rule_name: 'Checksum',
  severity: 'error',
  category: 'integrity',
  passed: false,
  message: 'Checksum does not match the record',
  element_ref: 'line 1',
  suggestion: null,
};

// AbsPreviewResponse
const PREVIEW = {
  record_count: 1,
  encoding: 'cp1252',
  total_weight_kg: '45.300',
  shapes: [
    {
      line_no: 1,
      super_group: 'BF2D',
      drawing_ref: 'Bügel',
      position: 'POS-7',
      length_mm: '4250.00',
      quantity: 12,
      weight_kg: '45.300',
      diameter_mm: '12.00',
      steel_grade: 'B500B',
      checksum_ok: false,
      block_layout: 'BF2D',
    },
  ],
  validation: { status: 'errors', error_count: 1, warning_count: 0, info_count: 0, findings: [ERROR_FINDING] },
};

function routeGet(path: string): unknown {
  if (path.startsWith('/v1/rebar-schedule/imports/?')) return importList();
  if (path.startsWith(`/v1/rebar-schedule/imports/${IMPORT_ID}/shapes`)) return SHAPE_LIST;
  if (path.startsWith(`/v1/rebar-schedule/imports/${IMPORT_ID}/cutting`)) return CUTTING;
  throw new Error(`unexpected GET ${path}`);
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <RebarSchedulePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function pickFile(container: HTMLElement, file: File) {
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
}

beforeEach(() => {
  apiMocks.apiGet.mockImplementation(async (path: string) => routeGet(path));
  apiMocks.apiDelete.mockResolvedValue(undefined);
  useProjectContextStore.setState({ activeProjectId: PROJECT_ID });
  useAuthStore.setState({ userRole: 'manager', accessToken: 'token' });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  // Here rather than at the end of a test body, so a failing assertion cannot
  // leave fetch stubbed for the tests after it.
  vi.unstubAllGlobals();
  useProjectContextStore.setState({ activeProjectId: null });
  useAuthStore.setState({ userRole: null, accessToken: null });
});

describe('RebarSchedulePage with the backend response shapes', () => {
  it('opens the list from the paged envelope, with each import validation status', async () => {
    renderPage();

    expect(await screen.findByText('wall_B1.abs')).toBeInTheDocument();
    // record_count and total_weight_kg (a Decimal string) reach the list row.
    expect(screen.getAllByText(/2 shapes/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/1[.,]23 t/).length).toBeGreaterThan(0);
    expect(screen.getByText('1 warning(s)')).toBeInTheDocument();
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
  });

  it('says a failed list request failed instead of claiming there are no imports', async () => {
    apiMocks.apiGet.mockRejectedValue(new ApiError(500, 'Internal Server Error', { detail: 'Database unavailable' }));
    renderPage();

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the rebar schedules.');
    expect(screen.getByRole('alert')).toHaveTextContent('Database unavailable');
    expect(screen.queryByText('No rebar imports yet')).not.toBeInTheDocument();
  });

  it('tells the user when the list holds fewer imports than the project has', async () => {
    apiMocks.apiGet.mockImplementation(async (path: string) =>
      path.startsWith('/v1/rebar-schedule/imports/?') ? importList(250) : routeGet(path),
    );
    renderPage();

    expect(await screen.findByText('Showing the newest 1 of 250 imports.')).toBeInTheDocument();
  });

  it('opens an import and shows its shapes, cutting list, validation and bad checksums', async () => {
    renderPage();

    fireEvent.click(await screen.findByText('wall_B1.abs'));

    expect(await screen.findByText('POS-7')).toBeInTheDocument();
    expect(screen.getByText('POS-8')).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText('B500B').length).toBe(2));
    // Cutting totals: 24 bars, 125.4 kg, summed from numbers, not glued strings.
    expect(screen.getByText('24')).toBeInTheDocument();
    expect(screen.getByText(/125[.,]4/)).toBeInTheDocument();
    // '12.00' from the cutting summary and 12.00 on a shape read the same.
    expect(screen.getAllByText('12').length).toBe(2);
    expect(screen.getByText('1 warning(s)')).toBeInTheDocument();
    expect(screen.getAllByRole('img', { name: 'The checksum does not match this record' })).toHaveLength(1);
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
  });

  it('deletes from the detail view through the confirm dialog', async () => {
    renderPage();
    fireEvent.click(await screen.findByText('wall_B1.abs'));
    await screen.findByText('POS-7');

    fireEvent.click(screen.getByRole('button', { name: /^Delete$/ }));
    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText('Delete import')).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: /^Delete$/ }));

    await waitFor(() => expect(apiMocks.apiDelete).toHaveBeenCalledWith(`/v1/rebar-schedule/imports/${IMPORT_ID}`));
  });

  it('offers neither upload nor delete to a viewer', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    const { container } = renderPage();
    await screen.findByText('wall_B1.abs');

    expect(container.querySelector('input[type="file"]')).toBeNull();
    expect(screen.queryByRole('button', { name: /^Delete$/ })).not.toBeInTheDocument();
  });

  it('previews the file bytes on the import decoder and labels errors as errors', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(PREVIEW));
    vi.stubGlobal('fetch', fetchMock);

    const { container } = renderPage();
    await screen.findByText('wall_B1.abs');
    // 0xFC is a cp1252 u-umlaut and not valid UTF-8 on its own.
    const bytes = new Uint8Array([0x42, 0x46, 0x32, 0x44, 0x40, 0x72, 0x42, 0xfc, 0x67, 0x65, 0x6c, 0x40]);
    const file = new File([bytes], 'buegel.abs', { type: 'application/octet-stream' });
    pickFile(container, file);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toBe('/api/v1/rebar-schedule/preview/file/?locale=en');
    const sent = (init.body as FormData).get('upload') as File;
    expect(new Uint8Array(await sent.arrayBuffer())).toEqual(bytes);
    expect(apiMocks.apiPost).not.toHaveBeenCalled();

    const errors = await screen.findByRole('region', { name: 'Errors' });
    expect(errors).toHaveTextContent('Checksum does not match the record');
    expect(screen.queryByRole('region', { name: 'Warnings' })).not.toBeInTheDocument();
    expect(screen.getByText('Bügel')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Import with errors/ })).toBeInTheDocument();
  });

  it('imports as the upload form field, follows import_record and says when the file was a duplicate', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ ...PREVIEW, validation: { ...PREVIEW.validation, status: 'passed', error_count: 0, findings: [] } }))
      .mockResolvedValueOnce(
        json(
          {
            import_record: IMPORT_RECORD,
            validation: { status: 'passed', error_count: 0, warning_count: 0, info_count: 0, findings: [] },
            duplicate: true,
          },
          201,
        ),
      );
    vi.stubGlobal('fetch', fetchMock);

    const { container } = renderPage();
    await screen.findByText('wall_B1.abs');
    pickFile(container, new File(['BF2D@Hj...@\r\n'], 'wall_B1.abs', { type: 'text/plain' }));

    fireEvent.click(await screen.findByRole('button', { name: /^Import$/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const [url, init] = fetchMock.mock.calls[1]!;
    expect(String(url)).toBe(`/api/v1/rebar-schedule/imports/?project_id=${PROJECT_ID}&locale=en`);
    const form = init.body as FormData;
    expect(form.get('upload')).toBeInstanceOf(File);
    expect(form.get('file')).toBeNull();

    expect(await screen.findByRole('status')).toHaveTextContent('This file was already imported on');
    await waitFor(() =>
      expect(apiMocks.apiGet).toHaveBeenCalledWith(
        expect.stringContaining(`/v1/rebar-schedule/imports/${IMPORT_ID}/shapes`),
      ),
    );
  });
});
