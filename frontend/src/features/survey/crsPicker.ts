// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure helpers behind the Set project CRS dialog.
 *
 * Suggestions (project pin, active pack, detected, geographic) come first;
 * the full EPSG catalogue is searched only for what the person types.
 */

import type { CrsInfo, CrsSuggestion, ProjectCrs } from './api';

export type CrsOption = CrsInfo & Partial<Pick<CrsSuggestion, 'reason' | 'confidence' | 'pack_country'>>;

/** "EPSG 32633 · WGS 84 / UTM zone 33N", or the local-grid label key's fallback. */
export function crsChipText(crs: Pick<ProjectCrs, 'horizontal_epsg' | 'horizontal_name' | 'is_local_grid'> | null, localLabel: string): string {
  if (!crs) return '';
  if (crs.is_local_grid) return localLabel;
  if (crs.horizontal_epsg == null) return '';
  return crs.horizontal_name ? `EPSG ${crs.horizontal_epsg} · ${crs.horizontal_name}` : `EPSG ${crs.horizontal_epsg}`;
}

/** Why a choice needs a second look: lat/lon cannot carry volumes or areas; a vertical system is not a plan. */
export function crsWarning(info: Pick<CrsInfo, 'is_geographic' | 'kind'> | null | undefined): 'geographic' | 'vertical' | null {
  if (!info) return null;
  if (info.kind === 'vertical') return 'vertical';
  if (info.is_geographic) return 'geographic';
  return null;
}

/** The query as an EPSG search: "EPSG:32633" and "epsg 32633" both read as 32633; one character is no query. */
export function normaliseQuery(q: string): string {
  const s = q.trim().replace(/^epsg\s*:?\s*/i, '');
  return s.length >= 2 ? s : '';
}

/** Suggestions first, then search hits not already suggested, vertical systems left out of the horizontal list. */
export function mergeOptions(suggestions: CrsSuggestion[], hits: CrsInfo[]): CrsOption[] {
  const seen = new Set<number>();
  const out: CrsOption[] = [];
  for (const s of suggestions) {
    if (seen.has(s.epsg)) continue;
    seen.add(s.epsg);
    out.push(s);
  }
  for (const h of hits) {
    if (seen.has(h.epsg) || h.kind === 'vertical') continue;
    seen.add(h.epsg);
    out.push(h);
  }
  return out;
}

/** The option to preselect: the confident detected or location suggestion, never the geographic fallback. */
export function preselect(options: CrsOption[], current: number | null): number | null {
  if (current != null) return current;
  const first = options.find((o) => o.reason === 'detected' || o.reason === 'project_location' || o.reason === 'pack');
  return first ? first.epsg : null;
}

/** Changing the system once points exist needs the new code typed again. */
export function changeNeedsTypedConfirm(current: ProjectCrs | null, pointCount: number, nextEpsg: number | null, nextLocal: boolean): boolean {
  if (!current || pointCount === 0) return false;
  return current.horizontal_epsg !== nextEpsg || current.is_local_grid !== nextLocal;
}

export function typedConfirmMatches(typed: string, nextEpsg: number | null, nextLocal: boolean): boolean {
  const expected = nextLocal ? 'LOCAL' : String(nextEpsg ?? '');
  return typed.trim().toUpperCase() === expected;
}
