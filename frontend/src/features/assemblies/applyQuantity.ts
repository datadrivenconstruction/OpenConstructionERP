/** Parse the "apply to BOQ" quantity field. Returns null unless it is a finite number > 0. */
export function parseApplyQuantity(raw: string): number | null {
  const n = Number(raw.trim());
  return raw.trim() !== '' && Number.isFinite(n) && n > 0 ? n : null;
}
