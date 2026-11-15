// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What "inside one demo" means for screens that list data from many projects.
 *
 * On the hosted demo one shared account owns every demo project, so a list
 * page without a scope mixes all of them. While a demo is open, lists default
 * to its project; the visitor can ask for every project (`showAll`).
 */

import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { demoProfile, type DemoProfile } from './demoProfiles';

export interface DemoProjectRef {
  id: string;
  name: string;
  metadata?: Record<string, unknown> | null;
}

/** The project the demo installer marked with this demo's slug (`metadata.demo_id`). */
export function demoProjectFor<T extends DemoProjectRef>(
  projects: readonly T[] | null | undefined,
  slug: string | null | undefined,
): T | null {
  if (!slug || !projects) return null;
  return projects.find((p) => typeof p.metadata?.demo_id === 'string' && p.metadata.demo_id === slug) ?? null;
}

export interface DemoScopeInput {
  demoMode: boolean;
  slug: string | null | undefined;
  showAll: boolean;
  projects: readonly DemoProjectRef[] | null | undefined;
}

export interface DemoScopeState {
  /** The open demo, null outside demo mode. */
  profile: DemoProfile | null;
  /** The open demo's project, once the project list has it. */
  project: { id: string; name: string } | null;
  /** The project lists narrow to; null shows everything. */
  projectId: string | null;
}

export function demoScopeFor({ demoMode, slug, showAll, projects }: DemoScopeInput): DemoScopeState {
  const profile = demoMode ? (demoProfile(slug) ?? null) : null;
  const hit = profile ? demoProjectFor(projects, profile.slug) : null;
  const project = hit ? { id: hit.id, name: hit.name } : null;
  return { profile, project, projectId: project && !showAll ? project.id : null };
}

/** Keep only the rows of the scoped project; no scope keeps every row. */
export function scopeToProject<T>(
  rows: readonly T[] | undefined,
  projectId: string | null,
  idOf: (row: T) => string | null | undefined,
): T[] | undefined {
  if (!rows) return undefined;
  if (!projectId) return [...rows];
  return rows.filter((row) => idOf(row) === projectId);
}

type Language = (typeof SUPPORTED_LANGUAGES)[number];

/** The supported UI language closest to `code`: exact, then its base, then English. */
export function uiLanguageFor(code: string | null | undefined): Language {
  const want = (code || 'en').toLowerCase();
  const base = want.split('-')[0];
  return (
    SUPPORTED_LANGUAGES.find((l) => l.code.toLowerCase() === want) ??
    SUPPORTED_LANGUAGES.find((l) => l.code.toLowerCase() === base) ??
    SUPPORTED_LANGUAGES[0]!
  );
}

/**
 * The market the language-and-market select shows: the open demo while the
 * interface is in that demo's language, otherwise '' (the select then names
 * the current language, never a placeholder).
 */
export function marketSwitchValue(
  activeSlug: string | null | undefined,
  available: readonly Pick<DemoProfile, 'slug' | 'locale'>[],
  uiLanguage: string | null | undefined,
): string {
  const shown = available.find((p) => p.slug === activeSlug);
  if (!shown) return '';
  const lang = (uiLanguage || 'en').split('-')[0];
  return shown.locale.split('-')[0] === lang ? shown.slug : '';
}
