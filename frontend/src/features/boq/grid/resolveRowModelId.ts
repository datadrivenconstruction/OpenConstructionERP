// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * Issue #347 - pick the BIM model that a BOQ row's linked elements belong to.
 *
 * A position records its own owning model in `cad_model_id` (stamped when the
 * link was created). The BOQ grid used to resolve EVERY row against one
 * project-level "first ready" model, so in a multi-model project a row whose
 * elements live in another model resolved to nothing (DB-UUID ids -> "not
 * found") or to the wrong element (stable_ids, unique only per model -> a
 * silent wrong quantity).
 *
 * Prefer the row's own model; fall back to the project-level model only when
 * the row has none (legacy rows, or genuinely single-model projects). An empty
 * string is treated as "no model" so a stray blank never suppresses the
 * fallback.
 *
 * @param rowModelId  the position's `cad_model_id` (may be null/undefined/'').
 * @param fallback    the project-level model id (BOQGrid context `bimModelId`).
 * @returns the model id to resolve this row's BIM links against, or null.
 */
export function resolveRowModelId(
  rowModelId: string | null | undefined,
  fallback: string | null | undefined,
): string | null {
  return rowModelId || fallback || null;
}
