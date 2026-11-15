// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The demo the visitor is in on the public hosted demo, and what it covers.
 *
 * Written when a demo opens (DemoSwitcherBar `open`); read by anything that
 * shows only a demo's own modules, such as the sidebar. Outside demo mode the
 * slug stays null and `groups`/`modules` are null: nothing is cut.
 */

import { create } from 'zustand';
import { MENU_MODE_IDS, type MenuModeId } from '@/app/layout/menuLayout';
import { navGroups } from '@/app/layout/navCatalog';
import {
  demoModuleRoutes,
  demoProfile,
  readChosenDemo,
  type DemoSlug,
} from '@/shared/lib/demoProfiles';

export interface DemoSessionState {
  slug: DemoSlug | null;
  /** UI language of the active demo's market, null outside a demo. */
  locale: string | null;
  /** Menu section ids the demo covers; null means every section. */
  groups: readonly string[] | null;
  /** Routes of the modules the demo covers, in menu order; null outside a demo. */
  modules: readonly string[] | null;
  /** The visitor asked list pages to show every demo project, not only this demo's. */
  showAll: boolean;
  /** "Show all modules" is on: the demo's section trimming is lifted; holds the menu mode to go back to. */
  restoreMode: MenuModeId | null;
  setRestoreMode: (mode: MenuModeId | null) => void;
  setDemo: (slug: DemoSlug | null) => void;
  setShowAll: (showAll: boolean) => void;
}

const SHOW_ALL_KEY = 'oe_demo_show_all';
const RESTORE_KEY = 'oe_menu_restore_mode';

function readRestoreMode(): MenuModeId | null {
  try {
    const v = sessionStorage.getItem(RESTORE_KEY);
    return v && MENU_MODE_IDS.includes(v as MenuModeId) ? (v as MenuModeId) : null;
  } catch {
    return null;
  }
}

function writeRestoreMode(mode: MenuModeId | null): void {
  try {
    if (mode) sessionStorage.setItem(RESTORE_KEY, mode);
    else sessionStorage.removeItem(RESTORE_KEY);
  } catch {
    // Storage blocked: the choice lasts until the next reload.
  }
}

function readShowAll(): boolean {
  try {
    return sessionStorage.getItem(SHOW_ALL_KEY) === '1';
  } catch {
    return false;
  }
}

function writeShowAll(showAll: boolean): void {
  try {
    if (showAll) sessionStorage.setItem(SHOW_ALL_KEY, '1');
    else sessionStorage.removeItem(SHOW_ALL_KEY);
  } catch {
    // Storage blocked: the choice lasts until the next reload.
  }
}

type DemoSessionData = Omit<DemoSessionState, 'setDemo' | 'setShowAll' | 'showAll' | 'restoreMode' | 'setRestoreMode'>;

function sessionFor(slug: DemoSlug | null): DemoSessionData {
  const profile = demoProfile(slug);
  if (!profile) return { slug: null, locale: null, groups: null, modules: null };
  return {
    slug: profile.slug,
    locale: profile.locale,
    groups: profile.groups,
    modules: demoModuleRoutes(profile, navGroups),
  };
}

export const useDemoSessionStore = create<DemoSessionState>((set) => ({
  ...sessionFor(readChosenDemo()),
  showAll: readShowAll(),
  restoreMode: readRestoreMode(),
  setRestoreMode: (mode) => {
    writeRestoreMode(mode);
    set({ restoreMode: mode });
  },
  // Opening a demo puts the lists back on that demo's own project.
  setDemo: (slug) => {
    writeShowAll(false);
    writeRestoreMode(null);
    set({ ...sessionFor(slug), showAll: false, restoreMode: null });
  },
  setShowAll: (showAll) => {
    writeShowAll(showAll);
    set({ showAll });
  },
}));
