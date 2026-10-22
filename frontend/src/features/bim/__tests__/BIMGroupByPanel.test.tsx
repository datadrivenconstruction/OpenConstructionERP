// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';
import type { BIMElementData } from '@/shared/ui/BIMViewer';
import BIMGroupByPanel from '../BIMGroupByPanel';
import BIMPropertyFilterBar from '../BIMPropertyFilterBar';

afterEach(cleanup);

const rows = [
  { id: 'w1', element_type: 'IfcWall', storey: 'Ground Floor', properties: { '[other] category': 'Walls' }, quantities: { area: 10 } },
  { id: 'w2', element_type: 'IfcWall', storey: 'Roof', properties: { '[other] category': 'Walls' }, quantities: { area: 2 } },
  { id: 'd1', element_type: 'IfcDoor', storey: 'Ground Floor', properties: { '[other] category': 'Doors' } },
] as unknown as BIMElementData[];

describe('BIMGroupByPanel', () => {
  it('lists groups with counts and isolates and selects one on click', () => {
    const onIsolate = vi.fn();
    const onSelect = vi.fn();
    render(<BIMGroupByPanel elements={rows} onIsolate={onIsolate} onSelect={onSelect} />);
    const groups = screen.getAllByTestId('bim-groupby-row');
    expect(groups).toHaveLength(2);
    expect(groups[0]!.textContent).toContain('Walls');
    expect(groups[0]!.textContent).toContain('2');
    fireEvent.click(within(groups[0]!).getByRole('button', { pressed: false }));
    expect(onIsolate).toHaveBeenLastCalledWith(['w1', 'w2']);
    expect(onSelect).toHaveBeenLastCalledWith(['w1', 'w2']);
    // A second click shows everything again.
    fireEvent.click(within(screen.getAllByTestId('bim-groupby-row')[0]!).getByRole('button', { pressed: true }));
    expect(onIsolate).toHaveBeenLastCalledWith([]);
  });

  it('nests a second level under an expandable row', () => {
    render(<BIMGroupByPanel elements={rows} onIsolate={vi.fn()} onSelect={vi.fn()} />);
    fireEvent.change(screen.getByTestId('bim-groupby-level2'), { target: { value: 'level' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Expand' })[0]!);
    expect(screen.getAllByTestId('bim-groupby-subrow').map((r) => r.textContent)).toEqual([
      expect.stringContaining('Ground Floor'),
      expect.stringContaining('Roof'),
    ]);
  });

  it('says so when nothing passes the filters', () => {
    render(<BIMGroupByPanel elements={[]} onIsolate={vi.fn()} onSelect={vi.fn()} />);
    expect(screen.getByTestId('bim-groupby-empty')).toBeTruthy();
  });
});

describe('BIMPropertyFilterBar', () => {
  it('adds a range condition and removes chips', () => {
    const onChange = vi.fn();
    const onClearAll = vi.fn();
    const removeLevel = vi.fn();
    render(
      <BIMPropertyFilterBar
        elements={rows}
        conditions={[]}
        onChange={onChange}
        baseChips={[{ id: 's', label: 'Roof', onRemove: removeLevel }]}
        onClearAll={onClearAll}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Remove filter Roof' }));
    expect(removeLevel).toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('bim-pfilter-open'));
    fireEvent.change(screen.getByTestId('bim-pfilter-field'), { target: { value: 'qty:area' } });
    const add = screen.getByTestId('bim-pfilter-add') as HTMLButtonElement;
    expect(add.disabled).toBe(true);
    fireEvent.change(screen.getByTestId('bim-pfilter-min'), { target: { value: '5' } });
    fireEvent.click(add);
    expect(onChange).toHaveBeenCalledWith([{ field: 'qty:area', op: 'between', value: '', min: 5, max: null }]);
    fireEvent.click(screen.getByTestId('bim-pfilter-clear-all'));
    expect(onClearAll).toHaveBeenCalled();
  });
});
