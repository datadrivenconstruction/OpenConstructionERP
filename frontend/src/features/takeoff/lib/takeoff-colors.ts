// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Group-colour reconciliation for the PDF takeoff viewer (issues #396/#397/#398).
 *
 * A group's custom colour lives in two places. `customGroupColors` is a map
 * keyed by group name; the same value is mirrored onto every measurement as
 * `groupColor` so the colour scheme round-trips to the server inside the
 * existing metadata blob without a schema change.
 *
 * The invariant these helpers exist to enforce:
 *
 *   The MAP is authoritative for every group it knows about. The copy mirrored
 *   onto a measurement is a cache of that map, never an input to it, except at
 *   one moment: hydration, which is how the map learns about a group in the
 *   first place.
 *
 * Before this module the two copies were kept in step by two standing effects,
 * one writing in each direction, each reading a snapshot the other had already
 * invalidated. When the two disagreed there was no fixed point: each write
 * republished the value it had read one render earlier, so the pair alternated
 * forever, kept every affected row permanently dirty (blocking the debounced
 * save) and wrote the inconsistent map back to localStorage, so a reload
 * resumed the loop instead of ending it.
 *
 * The direction is therefore one-way by construction here: {@link stampGroupColors}
 * is the only standing writer, {@link hydrateGroupColors} runs once per opened
 * document, and {@link groupColorCommit} owns the decision between the two so
 * the gate is testable rather than living inside a React effect.
 */

/** The subset of a measurement these helpers read and write. Structural on
 *  purpose: the viewer's `Measurement` and the shared lib `Measurement` both
 *  satisfy it, so neither has to import the other. */
export interface GroupColored {
  /** Name of the group this measurement belongs to. */
  group: string;
  /** Mirror of the group's custom colour. Undefined means "this group has no
   *  custom colour", which is a real, storable state (`group_custom_color`
   *  absent from the metadata blob), not a missing value. */
  groupColor?: string;
}

/** Group name -> custom colour. The authority while a document is open. */
export type GroupColors = Record<string, string>;

/** Base colour a measurement paints in when neither it nor its group has one. */
export const DEFAULT_MEASUREMENT_COLOR = '#3B82F6';

/**
 * The colour a measurement actually paints in.
 *
 * The precedence - own override, then group, then base - is the other half of
 * the clearing story in #396: clearing an override is only meaningful because
 * something downstream falls back to the group, so the two have to be read
 * together or "clear" silently means "paint in the base blue". It was written
 * out by hand at every site that needed it, which is how an override could be
 * cleared in one place and still honoured in another.
 *
 * Absent and empty are both treated as "no override": the swatches store a hex
 * string and clearing stores nothing, so an empty string only ever arrives from
 * a malformed row, and treating it as a colour would paint that row invisible.
 */
export function resolveMeasurementColor(
  measurement: { color?: string } & GroupColored,
  colors: GroupColors,
  fallback: string = DEFAULT_MEASUREMENT_COLOR,
): string {
  return measurement.color || colors[measurement.group] || fallback;
}

/**
 * Fold the colours mirrored onto measurements back into the map.
 *
 * This is a LOAD-TIME step, not a standing invariant. A colour chosen on
 * another machine (or in an earlier session, on a browser whose localStorage
 * was cleared) reaches this client only inside each measurement's metadata, so
 * the map has to be taught it once when the rows arrive. Running it on every
 * change to the array is what made the mirror a second writer.
 *
 * The mirror wins over the map here, deliberately: at load the map is a local
 * cache (localStorage) while the mirror came off the server, so the mirror is
 * the copy other people can see. That also gives a document already stuck in
 * the inconsistent state a deterministic way out - it settles on the server's
 * value instead of resuming the alternation.
 *
 * Returns the SAME object when nothing changed, so a caller can use reference
 * equality to skip a re-render.
 */
export function hydrateGroupColors(
  colors: GroupColors,
  measurements: GroupColored[],
): GroupColors {
  let changed = false;
  const next: Record<string, string> = { ...colors };
  for (const m of measurements) {
    if (m.groupColor && next[m.group] !== m.groupColor) {
      next[m.group] = m.groupColor;
      changed = true;
    }
  }
  return changed ? next : colors;
}

/**
 * Copy the authoritative map onto the measurements that mirror it.
 *
 * The only standing writer in the pair. A group the map does not know about is
 * left alone rather than cleared: a mirrored colour is the only evidence that
 * such a group was ever coloured, and clearing it would destroy that evidence
 * before {@link hydrateGroupColors} had a chance to read it - for instance when
 * rows resolve from the server after the user has already drawn something, so
 * the document is marked hydrated before those rows exist. Leaving it costs one
 * session of the group rendering in its base colour; clearing it would PATCH
 * the loss to the server permanently.
 *
 * Returns the SAME array when nothing changed.
 */
