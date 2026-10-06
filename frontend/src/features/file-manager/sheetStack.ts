// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Reading a sheet's revision stack off the rows the register already holds.
 *
 * Each sheet row names the row it replaced in `previous_version_id`. The
 * backend files an older revision uploaded late beneath the newer one, so the
 * links, not upload times, say which revision sits where.
 */
import type { SheetRow } from './types';

/** Metadata flag the backend sets when a revision could not be ranked against
 *  the one it replaced and upload order decided which is current. */
export function revisionOrderUnclear(sheet: SheetRow): boolean {
  return sheet.metadata?.revision_order_unclear === true;
}

/** How many links lead down from `row` through rows present in `byId`. */
function depthBelow(row: SheetRow, byId: Map<string, SheetRow>): number {
  const seen = new Set<string>([row.id]);
  let hops = 0;
  let node = row;
  while (node.previous_version_id) {
    const below = byId.get(node.previous_version_id);
    if (!below || seen.has(below.id)) break;
    seen.add(below.id);
    node = below;
    hops += 1;
  }
  return hops;
}

/**
 * The stack in the order its links give, newest first.
 *
 * Not upload order: an older revision uploaded after a newer one is filed
 * beneath it, so its place is its distance from the bottom of the chain. Rows
 * at the same depth (a fault in a drawing set, two pages claiming one
 * predecessor) fall back to upload time, newest first.
 */
export function orderStack(rows: SheetRow[]): SheetRow[] {
  const byId = new Map(rows.map((r) => [r.id, r]));
  const depth = new Map(rows.map((r) => [r.id, depthBelow(r, byId)]));
  return [...rows].sort((a, b) => {
    const d = (depth.get(b.id) ?? 0) - (depth.get(a.id) ?? 0);
    if (d !== 0) return d;
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  });
}

/**
 * For each row, how many earlier revisions sit beneath it in the loaded set.
 *
 * Counted only through rows the register has loaded, so a register cut at its
 * page limit can undercount; it never overcounts.
 */
export function earlierRevisionCounts(rows: SheetRow[]): Map<string, number> {
  const byId = new Map(rows.map((r) => [r.id, r]));
  return new Map(rows.map((r) => [r.id, depthBelow(r, byId)]));
}
