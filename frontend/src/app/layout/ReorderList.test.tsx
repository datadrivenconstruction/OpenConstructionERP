import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ReorderList } from './ReorderList';
import { NavItemBadge, registerNavItemBadge } from './NavItemBadge';
import { act } from 'react';

const entries = [
  { id: 'a', label: 'Alpha' },
  { id: 'b', label: 'Beta' },
  { id: 'c', label: 'Gamma' },
];

describe('ReorderList', () => {
  it('moves a row with Alt+Arrow keys', () => {
    const onMove = vi.fn();
    render(<ReorderList entries={entries} onMove={onMove} testId="l" />);
    const row = screen.getByTestId('l-row-b');
    fireEvent.keyDown(row, { key: 'ArrowDown', altKey: true });
    expect(onMove).toHaveBeenLastCalledWith(1, 2);
    fireEvent.keyDown(row, { key: 'ArrowUp', altKey: true });
    expect(onMove).toHaveBeenLastCalledWith(1, 0);
    fireEvent.keyDown(row, { key: 'ArrowDown' });
    expect(onMove).toHaveBeenCalledTimes(2);
  });

  it('ignores moves past the ends', () => {
    const onMove = vi.fn();
    render(<ReorderList entries={entries} onMove={onMove} testId="l" />);
    fireEvent.keyDown(screen.getByTestId('l-row-a'), { key: 'ArrowUp', altKey: true });
    expect(onMove).not.toHaveBeenCalled();
  });

  it('moves a row by drag and drop', () => {
    const onMove = vi.fn();
    render(<ReorderList entries={entries} onMove={onMove} testId="l" />);
    const dataTransfer = { setData: vi.fn(), effectAllowed: '' };
    fireEvent.dragStart(screen.getByTestId('l-row-c'), { dataTransfer });
    fireEvent.dragOver(screen.getByTestId('l-row-a'), { dataTransfer });
    fireEvent.drop(screen.getByTestId('l-row-a'), { dataTransfer });
    expect(onMove).toHaveBeenCalledWith(2, 0);
  });
});

describe('NavItemBadge', () => {
  it('renders nothing until a badge is registered for the route', () => {
    const { container } = render(<NavItemBadge itemId="/rfi" />);
    expect(container.innerHTML).toBe('');
    let off = () => {};
    act(() => {
      off = registerNavItemBadge('/rfi', ({ itemId }) => <span>badge {itemId}</span>);
    });
    expect(screen.getByText('badge /rfi')).toBeTruthy();
    act(() => off());
    expect(container.innerHTML).toBe('');
  });
});
