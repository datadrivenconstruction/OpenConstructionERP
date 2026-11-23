import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { FindingsList } from './FindingsList';

describe('FindingsList', () => {
  it('renders nothing for an empty or missing list', () => {
    const { container, rerender } = render(<FindingsList findings={[]} />);
    expect(container.firstChild).toBeNull();
    rerender(<FindingsList findings={undefined} />);
    expect(container.firstChild).toBeNull();
  });

  it('shows message, severity and affected values', () => {
    render(
      <FindingsList
        findings={[
          { rule_id: 'r1', severity: 'error', message: 'EAC does not equal BAC / CPI', params: { eac: '120.00' } },
          { rule_id: 'r2', severity: 'warning', message: 'CPI looks implausible', suggestion: 'Check the inputs' },
        ]}
      />,
    );
    const items = screen.getAllByTestId('finding-item');
    expect(items).toHaveLength(2);
    expect(items[0]!.getAttribute('data-severity')).toBe('error');
    expect(screen.getByText(/EAC does not equal/)).toBeTruthy();
    expect(screen.getByText(/eac: 120.00/)).toBeTruthy();
    expect(screen.getByText('Check the inputs')).toBeTruthy();
  });
});
