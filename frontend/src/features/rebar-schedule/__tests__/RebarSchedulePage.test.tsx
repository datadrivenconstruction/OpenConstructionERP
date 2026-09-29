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
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
const IMPORT_LIST = { items: [IMPORT_RECORD], total: 1, offset: 0, limit: 50 };

// RebarShapeResponse
function shape(lineNo: number, position: string, diameter: string, weight: string) {
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
    length_mm: '4250',
    quantity: 12,
    weight_kg: weight,
    diameter_mm: diameter,
    steel_grade: 'B500B',
    bending_roller_mm: '48',
    mesh_type: null,
    width_mm: null,
    height_mm: null,
    layer: null,
    stagger_group: null,
    geometry: null,
    block_layout: 'BF2D',
    checksum_ok: true,
    raw: 'BF2D@Hj...@',
  };
}

// RebarShapeListResponse
const SHAPE_LIST = {
  items: [shape(1, 'POS-7', '12', '45.300'), shape(2, 'POS-8', '16', '80.100')],
  total: 2,
  offset: 0,
  limit: 200,
};

// list[CuttingItem]: diameter_mm is a plain str, weight_kg a float
const CUTTING = [
  { diameter_mm: '12', bars: 12, weight_kg: 45.3 },
  { diameter_mm: '16', bars: 12, weight_kg: 80.1 },
];

function routeGet(path: string): unknown {
  if (path.startsWith('/v1/rebar-schedule/imports/?') || path.startsWith('/v1/rebar-schedule/imports?')) {
    return IMPORT_LIST;
  }
  if (path.startsWith(`/v1/rebar-schedule/imports/${IMPORT_ID}/shapes`)) return SHAPE_LIST;
  if (path.startsWith(`/v1/rebar-schedule/imports/${IMPORT_ID}/cutting`)) return CUTTING;
  throw new Error(`unexpected GET ${path}`);
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

beforeEach(() => {
  apiMocks.apiGet.mockImplementation(async (path: string) => routeGet(path));
  useProjectContextStore.setState({ activeProjectId: PROJECT_ID });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  useProjectContextStore.setState({ activeProjectId: null });
});

describe('RebarSchedulePage with the backend response shapes', () => {
  it('opens the list from the paged envelope instead of crashing on it', async () => {
    renderPage();

    expect(await screen.findByText('wall_B1.abs')).toBeInTheDocument();
    // record_count and total_weight_kg (a Decimal string) reach the list row.
    expect(screen.getAllByText(/2 shapes/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/1[.,]23 t/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
  });

  it('opens an import and shows its shapes and cutting list', async () => {
    renderPage();

    fireEvent.click(await screen.findByText('wall_B1.abs'));

    expect(await screen.findByText('POS-7')).toBeInTheDocument();
    expect(screen.getByText('POS-8')).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText('B500B').length).toBe(2));
    // Cutting totals: 24 bars, 125.4 kg, summed from numbers, not glued strings.
    expect(screen.getByText('24')).toBeInTheDocument();
    expect(screen.getByText(/125[.,]4/)).toBeInTheDocument();
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
  });

  it('dry-runs a file as JSON text and imports it as the upload form field', async () => {
    apiMocks.apiPost.mockResolvedValue({
      record_count: 1,
      encoding: 'ascii',
      total_weight_kg: '45.300',
      shapes: [
        {
          line_no: 1,
          super_group: 'BF2D',
          drawing_ref: 'S-101',
          position: 'POS-7',
          length_mm: '4250',
          quantity: 12,
          weight_kg: '45.300',
          diameter_mm: '12',
          steel_grade: 'B500B',
          checksum_ok: false,
          block_layout: 'BF2D',
        },
      ],
      validation: {
        status: 'errors',
        error_count: 1,
        warning_count: 0,
        info_count: 0,
        findings: [
          {
            rule_id: 'bvbs_abs.checksum',
            rule_name: 'Checksum',
            severity: 'error',
            category: 'integrity',
            passed: false,
            message: 'Checksum does not match the record',
            element_ref: 'line 1',
            suggestion: null,
          },
        ],
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          import_record: IMPORT_RECORD,
          validation: { status: 'passed', error_count: 0, warning_count: 0, info_count: 0, findings: [] },
          duplicate: false,
        }),
        { status: 201, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { container } = renderPage();
    await screen.findByText('wall_B1.abs');

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['BF2D@Hj...@\r\n'], 'wall_B1.abs', { type: 'text/plain' });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(apiMocks.apiPost).toHaveBeenCalled());
    const [path, body] = apiMocks.apiPost.mock.calls[0]!;
    expect(path).toBe('/v1/rebar-schedule/preview/');
    expect(body).toEqual({ content: 'BF2D@Hj...@\r\n', locale: 'en' });

    expect(await screen.findByText(/Checksum does not match the record/)).toBeInTheDocument();
    expect(screen.getByText('POS-7')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /^Import$/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain(`/api/v1/rebar-schedule/imports/?project_id=${PROJECT_ID}`);
    const form = init.body as FormData;
    expect(form.get('upload')).toBeInstanceOf(File);
    expect(form.get('file')).toBeNull();

    // The import response nests the record; the page follows it to the detail view.
    await waitFor(() =>
      expect(apiMocks.apiGet).toHaveBeenCalledWith(
        expect.stringContaining(`/v1/rebar-schedule/imports/${IMPORT_ID}/shapes`),
      ),
    );
    vi.unstubAllGlobals();
  });
});
