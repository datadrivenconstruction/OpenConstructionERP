import { isSection } from './api';

/** The fields of a BOQ row the batch planners read. */
export interface BatchRow {
  id: string;
  parent_id?: string | null;
  unit: string;
  ordinal?: string | null;
  description?: string | null;
}

/** A selected section and how many rows its delete takes with it. */
export interface SectionToDelete {
  id: string;
  ordinal: string;
  description: string;
  /** Positions (not sub-sections) anywhere below this section. */
  positionCount: number;
}

export interface BatchDeletePlan {
  /** Selected sections not already inside another selected section, in input order. */
  sections: SectionToDelete[];
  /** Selected positions outside every selected section: deleted one by one. */
  positionIds: string[];
  /** Positions removed together with the sections. */
  containedPositions: number;
}

/** Selected ids without section rows: unit, factor, classification and fill skip sections. */
export function withoutSections(rows: readonly BatchRow[], ids: readonly string[]): string[] {
  const byId = new Map(rows.map((r) => [r.id, r]));
  return ids.filter((id) => {
    const row = byId.get(id);
    return row !== undefined && !isSection(row);
  });
}

/**
 * Split a batch delete into section cascades and loose positions.
 *
 * A section delete cascades to its whole subtree, like the single delete, so
 * a selected row already under a selected section is not deleted twice.
 */
export function planBatchDelete(rows: readonly BatchRow[], ids: readonly string[]): BatchDeletePlan {
  const byId = new Map(rows.map((r) => [r.id, r]));
  const children = new Map<string, BatchRow[]>();
  for (const r of rows) {
    if (!r.parent_id) continue;
    const list = children.get(r.parent_id);
    if (list) list.push(r);
    else children.set(r.parent_id, [r]);
  }
  const selectedSections = new Set(ids.filter((id) => {
    const r = byId.get(id);
    return r !== undefined && isSection(r);
  }));
  const underSelected = (row: BatchRow): boolean => {
    let parent = row.parent_id ? byId.get(row.parent_id) : undefined;
    const seen = new Set<string>();
    while (parent && !seen.has(parent.id)) {
      if (selectedSections.has(parent.id)) return true;
      seen.add(parent.id);
      parent = parent.parent_id ? byId.get(parent.parent_id) : undefined;
    }
    return false;
  };
  const countPositions = (id: string): number => {
    let n = 0;
    const stack = [...(children.get(id) ?? [])];
    const seen = new Set<string>();
    while (stack.length > 0) {
      const r = stack.pop()!;
      if (seen.has(r.id)) continue;
      seen.add(r.id);
      if (!isSection(r)) n++;
      stack.push(...(children.get(r.id) ?? []));
    }
    return n;
  };

  const sections: SectionToDelete[] = [];
  const positionIds: string[] = [];
  for (const id of ids) {
    const row = byId.get(id);
    if (!row || underSelected(row)) continue;
    if (selectedSections.has(id)) {
      sections.push({
        id,
        ordinal: row.ordinal ?? '',
        description: row.description ?? '',
        positionCount: countPositions(id),
      });
    } else {
      positionIds.push(id);
    }
  }
  return {
    sections,
    positionIds,
    containedPositions: sections.reduce((s, x) => s + x.positionCount, 0),
  };
}
