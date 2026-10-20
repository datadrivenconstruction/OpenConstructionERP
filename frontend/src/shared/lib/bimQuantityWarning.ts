// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The warning a CAD/BIM import shows when it could not extract quantities.
 *
 * Without the DDC converter an IFC upload still imports its elements, but the
 * quantities come back empty unless the file carries explicit IFC
 * BaseQuantities. The backend stores such a model as `degraded` and names the
 * reason in `error_code` (codes mirrored from
 * `backend/app/modules/bim_hub/quantity_warning.py`). The upload dock used to
 * report it as a plain success and the viewer said nothing, so empty
 * quantities looked like a finished import. This maps the code to translated
 * text; the backend's English `error_message` is never shown as-is.
 */

export const BIM_QUANTITY_WARNING_CODES = [
  'no_quantities_converter_absent',
  'converter_absent',
  'no_quantities',
  'no_quantities_converter_failed',
  'converter_failed',
] as const;

export type BimQuantityWarningCode = (typeof BIM_QUANTITY_WARNING_CODES)[number];

export interface BimQuantityWarningText {
  key: string;
  defaultValue: string;
}

const TEXT: Record<BimQuantityWarningCode, BimQuantityWarningText> = {
  no_quantities_converter_absent: {
    key: 'bim.quantity_warning.no_quantities_converter_absent',
    defaultValue:
      'Quantities could not be extracted: the DDC converter is not available on this server. The elements were imported for viewing and linking only. Install the converter and retry the import to get areas, volumes and lengths.',
  },
  converter_absent: {
    key: 'bim.quantity_warning.converter_absent',
    defaultValue:
      'The DDC converter is not available on this server, so quantities were read only from the file’s embedded IFC base quantities and may be incomplete. Install the converter and retry the import for complete quantities.',
  },
  no_quantities: {
    key: 'bim.quantity_warning.no_quantities',
    defaultValue:
      'No quantities (area, volume, length) could be extracted from this file. The elements were imported for viewing and linking only.',
  },
  no_quantities_converter_failed: {
    key: 'bim.quantity_warning.no_quantities_converter_failed',
    defaultValue:
      'Quantities could not be extracted: the DDC converter is installed but did not finish this file (it timed out or stopped with an error). The elements were imported for viewing and linking only. Retry the import to run the converter again.',
  },
  converter_failed: {
    key: 'bim.quantity_warning.converter_failed',
    defaultValue:
      'The DDC converter is installed but did not finish this file (it timed out or stopped with an error), so quantities were read only from the file’s embedded IFC base quantities and may be incomplete. Retry the import for complete quantities.',
  },
};

function isWarningCode(code: unknown): code is BimQuantityWarningCode {
  return typeof code === 'string' && (BIM_QUANTITY_WARNING_CODES as readonly string[]).includes(code);
}

/**
 * The warning code for a model, or `null` when its quantities came through.
 *
 * Reads the top-level `error_code` first and falls back to `metadata.error_code`
 * (the single-model and list responses lift it; older payloads only carry it in
 * the metadata). A `degraded` model with no recognised code still warns, as the
 * converter case, since that is the only path that writes `degraded` today.
 */
export function bimQuantityWarningCode(model: {
  status?: string | null;
  error_code?: string | null;
  metadata?: Record<string, unknown> | null;
} | null | undefined): BimQuantityWarningCode | null {
  if (!model || model.status !== 'degraded') return null;
  if (isWarningCode(model.error_code)) return model.error_code;
  const fromMeta = model.metadata?.error_code;
  if (isWarningCode(fromMeta)) return fromMeta;
  return 'no_quantities_converter_absent';
}

/** The i18n key and English default for a warning code. */
export function bimQuantityWarningText(code: BimQuantityWarningCode): BimQuantityWarningText {
  return TEXT[code];
}
