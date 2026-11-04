/** Parse a number input value and clamp it into [min, max]; empty or NaN gives min. */
export function clampInput(raw: string, min: number, max = Number.POSITIVE_INFINITY, integer = false): number {
  const n = integer ? parseInt(raw, 10) : parseFloat(raw);
  if (!Number.isFinite(n)) return min;
  return Math.min(max, Math.max(min, n));
}
