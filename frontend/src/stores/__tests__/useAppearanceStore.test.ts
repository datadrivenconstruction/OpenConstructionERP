// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeEach, describe, expect, it } from 'vitest';
import { PLATFORM_APPEARANCE, USER_APPEARANCE_KEY, WORKSPACE_APPEARANCE_KEY } from '@/shared/lib/appearance';
import {
  MENU_ICON_OVERRIDES_KEY,
  MENU_PRESETS,
  PLATFORM_MENU,
  USER_MENU_KEY,
  matchMenuPreset,
} from '@/shared/lib/menuAppearance';
import { useAppearanceStore } from '../useAppearanceStore';

const html = () => document.documentElement.dataset;

beforeEach(() => {
  localStorage.clear();
  useAppearanceStore.getState().followWorkspace();
  useAppearanceStore.getState().setWorkspaceDefault(null);
  useAppearanceStore.getState().followWorkspaceMenu();
  useAppearanceStore.getState().setWorkspaceMenu(null);
  useAppearanceStore.getState().resetIconOverrides();
});

describe('useAppearanceStore', () => {
  it('a user with no choice follows the workspace default', () => {
    useAppearanceStore.getState().setWorkspaceDefault({ accent: 'emerald', radius: 'sharp' });
    const s = useAppearanceStore.getState();
    expect(s.user).toBeNull();
    expect(s.effective).toEqual({ ...PLATFORM_APPEARANCE, accent: 'emerald', radius: 'sharp' });
    expect(html().accent).toBe('emerald');
    expect(JSON.parse(localStorage.getItem(WORKSPACE_APPEARANCE_KEY)!)).toEqual({ accent: 'emerald', radius: 'sharp' });
  });

  it('a personal choice overrides the workspace and persists', () => {
    useAppearanceStore.getState().setWorkspaceDefault({ accent: 'emerald' });
    useAppearanceStore.getState().setAxis('accent', 'crimson');
    const s = useAppearanceStore.getState();
    expect(s.effective.accent).toBe('crimson');
    expect(html().accent).toBe('crimson');
    expect(JSON.parse(localStorage.getItem(USER_APPEARANCE_KEY)!).accent).toBe('crimson');
  });

  it('"use workspace default" drops the override', () => {
    useAppearanceStore.getState().setWorkspaceDefault({ density: 'compact' });
    useAppearanceStore.getState().setAppearance({ ...PLATFORM_APPEARANCE, accent: 'amber' });
    useAppearanceStore.getState().followWorkspace();
    const s = useAppearanceStore.getState();
    expect(s.user).toBeNull();
    expect(s.effective).toEqual({ ...PLATFORM_APPEARANCE, density: 'compact' });
    expect(localStorage.getItem(USER_APPEARANCE_KEY)).toBeNull();
    expect(html().density).toBe('compact');
  });

  it('rejects a workspace default with values it does not know', () => {
    useAppearanceStore.getState().setWorkspaceDefault({ accent: 'pink', font: 'inter' });
    expect(useAppearanceStore.getState().workspace).toEqual({ font: 'inter' });
  });
});

describe('useAppearanceStore menu look', () => {
  it('a preset sets every axis, paints <html> and is saved on this device', () => {
    const studio = MENU_PRESETS.find((p) => p.id === 'studio')!;
    useAppearanceStore.getState().setMenu(studio.value);
    const s = useAppearanceStore.getState();
    expect(s.menu).toEqual(studio.value);
    expect(matchMenuPreset(s.menu)).toBe('studio');
    expect(html().menuView).toBe('comfortable');
    expect(html().menuContainer).toBe('tile');
    expect(JSON.parse(localStorage.getItem(USER_MENU_KEY)!)).toEqual(studio.value);
  });

  it('changing one axis after a preset reads as Custom and keeps the rest', () => {
    const blueprint = MENU_PRESETS.find((p) => p.id === 'blueprint')!;
    useAppearanceStore.getState().setMenu(blueprint.value);
    useAppearanceStore.getState().setMenuAxis('stroke', 'bold');
    const s = useAppearanceStore.getState();
    expect(s.menu).toEqual({ ...blueprint.value, stroke: 'bold' });
    expect(matchMenuPreset(s.menu)).toBeNull();
    expect(html().menuStroke).toBe('bold');
  });

  it('follows the workspace menu until the user picks, and goes back on reset', () => {
    useAppearanceStore.getState().setWorkspaceMenu({ view: 'floating', active: 'tint', bogus: 1 });
    expect(useAppearanceStore.getState().menuWorkspace).toEqual({ view: 'floating', active: 'tint' });
    expect(useAppearanceStore.getState().menu).toEqual({ ...PLATFORM_MENU, view: 'floating', active: 'tint' });

    useAppearanceStore.getState().setMenuAxis('view', 'compact');
    expect(useAppearanceStore.getState().menu.view).toBe('compact');

    useAppearanceStore.getState().followWorkspaceMenu();
    expect(useAppearanceStore.getState().menuUser).toBeNull();
    expect(localStorage.getItem(USER_MENU_KEY)).toBeNull();
    expect(useAppearanceStore.getState().menu.view).toBe('floating');
    expect(html().menuView).toBe('floating');
  });

  it('keeps the style and the menu look apart', () => {
    useAppearanceStore.getState().setAxis('accent', 'teal');
    useAppearanceStore.getState().setMenuAxis('color', 'accent');
    useAppearanceStore.getState().followWorkspace();
    expect(useAppearanceStore.getState().menu.color).toBe('accent');
  });
});

describe('useAppearanceStore icon overrides', () => {
  it('maps a route to an icon name, persists it and resets it', () => {
    useAppearanceStore.getState().setIconOverride('/boq', 'Calculator');
    useAppearanceStore.getState().setIconOverride('/schedule', 'Timer');
    expect(useAppearanceStore.getState().iconOverrides).toEqual({ '/boq': 'Calculator', '/schedule': 'Timer' });
    expect(JSON.parse(localStorage.getItem(MENU_ICON_OVERRIDES_KEY)!)).toEqual({
      '/boq': 'Calculator',
      '/schedule': 'Timer',
    });

    useAppearanceStore.getState().setIconOverride('/boq', null);
    expect(useAppearanceStore.getState().iconOverrides).toEqual({ '/schedule': 'Timer' });

    useAppearanceStore.getState().resetIconOverrides();
    expect(useAppearanceStore.getState().iconOverrides).toEqual({});
    expect(localStorage.getItem(MENU_ICON_OVERRIDES_KEY)).toBeNull();
  });

  it('refuses names and routes that are not ours', () => {
    useAppearanceStore.getState().setIconOverride('/boq', '<img src=x>');
    useAppearanceStore.getState().setIconOverride('javascript:alert(1)', 'Truck');
    expect(useAppearanceStore.getState().iconOverrides).toEqual({});
  });
});
