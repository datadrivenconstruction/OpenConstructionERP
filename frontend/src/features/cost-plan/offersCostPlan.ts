// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Whether a bill has an NRM 1 reading to roll up.
 *
 * The cost plan groups positions by their NRM 1 element. On a project filed
 * under DIN 276, MasterFormat or any other standard it would list every
 * position as unallocated, so the editor offers it only where the reading
 * exists: a project classified under NRM, or a bill whose positions already
 * carry NRM codes (an imported UK bill on a project set up otherwise).
 * Both spellings of the standard are stored, so the match ignores case.
 */
export function offersCostPlan(
  classificationStandard: string | null | undefined,
  positions: ReadonlyArray<{ classification?: Record<string, string> | null }>,
): boolean {
  if ((classificationStandard ?? '').trim().toLowerCase().startsWith('nrm')) return true;
  return positions.some((p) => Boolean(p.classification?.nrm?.trim()));
}
