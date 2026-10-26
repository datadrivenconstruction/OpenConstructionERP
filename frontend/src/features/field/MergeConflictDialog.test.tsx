// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MergeConflictDialog } from './MergeConflictDialog';
import type { MergeConflict } from '@/shared/lib/offline/threeWayMerge';

const text: MergeConflict = {
  kind: 'text',
  field: 'description',
  base: 'crack',
  mine: 'crack, 2 m long',
  theirs: 'crack at gridline C',
};
const list: MergeConflict = {
  kind: 'checklist',
  field: 'checklist_data',
  items: [
    {
      id: 'a',
      base: { id: 'a', question: 'Rebar spacing', passed: true },
      mine: { id: 'a', question: 'Rebar spacing', passed: false },
      theirs: { id: 'a', question: 'Rebar spacing', passed: true, notes: 'rechecked' },
    },
  ],
};

function setup(conflicts: MergeConflict[]) {
  const onResolve = vi.fn();
  const onClose = vi.fn();
  const onKeepTheirs = vi.fn();
  render(
    <MergeConflictDialog
      open
      recordLabel="Cracked slab"
      conflicts={conflicts}
      onResolve={onResolve}
      onClose={onClose}
      onKeepTheirs={onKeepTheirs}
    />,
  );
  return { onResolve, onClose, onKeepTheirs };
}

describe('MergeConflictDialog', () => {
  it('renders nothing when closed', () => {
    render(<MergeConflictDialog open={false} conflicts={[text]} onResolve={vi.fn()} onClose={vi.fn()} />);
    expect(screen.queryByTestId('merge-conflict-dialog')).not.toBeInTheDocument();
  });

  it('shows mine and theirs side by side and blocks Apply until a side is picked', () => {
    setup([text]);
    expect(screen.getByTestId('merge-mine-description')).toHaveTextContent('crack, 2 m long');
    expect(screen.getByTestId('merge-theirs-description')).toHaveTextContent('crack at gridline C');
    expect(screen.getByText('Cracked slab')).toBeInTheDocument();
    expect(screen.getByTestId('merge-apply')).toBeDisabled();
  });

  it('resolves a long text with the server side', () => {
    const { onResolve } = setup([text]);
    fireEvent.click(screen.getByTestId('merge-theirs-description'));
    expect(screen.getByTestId('merge-theirs-description')).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByTestId('merge-apply'));
    expect(onResolve).toHaveBeenCalledWith({
      text: { description: { choice: 'theirs', value: 'crack at gridline C' } },
      checklist: {},
    });
  });

  it('resolves with a hand-merged text', () => {
    const { onResolve } = setup([text]);
    fireEvent.change(screen.getByTestId('merge-manual-description'), {
      target: { value: 'crack at gridline C, 2 m long' },
    });
    fireEvent.click(screen.getByTestId('merge-apply'));
    expect(onResolve).toHaveBeenCalledWith({
      text: { description: { choice: 'manual', value: 'crack at gridline C, 2 m long' } },
      checklist: {},
    });
  });

  it('resolves a checklist item by item', () => {
    const { onResolve } = setup([list]);
    expect(screen.getByTestId('merge-apply')).toBeDisabled();
    fireEvent.click(screen.getByTestId('merge-item-mine-a'));
    fireEvent.click(screen.getByTestId('merge-apply'));
    expect(onResolve).toHaveBeenCalledWith({ text: {}, checklist: { checklist_data: { a: 'mine' } } });
  });

  it('needs every conflict decided when text and checklist both clash', () => {
    setup([text, list]);
    fireEvent.click(screen.getByTestId('merge-mine-description'));
    expect(screen.getByTestId('merge-apply')).toBeDisabled();
    fireEvent.click(screen.getByTestId('merge-item-theirs-a'));
    expect(screen.getByTestId('merge-apply')).toBeEnabled();
  });

  it('can discard the local edit or decide later', () => {
    const { onKeepTheirs, onClose } = setup([text]);
    fireEvent.click(screen.getByTestId('merge-keep-theirs'));
    expect(onKeepTheirs).toHaveBeenCalled();
    fireEvent.click(screen.getByText('Decide later'));
    expect(onClose).toHaveBeenCalled();
  });
});
