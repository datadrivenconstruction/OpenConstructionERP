import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ClassificationPicker } from './ClassificationPicker';

describe('ClassificationPicker', () => {
  it('should render dropdown trigger with placeholder when no value', () => {
    render(
      <ClassificationPicker
        standard="din276"
        value={null}
        onSelect={vi.fn()}
        mode="dropdown"
      />,
    );
    expect(screen.getByText('Classification...')).toBeInTheDocument();
  });

  it('should render selected code when value is provided', () => {
    render(
      <ClassificationPicker
        standard="din276"
        value="330"
        onSelect={vi.fn()}
        mode="dropdown"
      />,
    );
    expect(screen.getByText('330')).toBeInTheDocument();
  });

  it('should open dropdown on click', () => {
    render(
      <ClassificationPicker
        standard="din276"
        value={null}
        onSelect={vi.fn()}
        mode="dropdown"
      />,
    );
    fireEvent.click(screen.getByText('Classification...'));
    // Should show the search input and DIN 276 label
    expect(screen.getByText('DIN276')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search...')).toBeInTheDocument();
  });

  it('should show DIN 276 tree root nodes', () => {
    render(
      <ClassificationPicker
        standard="din276"
        value={null}
        onSelect={vi.fn()}
        mode="dropdown"
      />,
    );
    fireEvent.click(screen.getByText('Classification...'));

    // Top-level DIN 276 codes
    expect(screen.getByText('100')).toBeInTheDocument();
    expect(screen.getByText('300')).toBeInTheDocument();
    expect(screen.getByText('400')).toBeInTheDocument();
    expect(screen.getByText('700')).toBeInTheDocument();
  });

  it('should show NRM tree when standard is nrm', () => {
    render(
      <ClassificationPicker
        standard="nrm"
        value={null}
        onSelect={vi.fn()}
        mode="dropdown"
      />,
    );
    fireEvent.click(screen.getByText('Classification...'));

    expect(screen.getByText('NRM')).toBeInTheDocument();
    expect(screen.getByText('Substructure')).toBeInTheDocument();
    expect(screen.getByText('Superstructure')).toBeInTheDocument();
  });

  it('should call onSelect when a node is clicked', () => {
    const onSelect = vi.fn();
    render(
      <ClassificationPicker
        standard="din276"
        value={null}
        onSelect={onSelect}
        mode="dropdown"
      />,
    );
    fireEvent.click(screen.getByText('Classification...'));

    // Click on the "100" code node
    const node100 = screen.getByText('100');
    fireEvent.click(node100);

    expect(onSelect).toHaveBeenCalledWith('100', expect.any(String));
  });

  it('should filter items by search query', () => {
    render(
      <ClassificationPicker
        standard="din276"
        value={null}
        onSelect={vi.fn()}
        mode="dropdown"
      />,
    );
    fireEvent.click(screen.getByText('Classification...'));

    const searchInput = screen.getByPlaceholderText('Search...');
    fireEvent.change(searchInput, { target: { value: 'wall' } });

    // Should find wall-related items (multiple matches expected)
    const wallItems = screen.getAllByText(/wall/i);
    expect(wallItems.length).toBeGreaterThan(0);
  });

  it('should render inline mode without trigger button', () => {
    render(
      <ClassificationPicker
        standard="din276"
        value={null}
        onSelect={vi.fn()}
        mode="inline"
      />,
    );
    // Should immediately show tree content
    expect(screen.getByText('100')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search...')).toBeInTheDocument();
  });

  it('should highlight selected value', () => {
    render(
      <ClassificationPicker
        standard="din276"
        value="300"
        onSelect={vi.fn()}
        mode="inline"
      />,
    );
    // The selected node should have the oe-blue color class
    const selected = screen.getByText('300');
    expect(selected.closest('button')).toHaveClass('bg-oe-blue/10');
  });

  it('should clear search on X button click', () => {
    render(
      <ClassificationPicker
        standard="din276"
        value={null}
        onSelect={vi.fn()}
        mode="inline"
      />,
    );
    const searchInput = screen.getByPlaceholderText('Search...');
    fireEvent.change(searchInput, { target: { value: 'concrete' } });

    // Find and click the X button
    const clearButton = searchInput.parentElement?.querySelector('button');
    if (clearButton) {
      fireEvent.click(clearButton);
      expect(searchInput).toHaveValue('');
    }
  });
});
