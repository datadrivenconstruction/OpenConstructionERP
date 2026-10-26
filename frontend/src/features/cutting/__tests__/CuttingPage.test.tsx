// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The cutting page against the response shapes backend/app/modules/cutting/schemas.py
 * sends (Decimals as strings). The api module is mocked, so the page logic,
 * the diagrams and the proposal flow are exercised together.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';

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

const api = vi.hoisted(() => ({
  fetchJobs: vi.fn(),
  fetchJob: vi.fn(),
  fetchPlan: vi.fn(),
  fetchProposal: vi.fn(),
  applyPlan: vi.fn(),
  optimiseJob: vi.fn(),
  savePieces: vi.fn(),
  saveStocks: vi.fn(),
  validateJob: vi.fn(),
  createJob: vi.fn(),
  updateJob: vi.fn(),
  deleteJob: vi.fn(),
  importBoq: vi.fn(),
  importFile: vi.fn(),
  importRebar: vi.fn(),
  importTakeoff: vi.fn(),
  fetchInventoryOffcuts: vi.fn(),
  addInventoryStock: vi.fn(),
  returnOffcuts: vi.fn(),
  downloadPlan: vi.fn(),
}));
vi.mock('../api', () => api);
vi.mock('@/features/procurement/requisitionsApi', () => ({
  listRequisitions: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  getRequisition: vi.fn(),
}));
vi.mock('@/shared/ui/BOQPicker', () => ({ BOQPicker: () => null }));

import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { CuttingPage } from '../CuttingPage';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';
const JOB_ID = '22222222-2222-4222-8222-222222222222';
const PLAN_ID = '33333333-3333-4333-8333-333333333333';
const POSITION_ID = '44444444-4444-4444-8444-444444444444';

const JOB = {
  id: JOB_ID,
  project_id: PROJECT_ID,
  name: 'Rebar 16 level 2',
  kind: 'linear',
  material: 'B500 16',
  kerf_mm: '3.00',
  trim_mm: '0.00',
  min_offcut_mm: '500.0',
  yield_threshold_pct: '85.00',
  unit_mass_kg: '1.5783',
  currency: 'EUR',
  source_type: 'manual',
  source_ref: null,
  boq_position_id: POSITION_ID,
  procurement_req_item_id: null,
  status: 'optimised',
  notes: null,
  created_by: null,
  created_at: '2026-10-25T10:00:00Z',
  updated_at: '2026-10-25T10:00:00Z',
  pieces: [
    { id: 'p1', ref: 'A', label: '', length_mm: '4000.0', width_mm: null, quantity: 2, rotatable: true, source_ref: null },
    { id: 'p2', ref: 'LONG', label: '', length_mm: '13000.0', width_mm: null, quantity: 1, rotatable: true, source_ref: null },
  ],
  stocks: [
    {
      id: 's1',
      ref: '12m',
      label: '',
      length_mm: '12000.0',
      width_mm: null,
      unit_cost: '60.0000',
      available: null,
      is_offcut: false,
      inventory_item_id: null,
    },
  ],
};

const PLAN = {
  id: PLAN_ID,
  job_id: JOB_ID,
  project_id: PROJECT_ID,
  kind: 'linear',
  algorithm: 'pattern-greedy+local-search',
  stock_count: 1,
  pieces_placed: 2,
  pieces_unplaced: 1,
  stock_total: '12.0000',
  pieces_total: '8.0000',
  offcut_total: '3.9940',
  scrap_total: '0.0060',
  yield_pct: '66.67',
  waste_pct: '0.05',
  cost: '60.0000',
  currency: 'EUR',
  exact: false,
  proven_optimal: false,
  elapsed_ms: 3,
  layout: {
    kind: 'linear',
    kerf_mm: '3.00',
    trim_mm: '0.00',
    bars: [
      {
        index: 1,
        stock_ref: '12m',
        stock_label: '',
        length_mm: '12000.0',
        is_offcut: false,
        inventory_item_id: null,
        cost: '60.0000',
        cuts: [
          { ref: 'A', label: '', length_mm: '4000.0', offset_mm: '0.0' },
          { ref: 'A', label: '', length_mm: '4000.0', offset_mm: '4003.0' },
        ],
        remnant_mm: '3994.0',
        offcut_mm: '3994.0',
        scrap_mm: '6.0',
      },
    ],
  },
  stock_usage: [],
  offcuts: [{ length_mm: '3994.0', width_mm: null, quantity: 1 }],
  unplaced: [{ ref: 'LONG', label: '', quantity: 1 }],
  validation: { status: 'errors', score: 0.5, errors: 1, warnings: 0, infos: 0, results: [] },
  settings: {},
  inventory_synced_at: null,
  applied_at: null,
  created_by: null,
  created_at: '2026-10-25T10:01:00Z',
};

