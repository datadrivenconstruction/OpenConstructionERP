// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Main screens of issue 554: the "Structure the bill" dialog and the recurring
 * lines panel, with their empty and error states.
 *
 * Run:  npx vitest run src/features/boq/__tests__/structureAndRecurringPanels.test.tsx
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock('react-i18next', () => {
  const t = (key: string, opts?: Record<string, unknown>) => {
    const fallback = opts?.defaultValue;
    if (typeof fallback !== 'string') return key;
    return fallback.replace(/\{\{(\w+)\}\}/g, (_m, k: string) => String(opts?.[k] ?? ''));
  };
  const value = { t, i18n: { language: 'en', changeLanguage: () => {} } };
  return {
    useTranslation: () => value,
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
    I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
  };
});

import { boqApi, type Position } from '../api';
import { StructureBillDialog } from '../StructureBillDialog';
import { RecurringLinesPanel } from '../RecurringLinesPanel';

const pos = (id: string, ordinal: string, description: string, unit: string, extra: Partial<Position> = {}): Position =>
  ({
    id,
    boq_id: 'b1',
    parent_id: null,
    sort_order: 0,
    ordinal,
    description,
    unit,
    quantity: unit === 'section' ? 0 : 2.625,
    unit_rate: unit === 'section' ? 0 : 120,
    ...extra,
  }) as unknown as Position;

const flat = [
  pos('a', '1', 'Gros oeuvre', 'pcs', { sort_order: 0, quantity: 1, unit_rate: 0 }),
  pos('b', '1.1', 'Beton', 'm3', { sort_order: 1 }),
  pos('c', '2', 'Charpente', 'pcs', { sort_order: 2, quantity: 1, unit_rate: 0 }),
  pos('d', '2.1', 'Ferme', 'u', { sort_order: 3 }),
];

const applyBtn = () => screen.getByText('Apply structure').closest('button') as HTMLButtonElement;

beforeEach(() => vi.restoreAllMocks());
afterEach(() => cleanup());

