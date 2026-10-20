// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Runtime side of per-item menu icons: resolves a route's override to a
 * component and gives each menu route its section tone.
 *
 * Overrides name icons from `menuIconCatalog.ts`, a lazily loaded chunk. It
 * is fetched only once the user has an override (or opens the picker); until
 * it arrives every row draws its default icon.
 */
import { create } from 'zustand';
import type { LucideIcon } from 'lucide-react';
import { useAppearanceStore } from '@/stores/useAppearanceStore';
import { SECTION_TONES } from '@/shared/lib/menuAppearance';
import { navGroups } from './navCatalog';

interface CatalogState {
  /** Catalogue icons by name, null until the chunk has loaded. */
  icons: Readonly<Record<string, LucideIcon>> | null;
  load: () => Promise<void>;
}

let pending: Promise<void> | null = null;

export const useMenuIconCatalog = create<CatalogState>((set, get) => ({
  icons: null,
  load: () => {
    if (get().icons) return Promise.resolve();
    pending ??= import('./menuIconCatalog')
      .then((m) => set({ icons: m.MENU_ICON_BY_NAME }))
      .catch(() => {
        pending = null; // offline or a stale deploy: try again next time
      });
    return pending;
  },
}));

function loadWhenNeeded(overrides: Record<string, string>) {
  if (Object.keys(overrides).length > 0) void useMenuIconCatalog.getState().load();
}
loadWhenNeeded(useAppearanceStore.getState().iconOverrides);
useAppearanceStore.subscribe((s) => loadWhenNeeded(s.iconOverrides));

/** The override icon for a menu route, or null (none set, or not loaded yet). */
export function getIconOverride(route: string): LucideIcon | null {
  const name = useAppearanceStore.getState().iconOverrides[route];
  if (!name) return null;
  return useMenuIconCatalog.getState().icons?.[name] ?? null;
}

/** A menu row's icon: its override when one is set, else its default. */
export function useMenuIcon(route: string, fallback: LucideIcon): LucideIcon {
  const name = useAppearanceStore((s) => s.iconOverrides[route]);
  const icons = useMenuIconCatalog((s) => s.icons);
  return (name && icons?.[name]) || fallback;
}

/** Subscribe a component that calls `getRouteIcon` to override changes. */
export function useIconOverridesVersion(): void {
  useAppearanceStore((s) => s.iconOverrides);
  useMenuIconCatalog((s) => s.icons);
}

const TONE_BY_ROUTE = new Map<string, number>();
navGroups.forEach((group, index) => {
  for (const item of group.items) {
    if (!TONE_BY_ROUTE.has(item.to)) TONE_BY_ROUTE.set(item.to, index % SECTION_TONES.length);
  }
});

/** Index into SECTION_TONES for a menu route: its section's place in the menu. */
export function sectionTone(route: string): number | undefined {
  return TONE_BY_ROUTE.get(route);
}
