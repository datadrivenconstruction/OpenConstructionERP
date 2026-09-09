// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Issue #435. On a variation's bill every line carries a chip saying what it
// does to the contract and whether it traces anywhere; on an ordinary bill
// the same cell carries nothing, because the question has no meaning there.
// The renderer only paints what the host puts in the grid context, so both
// halves are asserted here: the chip for each state, and its absence when
// the context carries no trace map at all.

import type { ICellRendererParams } from 'ag-grid-community';
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { OrdinalCellRenderer, type VariationLineTraceBadge } from './cellRenderers';

const t = (k: string, o?: Record<string, string | number>) => (o?.defaultValue as string) ?? k;

function renderOrdinal(context: Record<string, unknown>, id = 'p1') {
  const params = {
    data: { id, validation_status: 'pending' },
    value: '0010',
    context: { t, ...context },
  } as unknown as ICellRendererParams;
  return render(<OrdinalCellRenderer {...params} />);
}

const REMOVED: VariationLineTraceBadge = {
  kind: 'removed',
  traced: true,
  short: 'R',
  title: 'Traced to a contract line as removed.',
};

const UNTRACED: VariationLineTraceBadge = {
  kind: 'added',
  traced: false,
  short: '?',
  title: 'Not traced yet.',
};

describe('the provenance chip on the ordinal cell', () => {
  it('paints the kind of a traced line', () => {
    const { getByTestId } = renderOrdinal({ variationTraces: { p1: REMOVED }, variationUntracedBadge: UNTRACED });
    const chip = getByTestId('boq-variation-trace-badge');
    expect(chip.textContent).toBe('R');
    expect(chip.getAttribute('data-kind')).toBe('removed');
    expect(chip.getAttribute('title')).toBe('Traced to a contract line as removed.');
  });

  it('paints the untraced chip for a line the map does not know', () => {
    const { getByTestId } = renderOrdinal({ variationTraces: {}, variationUntracedBadge: UNTRACED });
    const chip = getByTestId('boq-variation-trace-badge');
    expect(chip.textContent).toBe('?');
    expect(chip.getAttribute('data-kind')).toBe('untraced');
  });

  it('paints nothing on an ordinary bill', () => {
    const { queryByTestId } = renderOrdinal({});
    expect(queryByTestId('boq-variation-trace-badge')).toBeNull();
  });
});
