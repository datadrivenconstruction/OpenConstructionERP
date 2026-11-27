import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Button } from './Button';

describe('Button disabledReason', () => {
  it('links a tooltip that opens on wrapper focus, click and hover', () => {
    const { container } = render(<Button disabledReason="Only an editor can do this.">Save</Button>);
    const btn = screen.getByRole('button', { name: 'Save' });
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute('title', 'Only an editor can do this.');
    const wrapper = container.querySelector('[data-oe-disabled-reason]') as HTMLElement;
    expect(wrapper).toHaveAttribute('tabindex', '0');
    expect(screen.queryByRole('tooltip')).toBeNull();

    fireEvent.focus(wrapper);
    const tip = screen.getByRole('tooltip');
    expect(tip).toHaveTextContent('Only an editor can do this.');
    expect(btn.getAttribute('aria-describedby')).toBe(tip.id);
    fireEvent.blur(wrapper);
    expect(screen.queryByRole('tooltip')).toBeNull();

    fireEvent.click(wrapper);
    expect(screen.getByRole('tooltip')).toBeInTheDocument();
    fireEvent.click(wrapper);
    fireEvent.mouseEnter(wrapper);
    expect(screen.getByRole('tooltip')).toBeInTheDocument();
  });

  it('adds no wrapper without a reason', () => {
    const { container } = render(<Button title="Hint">Save</Button>);
    expect(container.querySelector('[data-oe-disabled-reason]')).toBeNull();
    expect(screen.queryByRole('tooltip')).toBeNull();
    expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('title', 'Hint');
  });

  it('adds no wrapper for a plain disabled button', () => {
    const { container } = render(<Button disabled>Save</Button>);
    expect(container.querySelector('[data-oe-disabled-reason]')).toBeNull();
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
  });
});
