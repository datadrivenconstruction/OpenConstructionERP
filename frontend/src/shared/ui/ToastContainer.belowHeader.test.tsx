import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ToastContainer } from './ToastContainer';
import { useToastStore } from '@/stores/useToastStore';

describe('toast stack position', () => {
  beforeEach(() => {
    useToastStore.setState({ toasts: [] });
  });

  it('starts below the top bar, not over it', () => {
    useToastStore.getState().addToast({ type: 'success', title: 'Saved' });
    render(<ToastContainer />);
    const stack = screen.getByTestId('toast-stack');
    expect(stack.className).not.toMatch(/\btop-4\b/);
    expect(stack.style.top).toContain('var(--oe-header-height');
  });
});
