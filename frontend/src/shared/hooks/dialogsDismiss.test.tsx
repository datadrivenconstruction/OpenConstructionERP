import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ShareDialog } from '@/modules/collaboration/components/ShareDialog';
import { AcceptDialog } from '@/features/offers/offerParts';
import type { Offer } from '@/features/offers/api';

describe('hand-rolled dialogs dismiss on Escape', () => {
  it('ShareDialog closes on Escape and stays inert when closed', () => {
    const onClose = vi.fn();
    const { rerender } = render(<ShareDialog roomName="r" isOpen={false} onClose={onClose} />);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
    rerender(<ShareDialog roomName="r" isOpen onClose={onClose} />);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('ShareDialog closes on backdrop click and keeps focus inside', () => {
    const onClose = vi.fn();
    const { container } = render(<ShareDialog roomName="r" isOpen onClose={onClose} />);
    const overlay = container.firstElementChild as HTMLElement;
    expect(overlay.contains(document.activeElement)).toBe(true);
    fireEvent.mouseDown(overlay);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('AcceptDialog closes on Escape', () => {
    const onCancel = vi.fn();
    render(
      <AcceptDialog
        offer={{ id: 'o1', totals: { not_included: [] } } as unknown as Offer}
        canCreateContract={false}
        pending={false}
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );
    expect(screen.getByRole('dialog')).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
