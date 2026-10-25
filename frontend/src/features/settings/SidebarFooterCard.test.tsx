// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The "Sidebar footer" card: one switch per footer button, all on by default,
 * route tiles go through the per-user hidden list, the others stay on this
 * device, and the card says where Settings stays reachable.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

const hidden = vi.hoisted(() => ({ list: [] as string[], set: vi.fn() }));
vi.mock('@/shared/hooks/useHiddenModules', () => ({
  useHiddenModules: () => ({ hiddenModules: hidden.list, setHiddenModules: hidden.set, isLoading: false }),
}));

import { SidebarFooterCard } from './SidebarFooterCard';
import { FOOTER_PREFS_KEY, readFooterPrefs, resetFooterPrefsCache } from '@/shared/lib/footerPrefs';

const sw = (label: string) => screen.getByRole('switch', { name: `Show ${label} in the sidebar footer` });

beforeEach(() => {
  localStorage.clear();
  resetFooterPrefsCache();
  hidden.list = [];
  hidden.set.mockClear();
});

afterEach(() => cleanup());

describe('<SidebarFooterCard>', () => {
  it('lists the six footer buttons, all switched on by default', () => {
    render(<SidebarFooterCard />);
    expect(screen.getAllByRole('switch')).toHaveLength(6);
    for (const label of ['Settings', 'Users', 'Edit menu', 'About', 'GitHub', 'Community']) {
      expect(sw(label)).toHaveAttribute('aria-checked', 'true');
    }
  });

  it('keeps Edit menu, GitHub and Community on this device and shows the change at once', () => {
    render(<SidebarFooterCard />);
    fireEvent.click(sw('GitHub'));
    expect(sw('GitHub')).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(sw('Edit menu'));
    expect(JSON.parse(localStorage.getItem(FOOTER_PREFS_KEY)!)).toEqual({
      editMenu: true,
      github: true,
      community: false,
    });
    expect(readFooterPrefs().github).toBe(true);
    expect(hidden.set).not.toHaveBeenCalled();
    fireEvent.click(sw('GitHub'));
    expect(sw('GitHub')).toHaveAttribute('aria-checked', 'true');
  });

  it('hides Settings, Users and About through the per-user hidden list and restores them', () => {
    const { rerender } = render(<SidebarFooterCard />);
    fireEvent.click(sw('Settings'));
    expect(hidden.set).toHaveBeenLastCalledWith(['/settings']);

    hidden.list = ['/settings', '/about', '/boq'];
    rerender(<SidebarFooterCard />);
    expect(sw('Settings')).toHaveAttribute('aria-checked', 'false');
    expect(sw('About')).toHaveAttribute('aria-checked', 'false');
    expect(sw('Users')).toHaveAttribute('aria-checked', 'true');
    fireEvent.click(sw('Settings'));
    expect(hidden.set).toHaveBeenLastCalledWith(['/about', '/boq']);
  });

  it('says that Settings stays reachable from the profile menu', () => {
    render(<SidebarFooterCard />);
    expect(screen.getByText(/profile menu at the top right/i)).toBeTruthy();
  });

  it('ignores a damaged stored value and falls back to everything shown', () => {
    localStorage.setItem(FOOTER_PREFS_KEY, '{"github":"yes","editMenu":42}');
    resetFooterPrefsCache();
    expect(readFooterPrefs()).toEqual({ editMenu: false, github: false, community: false });
  });
});
