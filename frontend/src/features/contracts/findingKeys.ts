// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// React keys for a list of validation findings.
//
// A finding is not an entity and has no id. The obvious key — the rule that
// produced it joined to the element it points at, with the loop index as a
// fallback — looks index-guarded and is not, because the fallback is `?? i` and
// only engages on null. Any rule that reports more than one thing about one
// element defeats it, and so does an element reference of `''`: the EOT rule
// derives its reference from the claim's id and falls back to the empty string,
// which is not null. Both rows then get the same key, React keeps one and drops
// the other, and the user is told about half of what is wrong.
//
// So the key is built from everything that distinguishes the rows, and it
// still ends with an occurrence counter, because "everything" is only
// everything for the rules that exist today. The counter is not the array
// index: it counts repeats of identical content, so a row keeps its key when
// rows around it change, and only rows that are genuinely indistinguishable
// fall back to position.

/** The finding fields both violation lists in this feature carry. */
export interface KeyableFinding {
  rule_id: string;
  element_ref: string | null;
  message: string;
}

/**
 * Stable, unique React keys for `findings`, positionally aligned with it.
 *
 * Returned as an array rather than computed per item so uniqueness is decided
 * over the whole list rather than hoped for one row at a time.
 */
export function findingKeys(findings: readonly KeyableFinding[]): string[] {
  const seen = new Map<string, number>();
  return findings.map((f) => {
    const base = `${f.rule_id}|${f.element_ref ?? ''}|${f.message}`;
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    return n === 0 ? base : `${base}#${n}`;
  });
}
