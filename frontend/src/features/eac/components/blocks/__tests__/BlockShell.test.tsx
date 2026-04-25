/**
 * BlockShell unit tests — render contract, selection state, drag attributes.
 *
 * The drag-handle button only appears when `draggable=true`. We verify that
 * the `aria-grabbed` attribute is set appropriately on the shell so screen
 * readers can announce the draggable state (WCAG 2.1 AA expectation).
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { DndContext } from '@dnd-kit/core';
import { Star } from 'lucide-react';

import { BlockShell } from '../BlockShell';

function renderWithDnd(ui: React.ReactElement) {
  return render(<DndContext>{ui}</DndContext>);
}

describe('BlockShell', () => {
  it('renders the canonical label and icon when no overrides are passed', () => {
    renderWithDnd(<BlockShell color="selector" />);
    // Default label for the selector color is "Selector"
    expect(screen.getByText('Selector')).toBeInTheDocument();
    // role=group with the same label on aria-label
    expect(screen.getByRole('group', { name: 'Selector' })).toBeInTheDocument();
  });

  it('renders a custom label and a custom icon when provided', () => {
    renderWithDnd(
      <BlockShell color="logic" label="My logic block" icon={<Star data-testid="custom-icon" />} />,
    );
    expect(screen.getByText('My logic block')).toBeInTheDocument();
    expect(screen.getByTestId('custom-icon')).toBeInTheDocument();
  });

  it('applies aria-selected when selected=true', () => {
    renderWithDnd(<BlockShell color="attribute" selected onSelect={vi.fn()} />);
    const group = screen.getByRole('group');
    expect(group).toHaveAttribute('aria-selected', 'true');
    expect(group).toHaveAttribute('data-block-selected', 'true');
  });

  it('omits aria-selected when not selected', () => {
    renderWithDnd(<BlockShell color="attribute" />);
    expect(screen.getByRole('group')).not.toHaveAttribute('aria-selected');
  });

  it('renders drag handle and aria-grabbed=false when draggable=true', () => {
    renderWithDnd(<BlockShell color="constraint" draggable sortableId="b1" />);
    const handle = screen.getByTestId('eac-block-drag-handle');
    expect(handle).toBeInTheDocument();
    // Not currently being dragged → aria-grabbed=false
    expect(screen.getByRole('group')).toHaveAttribute('aria-grabbed', 'false');
  });

  it('does not render drag handle when draggable=false', () => {
    renderWithDnd(<BlockShell color="variable" />);
    expect(screen.queryByTestId('eac-block-drag-handle')).toBeNull();
    expect(screen.getByRole('group')).not.toHaveAttribute('aria-grabbed');
  });

  it('fires onSelect on click when handler is provided', () => {
    const handler = vi.fn();
    renderWithDnd(<BlockShell color="selector" onSelect={handler} />);
    fireEvent.click(screen.getByRole('group'));
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('fires onSelect on Enter and Space keypress', () => {
    const handler = vi.fn();
    renderWithDnd(<BlockShell color="selector" onSelect={handler} />);
    const group = screen.getByRole('group');
    fireEvent.keyDown(group, { key: 'Enter' });
    fireEvent.keyDown(group, { key: ' ' });
    expect(handler).toHaveBeenCalledTimes(2);
  });

  it('exposes the color via data-block-color for downstream selectors', () => {
    renderWithDnd(<BlockShell color="logic" />);
    expect(screen.getByRole('group')).toHaveAttribute('data-block-color', 'logic');
  });
});
