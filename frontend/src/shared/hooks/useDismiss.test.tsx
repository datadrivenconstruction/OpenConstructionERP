import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { useDismiss } from './useDismiss';

function Dialog({ onClose, backdrop, busy }: { onClose: () => void; backdrop?: boolean; busy?: boolean }) {
  const dismiss = useDismiss({ onClose, backdrop, busy });
  return (
    <div {...dismiss} data-testid="overlay">
      <div>
        <input data-testid="field" />
      </div>
    </div>
  );
}

describe('useDismiss', () => {
  it('closes on Escape and moves focus into the dialog', () => {
    const onClose = vi.fn();
    render(<Dialog onClose={onClose} />);
    expect(document.activeElement).toBe(screen.getByTestId('field'));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes on backdrop mousedown only when enabled and only on the backdrop', () => {
    const onClose = vi.fn();
    const { rerender } = render(<Dialog onClose={onClose} />);
    fireEvent.mouseDown(screen.getByTestId('overlay'));
    expect(onClose).not.toHaveBeenCalled();
    rerender(<Dialog onClose={onClose} backdrop />);
    fireEvent.mouseDown(screen.getByTestId('field'));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.mouseDown(screen.getByTestId('overlay'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('ignores Escape and backdrop while busy', () => {
    const onClose = vi.fn();
    render(<Dialog onClose={onClose} backdrop busy />);
    fireEvent.keyDown(document, { key: 'Escape' });
    fireEvent.mouseDown(screen.getByTestId('overlay'));
    expect(onClose).not.toHaveBeenCalled();
  });

  it('only the topmost overlay reacts to Escape', () => {
    const outer = vi.fn();
    const inner = vi.fn();
    render(
      <>
        <Dialog onClose={outer} />
        <Dialog onClose={inner} />
      </>,
    );
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(inner).toHaveBeenCalledTimes(1);
    expect(outer).not.toHaveBeenCalled();
  });
});
