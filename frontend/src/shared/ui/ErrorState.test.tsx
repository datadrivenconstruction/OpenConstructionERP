import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ErrorState } from './ErrorState';

describe('ErrorState', () => {
  it('renders the reason (why) and the hint (fix)', () => {
    render(
      <ErrorState
        title="The import file could not be read."
        hint="Check that it is a valid GAEB XML and try again."
      />,
    );
    expect(screen.getByText('The import file could not be read.')).toBeInTheDocument();
    expect(
      screen.getByText('Check that it is a valid GAEB XML and try again.'),
    ).toBeInTheDocument();
  });

  it('exposes the alert role for assistive tech', () => {
    render(<ErrorState title="Something failed" />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('shows Retry only when onRetry is given and calls it', () => {
    const onRetry = vi.fn();
    const { rerender } = render(<ErrorState title="x" />);
    expect(screen.queryByText('Retry')).toBeNull();

    rerender(<ErrorState title="x" onRetry={onRetry} />);
    fireEvent.click(screen.getByText('Retry'));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('renders a support link when supportHref is given', () => {
    render(<ErrorState title="x" supportHref="mailto:info@datadrivenconstruction.io" />);
    const link = screen.getByText('Contact support').closest('a');
    expect(link).toHaveAttribute('href', 'mailto:info@datadrivenconstruction.io');
  });
});
