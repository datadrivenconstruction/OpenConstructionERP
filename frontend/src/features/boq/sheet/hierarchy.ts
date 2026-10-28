// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Outline levels for the sheet: group rows by the bill's hierarchy, collapse
 * and expand, and name each level the way the active standard does.
 */

import { isSection, type Position } from '../api';

export interface OutlineRow {
  position: Position;
  level: number;
  isGroup: boolean;
  hasChildren: boolean;
}

/**
 * Rows in bill order with their depth. Depth comes from parent_id; a row
 * whose parent is missing is treated as top level, never dropped.
 */
export function buildOutline(positions: Position[]): OutlineRow[] {
  const byId = new Map(positions.map((p) => [p.id, p]));
  const childCount = new Map<string, number>();
  for (const p of positions) {
    if (p.parent_id && byId.has(p.parent_id)) childCount.set(p.parent_id, (childCount.get(p.parent_id) ?? 0) + 1);
  }
  const depth = new Map<string, number>();
  const levelOf = (p: Position, guard = 0): number => {
    const known = depth.get(p.id);
    if (known !== undefined) return known;
    const parent = p.parent_id ? byId.get(p.parent_id) : undefined;
    const lvl = parent && guard < 32 ? levelOf(parent, guard + 1) + 1 : 0;
    depth.set(p.id, lvl);
    return lvl;
  };
  return positions.map((p) => ({
    position: p,
    level: levelOf(p),
    isGroup: isSection(p),
    hasChildren: (childCount.get(p.id) ?? 0) > 0,
  }));
}

/** Rows left visible when the groups in `collapsed` are folded. */
export function visibleRows(outline: OutlineRow[], collapsed: ReadonlySet<string>): OutlineRow[] {
  if (collapsed.size === 0) return outline;
  const out: OutlineRow[] = [];
  let hideBelow: number | null = null;
  for (const r of outline) {
    if (hideBelow !== null) {
      if (r.level > hideBelow) continue;
      hideBelow = null;
    }
    out.push(r);
    if (r.hasChildren && collapsed.has(r.position.id)) hideBelow = r.level;
  }
  return out;
}

/** Group ids down to `level` (0 = top) for "show outline level N". */
export function groupsDeeperThan(outline: OutlineRow[], level: number): Set<string> {
  return new Set(outline.filter((r) => r.hasChildren && r.level >= level).map((r) => r.position.id));
}

/** Translation keys for hierarchy level names per standard; i18n carries the words. */
const LEVEL_KEYS: Record<string, string[]> = {
  gaeb: ['boq.sheet.level_gaeb_lot', 'boq.sheet.level_gaeb_title', 'boq.sheet.level_gaeb_subtitle'],
  din276: ['boq.sheet.level_din276_1', 'boq.sheet.level_din276_2', 'boq.sheet.level_din276_3'],
  nrm: ['boq.sheet.level_nrm_group', 'boq.sheet.level_nrm_element', 'boq.sheet.level_nrm_sub_element'],
  masterformat: ['boq.sheet.level_mf_division', 'boq.sheet.level_mf_section', 'boq.sheet.level_mf_subsection'],
};

export function standardFamily(standard: string | null | undefined): keyof typeof LEVEL_KEYS | 'generic' {
  const s = (standard ?? '').toLowerCase().replace(/[^a-z0-9]/g, '');
  if (s.startsWith('gaeb') || s === 'oz' || s === 'stlb') return 'gaeb';
  if (s.startsWith('din276')) return 'din276';
  if (s.startsWith('nrm')) return 'nrm';
  if (s.startsWith('masterformat') || s.startsWith('csi')) return 'masterformat';
  return 'generic';
}

/** i18n key naming a group row at `level` under the standard, and the ordinal column header key. */
export function levelKey(standard: string | null | undefined, level: number): string {
  const fam = standardFamily(standard);
  if (fam === 'generic') return 'boq.sheet.level_generic';
  const keys = LEVEL_KEYS[fam]!;
  return keys[Math.min(level, keys.length - 1)]!;
}

export function ordinalHeaderKey(standard: string | null | undefined): string {
  const fam = standardFamily(standard);
  return fam === 'generic' ? 'boq.sheet.col_ordinal' : `boq.sheet.col_ordinal_${fam}`;
}