const SUMMARY = {
  id: JOB_ID,
  project_id: PROJECT_ID,
  name: JOB.name,
  kind: 'linear',
  material: 'B500 16',
  status: 'optimised',
  source_type: 'manual',
  piece_count: 3,
  stock_count: 1,
  latest_plan_id: PLAN_ID,
  latest_yield_pct: '66.67',
  latest_waste_pct: '0.05',
  latest_cost: '60.0000',
  updated_at: '2026-10-25T10:00:00Z',
};

function renderPage(ui: ReactNode = <CuttingPage />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('CuttingPage', () => {
  beforeEach(() => {
    useProjectContextStore.setState({ activeProjectId: PROJECT_ID, activeProjectName: 'Tower' });
    useAuthStore.setState({ userRole: 'editor' });
    api.fetchJobs.mockResolvedValue([SUMMARY]);
    api.fetchJob.mockResolvedValue(JOB);
    api.fetchPlan.mockResolvedValue(PLAN);
  });
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('asks for a project when none is active', () => {
    useProjectContextStore.setState({ activeProjectId: null });
    renderPage();
    expect(screen.getByText('Select a project')).toBeTruthy();
  });

  it('shows the job, flags an oversize piece and draws the latest plan', async () => {
    renderPage();
    expect(await screen.findByRole('heading', { name: 'Rebar 16 level 2' })).toBeTruthy();
    expect(await screen.findByText('These pieces fit no stock entry: LONG')).toBeTruthy();
    expect(await screen.findByTestId('linear-diagram')).toBeTruthy();
    expect(screen.getByText('Pieces not placed (1): LONG x1')).toBeTruthy();
    expect(screen.getByText('66.7 %')).toBeTruthy();
    expect(screen.getByText('1 x')).toBeTruthy();
  });

  it('shows the proposal with its confidence and applies it only on confirmation', async () => {
    api.fetchProposal.mockResolvedValue({
      plan_id: PLAN_ID,
      waste_factor: '1.0008',
      waste_pct: '0.05',
      yield_pct: '66.67',
      confidence: 0.4,
      lines: [
        {
          target: 'boq_position',
          target_id: POSITION_ID,
          label: '01.001 Rebar 16 mm',
          unit: 'm',
          current_quantity: '8.5',
          proposed_quantity: '8.006',
          basis: 'length',
          appliable: false,
          reason: 'pieces_unplaced',
        },
      ],
    });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Propose quantities' }));
    expect(await screen.findByTestId('cutting-proposal')).toBeTruthy();
    expect(await screen.findByText('Some pieces are unplaced')).toBeTruthy();
    const confirm = screen.getByRole('button', { name: 'Confirm and update lines' }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    expect(api.applyPlan).not.toHaveBeenCalled();
  });

  it('hides editing controls from a viewer', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    renderPage();
    expect(await screen.findByRole('heading', { name: 'Rebar 16 level 2' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Optimise' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'New job' })).toBeNull();
  });

  it('runs the optimiser and shows the validation outcome', async () => {
    api.optimiseJob.mockResolvedValue({
      ...PLAN,
      validation: {
        status: 'errors',
        score: 0.5,
        errors: 1,
        warnings: 0,
        infos: 0,
        results: [
          {
            rule_id: 'cutting.piece_fits_stock',
            rule_name: 'Piece fits stock',
            severity: 'error',
            category: 'consistency',
            passed: false,
            message: 'Piece LONG (13000.0 mm) fits no stock entry',
            element_ref: 'piece:LONG',
            suggestion: null,
          },
        ],
      },
    });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Optimise' }));
    await waitFor(() => expect(api.optimiseJob).toHaveBeenCalledWith(JOB_ID));
    expect(await screen.findByText('Piece LONG (13000.0 mm) fits no stock entry')).toBeTruthy();
    expect(screen.getByText('Validation: 1 errors, 0 warnings')).toBeTruthy();
  });
});
