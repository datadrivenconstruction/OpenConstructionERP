// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The "Menu look" card: styles are a radiogroup a keyboard and a screen reader
 * can use, pointing at a style previews it on <html> and leaving restores the
 * chosen look, an option change reads as Custom, and an admin saves only the
 * menu part of the workspace appearance.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

const apiPut = vi.fn().mockResolvedValue({});
vi.mock('@/shared/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/shared/lib/api')>()),
  apiPut: (...args: unknown[]) => apiPut(...args),
}));

import { useAppearanceStore } from '@/stores/useAppearanceStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { MENU_PRESETS, PLATFORM_MENU } from '@/shared/lib/menuAppearance';
import { MenuAppearanceCard } from './MenuAppearanceCard';

const html = () => document.documentElement.dataset;

function styles() {
  return within(screen.getByRole('radiogroup', { name: 'Menu look' }));
}

beforeEach(() => {
  localStorage.clear();
  useAppearanceStore.getState().followWorkspaceMenu();
  useAppearanceStore.getState().setWorkspaceMenu(null);
  useAppearanceStore.getState().resetIconOverrides();
  apiPut.mockClear();
});

afterEach(() => useAuthStore.setState({ userRole: null } as never));

describe('<MenuAppearanceCard>', () => {
  it('offers the six styles plus Custom as radios, Classic checked', () => {
    render(<MenuAppearanceCard />);
    const radios = styles().getAllByRole('radio');
    expect(radios).toHaveLength(MENU_PRESETS.length + 1);
    expect(styles().getByRole('radio', { name: /Classic/ })).toHaveAttribute('aria-checked', 'true');
    expect(styles().getByRole('radio', { name: /Custom/ })).toHaveAttribute('aria-checked', 'false');
  });

  it('previews a style on focus, restores on blur, keeps it on Enter/click', () => {
    render(<MenuAppearanceCard />);
    const site = styles().getByRole('radio', { name: /Site office/ });
    fireEvent.focus(site);
    expect(html().menuColor).toBe('sections');
    fireEvent.blur(site);
    expect(html().menuColor).toBe(PLATFORM_MENU.color);

    fireEvent.click(site);
    expect(site).toHaveAttribute('aria-checked', 'true');
    expect(useAppearanceStore.getState().menu).toEqual(MENU_PRESETS.find((p) => p.id === 'site_office')!.value);
    expect(html().menuView).toBe('comfortable');
  });

  it('an option change after a style reads as Custom; Reset goes back', () => {
    render(<MenuAppearanceCard />);
    fireEvent.click(styles().getByRole('radio', { name: /Studio/ }));
    const weight = screen.getByRole('radiogroup', { name: 'Icon weight' });
    const bold = within(weight).getByRole('radio', { name: 'Bold' });
    fireEvent.click(bold);
    expect(bold).toHaveAttribute('aria-checked', 'true');
    expect(styles().getByRole('radio', { name: /Custom/ })).toHaveAttribute('aria-checked', 'true');
    expect(html().menuStroke).toBe('bold');

    fireEvent.click(screen.getByRole('button', { name: /Reset to default/ }));
    expect(useAppearanceStore.getState().menu).toEqual(PLATFORM_MENU);
    expect(styles().getByRole('radio', { name: /Classic/ })).toHaveAttribute('aria-checked', 'true');
  });

  it('every option group is a labelled radiogroup', () => {
    render(<MenuAppearanceCard />);
    const groups = ['Layout', 'Current item', 'Section headers', 'Icon weight', 'Icon shape', 'Icon colour', 'Icons'];
    for (const name of groups) {
      const group = screen.getByRole('radiogroup', { name });
      expect(within(group).getAllByRole('radio').some((r) => r.getAttribute('aria-checked') === 'true')).toBe(true);
    }
  });

  it('lists overridden item icons with a reset', () => {
    useAppearanceStore.getState().setIconOverride('/boq', 'Calculator');
    render(<MenuAppearanceCard />);
    const reset = screen.getByRole('button', { name: /Reset the icon of/ });
    fireEvent.click(reset);
    expect(useAppearanceStore.getState().iconOverrides).toEqual({});
  });

  it('admins save the menu look alone as the workspace default', async () => {
    useAuthStore.setState({ userRole: 'admin' } as never);
    render(<MenuAppearanceCard />);
    fireEvent.click(styles().getByRole('radio', { name: /Executive/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Set as workspace default' }));
    const executive = MENU_PRESETS.find((p) => p.id === 'executive')!.value;
    expect(apiPut).toHaveBeenCalledWith('/v1/branding/', { appearance: { menu: executive } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Set as workspace default' })).toBeEnabled());
    expect(useAppearanceStore.getState().menuWorkspace).toEqual(executive);
  });
});
