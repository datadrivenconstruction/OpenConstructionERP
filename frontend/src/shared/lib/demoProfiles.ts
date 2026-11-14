// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The showcase demos on the public hosted demo. Each one is a company
 * type: it brings its own look and a menu cut down to the sections that kind
 * of company works in, so a visitor sees their own day, not all 200 modules.
 */

import type { Appearance } from './appearance';

export type DemoSlug =
  | 'full-showcase-riyadh'
  | 'residential-berlin'
  | 'office-london'
  | 'medical-us'
  | 'condo-toronto'
  | 'school-paris'
  | 'office-shanghai';

/** How the sidebar looks while a demo is active (`html[data-oe-menu]`, see index.css). */
export const MENU_STYLES = ['standard', 'tinted', 'dark', 'pill', 'outline'] as const;
export type DemoMenuStyle = (typeof MENU_STYLES)[number];

export interface DemoProfile {
  slug: DemoSlug;
  appearance: Appearance;
  /** Menu sections shown for this demo; null means every section. */
  groups: readonly string[] | null;
  /** Sidebar style that sets this demo apart from the others. */
  menuStyle: DemoMenuStyle;
  /** i18n key stem: `<stem>.country`, `.title`, `.audience`, `.body`, `.point_1..3`. */
  stem: string;
  /** UI language the market switch sets for this demo; its project data is written in it. */
  locale: string;
  /** Country pack the demo project is composed from (`packs/<id>`). */
  pack: string;
  /** Standards and currency of the project data, shown as is (proper names, not translated). */
  standards: string;
}

// Always present so the visitor can find help, settings and the projects list.
const BASE = ['grp_overview', 'grp_documents', 'grp_communication'] as const;

/**
 * Seven demos: the full platform plus six countries, six kinds of company. Every group listed here
 * has seeded data in that project (see core/demo_projects.py), so no demo
 * opens an empty screen.
 */
export const DEMO_PROFILES: readonly DemoProfile[] = [
  {
    slug: 'full-showcase-riyadh',
    locale: 'en',
    pack: 'saudi-vision2030',
    standards: 'MasterFormat · SBC · SAR',
    menuStyle: 'standard',
    appearance: { accent: 'blue', font: 'inter', density: 'comfortable', radius: 'standard', text: 'default', look: 'standard' },
    groups: null,
    stem: 'demo_profiles.full_showcase',
  },
  {
    slug: 'residential-berlin',
    locale: 'de',
    pack: 'germany-de',
    standards: 'DIN 276 · GAEB XML · EUR',
    menuStyle: 'outline',
    appearance: { accent: 'graphite', font: 'ibm-plex-sans', density: 'normal', radius: 'sharp', text: 'default', look: 'classic' },
    groups: [
      ...BASE,
      'grp_takeoff',
      'grp_cost_data',
      'grp_estimating',
      'grp_procurement',
      'grp_scheduling',
      'grp_cost_control',
      'grp_change',
      'grp_site',
      'grp_quality',
      'grp_finance',
    ],
    stem: 'demo_profiles.dach_contractor',
  },
  {
    slug: 'office-london',
    locale: 'en-GB',
    pack: 'uk-jct',
    standards: 'NRM · JCT · GBP',
    menuStyle: 'tinted',
    appearance: { accent: 'violet', font: 'source-sans-3', density: 'comfortable', radius: 'round', text: 'default', look: 'standard' },
    groups: [
      ...BASE,
      'grp_takeoff',
      'grp_cost_data',
      'grp_estimating',
      'grp_estimate_detail',
      'grp_procurement',
      'grp_cost_control',
      'grp_commercial',
      'grp_change',
      'grp_finance',
    ],
    stem: 'demo_profiles.uk_consultancy',
  },
  {
    slug: 'medical-us',
    locale: 'en-US',
    pack: 'us-texas',
    standards: 'MasterFormat · AIA · USD',
    menuStyle: 'dark',
    appearance: { accent: 'amber', font: 'inter', density: 'compact', radius: 'sharp', text: 'default', look: 'standard' },
    groups: [
      ...BASE,
      'grp_coordination',
      'grp_estimating',
      'grp_scheduling',
      'grp_cost_control',
      'grp_commercial',
      'grp_change',
      'grp_quality',
      'grp_safety',
      'grp_handover',
      'grp_finance',
    ],
    stem: 'demo_profiles.us_owners_rep',
  },
  {
    slug: 'condo-toronto',
    locale: 'en',
    pack: 'canada-ca',
    standards: 'MasterFormat · CCDC · CAD',
    menuStyle: 'pill',
    appearance: { accent: 'teal', font: 'system', density: 'normal', radius: 'round', text: 'default', look: 'classic' },
    groups: [
      ...BASE,
      'grp_takeoff',
      'grp_cost_data',
      'grp_estimating',
      'grp_scheduling',
      'grp_cost_control',
      'grp_commercial',
      'grp_procurement',
      'grp_change',
      'grp_quality',
      'grp_handover',
      'grp_finance',
    ],
    stem: 'demo_profiles.ca_developer',
  },
  {
    slug: 'school-paris',
    locale: 'fr',
    pack: 'france-fr',
    standards: 'DPGF · RE 2020 · EUR',
    menuStyle: 'tinted',
    appearance: { accent: 'emerald', font: 'source-sans-3', density: 'normal', radius: 'standard', text: 'default', look: 'standard' },
    groups: [
      ...BASE,
      'grp_takeoff',
      'grp_cost_data',
      'grp_estimating',
      'grp_procurement',
      'grp_scheduling',
      'grp_cost_control',
      'grp_change',
      'grp_site',
      'grp_quality',
    ],
    stem: 'demo_profiles.fr_economist',
  },
  {
    slug: 'office-shanghai',
    locale: 'zh',
    pack: 'china-gbt50500',
    standards: 'GB 50500 · GB/T 50378 · CNY',
    menuStyle: 'outline',
    appearance: { accent: 'crimson', font: 'system', density: 'compact', radius: 'standard', text: 'default', look: 'standard' },
    groups: [
      ...BASE,
      'grp_takeoff',
      'grp_cost_data',
      'grp_estimating',
      'grp_procurement',
      'grp_scheduling',
      'grp_cost_control',
      'grp_commercial',
      'grp_change',
      'grp_quality',
      'grp_finance',
    ],
    stem: 'demo_profiles.cn_cost_consultant',
  },
];

