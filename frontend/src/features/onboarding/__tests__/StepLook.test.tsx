// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The optional "How your platform will look" step: cards drive a live preview,
 * nothing is applied before Apply, Skip keeps the defaults, and an admin also
 * saves the workspace default.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const apiPut = vi.fn().mockResolvedValue({});
vi.mock('@/shared/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/shared/lib/api')>()),
  apiPut: (...args: unknown[]) => apiPut(...args),
}));

import { useAppearanceStore } from '@/stores/useAppearanceStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { APPEARANCE_PRESETS, PLATFORM_APPEARANCE } from '@/shared/lib/appearance';
import { MENU_PRESETS, PLATFORM_MENU } from '@/shared/lib/menuAppearance';
import { StepLook } from '../StepLook';

const preview = () => screen.getByTestId('look-preview');

beforeEach(() => {
  localStorage.clear();
  const s = useAppearanceStore.getState();
  s.followWorkspace();
  s.setWorkspaceDefault(null);
  s.followWorkspaceMenu();
  s.setWorkspaceMenu(null);
  apiPut.mockClear();
});

afterEach(() => {
  cleanup();
  useAuthStore.setState({ userRole: null } as never);
});

function renderStep() {
  const onNext = vi.fn();
  const onBack = vi.fn();
  render(<StepLook onNext={onNext} onBack={onBack} />);
  return { onNext, onBack };
}

describe('<StepLook>', () => {
  it('offers every ready style, menu set and accent as radios in three groups', () => {
    renderStep();
    expect(screen.getAllByRole('radiogroup')).toHaveLength(3);
    expect(screen.getByRole('radiogroup', { name: 'Colour style' }).querySelectorAll('[role="radio"]')).toHaveLength(
      APPEARANCE_PRESETS.length,
    );
    expect(screen.getByRole('radiogroup', { name: 'Menu view' }).querySelectorAll('[role="radio"]')).toHaveLength(
      MENU_PRESETS.length,
    );
    expect(screen.getAllByRole('radio', { name: 'Classic' }).every((r) => r.getAttribute('aria-checked') === 'true')).toBe(true);
  });

  it('updates the preview at once when a style, a menu or an accent is picked', () => {
    renderStep();
    expect(preview().dataset.accent).toBe(PLATFORM_APPEARANCE.accent);
    expect(preview().dataset.view).toBe(PLATFORM_MENU.view);

    const styleGroup = screen.getByRole('radiogroup', { name: 'Colour style' });
    fireEvent.click(styleGroup.querySelector('[aria-label="Studio"]')!);
    expect(preview().dataset.accent).toBe('violet');
    expect(preview().dataset.font).toBe('inter');
    expect(preview().dataset.radius).toBe('round');

    const menus = screen.getByRole('radiogroup', { name: 'Menu view' });
    fireEvent.click(menus.querySelector('[aria-label="Executive"]')!);
    expect(preview().dataset.view).toBe('floating');

    fireEvent.click(screen.getByRole('radio', { name: 'amber' }));
    expect(preview().dataset.accent).toBe('amber');
    // A custom mix: no ready style is checked any more.
    const styles = screen.getByRole('radiogroup', { name: 'Colour style' });
    expect(styles.querySelector('[aria-checked="true"]')).toBeNull();
  });

  it('applies nothing to the app before Apply', () => {
    renderStep();
    fireEvent.click(screen.getByRole('radio', { name: 'crimson' }));
    expect(useAppearanceStore.getState().effective.accent).toBe(PLATFORM_APPEARANCE.accent);
    expect(useAppearanceStore.getState().user).toBeNull();
  });

  it('moves the choice with the arrow keys, rolling the tab stop', () => {
    renderStep();
    const accents = screen.getByRole('radiogroup', { name: 'Accent colour' });
    const first = accents.querySelector<HTMLButtonElement>('[role="radio"]')!;
    first.focus();
    expect(first.tabIndex).toBe(0);
    fireEvent.keyDown(first, { key: 'ArrowRight' });
    const second = accents.querySelectorAll<HTMLButtonElement>('[role="radio"]')[1]!;
    expect(second.getAttribute('aria-checked')).toBe('true');
    expect(second.tabIndex).toBe(0);
    expect(first.tabIndex).toBe(-1);
    expect(preview().dataset.accent).toBe('teal');
  });

  it('Apply writes the picks through the store and moves on, without a server call for a non-admin', async () => {
    const { onNext } = renderStep();
    fireEvent.click(screen.getByRole('radio', { name: 'violet' }));
    const menus = screen.getByRole('radiogroup', { name: 'Menu view' });
    fireEvent.click(menus.querySelector('[aria-label="Focus"]')!);
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));

    await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
    const s = useAppearanceStore.getState();
    expect(s.effective.accent).toBe('violet');
    expect(s.menu).toEqual(MENU_PRESETS.find((p) => p.id === 'focus')!.value);
    expect(apiPut).not.toHaveBeenCalled();
  });

  it('Skip keeps the defaults and touches neither the store nor the server', () => {
    const { onNext } = renderStep();
    fireEvent.click(screen.getByRole('radio', { name: 'crimson' }));
    fireEvent.click(screen.getByRole('button', { name: 'Skip' }));

    expect(onNext).toHaveBeenCalledTimes(1);
    const s = useAppearanceStore.getState();
    expect(s.user).toBeNull();
    expect(s.menuUser).toBeNull();
    expect(s.effective).toEqual(PLATFORM_APPEARANCE);
    expect(s.menu).toEqual(PLATFORM_MENU);
    expect(apiPut).not.toHaveBeenCalled();
  });

  it('Back goes back without applying', () => {
    const { onBack } = renderStep();
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(onBack).toHaveBeenCalledTimes(1);
    expect(useAppearanceStore.getState().user).toBeNull();
  });

  it('an administrator also saves the look as the workspace default', async () => {
    useAuthStore.setState({ userRole: 'admin' } as never);
    const { onNext } = renderStep();
    expect(screen.getByText(/also makes this the default for your workspace/)).toBeTruthy();
    fireEvent.click(screen.getByRole('radio', { name: 'emerald' }));
    const menus = screen.getByRole('radiogroup', { name: 'Menu view' });
    fireEvent.click(menus.querySelector('[aria-label="Blueprint"]')!);
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));

    await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
    const blueprint = MENU_PRESETS.find((p) => p.id === 'blueprint')!.value;
    expect(apiPut).toHaveBeenCalledWith('/v1/branding/', {
      appearance: { ...PLATFORM_APPEARANCE, accent: 'emerald', menu: blueprint },
    });
    const s = useAppearanceStore.getState();
    expect(s.workspace?.accent).toBe('emerald');
    expect(s.menuWorkspace).toEqual(blueprint);
  });

  it('keeps the personal look and still moves on when the workspace save fails', async () => {
    useAuthStore.setState({ userRole: 'admin' } as never);
    apiPut.mockRejectedValueOnce(new Error('offline'));
    const { onNext } = renderStep();
    fireEvent.click(screen.getByRole('radio', { name: 'teal' }));
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));

    await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
    expect(useAppearanceStore.getState().effective.accent).toBe('teal');
    expect(useAppearanceStore.getState().workspace).toBeNull();
  });
});
