import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { PlugCell, PlugTotalsRows, LevelingCheckBanner, PackageTypeField } from './LevelingPlugs';
import type { BidLevelingRow, LevelingPlug } from './api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, second?: string | { defaultValue?: string }) =>
      typeof second === 'string' ? second : (second?.defaultValue ?? key),
  }),
}));
vi.mock('@/shared/ui/MoneyDisplay', () => ({
  MoneyDisplay: ({ amount }: { amount: number }) => <span>{`M${amount}`}</span>,
}));

afterEach(cleanup);

const plug = (over: Partial<LevelingPlug> = {}): LevelingPlug => ({
  id: 'p1',
  bidder_id: 'b1',
  line_item_id: 'l1',
  amount: '120.5',
  source: 'median',
  reason: 'missing',
  note: '',
  ...over,
});

describe('PlugCell', () => {
  it('renders amount, dashed style and source badge', () => {
    render(<PlugCell plug={plug()} onSave={vi.fn()} />);
    expect(screen.getByTestId('plug-cell').className).toContain('border-dashed');
    expect(screen.getByTestId('plug-source').textContent).toBe('Median of bids');
    expect(screen.getByText('M120.5')).toBeTruthy();
    expect(screen.queryByLabelText('Clear manual plug')).toBeNull();
  });

  it('saves a manual override as a decimal string', () => {
    const onSave = vi.fn();
    render(<PlugCell plug={plug()} onSave={onSave} />);
    fireEvent.click(screen.getByTitle('Override this plug'));
    fireEvent.change(screen.getByLabelText('Plug amount'), { target: { value: '99.9' } });
    fireEvent.click(screen.getByText('Save'));
    expect(onSave).toHaveBeenCalledWith('99.9');
  });

  it('clears a manual plug with null', () => {
    const onSave = vi.fn();
    render(<PlugCell plug={plug({ source: 'manual' })} onSave={onSave} />);
    expect(screen.getByTestId('plug-source').textContent).toBe('Manual');
    fireEvent.click(screen.getByLabelText('Clear manual plug'));
    expect(onSave).toHaveBeenCalledWith(null);
  });
});

describe('PlugTotalsRows', () => {
  it('shows totals without and with plugs and gap counts', () => {
    const rows = [
      { bidder_id: 'b1', raw_total: '100', normalized_total: '150', plugged_total: '150', gap_lines: 3, unpriced_gap_lines: 1 },
    ] as unknown as BidLevelingRow[];
    render(
      <table>
        <tbody>
          <PlugTotalsRows columns={[{ id: 'b1', name: 'A' }]} rows={rows} />
        </tbody>
      </table>,
    );
    expect(screen.getByTestId('total-without-plugs').textContent).toContain('M100');
    expect(screen.getByTestId('total-with-plugs').textContent).toContain('M150');
    expect(screen.getByTestId('gap-counts').textContent).toContain('3 (1)');
  });
});

describe('LevelingCheckBanner', () => {
  it('shows only failed results', () => {
    render(
      <LevelingCheckBanner
        check={{
          status: 'warning',
          counts: {},
          results: [
            { rule_id: 'a', severity: 'warning', passed: false, message: 'Plug share is high' },
            { rule_id: 'b', severity: 'warning', passed: true, message: 'All fine' },
          ],
        }}
      />,
    );
    expect(screen.getByText('Plug share is high')).toBeTruthy();
    expect(screen.queryByText('All fine')).toBeNull();
  });

  it('renders nothing when all passed', () => {
    const { container } = render(<LevelingCheckBanner check={{ status: 'ok', counts: {}, results: [] }} />);
    expect(container.firstChild).toBeNull();
  });
});

describe('PackageTypeField', () => {
  it('explains the chosen type and can be disabled', () => {
    const onChange = vi.fn();
    const { rerender } = render(<PackageTypeField value="subcontract" onChange={onChange} />);
    expect(screen.getByTestId('package-type-hint').textContent).toContain('subcontract agreement');
    fireEvent.change(screen.getByLabelText('Package type'), { target: { value: 'supply' } });
    expect(onChange).toHaveBeenCalledWith('supply');
    rerender(<PackageTypeField value="supply" onChange={onChange} disabled />);
    expect(screen.getByTestId('package-type-hint').textContent).toContain('purchase order');
    expect((screen.getByLabelText('Package type') as HTMLSelectElement).disabled).toBe(true);
  });
});
