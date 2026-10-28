// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Fill handle and fill down. Two or more numeric seeds continue their step,
 * an ordinal like 01.02.0010 counts on in its last segment keeping the padding,
 * anything else repeats the seeds in order.
 */

const TRAILING_NUMBER = /^(.*?)(\d+)(\D*)$/;

function numericStep(seeds: number[]): number | null {
  if (seeds.length < 2) return null;
  const step = seeds[1]! - seeds[0]!;
  for (let i = 2; i < seeds.length; i += 1) {
    if (Math.abs(seeds[i]! - seeds[i - 1]! - step) > 1e-9) return null;
  }
  return step;
}

/**
 * Values for `count` cells after `seeds`. `parse` reads a seed as a number in
 * the user's locale and `format` writes one back, so a German 2,5 continues as
 * 3,0 and not as 3.0.
 */
export function fillSeries(
  seeds: string[],
  count: number,
  parse: (s: string) => number | null,
  format: (n: number) => string,
): string[] {
  if (seeds.length === 0 || count <= 0) return [];
  const nums = seeds.map(parse);
  if (nums.every((n): n is number => n !== null)) {
    const step = numericStep(nums);
    if (step !== null) {
      const last = nums[nums.length - 1]!;
      return Array.from({ length: count }, (_, i) => format(Math.round((last + step * (i + 1)) * 1e6) / 1e6));
    }
    return Array.from({ length: count }, (_, i) => seeds[i % seeds.length]!);
  }
  const parts = seeds.map((s) => TRAILING_NUMBER.exec(s));
  const first = parts[0];
  if (first && parts.every((p) => p && p[1] === first[1] && p[3] === first[3])) {
    const ns = parts.map((p) => Number(p![2]));
    const step = numericStep(ns) ?? (seeds.length === 1 ? 1 : null);
    if (step !== null && step !== 0) {
      const width = first[2]!.length;
      const last = ns[ns.length - 1]!;
      return Array.from({ length: count }, (_, i) => {
        const n = Math.max(0, last + step * (i + 1));
        return `${first[1]}${String(n).padStart(width, '0')}${first[3]}`;
      });
    }
  }
  return Array.from({ length: count }, (_, i) => seeds[i % seeds.length]!);
}
