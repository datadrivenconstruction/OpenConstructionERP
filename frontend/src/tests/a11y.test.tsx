// @ts-nocheck
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { axe, toHaveNoViolations } from 'jest-axe';
import { MemoryRouter } from 'react-router-dom';

expect.extend(toHaveNoViolations);

/** Wrapper providing Router context for components that use NavLink/Link. */
function RouterWrapper({ children }: { children: React.ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>;
}

/* ── Import components lazily to avoid side-effect issues ────────────── */

import { EmptyState } from '@/shared/ui/EmptyState';
import { SkeletonText, SkeletonCard, SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { NotFoundPage } from '@/shared/ui/NotFoundPage';

describe('Accessibility (axe-core)', () => {
  it('EmptyState should have no a11y violations', async () => {
    const { container } = render(
      <EmptyState
        icon="FolderOpen"
        title="No items found"
        description="Create your first item to get started."
      />,
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('EmptyState with action button should have no a11y violations', async () => {
    const { container } = render(
      <EmptyState
        icon="Plus"
        title="No projects"
        description="Get started by creating a project."
        action={{ label: 'Create Project', onClick: () => {} }}
      />,
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('SkeletonText should have no a11y violations', async () => {
    const { container } = render(<SkeletonText lines={3} />);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('SkeletonCard should have no a11y violations', async () => {
    const { container } = render(<SkeletonCard count={2} />);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('SkeletonTable should have no a11y violations', async () => {
    const { container } = render(<SkeletonTable rows={3} columns={4} />);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('NotFoundPage should have no a11y violations', async () => {
    const { container } = render(
      <RouterWrapper>
        <NotFoundPage />
      </RouterWrapper>,
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
