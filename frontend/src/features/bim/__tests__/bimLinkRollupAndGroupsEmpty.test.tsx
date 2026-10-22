// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// After linking 370 beams the viewer still said "Unlinked 534": the skeleton
// rows carry no links. And the Groups tab with no groups rendered nothing,
// collapsing the sidebar to a strip.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

vi.mock('../BIMFilterPanel', () => ({ default: () => <div data-testid="filters-body" /> }));
vi.mock('../BIMGroupsPanel', () => ({ default: () => <div data-testid="groups-body" /> }));
vi.mock('../BIMGroupByPanel', () => ({ default: () => <div data-testid="groupby-body" /> }));

import BIMFilterGroupsPanel from '../BIMFilterGroupsPanel';
import { mergeBoqLinkRollup } from '../bimLinkRollup';
import type { BIMElementData } from '@/shared/ui/BIMViewer';
import type { BIMElementGroup, BIMModelBOQLinkAggregate } from '../api';

afterEach(cleanup);

const rows = ['a', 'b', 'c'].map((id) => ({ id, name: id, element_type: 'Beam' }) as BIMElementData);

describe('mergeBoqLinkRollup', () => {
  it('marks the linked elements so the unlinked count drops', () => {
    const rollup = [
      { boq_position_id: 'p1', boq_id: 'b1', link_type: 'manual', confidence: 'high', element_ids: ['a', 'b'] },
    ] as BIMModelBOQLinkAggregate[];
    const merged = mergeBoqLinkRollup(rows, rollup);
    const unlinked = merged.filter((el) => (el.boq_links?.length ?? 0) === 0);
    expect(unlinked.map((el) => el.id)).toEqual(['c']);
    expect(merged[0]!.boq_links![0]!.boq_position_id).toBe('p1');
  });

  it('returns the rows untouched without a roll-up', () => {
    expect(mergeBoqLinkRollup(rows, undefined)).toBe(rows);
  });
});

describe('BIMFilterGroupsPanel Groups tab', () => {
  const props = {
    elements: rows,
    savedGroups: [] as BIMElementGroup[],
    projectId: 'p-1',
    onFilterChange: vi.fn(),
    onClose: vi.fn(),
  } as unknown as Parameters<typeof BIMFilterGroupsPanel>[0];

  it('shows an empty state with a way back to the filters', () => {
    render(<BIMFilterGroupsPanel {...props} />);
    fireEvent.click(screen.getByTestId('bim-filter-groups-tab-groups'));
    expect(screen.getByTestId('bim-groups-empty')).toBeTruthy();
    expect(screen.queryByTestId('groups-body')).toBeNull();
    fireEvent.click(screen.getByText('Open filters'));
    expect(screen.getByTestId('filters-body')).toBeTruthy();
  });

  it('opens on ad hoc grouping even with no saved groups', () => {
    render(<BIMFilterGroupsPanel {...props} onIsolateIds={vi.fn()} />);
    fireEvent.click(screen.getByTestId('bim-filter-groups-tab-groups'));
    expect(screen.getByTestId('groupby-body')).toBeTruthy();
    expect(screen.getByTestId('bim-groups-empty')).toBeTruthy();
  });

  it('shows the groups list when there are groups', () => {
    render(<BIMFilterGroupsPanel {...props} savedGroups={[{ id: 'g1' } as BIMElementGroup]} />);
    fireEvent.click(screen.getByTestId('bim-filter-groups-tab-groups'));
    expect(screen.getByTestId('groups-body')).toBeTruthy();
  });
});
