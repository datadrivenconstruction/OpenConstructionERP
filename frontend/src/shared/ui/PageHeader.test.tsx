/**
 * PageHeader keeps one action row: more than five actions collapse the
 * secondaries past the fourth into a "More actions" menu; primaries stay.
 */
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { PageHeader } from './PageHeader';
import { Button } from './Button';

function actions(n: number, primaryAt = -1) {
  return (
    <>
      {Array.from({ length: n }, (_, i) => (
        <Button key={i} variant={i === primaryAt ? 'primary' : 'secondary'}>
          {`A${i}`}
        </Button>
      ))}
    </>
  );
}

describe('PageHeader actions overflow', () => {
  it('shows up to five actions inline without a menu', () => {
    render(<PageHeader subtitle="s" actions={actions(5)} />);
    expect(screen.getAllByRole('button')).toHaveLength(5);
    expect(screen.queryByTestId('page-header-overflow')).toBeNull();
  });

  it('moves the rest into the menu and keeps the primary visible', () => {
    render(<PageHeader subtitle="s" actions={actions(8, 7)} />);
    expect(screen.getByText('A7')).toBeTruthy();
    expect(screen.getByText('A2')).toBeTruthy();
    // Overflowed actions stay mounted (their dialogs survive) inside the closed menu.
    expect(screen.queryByRole('menu')).toBeNull();
    expect(screen.getByText('A3').closest('[role="menu"]')?.getAttribute('aria-hidden')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'More actions' }));
    expect(screen.getByRole('menu')).toBeTruthy();
    expect(screen.getByText('A6')).toBeTruthy();
    fireEvent.click(screen.getByText('A6'));
    expect(screen.queryByRole('menu')).toBeNull();
  });
});
