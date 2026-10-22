// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Settings > General additions: the workspace logo card is admin-only, the edit
 * button toggle saves through the branding API, the custom company colour
 * applies live with a contrast warning, and the work preferences are wired.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const apiPut = vi.fn();
vi.mock('@/shared/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/shared/lib/api')>()),
  apiPut: (...args: unknown[]) => apiPut(...args),
}));

import { useAuthStore } from '@/stores/useAuthStore';
import { useBrandingStore } from '@/stores/useBrandingStore';
import { useAppearanceStore } from '@/stores/useAppearanceStore';
import { checkAccent, customAccentCss, contrastRatio } from '@/shared/lib/customAccent';
import { landingPath, weekStartOverride } from '@/shared/lib/workPrefs';
import { getWeekStartsOn } from '@/shared/lib/weekStart';
import { WorkspaceBrandCard } from './WorkspaceBrandCard';
import { WorkPrefsCard } from './WorkPrefsCard';
import { AppearanceStyleCard } from './AppearanceStyleCard';

beforeEach(() => {
  localStorage.clear();
  apiPut.mockReset();
  useBrandingStore.getState().setOptions(null);
  useAppearanceStore.getState().followWorkspace();
  useAppearanceStore.getState().setWorkspaceDefault(null);
});

afterEach(() => useAuthStore.setState({ userRole: null } as never));

describe('<WorkspaceBrandCard>', () => {
  it('shows no controls to a non-admin', () => {
    useAuthStore.setState({ userRole: 'editor' } as never);
    render(<WorkspaceBrandCard />);
    expect(screen.queryByRole('switch')).toBeNull();
    expect(screen.queryByRole('button', { name: /Upload/ })).toBeNull();
    expect(screen.getByText(/Only an administrator/)).toBeInTheDocument();
  });

  it('lets an admin hide the edit button next to the logo', async () => {
    useAuthStore.setState({ userRole: 'admin' } as never);
    apiPut.mockResolvedValue({ show_logo_edit: false });
    render(<WorkspaceBrandCard />);
    fireEvent.click(screen.getByRole('switch', { name: 'Edit button next to the logo' }));
    await waitFor(() => expect(apiPut).toHaveBeenCalledWith('/v1/branding/', { show_logo_edit: false }));
    await waitFor(() => expect(useBrandingStore.getState().options.showLogoEdit).toBe(false));
  });
});

describe('custom company colour', () => {
  it('derives readable shades and flags a light colour', () => {
    expect(checkAccent('#0071e3').passesAA).toBe(true);
    const pale = checkAccent('#ffd400');
    expect(pale.passesAA).toBe(false);
    expect(contrastRatio(pale.accessible, '#ffffff')).toBeGreaterThanOrEqual(4.5);
    expect(customAccentCss('#ffd400')).toContain("html.dark[data-accent='custom']");
  });

  it('applies live and warns on low contrast', () => {
    render(<AppearanceStyleCard />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Hex code' }), { target: { value: '#ffd400' } });
    expect(document.documentElement.dataset.accent).toBe('custom');
    expect(screen.getByRole('status')).toHaveTextContent(/hard to read/);
    // A preset accent replaces the custom colour.
    fireEvent.click(screen.getByRole('radio', { name: 'teal' }));
    expect(document.documentElement.dataset.accent).toBe('teal');
    expect(useAppearanceStore.getState().effective.accentHex).toBeUndefined();
  });
});

describe('<WorkPrefsCard>', () => {
  it('sets the start page and the first day of the week', () => {
    render(<WorkPrefsCard />);
    fireEvent.click(screen.getByRole('radio', { name: 'Projects' }));
    fireEvent.click(screen.getByRole('radio', { name: 'Saturday' }));
    expect(landingPath()).toBe('/projects');
    expect(weekStartOverride()).toBe(6);
    expect(getWeekStartsOn()).toBe(6);
  });
});
