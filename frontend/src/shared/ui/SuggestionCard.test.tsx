import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { SuggestionCard } from './SuggestionCard';

describe('SuggestionCard', () => {
  it('renders the title and reason', () => {
    render(<SuggestionCard title="Add formwork position" reason="Concrete walls usually need formwork." />);
    expect(screen.getByText('Add formwork position')).toBeInTheDocument();
    expect(screen.getByText('Concrete walls usually need formwork.')).toBeInTheDocument();
  });

  it('renders Accept / Edit / Reject only for the callbacks provided', () => {
    const onAccept = vi.fn();
    render(<SuggestionCard title="x" onAccept={onAccept} />);
    expect(screen.getByText('Accept')).toBeInTheDocument();
    expect(screen.queryByText('Edit')).toBeNull();
    expect(screen.queryByText('Reject')).toBeNull();
  });

  it('calls the action handlers on click', () => {
    const onAccept = vi.fn();
    const onReject = vi.fn();
    render(<SuggestionCard title="x" onAccept={onAccept} onReject={onReject} />);
    fireEvent.click(screen.getByText('Accept'));
    fireEvent.click(screen.getByText('Reject'));
    expect(onAccept).toHaveBeenCalledTimes(1);
    expect(onReject).toHaveBeenCalledTimes(1);
  });

  it('is read-only (no buttons) when no callbacks are given', () => {
    const { container } = render(<SuggestionCard title="x" reason="y" />);
    expect(container.querySelector('button')).toBeNull();
  });

  it('shows the confidence badge when a confidence is given', () => {
    render(<SuggestionCard title="x" confidence="high" />);
    expect(screen.getByText('High confidence')).toBeInTheDocument();
  });

  it('disables the actions while busy', () => {
    render(<SuggestionCard title="x" onAccept={vi.fn()} busy />);
    expect(screen.getByText('Accept').closest('button')).toBeDisabled();
  });
});
