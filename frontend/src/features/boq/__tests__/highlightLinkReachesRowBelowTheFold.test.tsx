// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A `?highlight=<positionId>` link lands on its row even when the row is far
 * down the bill.
 *
 * Change orders link to the section their approval appended, which is always
 * the last rows of the bill, and progress links to positions anywhere in it.
 * The editor used to look for the row in the DOM, but the grid virtualises its
 * rows, so a row below the fold had no node: nothing scrolled, nothing flashed,
 * and the parameter was dropped anyway. The jump now goes through the grid's
 * own handle, which finds the row in the grid model. Here the grid is a stub
 * that renders no rows at all (everything is "below the fold") and answers the
 * handle from a list of ids it knows.
 *
 * Run:  npx vitest run src/features/boq/__tests__/highlightLinkReachesRowBelowTheFold.test.tsx
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';

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

/** What the stub grid's model holds, and every jump it was asked for. */
const gridModel: { rowIds: Set<string>; missesBeforeRows: number; asked: string[] } = {
  rowIds: new Set(),
  missesBeforeRows: 0,
  asked: [],
};

vi.mock('../BOQGrid', () => ({
  __esModule: true,
  default: React.forwardRef<unknown, Record<string, unknown>>(function BOQGridStub(_props, ref) {
    React.useImperativeHandle(ref, () => ({
      clearSelection: () => undefined,
      beginEditDescription: () => undefined,
      setAllResourcesExpanded: () => undefined,
      scrollToPosition: (positionId: string) => {
        gridModel.asked.push(positionId);
        // The rows reach the grid a moment after the bill: the first few
        // asks find an empty model.
        if (gridModel.asked.length <= gridModel.missesBeforeRows) return false;
        return gridModel.rowIds.has(positionId);
      },
    }));
    return <div data-testid="boq-grid-stub" />;
  }),
}));

vi.mock('../pdfReport', () => ({ generateBOQPdf: vi.fn() }));
vi.mock('@/features/bim/api', () => ({ fetchBIMModels: vi.fn().mockResolvedValue({ items: [] }) }));

const BOQ_ID = 'boq-3';
const PROJECT_ID = 'proj-1';

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return {
    ...actual,
    boqApi: {
      get: vi.fn(async () => ({
        id: BOQ_ID,
        project_id: PROJECT_ID,
        name: 'Riverside HQ Bill',
        status: 'draft',
        is_locked: false,
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

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-search">{location.search}</div>;
}

async function renderAt(search: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity, gcTime: Infinity } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/boq/${BOQ_ID}${search}`]}>
        <Routes>
          <Route
            path="/boq/:boqId"
            element={
              <>
                <BOQEditorPage />
                <LocationProbe />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByTestId('boq-grid-stub', {}, { timeout: 10_000 });
}

const search = () => screen.getByTestId('location-search').textContent ?? '';

beforeEach(() => {
  vi.clearAllMocks();
  Element.prototype.scrollIntoView = vi.fn();
  gridModel.rowIds = new Set(['p1', 'sec-9']);
  gridModel.missesBeforeRows = 0;
  gridModel.asked = [];
});

afterEach(() => cleanup());

describe('a highlight link into the bill', () => {
  it('asks the grid to bring a row with no DOM node into view', async () => {
    // No row is rendered by the stub, so a DOM lookup finds nothing; only the
    // grid's handle can reach the change-order section at the end of the bill.
    await renderAt('?highlight=sec-9');

    await waitFor(() => expect(gridModel.asked).toContain('sec-9'), { timeout: 3000 });
    await waitFor(() => expect(search()).not.toContain('highlight'));
    expect(gridModel.asked).toEqual(['sec-9']);
  });

  it('keeps the link until the rows reach the grid, then lands it', async () => {
    gridModel.missesBeforeRows = 3;
    await renderAt('?highlight=sec-9');

    await waitFor(() => expect(gridModel.asked.length).toBeGreaterThanOrEqual(1), { timeout: 3000 });
    // A miss on an empty model must not throw the link away.
    expect(search()).toContain('highlight=sec-9');

    await waitFor(() => expect(search()).not.toContain('highlight'), { timeout: 4000 });
    expect(gridModel.asked).toHaveLength(4);
  });

  it('gives up on a row that is not in this bill and drops the link', async () => {
    await renderAt('?highlight=gone-7');

    await waitFor(() => expect(search()).not.toContain('highlight'), { timeout: 6000 });
    const tries = gridModel.asked.length;
    expect(tries).toBeGreaterThan(1);
    expect(gridModel.asked.every((id) => id === 'gone-7')).toBe(true);
    // And it stops asking once the link is gone.
    await new Promise((r) => setTimeout(r, 600));
    expect(gridModel.asked).toHaveLength(tries);
  }, 12_000);
});
