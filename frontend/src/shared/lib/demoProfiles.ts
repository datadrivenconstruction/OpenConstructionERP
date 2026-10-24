// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The four showcase demos on the public hosted demo. Each one is a company
 * type: it brings its own look and a menu cut down to the sections that kind
 * of company works in, so a visitor sees their own day, not all 200 modules.
 */

import type { Appearance } from './appearance';

export type DemoSlug = 'consultancy-riyadh' | 'contractor-jeddah' | 'site-development-dammam' | 'full-showcase-riyadh';

export interface DemoProfile {
  slug: DemoSlug;
  appearance: Appearance;
  /** Menu sections shown for this demo; null means every section. */
  groups: readonly string[] | null;
  /** i18n key stem: `<stem>.title`, `.audience`, `.body`, `.point_1..3`. */
  stem: string;
}

// Always present so the visitor can find help, settings and the projects list.
const BASE = ['grp_overview', 'grp_documents', 'grp_communication'] as const;

export const DEMO_PROFILES: readonly DemoProfile[] = [
  {
    slug: 'consultancy-riyadh',
    appearance: { accent: 'violet', font: 'inter', density: 'comfortable', radius: 'round' },
    groups: [...BASE, 'grp_drawings', 'grp_cost_data', 'grp_estimating', 'grp_scheduling', 'grp_commercial', 'grp_controls_bi'],
    stem: 'demo_profiles.consultancy',
  },
  {
    slug: 'contractor-jeddah',
    appearance: { accent: 'amber', font: 'ibm-plex-sans', density: 'compact', radius: 'sharp' },
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
      'grp_safety',
      'grp_finance',
    ],
    stem: 'demo_profiles.contractor',
  },
  {
    slug: 'site-development-dammam',
    appearance: { accent: 'emerald', font: 'source-sans-3', density: 'comfortable', radius: 'standard' },
    groups: [...BASE, 'grp_takeoff', 'grp_reality', 'grp_estimating', 'grp_scheduling', 'grp_field', 'grp_site', 'grp_esg', 'grp_handover'],
    stem: 'demo_profiles.site_development',
  },
  {
    slug: 'full-showcase-riyadh',
    appearance: { accent: 'blue', font: 'system', density: 'comfortable', radius: 'standard' },
    groups: null,
    stem: 'demo_profiles.full_showcase',
  },
];

export function demoProfile(slug: string | null | undefined): DemoProfile | undefined {
  return DEMO_PROFILES.find((p) => p.slug === slug);
}

/** Menu sections to hide for a demo: every known section outside its list. */
export function hiddenGroupsFor(profile: DemoProfile, allGroupIds: readonly string[]): string[] {
  if (!profile.groups) return [];
  const keep = new Set(profile.groups);
  return allGroupIds.filter((id) => !keep.has(id) && id !== 'grp_learn' && id !== 'learn');
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
