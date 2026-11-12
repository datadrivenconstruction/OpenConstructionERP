import { render, screen, fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { SidebarToolsCollapse, SIDEBAR_TOOLS_KEY } from './SidebarToolsCollapse';

describe('SidebarToolsCollapse', () => {
  beforeEach(() => localStorage.clear());

  it('is open by default and toggles with aria-expanded, remembering the state', () => {
    const { unmount } = render(
      <SidebarToolsCollapse iconified={false}>
        <span>tools</span>
      </SidebarToolsCollapse>,
    );
    const btn = screen.getByTestId('sidebar-tools-toggle');
    expect(btn.getAttribute('aria-expanded')).toBe('true');
    fireEvent.click(btn);
    expect(btn.getAttribute('aria-expanded')).toBe('false');
    expect(screen.getByTestId('sidebar-tools-region').getAttribute('data-open')).toBe('false');
    expect(localStorage.getItem(SIDEBAR_TOOLS_KEY)).toBe('0');
    unmount();
    render(
      <SidebarToolsCollapse iconified>
        <span>tools</span>
      </SidebarToolsCollapse>,
    );
    expect(screen.getByTestId('sidebar-tools-toggle').getAttribute('aria-expanded')).toBe('false');
  });

  it('stays open while the menu editor forces it', () => {
    localStorage.setItem(SIDEBAR_TOOLS_KEY, '0');
    render(
      <SidebarToolsCollapse iconified={false} forceOpen>
        <span>tools</span>
      </SidebarToolsCollapse>,
    );
    expect(screen.getByTestId('sidebar-tools-toggle').getAttribute('aria-expanded')).toBe('true');
  });

  it('renders a single icon plus the short word when collapsed, and expands on click', () => {
    localStorage.setItem(SIDEBAR_TOOLS_KEY, '0');
    render(
      <SidebarToolsCollapse iconified={false}>
        <span>tools</span>
      </SidebarToolsCollapse>,
    );
    const btn = screen.getByTestId('sidebar-tools-toggle');
    expect(btn.textContent).toBe('System');
    expect(btn.querySelectorAll('svg').length).toBe(2);
    expect(btn.getAttribute('aria-controls')).toBe(
      screen.getByTestId('sidebar-tools-region').getAttribute('id'),
    );
    fireEvent.click(btn);
    expect(btn.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByTestId('sidebar-tools-region').getAttribute('data-open')).toBe('true');
  });
});
