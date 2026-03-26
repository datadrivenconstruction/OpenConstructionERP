import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { EmptyState } from './EmptyState';

describe('EmptyState', () => {
  it('renders icon, title, and description', () => {
    render(
      <EmptyState
        icon={<span data-testid="test-icon">icon</span>}
        title="No items found"
        description="Try adjusting your search"
      />,
    );

    expect(screen.getByTestId('test-icon')).toBeInTheDocument();
    expect(screen.getByText('No items found')).toBeInTheDocument();
    expect(screen.getByText('Try adjusting your search')).toBeInTheDocument();
  });

  it('renders action button from { label, onClick } and calls onClick when clicked', () => {
    const handleClick = vi.fn();

    render(
      <EmptyState
        icon={<span>icon</span>}
        title="Empty"
        action={{ label: 'Create Item', onClick: handleClick }}
      />,
    );

    const button = screen.getByText('Create Item');
    expect(button).toBeInTheDocument();

    fireEvent.click(button);
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('renders without action (no button shown)', () => {
    const { container } = render(
      <EmptyState icon={<span>icon</span>} title="Nothing here" />,
    );

    // There should be no button element rendered
    expect(container.querySelector('button')).toBeNull();
  });

  it('renders without description', () => {
    const { container } = render(
      <EmptyState icon={<span>icon</span>} title="Title only" />,
    );

    expect(screen.getByText('Title only')).toBeInTheDocument();
    // Verify there is no <p> tag (description container)
    const paragraphs = container.querySelectorAll('p');
    expect(paragraphs.length).toBe(0);
  });

  it('renders ReactNode action for backward compatibility', () => {
    const handleClick = vi.fn();

    render(
      <EmptyState
        icon={<span>icon</span>}
        title="Empty"
        action={<button onClick={handleClick}>Custom Button</button>}
      />,
    );

    const button = screen.getByText('Custom Button');
    expect(button).toBeInTheDocument();

    fireEvent.click(button);
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('renders without icon', () => {
    render(<EmptyState title="No icon state" description="Some text" />);

    expect(screen.getByText('No icon state')).toBeInTheDocument();
    expect(screen.getByText('Some text')).toBeInTheDocument();
  });

  it('applies custom className', () => {
    const { container } = render(
      <EmptyState title="Custom class" className="my-custom-class" />,
    );

    const wrapper = container.firstElementChild!;
    expect(wrapper.classList.contains('my-custom-class')).toBe(true);
  });
});
