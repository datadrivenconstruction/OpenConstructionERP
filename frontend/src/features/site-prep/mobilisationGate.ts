// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What the mobilisation banner is entitled to say.
//
// The banner used to read a plain boolean, and both of its defaults pointed at
// green: an unloaded report became "ready", and an unknown gate count became
// zero. A project with no mobilisation plan at all therefore announced "All
// commencement gates are satisfied. The site can be mobilised." above "Gates
// cleared 0 of 0" - a claim about every member of an empty set, asserted from
// no data whatsoever.
//
// `gate_ready` is not at fault and is not touched. On the server it is a
// blocking predicate ("does anything hard-stop the start"), deliberately
// vacuous without gates and covered by a test that says so. Vacuous truth is a
// sound answer to "is anything blocking" and a false answer to "is everything
// done", and the banner asks the second question. The distinction lives here,
// at the point where a boolean becomes a sentence.

/** What the banner knows about the commencement gates. */
export type MobilisationGateState =
  /** Gates exist and every one of them is satisfied. */
  | 'ready'
  /** Gates exist and at least one is still open. */
  | 'blocked'
  /** No gates are defined, or nothing has loaded: no claim can be made. */
  | 'undetermined';

/** The fields of a readiness report this decision reads. */
interface ReadinessLike {
  gate_ready: boolean;
  overall: { gate_total: number };
}

/** The fields of a gate status this decision reads. */
interface GateLike {
  gate_ready: boolean;
  gate_total: number;
}

/**
 * Decide what the banner may claim, from whichever source has answered.
 *
 * The gate endpoint wins over the readiness report where both are present,
 * matching the precedence the page has always used. Absence is never resolved
 * to a default here: if neither source reports, the state is undetermined,
 * because "we have not been told" and "everything is fine" are different
 * things and only one of them may be printed in green.
 */
export function mobilisationGateState(
  readiness: ReadinessLike | undefined,
  gate: GateLike | undefined,
): MobilisationGateState {
  const total = gate?.gate_total ?? readiness?.overall.gate_total;
  const ready = gate?.gate_ready ?? readiness?.gate_ready;

  // Nothing has loaded, or the payload carries no gate count to reason about.
  if (total === undefined || ready === undefined) return 'undetermined';

  // Gates exist only if some were defined. Nought of nought is not a pass.
  if (total <= 0) return 'undetermined';

  return ready ? 'ready' : 'blocked';
}
