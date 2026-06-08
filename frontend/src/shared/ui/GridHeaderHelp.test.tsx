import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { GridHeaderHelp, type GridHeaderHelpParams } from './GridHeaderHelp';

function makeParams(overrides: Partial<GridHeaderHelpParams> = {}): GridHeaderHelpParams {
  const column = {
    getSort: () => null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  };
  return {
    displayName: 'Unit rate',
    enableSorting: true,
    column,
    progressSort: vi.fn(),
    ...overrides,
  } as unknown as GridHeaderHelpParams;
}

describe('GridHeaderHelp', () => {
  it('renders the header label', () => {
    render(<GridHeaderHelp {...makeParams()} />);
    expect(screen.getByText('Unit rate')).toBeInTheDocument();
  });

  it('progresses the sort when the sortable label is clicked', () => {
    const progressSort = vi.fn();
    render(<GridHeaderHelp {...makeParams({ progressSort })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Unit rate' }));
    expect(progressSort).toHaveBeenCalledTimes(1);
  });

  it('does not make the label a button when sorting is disabled', () => {
    render(<GridHeaderHelp {...makeParams({ enableSorting: false })} />);
    expect(screen.queryByRole('button', { name: 'Unit rate' })).toBeNull();
  });

  it('renders the help (i) trigger when helpText is given', () => {
    render(<GridHeaderHelp {...makeParams({ helpText: 'The price for one unit of work.' })} />);
    expect(screen.getByLabelText('Info')).toBeInTheDocument();
  });

  it('subscribes and unsubscribes to the column sort event', () => {
    const column = {
      getSort: () => null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    };
    const { unmount } = render(<GridHeaderHelp {...makeParams({ column: column as never })} />);
    expect(column.addEventListener).toHaveBeenCalledWith('sortChanged', expect.any(Function));
    unmount();
    expect(column.removeEventListener).toHaveBeenCalledWith('sortChanged', expect.any(Function));
  });
});
