// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The showcase demos on the public hosted demo. Each one is a company
 * type: it brings its own look and a menu cut down to the sections that kind
 * of company works in, so a visitor sees their own day, not all 200 modules.
 */

import type { Appearance } from './appearance';
import { canonicalGroupId } from '@/app/layout/navCatalog';
import type { MenuModeId } from '@/app/layout/menuLayout';

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
  /** Menu sections shown for this demo; null means every section. Folded
   *  section ids still work (see `canonicalGroupId`). */
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
  /** Cost database region (`REGION_MAP` id) the cost screens open on in this demo. */
  costRegion: string;
  /** Sidebar work mode the demo opens in: the short list of that company's daily screens. */
  menuMode: MenuModeId;
  /** Picture for the demo's hexagon: the company type whose site scene it wears, and the drawing used without a photo. */
  face?: DemoFace;
}

export type DemoFaceKind = 'tower' | 'residential' | 'hospital' | 'bridge' | 'warehouse';

export interface DemoFace {
  /** Company-type id whose Cases thumb is the photo (either id scheme). */
  companyType: string;
  kind: DemoFaceKind;
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
    costRegion: 'AR_DUBAI',
    menuMode: 'all',
    standards: 'MasterFormat · SBC · SAR',
    menuStyle: 'standard',
    appearance: { accent: 'blue', font: 'inter', density: 'comfortable', radius: 'standard', text: 'default', look: 'standard' },
    groups: null,
    stem: 'demo_profiles.full_showcase',
    face: { companyType: 'full_enterprise', kind: 'hospital' },
  },
  {
    slug: 'residential-berlin',
    locale: 'de',
    pack: 'germany-de',
    costRegion: 'DE_BERLIN',
    menuMode: 'estimator',
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
    face: { companyType: 'general_contractor', kind: 'residential' },
  },
  {
    slug: 'office-london',
    locale: 'en-GB',
    pack: 'uk-jct',
    costRegion: 'UK_GBP',
    menuMode: 'finance',
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
    face: { companyType: 'commercial-manager', kind: 'tower' },
  },
  {
    slug: 'medical-us',
    locale: 'en-US',
    pack: 'us-texas',
    costRegion: 'USA_USD',
    menuMode: 'manager',
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
    face: { companyType: 'construction-manager', kind: 'hospital' },
  },
  {
    slug: 'condo-toronto',
    locale: 'en',
    pack: 'canada-ca',
    costRegion: 'ENG_TORONTO',
    menuMode: 'manager',
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
    face: { companyType: 'real_estate_developer', kind: 'tower' },
  },
  {
    slug: 'school-paris',
    locale: 'fr',
    pack: 'france-fr',
    costRegion: 'FR_PARIS',
    menuMode: 'estimator',
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
    costRegion: 'ZH_SHANGHAI',
    menuMode: 'estimator',
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
  const keep = profile.groups ? new Set(profile.groups.map(canonicalGroupId)) : null;
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
