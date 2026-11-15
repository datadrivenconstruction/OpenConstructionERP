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
  setDemo: (slug: DemoSlug | null) => void;
  setShowAll: (showAll: boolean) => void;
}

const SHOW_ALL_KEY = 'oe_demo_show_all';

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

type DemoSessionData = Omit<DemoSessionState, 'setDemo' | 'setShowAll' | 'showAll'>;

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
  // Opening a demo puts the lists back on that demo's own project.
  setDemo: (slug) => {
    writeShowAll(false);
    set({ ...sessionFor(slug), showAll: false });
  },
  setShowAll: (showAll) => {
    writeShowAll(showAll);
    set({ showAll });
  },
}));
