// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Friendly, translatable copy for the structured parameter problems the
// backend returns from validate-parameters / expand-preview (Issue #365).
//
// The server hands back a stable `code` (empty_name | duplicate |
// invalid_value | missing_formula | syntax | invalid_ref | cycle |
// div_by_zero) plus a raw English `message`. This maps each known code to an
// i18n key + English default so a call site can render
// `t(key, { defaultValue })`; unknown/future codes return null so the caller
// can fall back to the server message and nothing renders a raw key.

/** An i18n key + its English default for a known parameter-error code. */
export interface ParameterErrorText {
  key: string;
  defaultValue: string;
}

/**
 * Map a structured parameter-error `code` to a translatable message.
 * Returns null for codes we don't have friendly copy for, so the caller
 * surfaces the server-provided message instead.
 */
export function parameterErrorText(code: string): ParameterErrorText | null {
  switch (code) {
    case 'empty_name':
      return {
        key: 'assembly.params.err_empty_name',
        defaultValue: 'Every parameter needs a name.',
      };
    case 'duplicate':
      return {
        key: 'assembly.params.err_duplicate',
        defaultValue: 'Duplicate parameter name - each name must be unique.',
      };
    case 'invalid_value':
      return {
        key: 'assembly.params.err_invalid_value',
        defaultValue: 'Input and constant parameters need a numeric value.',
      };
    case 'missing_formula':
      return {
        key: 'assembly.params.err_missing_formula',
        defaultValue: 'A calculated parameter needs a formula.',
      };
    case 'syntax':
      return {
        key: 'assembly.params.err_syntax',
        defaultValue: 'The formula could not be parsed - check the syntax.',
      };
    case 'invalid_ref':
      return {
        key: 'assembly.params.err_invalid_ref',
        defaultValue: 'A formula references a parameter that does not exist.',
      };
    case 'cycle':
      return {
        key: 'assembly.params.err_cycle',
        defaultValue: 'Calculated parameters reference each other in a cycle.',
      };
    case 'div_by_zero':
      return {
        key: 'assembly.params.err_div_by_zero',
        defaultValue: 'A formula divides by zero at these values.',
      };
    default:
      return null;
  }
}