describe('StructureBillDialog', () => {
  const setup = (positions: Position[], over: Partial<React.ComponentProps<typeof StructureBillDialog>> = {}) => {
    const props = { open: true, boqId: 'b1', positions, onClose: vi.fn(), onDone: vi.fn(), onError: vi.fn(), ...over };
    render(<StructureBillDialog {...props} />);
    return props;
  };

  it('renders nothing while closed', () => {
    setup(flat, { open: false });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('lists every row and keeps Apply disabled until a level changes', () => {
    setup(flat);
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(screen.getAllByRole('combobox')).toHaveLength(4);
    expect(applyBtn().disabled).toBe(true);
  });

  it('suggests levels from the numbering and sends all rows in document order', async () => {
    const spy = vi.spyOn(boqApi, 'restructurePositions').mockResolvedValue({
      sections: 2,
      positions: 1,
      converted_to_section: 2,
      converted_to_position: 0,
    });
    const p = setup(flat);
    fireEvent.click(screen.getByText('Suggest from numbering'));
    fireEvent.click(screen.getByText('Apply structure'));
    await waitFor(() => expect(p.onDone).toHaveBeenCalled());
    expect(spy).toHaveBeenCalledWith('b1', [
      { position_id: 'a', level: 1 },
      { position_id: 'b', level: 0 },
      { position_id: 'c', level: 1 },
      { position_id: 'd', level: 0 },
    ]);
    expect(vi.mocked(p.onDone as (m: string) => void).mock.calls[0]![0]).toContain('Sections: 2');
  });

  it('a manual level choice is what gets sent', async () => {
    const spy = vi.spyOn(boqApi, 'restructurePositions').mockResolvedValue({
      sections: 1,
      positions: 2,
      converted_to_section: 1,
      converted_to_position: 0,
    });
    const p = setup(flat);
    fireEvent.change(screen.getAllByRole('combobox')[0]!, { target: { value: '3' } });
    fireEvent.click(screen.getByText('Apply structure'));
    await waitFor(() => expect(p.onDone).toHaveBeenCalled());
    expect(spy.mock.calls[0]![1][0]).toEqual({ position_id: 'a', level: 3 });
  });

  it('shows the server refusal through onError and stays open', async () => {
    vi.spyOn(boqApi, 'restructurePositions').mockRejectedValue(new Error('Linked line 1.1 cannot become a section'));
    const p = setup(flat);
    fireEvent.click(screen.getByText('Suggest from numbering'));
    fireEvent.click(screen.getByText('Apply structure'));
    await waitFor(() => expect(p.onError).toHaveBeenCalledWith('Linked line 1.1 cannot become a section'));
    expect(p.onDone).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog')).toBeTruthy();
    await waitFor(() => expect(applyBtn().disabled).toBe(false));
  });

  it('an empty bill shows an empty table and nothing to apply', () => {
    setup([]);
    expect(screen.queryAllByRole('combobox')).toHaveLength(0);
    expect(applyBtn().disabled).toBe(true);
  });

  it('existing sections show their current depth', () => {
    const nested = [
      pos('s1', '1', 'Lot', 'section', { sort_order: 0 }),
      pos('s2', '1.1', 'Sub', 'section', { sort_order: 0, parent_id: 's1' }),
      pos('l', '1.1.1', 'Line', 'm3', { sort_order: 0, parent_id: 's2' }),
    ];
    setup(nested);
    expect(screen.getAllByRole('combobox').map((s) => (s as HTMLSelectElement).value)).toEqual(['1', '2', '0']);
  });

  it('Cancel closes without calling the server', () => {
    const spy = vi.spyOn(boqApi, 'restructurePositions');
    const p = setup(flat);
    fireEvent.click(screen.getByText('Cancel'));
    expect(p.onClose).toHaveBeenCalled();
    expect(spy).not.toHaveBeenCalled();
  });
});

describe('RecurringLinesPanel', () => {
  const bill = [
    pos('1', '1.1', 'Béton C25/30', 'm3', { unit_rate: 110 }),
    pos('2', '2.1', 'Béton C25/30', 'm3', { unit_rate: 125 }),
    pos('3', '3.1', 'Coffrage', 'm2', { unit_rate: 30 }),
    pos('4', '3.2', 'Coffrage', 'm2', { unit_rate: 30 }),
    pos('5', '4', 'Lot', 'section'),
  ];
  const setup = (positions: Position[], over: Partial<React.ComponentProps<typeof RecurringLinesPanel>> = {}) => {
    const props = { open: true, boqId: 'b1', positions, onClose: vi.fn(), onDone: vi.fn(), onError: vi.fn(), ...over };
    render(<RecurringLinesPanel {...props} />);
    return props;
  };

  it('says so when no line recurs', () => {
    setup([bill[0]!, bill[2]!]);
    expect(screen.getByText('No line appears more than once in this bill.')).toBeTruthy();
  });

  it('flags only the lines priced differently', () => {
    setup(bill);
    expect(screen.getAllByLabelText('Priced differently')).toHaveLength(1);
    expect(screen.getAllByText(/Occurrences: 2/)).toHaveLength(2);
  });

  it('applies one rate to every occurrence of the line', async () => {
    const spy = vi
      .spyOn(boqApi, 'bulkUpdatePositions')
      .mockResolvedValue({ updated: 1, unchanged: 1, skipped: 0, failed_ids: [] } as never);
    const p = setup(bill);
    fireEvent.click(screen.getByText(/Béton C25\/30/));
    fireEvent.change(screen.getByLabelText('Rate'), { target: { value: '118.5' } });
    fireEvent.click(screen.getByText('Apply to all'));
    await waitFor(() => expect(p.onDone).toHaveBeenCalled());
    expect(spy).toHaveBeenCalledWith('b1', { ids: ['1', '2'], set_rate: '118.5' });
    expect(vi.mocked(p.onDone as (m: string) => void).mock.calls[0]![0]).toContain('Rate applied: 1');
  });

  it('refuses a negative or unreadable rate without calling the server', async () => {
    const spy = vi.spyOn(boqApi, 'bulkUpdatePositions');
    const p = setup(bill);
    fireEvent.click(screen.getByText(/Béton C25\/30/));
    for (const bad of ['-5', 'abc']) {
      fireEvent.change(screen.getByLabelText('Rate'), { target: { value: bad } });
      fireEvent.click(screen.getByText('Apply to all'));
    }
    await waitFor(() => expect(p.onError).toHaveBeenCalledTimes(2));
    expect(spy).not.toHaveBeenCalled();
  });

  it('reports a server failure and keeps the entered rate', async () => {
    vi.spyOn(boqApi, 'bulkUpdatePositions').mockRejectedValue(new Error('BOQ is locked'));
    const p = setup(bill);
    fireEvent.click(screen.getByText(/Béton C25\/30/));
    fireEvent.change(screen.getByLabelText('Rate'), { target: { value: '100' } });
    fireEvent.click(screen.getByText('Apply to all'));
    await waitFor(() => expect(p.onError).toHaveBeenCalledWith('BOQ is locked'));
    expect((screen.getByLabelText('Rate') as HTMLInputElement).value).toBe('100');
  });

  it('a locked bill offers no way to apply a rate', () => {
    setup(bill, { readOnly: true });
    fireEvent.click(screen.getByText(/Béton C25\/30/));
    expect(screen.queryByText('Apply to all')).toBeNull();
  });

  it('renders nothing while closed', () => {
    setup(bill, { open: false });
    expect(screen.queryByLabelText('Recurring lines')).toBeNull();
  });
});
