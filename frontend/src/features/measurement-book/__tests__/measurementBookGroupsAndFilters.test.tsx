// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The measurement book listed positions flat. Lines now sit under their BOQ
// sections and subsections, filter by contract (BOQ) and section, take a
// progress percentage inline, and open their measurements in a dialog.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const mocks = vi.hoisted(() => ({
  fetchPositions: vi.fn(),
  fetchEntries: vi.fn(),
  setPositionPercent: vi.fn(),
}));

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    fetchPositions: (...a: unknown[]) => mocks.fetchPositions(...a),
    fetchEntries: (...a: unknown[]) => mocks.fetchEntries(...a),
    setPositionPercent: (...a: unknown[]) => mocks.setPositionPercent(...a),
    fetchValidation: () => Promise.resolve({ status: 'passed', results: [] }),
  };
});

import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { MeasurementBookPage, buildBookRows } from '../MeasurementBookPage';
import type { PositionSummary } from '../api';

const EARTH = { id: 's1', ordinal: '01', description: 'Earthworks' };
const DIG = { id: 's11', ordinal: '01.01', description: 'Excavation' };
const MASONRY = { id: 's2', ordinal: '02', description: 'Masonry' };

function line(id: string, ordinal: string, sections: PositionSummary['sections'], boq = 'b1'): PositionSummary {
  return {
    boq_position_id: id,
    boq_id: boq,
    boq_name: boq === 'b1' ? 'Lot 1 Structure' : 'Lot 2 Finishes',
    sections,
    ordinal,
    description: `Line ${ordinal}`,
    unit: 'm3',
    boq_quantity: '10',
    unit_rate: '5',
    measured_quantity: '4',
    checked_quantity: '0',
    entry_count: 1,
    unchecked_count: 1,
    percent_measured: '40.00',
    value_to_date: '0',
  };
}

const ROWS = [
  line('p1', '01.01.010', [EARTH, DIG]),
  line('p2', '01.01.020', [EARTH, DIG]),
  line('p3', '02.010', [MASONRY]),
  line('p4', '9.010', [], 'b2'),
];

beforeEach(() => {
  useProjectContextStore.setState({ activeProjectId: 'proj-1' } as never);
  mocks.fetchPositions.mockResolvedValue(ROWS);
  mocks.fetchEntries.mockResolvedValue([]);
  mocks.setPositionPercent.mockResolvedValue(null);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function mountPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <MeasurementBookPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('buildBookRows', () => {
  it('puts each section header once, nested, before its first line', () => {
    const kinds = buildBookRows(ROWS).map((r) =>
      r.kind === 'section' ? `S${r.depth}:${r.section.ordinal}` : `P${r.depth}:${r.position.ordinal}`,
    );
    expect(kinds).toEqual(['S0:01', 'S1:01.01', 'P2:01.01.010', 'P2:01.01.020', 'S0:02', 'P1:02.010', 'P0:9.010']);
  });
});

describe('MeasurementBookPage', () => {
  it('filters by contract and by section', async () => {
    mountPage();
    await screen.findByText('Line 01.01.010');
    expect(screen.getAllByTestId('measurement-book-section')).toHaveLength(3);

    fireEvent.change(screen.getByLabelText('Contract (BOQ)'), { target: { value: 'b2' } });
    expect(screen.getAllByTestId('measurement-book-position')).toHaveLength(1);
    expect(screen.getByText('Line 9.010')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Contract (BOQ)'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Section'), { target: { value: 's11' } });
    expect(screen.getAllByTestId('measurement-book-position')).toHaveLength(2);
  });

  it('sets the percentage inline without opening the line', async () => {
    mountPage();
    await screen.findByText('Line 02.010');
    const boxes = screen.getAllByRole('spinbutton', { name: 'Set progress %' });
    fireEvent.change(boxes[2]!, { target: { value: '75' } });
    fireEvent.keyDown(boxes[2]!, { key: 'Enter' });

    await waitFor(() => expect(mocks.setPositionPercent).toHaveBeenCalledWith('proj-1', 'p3', '75'));
    expect(screen.queryByTestId('measurement-book-position-dialog')).toBeNull();
  });

  it('opens the measurements of a line in a dialog over the list', async () => {
    mountPage();
    fireEvent.click(await screen.findByText('Line 02.010'));

    expect(await screen.findByTestId('measurement-book-position-dialog')).toBeTruthy();
    expect(screen.getByTestId('measurement-book-form')).toBeTruthy();
    expect(screen.getAllByTestId('measurement-book-position')).toHaveLength(4);
  });
});