export function stampGroupColors<M extends GroupColored>(
  measurements: M[],
  colors: GroupColors,
): M[] {
  let changed = false;
  const next = measurements.map((m) => {
    const wanted = colors[m.group];
    if (wanted === undefined || m.groupColor === wanted) return m;
    changed = true;
    return { ...m, groupColor: wanted };
  });
  return changed ? next : measurements;
}

/**
 * Move a measurement into another group, re-pointing its mirrored colour at the
 * destination group's colour in the same step.
 *
 * Carrying the source group's colour across is what repainted the destination:
 * the stale mirror was published to the whole destination group by the
 * reconstruction pass, so one property edit rewrote a group-level setting. The
 * destination may legitimately have no custom colour, in which case the mirror
 * is cleared (undefined) and the group keeps its base colour.
 *
 * Pass the measurement as it stood BEFORE the rest of the patch was applied:
 * called on an already-patched row the guard compares the new group with
 * itself, returns early, and leaves the stale colour attached.
 */
export function retargetGroupColor<M extends GroupColored>(
  measurement: M,
  group: string,
  colors: GroupColors,
): M {
  if (measurement.group === group) return measurement;
  return { ...measurement, group, groupColor: colors[group] };
}

/** State the viewer holds for one document's group colours. */
export interface GroupColorState<M extends GroupColored> {
  /** The authoritative map. */
  colors: GroupColors;
  /** The rows carrying the mirrored copy. */
  measurements: M[];
  /** Document identity the map was hydrated for; null before any hydration.
   *  A plain string identity (never null) is used for the documents themselves,
   *  so null can never collide with a real one. */
  hydratedFor: string | null;
}

/**
 * What the viewer should write in this commit.
 *
 * Both copies are nullable, and AT MOST ONE of them is ever non-null. That is
 * the contract the whole fix rests on, and it is expressible here precisely so
 * a test can hold it: the defect was two writes landing in the same commit,
 * each computed from the state the other had already superseded. A shape that
 * could not describe the broken behaviour would make the tests unfalsifiable.
 */
export interface GroupColorAction<M extends GroupColored> {
  /** Map to publish, or null to leave the map alone this commit. */
  colors: GroupColors | null;
  /** Rows to publish, or null to leave the mirror alone this commit. */
  measurements: M[] | null;
  /** Identity the map is hydrated for once this commit is applied. */
  hydratedFor: string | null;
}

/**
 * Decide what a single reconciliation commit should write.
 *
 * Hydration happens once per document identity and STOPS there: the commit that
 * hydrates does not also stamp, so the map hydration produced is the one the
 * NEXT commit publishes, rather than a stamp reading the pre-hydration map and
 * fighting it. One writer per commit is the entire mechanism, which is why the
 * decision lives here - where a test can drive it - instead of inside a React
 * effect where only a browser could.
 *
 * ``identity`` must identify the DOCUMENT, not just its id: a freshly dropped
 * local file has no server id yet, so several such files would otherwise share
 * one identity and only the first would ever hydrate.
 */
export function groupColorCommit<M extends GroupColored>(
  state: GroupColorState<M>,
  identity: string,
): GroupColorAction<M> {
  if (state.hydratedFor !== identity) {
    // Nothing to hydrate FROM yet. Staying un-hydrated is the safe answer: it
    // keeps the gate open for the rows that are still loading.
    if (state.measurements.length === 0) {
      return { colors: null, measurements: null, hydratedFor: state.hydratedFor };
    }
    return {
      colors: hydrateGroupColors(state.colors, state.measurements),
      measurements: null,
      hydratedFor: identity,
    };
  }
  const measurements = stampGroupColors(state.measurements, state.colors);
  return {
    colors: null,
    measurements: measurements === state.measurements ? null : measurements,
    hydratedFor: state.hydratedFor,
  };
}

/**
 * Document identity for the group-colour gate.
 *
 * Deliberately the same triple the persistence hook keys its load on: a null
 * document id is a normal state (a local drop that has not been uploaded), so
 * the id alone would make every such file look like the same document.
 */
export function groupColorIdentity(
  projectId: string | null | undefined,
  documentId: string | null | undefined,
  fileName: string | null | undefined,
): string {
  return `${projectId ?? ''}|${documentId ?? ''}|${fileName ?? ''}`;
}