export function demoProfile(slug: string | null | undefined): DemoProfile | undefined {
  return DEMO_PROFILES.find((p) => p.slug === slug);
}

/**
 * Routes of the modules a demo covers: every menu item in its sections, in menu
 * order. The full platform covers every item. The sidebar reads this (or the
 * store below) to show a demo's own modules and nothing else.
 */
export function demoModuleRoutes(
  profile: DemoProfile,
  groups: readonly { id: string; items: readonly { to: string }[] }[],
): string[] {
  const keep = profile.groups ? new Set(profile.groups) : null;
  return groups.filter((g) => !keep || keep.has(g.id)).flatMap((g) => g.items.map((i) => i.to));
}

/** Menu sections to hide for a demo: every known section outside its list. */
export function hiddenGroupsFor(profile: DemoProfile, allGroupIds: readonly string[]): string[] {
  if (!profile.groups) return [];
  const keep = new Set(profile.groups);
  return allGroupIds.filter((id) => !keep.has(id) && id !== 'grp_learn' && id !== 'learn');
}

/** Set or clear the demo sidebar style on <html>; null leaves the platform menu alone. */
export function applyDemoMenuStyle(
  style: DemoMenuStyle | null,
  root: HTMLElement = document.documentElement,
): void {
  if (style && style !== 'standard') root.dataset.oeMenu = style;
  else delete root.dataset.oeMenu;
}

const CHOSEN_KEY = 'oe_demo_chosen';

export function readChosenDemo(): DemoSlug | null {
  try {
    const v = sessionStorage.getItem(CHOSEN_KEY);
    return demoProfile(v)?.slug ?? null;
  } catch {
    return null;
  }
}

export function writeChosenDemo(slug: DemoSlug): void {
  try {
    sessionStorage.setItem(CHOSEN_KEY, slug);
  } catch {
    // Storage blocked: the visitor is asked again next time, nothing breaks.
  }
}
