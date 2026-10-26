// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { defaultFilterPref, initialFilter } from '@/shared/lib/defaultFilters';
import { SaveDefaultFilter } from '../SaveDefaultFilter';

const neutral = { type: '', mine: false };

beforeEach(() => {
  localStorage.clear();
  defaultFilterPref.reset();
});

describe('initialFilter', () => {
  it('is the neutral filter when nothing was saved', () => {
    expect(initialFilter('tasks', neutral)).toEqual(neutral);
  });

  it('lays the saved fields over the neutral ones and ignores fields of the wrong kind', () => {
    defaultFilterPref.write({ tasks: { type: 'safety', mine: 'yes' as unknown as boolean } });
    expect(initialFilter('tasks', neutral)).toEqual({ type: 'safety', mine: false });
  });

  it('drops unknown pages and non-primitive values from storage', () => {
    const stop = defaultFilterPref.subscribe(() => {});
    localStorage.setItem('oe_default_filters_v1', JSON.stringify({ nope: { a: 'b' }, rfi: { status: ['x'], view: 'mine' } }));
    window.dispatchEvent(new StorageEvent('storage', { key: 'oe_default_filters_v1' }));
    stop();
    expect(defaultFilterPref.read()).toEqual({ rfi: { view: 'mine' } });
  });
});

describe('<SaveDefaultFilter>', () => {
  it('renders nothing while nothing is narrowed and nothing is saved', () => {
    const { container } = render(<SaveDefaultFilter page="tasks" current={neutral} neutral={neutral} />);
    expect(container.firstChild).toBeNull();
  });

  it('saves the filters on screen, then offers only Clear', () => {
    const current = { type: 'safety', mine: true };
    const { rerender } = render(<SaveDefaultFilter page="tasks" current={current} neutral={neutral} />);
    fireEvent.click(screen.getByRole('button', { name: 'Save as my default' }));
    expect(defaultFilterPref.read().tasks).toEqual(current);
    rerender(<SaveDefaultFilter page="tasks" current={current} neutral={neutral} />);
    expect(screen.queryByRole('button', { name: 'Save as my default' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Clear my default' }));
    expect(defaultFilterPref.read().tasks).toBeUndefined();
  });

  it('keeps other pages when one is cleared', () => {
    defaultFilterPref.write({ tasks: { type: 'a', mine: false }, rfi: { status: 'open' } });
    render(<SaveDefaultFilter page="tasks" current={neutral} neutral={neutral} />);
    fireEvent.click(screen.getByRole('button', { name: 'Clear my default' }));
    expect(defaultFilterPref.read()).toEqual({ rfi: { status: 'open' } });
  });
});
