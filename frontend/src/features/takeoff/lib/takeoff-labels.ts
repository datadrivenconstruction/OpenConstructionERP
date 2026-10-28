// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Default-label counter seeding (issue #384).
 *
 * New measurements get an auto label ("Distance 1", "Area 2", ...) from a
 * per-type counter that starts at 0 and increments on each draw. The counter is
 * reset to 0 on every load path (file upload, deep-link, clear-all) but was
 * never re-seeded from the measurements that hydrate afterwards, so a reopened
 * document recounted from 1 and produced a second "Distance 1" alongside the
 * one already on the sheet. Those labels flow into the BOQ export description,
 * where a duplicate is ambiguous.
 *
 * {@link seedAnnotationCounters} scans the hydrated measurements and returns,
 * per measurement type, the highest trailing integer already present in any
 * measurement's annotation / label. The caller raises its per-type counters to
 * these values (never lowering them), so the next auto label resumes above the
 * numbers already in use and can never collide with an existing one.
 *
 * It deliberately keys on the trailing number rather than the localized label
 * prefix, so it stays correct in every language and is robust to a user having
 * renamed a measurement to something ending in a number: over-counting only
 * skips a number (harmless), whereas under-counting would reduplicate.
 */

/** Minimal shape needed to seed counters: the measurement's type and whatever
 *  human label it carries (annotation preferred, label as a fallback). */
export interface Labelled {
  type: string;
  annotation?: string;
  label?: string;
}

/** Highest trailing integer per measurement type across the given measurements.
 *  Types with no numbered label are absent from the result (treated as 0 by the
 *  caller). Does not mutate the input. */
export function seedAnnotationCounters(
  measurements: readonly Labelled[],
): Record<string, number> {
  const counters: Record<string, number> = {};
  for (const m of measurements) {
    const text = m.annotation || m.label || '';
    // Trailing run of digits, ignoring trailing whitespace.
    const match = /(\d+)\s*$/.exec(text);
    if (!match) continue;
    const n = Number.parseInt(match[1]!, 10);
    if (!Number.isFinite(n)) continue;
    if (n > (counters[m.type] ?? 0)) counters[m.type] = n;
  }
  return counters;
}
