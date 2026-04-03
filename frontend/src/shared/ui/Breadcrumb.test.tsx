import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { Breadcrumb } from './Breadcrumb';

function renderBreadcrumb(items: { label: string; to?: string }[]) {
  return render(
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Breadcrumb items={items} />
    </BrowserRouter>,
  );
}

describe('Breadcrumb', () => {
  it('should render nothing when items array is empty', () => {
    const { container } = renderBreadcrumb([]);
    expect(container.querySelector('nav')).toBeNull();
  });

  it('should render home icon link', () => {
    renderBreadcrumb([{ label: 'Page' }]);
    const homeLink = screen.getByLabelText('Dashboard');
    expect(homeLink).toBeInTheDocument();
    expect(homeLink).toHaveAttribute('href', '/');
  });

  it('should render a single item as non-link', () => {
    renderBreadcrumb([{ label: 'Current Page' }]);
    expect(screen.getByText('Current Page')).toBeInTheDocument();
    expect(screen.getByText('Current Page').closest('a')).toBeNull();
  });

  it('should render intermediate items as links', () => {
    renderBreadcrumb([
      { label: 'Projects', to: '/projects' },
      { label: 'My Project' },
    ]);
    const link = screen.getByText('Projects');
    expect(link.closest('a')).toHaveAttribute('href', '/projects');
    // Last item should not be a link
    expect(screen.getByText('My Project').closest('a')).toBeNull();
  });

  it('should render three-level breadcrumb', () => {
    renderBreadcrumb([
      { label: 'Projects', to: '/projects' },
      { label: 'Project A', to: '/projects/1' },
      { label: 'BOQ Editor' },
    ]);
    expect(screen.getByText('Projects')).toBeInTheDocument();
    expect(screen.getByText('Project A')).toBeInTheDocument();
    expect(screen.getByText('BOQ Editor')).toBeInTheDocument();
  });
});
