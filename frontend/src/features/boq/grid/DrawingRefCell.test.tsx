// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { ICellRendererParams } from 'ag-grid-community';

import { DrawingRefCellRenderer, drawingRefCellView } from './DrawingRefCell';
import { BOQFilterBar } from '../BOQFilterBar';
import {
  drawingRefLabel,
  drawingRefViewerUrl,
  isOnOutdatedDrawing,
  type DrawingRef,
  type PositionDrawingRefs,
} from '../drawingRefsApi';

function ref(over: Partial<DrawingRef> = {}): DrawingRef {
  return {
    document_id: 'd1',
    takeoff_document_id: 't1',
    sheet_id: 's1',
    drawing_number: 'A-101',
    drawing_title: 'Ground floor plan',
    revision: 'C',
    current_revision: 'C',
    page: 3,
    measurement_count: 4,
    outdated: false,
    compare: null,
    ...over,
  };
}

function entry(over: Partial<PositionDrawingRefs> = {}): PositionDrawingRefs {
  return { position_id: 'p1', ordinal: '1', outdated: false, manual: null, refs: [ref()], ...over };
}

function cell(e: PositionDrawingRefs | undefined) {
  const ctx = {
    drawingRefs: new Map(e ? [['p1', e]] : []),
    onOpenDrawingRef: vi.fn(),
    onCompareDrawingRef: vi.fn(),
    onOpenDrawingRefs: vi.fn(),
  };
  const params = { data: { id: 'p1' }, context: ctx } as unknown as ICellRendererParams;
  render(<DrawingRefCellRenderer {...params} />);
  return ctx;
}

describe('drawing reference helpers', () => {
  it('labels number and revision, and builds viewer links', () => {
    expect(drawingRefLabel({ drawing_number: 'A-101', revision: 'C' })).toBe('A-101 · rev C');
    expect(drawingRefLabel({ drawing_ref: 'S-2', drawing_revision: null })).toBe('S-2');
    expect(drawingRefViewerUrl(ref())).toBe('/takeoff?tab=measurements&doc=t1&page=3');
    expect(drawingRefViewerUrl(ref({ takeoff_document_id: null }))).toBe(
      '/takeoff?tab=measurements&doc=d1&source=document&page=3',
    );
  });

  it('counts the references behind +N', () => {
    expect(drawingRefCellView(entry({ refs: [ref(), ref({ page: 4 })], manual: { drawing_ref: 'X', drawing_revision: null } })).more).toBe(2);
  });
});

describe('<DrawingRefCellRenderer>', () => {
  it('shows number and revision and opens the sheet on click', () => {
    const ctx = cell(entry());
    const chip = screen.getByTestId('drawing-ref-chip-p1');
    expect(chip).toHaveTextContent('A-101 · rev C');
    expect(chip).toHaveAttribute('title', expect.stringMatching(/Ground floor plan · page 3/));
    fireEvent.click(chip);
    expect(ctx.onOpenDrawingRef).toHaveBeenCalledWith(expect.objectContaining({ page: 3 }));
    expect(screen.queryByTestId('drawing-ref-revised-p1')).not.toBeInTheDocument();
  });

  it('badges a revised sheet and opens the compare', () => {
    const r = ref({ outdated: true, current_revision: 'D', compare: { from_document_id: 't1', to_document_id: 't2' } });
    const ctx = cell(entry({ outdated: true, refs: [r] }));
    fireEvent.click(screen.getByTestId('drawing-ref-revised-p1'));
    expect(ctx.onCompareDrawingRef).toHaveBeenCalledWith(r);
  });

  it('shows +N for several sheets and opens the panel', () => {
    const ctx = cell(entry({ refs: [ref(), ref({ page: 4 }), ref({ page: 5 })] }));
    fireEvent.click(screen.getByText('+2'));
    expect(ctx.onOpenDrawingRefs).toHaveBeenCalledWith('p1');
  });

  it('renders a hand-entered reference as a chip', () => {
    cell(entry({ refs: [], manual: { drawing_ref: 'S-7', drawing_revision: 'B' } }));
    expect(screen.getByTestId('drawing-ref-chip-p1')).toHaveTextContent('S-7 · rev B');
  });

  it('offers an add control when the line has no reference', () => {
    const ctx = cell(undefined);
    fireEvent.click(screen.getByTestId('drawing-ref-add-p1'));
    expect(ctx.onOpenDrawingRefs).toHaveBeenCalledWith('p1');
  });
});

describe('outdated-drawing filter', () => {
  it('matches only positions on a revised sheet', () => {
    const map = new Map([
      ['p1', entry({ outdated: true })],
      ['p2', entry({ position_id: 'p2' })],
    ]);
    expect(isOnOutdatedDrawing(map, 'p1')).toBe(true);
    expect(isOnOutdatedDrawing(map, 'p2')).toBe(false);
    expect(isOnOutdatedDrawing(map, 'p3')).toBe(false);
    expect(isOnOutdatedDrawing(undefined, 'p1')).toBe(false);
  });

  it('shows the chip with the count and selects the filter', () => {
    const onFilter = vi.fn();
    render(
      <BOQFilterBar
        search=""
        onSearch={vi.fn()}
        filter="all"
        onFilter={onFilter}
        shown={5}
        total={5}
        active={false}
        onClear={vi.fn()}
        outdatedDrawingCount={3}
      />,
    );
    fireEvent.click(screen.getByText('On revised drawings (3)'));
    expect(onFilter).toHaveBeenCalledWith('drawing_revised');
  });
});
