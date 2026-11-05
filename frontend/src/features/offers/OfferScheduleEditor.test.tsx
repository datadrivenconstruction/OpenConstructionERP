import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { OfferScheduleEditor } from './OfferScheduleEditor';
import { rowsFromTemplate, type ScheduleRow } from './schedule';

function Harness({ initial, readOnly = false }: { initial: ScheduleRow[]; readOnly?: boolean }) {
  const [rows, setRows] = useState(initial);
  return <OfferScheduleEditor rows={rows} net="48350.00" currency="EUR" readOnly={readOnly} onChange={setRows} />;
}

describe('OfferScheduleEditor', () => {
  it('shows a green status for a complete schedule and announces it politely', () => {
    render(<Harness initial={rowsFromTemplate('30_40_30', '48350.00', 'EUR')} />);
    const bar = screen.getByRole('status');
    expect(bar.getAttribute('aria-live')).toBe('polite');
    expect(bar.getAttribute('data-state')).toBe('ok');
  });

  it('recomputes the amount on blur and lets the last row take the rest', () => {
    render(<Harness initial={rowsFromTemplate('30_40_30', '48350.00', 'EUR')} />);
    const percents = screen.getAllByLabelText('%');
    const first = percents[0] as HTMLElement;
    fireEvent.change(first, { target: { value: '50' } });
    fireEvent.blur(first);
    const amounts = screen.getAllByRole('textbox').filter((el) => (el as HTMLInputElement).value === '24175.00');
    expect(amounts.length).toBe(1);
    expect(screen.getByRole('status').getAttribute('data-state')).toBe('ok');
  });

  it('offers the 30 / 40 / 30 start when the schedule is empty and hides it when read-only', () => {
    const { unmount } = render(<Harness initial={[]} />);
    expect(screen.getByRole('button')).toBeTruthy();
    unmount();
    render(<Harness initial={[]} readOnly />);
    expect(screen.queryByRole('button')).toBeNull();
  });
});
