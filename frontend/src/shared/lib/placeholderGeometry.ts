// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Why a converted model shows boxes instead of meshes, from the server's
 * `metadata.placeholder_reason` (see `bim_hub/quantity_warning.py`).
 */

/** True when the converter ran and simply writes no mesh for this format, so an install would change nothing. */
export function placeholderFromConverterWithoutMesh(metadata: Record<string, unknown> | null | undefined): boolean {
  return metadata?.['placeholder_reason'] === 'converter_no_mesh';
}
