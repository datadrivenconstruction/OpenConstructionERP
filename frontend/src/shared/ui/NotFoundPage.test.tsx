// @ts-nocheck
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { NotFoundPage } from './NotFoundPage';

function renderWithRouter() {
  return render(
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <NotFoundPage />
    </BrowserRouter>,
  );
}

describe('NotFoundPage', () => {
  it('should render 404 text', () => {
    renderWithRouter();
    expect(screen.getByText('404')).toBeInTheDocument();
  });

  it('should show "Page not found" heading', () => {
    renderWithRouter();
    expect(screen.getByText('Page not found')).toBeInTheDocument();
  });

  it('should show description text', () => {
    renderWithRouter();
    expect(screen.getByText(/does not exist or has been moved/)).toBeInTheDocument();
  });

  it('should have Go back button', () => {
    renderWithRouter();
    expect(screen.getByText('Go back')).toBeInTheDocument();
  });

  it('should have Dashboard link', () => {
    renderWithRouter();
    const dashboardLink = screen.getByText('Dashboard');
    expect(dashboardLink).toBeInTheDocument();
    expect(dashboardLink.closest('a')).toHaveAttribute('href', '/');
  });
});
