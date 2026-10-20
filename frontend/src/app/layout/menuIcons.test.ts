// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A user's icon for a menu item must show wherever that route's icon shows:
// the sidebar row (useMenuIcon), the top-bar chip (getRouteIcon) and the
// command palette (getIconOverride). Reset brings every one back.
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { Calculator, Timer } from 'lucide-react';
import { useAppearanceStore } from '@/stores/useAppearanceStore';
import { SECTION_TONES } from '@/shared/lib/menuAppearance';
import { navGroups } from './navCatalog';
import { getRouteIcon } from './routeIcons';
import { getIconOverride, sectionTone, useMenuIconCatalog } from './menuIcons';
import { MENU_ICON_BY_NAME, MENU_ICON_GROUPS } from './menuIconCatalog';

const boq = navGroups.flatMap((g) => g.items).find((i) => i.to === '/boq')!;

beforeEach(async () => {
  useAppearanceStore.getState().resetIconOverrides();
  await useMenuIconCatalog.getState().load();
});

afterEach(() => useAppearanceStore.getState().resetIconOverrides());

describe('menu icon overrides', () => {
  it('reach the top-bar chip, detail routes and nested project routes', () => {
    expect(getRouteIcon('/boq')).toBe(boq.icon);
    useAppearanceStore.getState().setIconOverride('/boq', 'Calculator');
    expect(getRouteIcon('/boq')).toBe(Calculator);
    expect(getRouteIcon('/boq/123')).toBe(Calculator);
    expect(getRouteIcon('/projects/p1/boq')).toBe(Calculator);
    expect(getIconOverride('/boq')).toBe(Calculator);
  });

  it('cover the root route too', () => {
    useAppearanceStore.getState().setIconOverride('/', 'Timer');
    expect(getRouteIcon('/')).toBe(Timer);
  });

  it('reset to the default icon', () => {
    useAppearanceStore.getState().setIconOverride('/boq', 'Calculator');
    useAppearanceStore.getState().setIconOverride('/boq', null);
    expect(getRouteIcon('/boq')).toBe(boq.icon);
    expect(getIconOverride('/boq')).toBeNull();
  });

  it('ignore a stored name the catalogue does not have', () => {
    useAppearanceStore.getState().setIconOverride('/boq', 'NoSuchIcon');
    expect(getRouteIcon('/boq')).toBe(boq.icon);
  });
});

describe('icon catalogue', () => {
  it('is a curated set of 150 to 250 unique icons', () => {
    const names = MENU_ICON_GROUPS.flatMap((g) => g.icons.map((i) => i.name));
    expect(names.length).toBeGreaterThanOrEqual(150);
    expect(names.length).toBeLessThanOrEqual(250);
    expect(new Set(names).size).toBe(names.length);
    for (const name of names) expect(MENU_ICON_BY_NAME[name]).toBeTruthy();
  });
});

describe('section tones', () => {
  it('give each menu section a tone, neighbours differing', () => {
    const tones = navGroups.map((g) => sectionTone(g.items[0]!.to));
    for (const tone of tones) expect(tone).toBeLessThan(SECTION_TONES.length);
    for (let i = 1; i < tones.length; i += 1) {
      if (navGroups[i]!.items[0]!.to !== navGroups[i - 1]!.items[0]!.to) expect(tones[i]).not.toBe(tones[i - 1]);
    }
  });
});
