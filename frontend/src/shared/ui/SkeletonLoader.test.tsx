import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SkeletonText, SkeletonCard, SkeletonTable, SkeletonGrid } from './SkeletonLoader';

describe('SkeletonText', () => {
  it('should render with default full width', () => {
    render(<SkeletonText />);
    const el = screen.getByTestId('skeleton-text');
    expect(el).toBeInTheDocument();
    expect(el.className).toContain('w-full');
  });

  it('should render with custom width class', () => {
    render(<SkeletonText width="w-3/4" />);
    const el = screen.getByTestId('skeleton-text');
    expect(el.className).toContain('w-3/4');
  });

  it('should apply custom className', () => {
    render(<SkeletonText className="mt-4" />);
    const el = screen.getByTestId('skeleton-text');
    expect(el.className).toContain('mt-4');
  });

  it('should have aria-hidden attribute', () => {
    render(<SkeletonText />);
    const el = screen.getByTestId('skeleton-text');
    expect(el).toHaveAttribute('aria-hidden', 'true');
  });

  it('should have animate-pulse class for animation', () => {
    render(<SkeletonText />);
    const el = screen.getByTestId('skeleton-text');
    expect(el.className).toContain('animate-pulse');
  });
});

describe('SkeletonCard', () => {
  it('should render a card-shaped placeholder', () => {
    render(<SkeletonCard />);
    const el = screen.getByTestId('skeleton-card');
    expect(el).toBeInTheDocument();
  });

  it('should have aria-hidden attribute', () => {
    render(<SkeletonCard />);
    const el = screen.getByTestId('skeleton-card');
    expect(el).toHaveAttribute('aria-hidden', 'true');
  });

  it('should use surface-elevated background', () => {
    render(<SkeletonCard />);
    const el = screen.getByTestId('skeleton-card');
    expect(el.className).toContain('bg-surface-elevated');
  });

  it('should apply custom className', () => {
    render(<SkeletonCard className="my-custom" />);
    const el = screen.getByTestId('skeleton-card');
    expect(el.className).toContain('my-custom');
  });
});

describe('SkeletonTable', () => {
  it('should render with default 5 rows', () => {
    render(<SkeletonTable />);
    const el = screen.getByTestId('skeleton-table');
    expect(el).toBeInTheDocument();
    const rows = screen.getAllByTestId('skeleton-table-row');
    expect(rows).toHaveLength(5);
  });

  it('should render with specified number of rows', () => {
    render(<SkeletonTable rows={3} />);
    const rows = screen.getAllByTestId('skeleton-table-row');
    expect(rows).toHaveLength(3);
  });

  it('should render with 10 rows when specified', () => {
    render(<SkeletonTable rows={10} />);
    const rows = screen.getAllByTestId('skeleton-table-row');
    expect(rows).toHaveLength(10);
  });

  it('should have aria-hidden attribute', () => {
    render(<SkeletonTable />);
    const el = screen.getByTestId('skeleton-table');
    expect(el).toHaveAttribute('aria-hidden', 'true');
  });

  it('should apply custom className', () => {
    render(<SkeletonTable className="extra" />);
    const el = screen.getByTestId('skeleton-table');
    expect(el.className).toContain('extra');
  });
});

describe('SkeletonGrid', () => {
  it('should render default 6 skeleton cards', () => {
    render(<SkeletonGrid />);
    const grid = screen.getByTestId('skeleton-grid');
    expect(grid).toBeInTheDocument();
    const cards = screen.getAllByTestId('skeleton-card');
    expect(cards).toHaveLength(6);
  });

  it('should render specified number of items', () => {
    render(<SkeletonGrid items={4} />);
    const cards = screen.getAllByTestId('skeleton-card');
    expect(cards).toHaveLength(4);
  });

  it('should render 9 items when specified', () => {
    render(<SkeletonGrid items={9} />);
    const cards = screen.getAllByTestId('skeleton-card');
    expect(cards).toHaveLength(9);
  });

  it('should have aria-hidden attribute', () => {
    render(<SkeletonGrid />);
    const grid = screen.getByTestId('skeleton-grid');
    expect(grid).toHaveAttribute('aria-hidden', 'true');
  });

  it('should use default grid columns class', () => {
    render(<SkeletonGrid />);
    const grid = screen.getByTestId('skeleton-grid');
    expect(grid.className).toContain('sm:grid-cols-2');
    expect(grid.className).toContain('lg:grid-cols-3');
  });

  it('should accept custom grid columns class', () => {
    render(<SkeletonGrid gridCols="sm:grid-cols-3 lg:grid-cols-4" />);
    const grid = screen.getByTestId('skeleton-grid');
    expect(grid.className).toContain('sm:grid-cols-3');
    expect(grid.className).toContain('lg:grid-cols-4');
  });

  it('should apply custom className', () => {
    render(<SkeletonGrid className="my-grid" />);
    const grid = screen.getByTestId('skeleton-grid');
    expect(grid.className).toContain('my-grid');
  });
});
