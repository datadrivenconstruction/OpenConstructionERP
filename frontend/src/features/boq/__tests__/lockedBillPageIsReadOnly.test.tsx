// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The editor of a locked bill says it is locked and offers no way to add.
 *
 * A locked bill showed Add Position in the toolbar and a grid that took typing,
 * and the server answered each attempt with a 409. The page now says the bill
 * is locked, in a banner above the table, drops the add actions, and hands the
 * grid its read-only flag. The grid's own behaviour under that flag is pinned in
 * lockedBillIsReadOnly.test.tsx; here the grid is a stub that records it.
 *
 * Run:  npx vitest run src/features/boq/__tests__/lockedBillPageIsReadOnly.test.tsx
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

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

const grid: { readOnly: unknown } = { readOnly: undefined };

vi.mock('../BOQGrid', () => ({
  __esModule: true,
  default: React.forwardRef<unknown, { readOnly?: boolean }>(function BOQGridStub(props, _ref) {
    grid.readOnly = props.readOnly;
    return <div data-testid="boq-grid-stub" />;
  }),
}));

vi.mock('../pdfReport', () => ({ generateBOQPdf: vi.fn() }));
vi.mock('@/features/bim/api', () => ({ fetchBIMModels: vi.fn().mockResolvedValue({ items: [] }) }));

const BOQ_ID = 'boq-1';
const PROJECT_ID = 'proj-1';
const bill = { locked: false };

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return {
    ...actual,
    boqApi: {
      get: vi.fn(async () => ({
        id: BOQ_ID,
        project_id: PROJECT_ID,
        name: 'Riverside HQ Bill',
        status: bill.locked ? 'final' : 'draft',
        is_locked: bill.locked,
        positions: [
          {
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
          },
        ],
      })),
      getMarkups: vi.fn(async () => ({ markups: [] })),
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
  return {
    ...actual,
    projectsApi: {
      ...actual.projectsApi,
      get: vi.fn(async () => ({ id: PROJECT_ID, name: 'Riverside HQ', currency: 'EUR', fx_rates: [] })),
    },
  };
});

import { BOQEditorPage } from '../BOQEditorPage';

async function renderPage() {
  const client = new QueryClient({
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
  await screen.findByTestId('boq-grid-stub', {}, { timeout: 10_000 });
}

beforeEach(() => {
  vi.clearAllMocks();
  Element.prototype.scrollIntoView = vi.fn();
  grid.readOnly = undefined;
});

afterEach(() => cleanup());

describe('the editor of a locked bill', () => {
  it('says the bill is locked and offers no Add Position', async () => {
    bill.locked = true;
    await renderPage();

    expect(screen.getByTestId('boq-locked-banner')).toBeTruthy();
    expect(screen.queryByTestId('boq-add-position-button')).toBeNull();
    expect(grid.readOnly).toBe(true);
  });

  it('shows no banner and keeps Add Position on an open bill', async () => {
    bill.locked = false;
    await renderPage();

    expect(screen.queryByTestId('boq-locked-banner')).toBeNull();
    expect(screen.getByTestId('boq-add-position-button')).toBeTruthy();
    expect(grid.readOnly).toBe(false);
  });
});
