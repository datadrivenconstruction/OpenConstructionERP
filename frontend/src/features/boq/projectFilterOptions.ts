// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Options for the project filter on the estimates list.
 *
 * Two projects may carry the same name (a copy, or the same job for two
 * clients). The filter used to fold them into one option keyed by name, so
 * picking it filtered on whichever id survived the fold and the other
 * project's estimates could not be reached. Options are keyed by id, and a
 * name shared by more than one project carries a short id so the reader can
 * tell the options apart.
 */

export interface ProjectFilterOption {
  id: string;
  label: string;
}

export function projectFilterOptions(projects: ReadonlyArray<{ id: string; name: string }>): ProjectFilterOption[] {
  const seen = new Set<string>();
  const unique = projects.filter((p) => {
    if (seen.has(p.id)) return false;
    seen.add(p.id);
    return true;
  });
  const nameCount = new Map<string, number>();
  for (const p of unique) nameCount.set(p.name, (nameCount.get(p.name) ?? 0) + 1);
  return unique.map((p) => ({
    id: p.id,
    label: (nameCount.get(p.name) ?? 0) > 1 ? `${p.name} · ${p.id.slice(0, 8)}` : p.name,
  }));
}
