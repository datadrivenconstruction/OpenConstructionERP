// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Measurement paint (z) order helpers (issue #379).
 *
 * Takeoff measurements paint in array order (later index = painted on top),
 * and until now the user could not influence it: the only way to bring a shape
 * to the front was to delete and redraw it. These helpers give a measurement an
 * optional explicit ``order`` key that drives the paint order everywhere it
 * matters - the canvas paint pass, the click hit-test precedence, the sidebar
 * list and the PDF export - so a bring-to-front / send-to-back stays consistent
 * across all four surfaces and survives a reload (the key round-trips via the
 * measurement metadata blob, so no schema change is needed).
 *
 * A measurement the user never reordered carries no ``order``; it then falls
 * back to its position in the array (creation order, the stable #375 baseline),
 * so existing measurements are painted exactly as before.
 */

/** Minimal shape the ordering helpers need: an optional numeric order key and
 *  the group the row belongs to (issue #394 bands the projection by group). */
export interface Orderable {
  order?: number;
  group?: string;
  /** This row's copy of its group's band (issue #393). A cache of the
   *  authoritative map, never an input to it except at hydration. See
   *  {@link hydrateGroupBands}. */
  groupBand?: number;
}

/** Group name a row with no group of its own is filed under. Matches the
 *  `m.group || 'General'` idiom the sidebar and the exporters bucket with, so a
 *  row whose group is an empty string bands where it is displayed. A `??`
 *  fallback would band it separately from the bucket it renders in. */
const DEFAULT_GROUP = 'General';

/** Empty band map. Every group then resolves to band 0, so a banded sort
 *  collapses to the single-level behaviour and callers that pass nothing are
 *  unaffected. */
const NO_GROUP_ORDER: Readonly<Record<string, number>> = {};

/**
 * Resolve the group a row bands, buckets and scopes under.
 *
 * Exported so every surface that groups measurements normalises the same way.
 * A raw `a.group === b.group` comparison splits an empty-string group away from
 * the General bucket it actually renders in, which silently scopes an operation
 * to the wrong set; going through here is what keeps banding, bucketing and the
 * band-scoped bring-to-front / send-to-back agreeing on what a group is.
 */
export const groupOf = (item: Orderable): string => item.group || DEFAULT_GROUP;

/**
 * Assign each group a band, deciding where its block sits relative to the other
 * groups (issue #394).
 *
 * Until now a group's position was a side effect of its members' paint keys: a
 * group block sat wherever its earliest member happened to land, so restacking
 * one measurement relocated its whole group. A band gives the group a position
 * of its own, and defaults it to first appearance in the array - creation order,
 * which no per-measurement reorder can change.
 *
 * ``explicit`` wins where it is set, and any group missing from it is banded
 * after the highest explicit band, in first-appearance order. Passing nothing
 * makes the whole map derived: opening a document writes nothing, and two
 * clients looking at the same measurements compute the same bands without
 * either having to store them (issue #400 is what fills ``explicit`` in).
 */
export function groupBands<T extends Orderable>(
  items: readonly T[],
  explicit: Readonly<Record<string, number>> = NO_GROUP_ORDER,
): Record<string, number> {
  const bands: Record<string, number> = { ...explicit };
  // Derived bands start above every explicit one so an un-banded group never
  // displaces a group the user positioned deliberately.
  let next = 0;
  for (const band of Object.values(explicit)) next = Math.max(next, band + 1);
  for (const item of items) {
    const group = groupOf(item);
    if (bands[group] === undefined) bands[group] = next++;
  }
  return bands;
}

/**
 * Stable projection of a measurement list into paint (z) order.
 *
 * Higher effective order paints later (on top). The effective order of a row is
 * its explicit ``order`` when set, else its index in the input array, so a set
 * with no explicit keys is returned in its original order. Ties (an explicit
 * key equal to another row's index, or two equal keys) break on the original
 * index, keeping the sort deterministic and stable.
 *
 * ``groupOrder`` makes the projection band-major (issue #394): rows sort by
 * their group's band first, so every group paints as one contiguous block and a
 * measurement-level reorder can no longer move its group. Omitting it leaves
 * every row in band 0, which collapses the comparator to the ``key`` / ``index``
 * tie-breaks above - so every existing caller keeps its current behaviour.
 *
 * Does not mutate the input.
 */
export function sortByPaintOrder<T extends Orderable>(
  items: T[],
  groupOrder: Readonly<Record<string, number>> = NO_GROUP_ORDER,
): T[] {
  return items
    .map((item, index) => ({
      item,
      index,
      band: groupOrder[groupOf(item)] ?? 0,
      key: item.order ?? index,
    }))
    .sort((a, b) => a.band - b.band || a.key - b.key || a.index - b.index)
    .map((entry) => entry.item);
}

/**
 * Compute the band map that drops one group next to another (issue #400).
 *
 * Unlike a measurement drop, this renumbers every group sequentially rather
 * than handing the moved group a fractional key between its new neighbours.
 * The reason is {@link groupBands}' creation-order default: it bands every
 * group with no explicit entry AFTER the highest explicit one. Banding the
 * dragged group alone would therefore push every untouched group above it -
 * dropping ``C`` between ``A`` and ``B`` with nothing banded yet would give
 * ``C`` 0.5 and then re-derive ``A`` and ``B`` above it, landing ``C`` at the
 * front instead of the middle. Stamping every group in one pass is what makes
 * the result the order the user actually dropped.
 *
 * ``displayed`` must list EVERY group in the document, not just the groups on
 * the current page: the band map is per document, so renumbering only the
 * visible subset would drop the band of every group that lives on another page.
 *
 * Returns ``null`` when the move changes nothing (same group, either name
 * missing, or the drop resolves to the slot the group already occupies), so the
 * caller can skip a write that would otherwise re-stamp every measurement.
 */
export function reorderGroups(
  displayed: readonly string[],
  draggedGroup: string,
  targetGroup: string,
  place: 'before' | 'after',
): Record<string, number> | null {
  if (draggedGroup === targetGroup) return null;
  if (!displayed.includes(draggedGroup) || !displayed.includes(targetGroup)) return null;
  // Remove the dragged group BEFORE resolving the target's index. Splicing at
  // the target's index in the original list would put a group dragged from
  // above the target straight back where it started, so the move would silently
  // no-op in exactly the direction users try first.
  const rest = displayed.filter((g) => g !== draggedGroup);
  const targetIdx = rest.indexOf(targetGroup);
  if (targetIdx === -1) return null;
  const insertAt = place === 'before' ? targetIdx : targetIdx + 1;
  const next = [...rest.slice(0, insertAt), draggedGroup, ...rest.slice(insertAt)];
  // A drop back into the same slot is not worth a document-wide write.
  if (next.every((g, i) => g === displayed[i])) return null;
  const bands: Record<string, number> = {};
  next.forEach((g, i) => {
    bands[g] = i;
  });
  return bands;
}

/**
 * Compute the ``order`` value that moves one row to an edge of the stack.
 *
 * ``edge: 'front'`` returns ``max(effective order) + 1`` so the row paints on
 * top of every other row in ``subset``; ``edge: 'back'`` returns
 * ``min(effective order) - 1`` so it paints beneath them. The effective order
 * uses the same index fallback as {@link sortByPaintOrder}, so bring-to-front
 * works even when nothing in ``subset`` has an explicit key yet. Only the moved
 * row's key changes - neighbours are never renumbered - so a reorder is a
 * single-row edit (one PATCH), not a bulk rewrite.
 *
 * Returns ``null`` when ``subset`` is empty (nothing to compare against).
 */
export function orderKeyForEdge<T extends Orderable>(
  subset: T[],
  edge: 'front' | 'back',
): number | null {
  if (subset.length === 0) return null;
  // Reduce rather than spread into Math.max/min: a large document can hold
  // thousands of measurements, and ``Math.max(...bigArray)`` can overflow the
  // call stack.
  let acc = subset[0]!.order ?? 0;
  for (let i = 1; i < subset.length; i++) {
    const key = subset[i]!.order ?? i;
    acc = edge === 'front' ? Math.max(acc, key) : Math.min(acc, key);
  }
  return edge === 'front' ? acc + 1 : acc - 1;
}

/**
 * Order key that inserts a row between two effective paint keys (issue #379
 * drag-to-reorder). A ``null`` bound means the very back (``below``) or the very
 * front (``above``) of the stack, so the row steps one unit past the present
 * edge; between two real keys it takes their midpoint, which keeps the moved row
 * strictly between its new neighbours without renumbering them (a single-row
 * PATCH). With both bounds null (an empty stack) it returns 0.
 */
export function orderKeyBetween(below: number | null, above: number | null): number {
  if (below === null && above === null) return 0;
  if (below === null) return above! - 1;
  if (above === null) return below! + 1;
  return (below + above) / 2;
}

/**
 * Compute the ``order`` key that drops ``draggedId`` next to ``targetId`` in the
 * paint-order projection (issue #379). ``place`` decides whether the dragged row
 * lands immediately before or after the target in that projection. Effective
 * keys use the same ``order ?? array-index`` fallback as {@link sortByPaintOrder}
 * so the result is consistent with the canvas / hit-test / sidebar ordering, and
 * the dragged row is excluded when picking the neighbours so it does not compare
 * against its own old slot.
 *
 * The neighbours are scoped to the TARGET's group (issue #393). Since the
 * projection became band-major the key only ever competes with the keys inside
 * one band, so a key picked against the whole flat list is meaningless the
 * moment the two groups differ: it would be compared against rows that sort in
 * a different band entirely and could land the row anywhere within its new
 * group. Scoping is what makes a cross-group drop land where it was dropped.
 * With every row in one group this is the whole list, so a single-group
 * document behaves exactly as before.
 *
 * The effective keys are still computed from each row's index in the FULL array
 * before scoping. That fallback has to match {@link sortByPaintOrder}, which
 * indexes globally; renumbering from zero inside the group would give a row
 * with no explicit key a different effective key here than it has on screen.
 *
 * Returns ``null`` when the target is missing or the drop is a no-op (the
 * dragged row would keep its current key AND its current group), so the caller
 * can skip the update.
 *
 * This is the single-row half of {@link planMeasurementDrop}, and it is the
 * whole answer only while a distinct midpoint still exists. Where the gap is
 * exhausted (issue #405) it returns ``null`` rather than a key equal to a
 * neighbour's: refusing the drop is wrong, but it is a visible kind of wrong,
 * whereas the colliding key silently put the row on the other side of the row
 * it was dropped against and carried that into every export. A caller that has
 * to place the row, rather than merely price the move, wants
 * {@link planMeasurementDrop}.
 */
export function orderKeyForDrop<T extends Orderable & { id: string }>(
  items: readonly T[],
  draggedId: string,
  targetId: string,
  place: 'before' | 'after',
): number | null {
  const plan = planMeasurementDrop(items, draggedId, targetId, place);
  return plan !== null && plan.kind === 'single' ? plan.order : null;
}

/* ── Exhausted gaps (issue #405) ─────────────────────────────────────────── */

/**
 * Did ``key`` land strictly between its bounds?
 *
 * {@link orderKeyBetween} promises a value between its two neighbours, and for
 * a midpoint that promise is arithmetic rather than absolute: ``order`` is a
 * float64, so once a gap is narrow enough its midpoint rounds to one of its own
 * bounds and the promise quietly stops holding. A ``null`` bound is the edge of
 * the stack and constrains nothing, but the step past it is checked too, since
 * ``below + 1`` also stops moving out near the top of the range.
 */
function landedBetween(key: number, below: number | null, above: number | null): boolean {
  if (below !== null && !(key > below)) return false;
  if (above !== null && !(key < above)) return false;
  return true;
}

/**
 * What a drop has to write. Either one row's new key, or, when the gap the row
 * was dropped into can no longer hold a distinct key, a new key for every row
 * in the target's group.
 */
export type DropPlan =
  | { readonly kind: 'single'; readonly id: string; readonly order: number }
  | { readonly kind: 'renumber'; readonly orders: ReadonlyMap<string, number> };

/**
 * Resolve a drop into the writes that perform it (issue #405).
 *
 * {@link orderKeyForDrop} hands the dropped row the midpoint of its two new
 * neighbours, which keeps a drag to a single-row write. Repeated drops into the
 * SAME slot halve that gap each time, and float64 runs out: measured against
 * this module, three rows with no explicit keys take 53 drops before the
 * midpoint comes back equal to the target's own key, and 55 before the no-op
 * guard reads a real drop as a no-op and nothing moves at all. The keys live in
 * the measurement metadata, so the count accumulates across sessions instead of
 * needing one long sitting, and nothing renumbers them: ``reorderGroups``
 * renumbers group bands, never measurement keys.
 *
 * Once two rows hold the same key {@link sortByPaintOrder} breaks the tie on
 * array position. That is stable and survives a reload, but it is not the slot
 * the row was released into, and the same wrong projection is what the annotated
 * PDF, the spreadsheet exports and the BOQ ordinals all read.
 *
 * So the midpoint is checked rather than trusted. When it lands where it was
 * promised the plan is the single-row write the drag has always been. When it
 * does not, the whole of the target's group is renumbered to consecutive
 * integers in the order the user actually asked for, which reopens unit-wide
 * gaps and puts the row where it was dropped. The slow path is paid only on the
 * drop that would otherwise fail.
 *
 * Three details are forced by existing behaviour rather than chosen:
 *
 * - The renumber spans the group across the WHOLE array, not the current page,
 *   for the reason {@link sortByPaintOrder} already implies: the projection is
 *   per document, so renumbering a page would strand the group's rows on other
 *   pages against freshly numbered neighbours.
 * - Every row in the group is given an explicit key, including rows that never
 *   carried one. Leaving those on the ``order ?? index`` fallback would sort
 *   them against the new integers by array position, which is not where they
 *   are on screen.
 * - The dragged row is numbered along with the rest, since it is excluded from
 *   its own neighbour search and would otherwise keep its stale key.
 *
 * Returns ``null`` when the target is missing or the drop changes nothing: the
 * dragged row already holds the key AND the group, or, on the renumber path,
 * the group is already in the requested order.
 */
export function planMeasurementDrop<T extends Orderable & { id: string }>(
  items: readonly T[],
  draggedId: string,
  targetId: string,
  place: 'before' | 'after',
): DropPlan | null {
  if (draggedId === targetId) return null;
  const target = items.find((m) => m.id === targetId);
  if (!target) return null;
  const targetGroup = groupOf(target);
  // Effective key per row, indexed on the ORIGINAL array position so the
  // fallback matches sortByPaintOrder; then keep only the target's group and
  // sort exactly as the projection does, index breaking a tie.
  const inGroup = items
    .map((item, index) => ({
      id: item.id,
      order: item.order,
      group: groupOf(item),
      key: item.order ?? index,
      index,
    }))
    .filter((k) => k.group === targetGroup)
    .sort((a, b) => a.key - b.key || a.index - b.index);
  // The dragged row must not compare against its own old slot when the
  // neighbours are picked.
  const neighbours = inGroup.filter((k) => k.id !== draggedId);
  const targetIdx = neighbours.findIndex((k) => k.id === targetId);
  if (targetIdx === -1) return null;
  const insertAt = place === 'before' ? targetIdx : targetIdx + 1;
  const below = insertAt > 0 ? neighbours[insertAt - 1]!.key : null;
  const above = insertAt < neighbours.length ? neighbours[insertAt]!.key : null;
  const newOrder = orderKeyBetween(below, above);
  const dragged = items.find((m) => m.id === draggedId) ?? null;

  if (landedBetween(newOrder, below, above)) {
    // A row that already holds this key but sits in another group is still a
    // real move: the caller has a group change to apply even though the key is
    // unchanged. Only a same-group, same-key drop is the no-op.
    if (dragged && dragged.order === newOrder && groupOf(dragged) === targetGroup) return null;
    return { kind: 'single', id: draggedId, order: newOrder };
  }

  const requested = [
    ...neighbours.slice(0, insertAt).map((k) => k.id),
    draggedId,
    ...neighbours.slice(insertAt).map((k) => k.id),
  ];
  // Renumbering repairs the collapsed keys, but a drop onto the slot the row is
  // already in is still not a drop. Checking the projected order rather than the
  // keys is what makes this a no-op only when the screen would not change.
  const current = inGroup.map((k) => k.id);
  if (
    dragged &&
    groupOf(dragged) === targetGroup &&
    current.length === requested.length &&
    current.every((id, i) => id === requested[i])
  ) {
    return null;
  }
  const orders = new Map<string, number>();
  requested.forEach((id, i) => orders.set(id, i));
  return { kind: 'renumber', orders };
}

/* ── Pinning the band map (issue #393) ──────────────────────────────────── */

/**
 * Freeze the band map that is currently on screen.
 *
 * {@link groupBands} defaults a group's band to its first appearance in the
 * measurement array, which is stable right up until a measurement changes
 * group. Moving the first-appearing member of one group into another re-derives
 * the group it left from its next member, and that member can sit anywhere, so
 * two group blocks trade places because the user dragged a single row. That is
 * the very complaint issue #394 is about, arriving through a different door.
 *
 * Stamping the whole map before such a move pins every group where the user can
 * see it, so the move changes exactly what was dragged. Every group in the
 * document is stamped, not the groups on the current page: the map is per
 * document, and a partial stamp would drop the band of every group living on
 * another sheet.
 *
 * Only regrouping needs this. A plain restack cannot change any group's first
 * appearance, so it must not stamp, or the derived default would be dead code
 * after the first drag in any document.
 */
export function freezeGroupBands<T extends Orderable>(
  items: readonly T[],
  explicit: Readonly<Record<string, number>> = NO_GROUP_ORDER,
): Record<string, number> {
  return groupBands(items, explicit);
}

/**
 * Learn the band map back from the copies mirrored onto the measurements.
 *
 * The measurements are what round-trips to the server, so on a cache-less
 * reload the mirrored copy is the only surviving evidence of a pinned map. This
 * is the ONE place a mirrored band may be read as an input; everywhere else the
 * map is authoritative and the copy is a cache of it. Issue #398 is what that
 * rule is for: when two writers each read a snapshot the other had already
 * invalidated, the pair had no fixed point and rewrote each other forever.
 *
 * Returns the original object when it learns nothing, so a caller storing this
 * in state does not re-render on every pass.
 */
export function hydrateGroupBands<T extends Orderable>(
  bands: Readonly<Record<string, number>>,
  items: readonly T[],
): Record<string, number> {
  let changed = false;
  const next: Record<string, number> = { ...bands };
  for (const item of items) {
    if (item.groupBand === undefined) continue;
    const group = groupOf(item);
    if (next[group] !== item.groupBand) {
      next[group] = item.groupBand;
      changed = true;
    }
  }
  return changed ? next : (bands as Record<string, number>);
}

/**
 * Copy the authoritative map onto the rows that mirror it.
 *
 * The single standing writer of the pair, matching how the group colour scheme
 * was rebuilt after issue #398. A group the map does not know about is left
 * alone rather than cleared: the mirrored band is the only evidence that such a
 * group was ever pinned, and clearing it would destroy that evidence before
 * {@link hydrateGroupBands} had the chance to read it, which is exactly what
 * happens when rows arrive from the server after the user has already drawn
 * something.
 *
 * Returns the original array when nothing needs writing, so this can sit in an
 * effect without looping.
 */
export function stampGroupBands<T extends Orderable>(
  items: T[],
  bands: Readonly<Record<string, number>>,
): T[] {
  let changed = false;
  const next = items.map((item) => {
    const band = bands[groupOf(item)];
    if (band === undefined || item.groupBand === band) return item;
    changed = true;
    return { ...item, groupBand: band };
  });
  return changed ? next : items;
}

/** Inputs the band commit decides from. */
export interface GroupBandState<T extends Orderable> {
  bands: Readonly<Record<string, number>>;
  items: T[];
  /** Document identity the bands were last hydrated for, or null. */
  hydratedFor: string | null;
}

/** What the caller should write this pass. A ``null`` side is left alone. */
export interface GroupBandAction<T extends Orderable> {
  bands: Record<string, number> | null;
  items: T[] | null;
  hydratedFor: string | null;
}

/**
 * Decide which half of the band pair to write (issues #393/#398).
 *
 * Deliberately a plain function rather than logic inside an effect, and
 * deliberately the same shape as the group-colour commit next door. Issue #398
 * is the reason both exist: two standing effects, one writing in each
 * direction, each reading a snapshot the other had already invalidated, had no
 * fixed point and rewrote each other forever. Here the direction is one way per
 * pass and settled before any state is touched, so it can be reasoned about and
 * tested without rendering anything.
 *
 * Until a document has been hydrated the mirrored copies are the input and the
 * map is the output; from then on the map is the input and the copies are the
 * output, forever. An empty item list leaves the gate open rather than
 * declaring the document hydrated, because rows still arriving from the server
 * would otherwise be treated as a document that had nothing pinned.
 */
export function groupBandCommit<T extends Orderable>(
  state: GroupBandState<T>,
  identity: string,
): GroupBandAction<T> {
  if (state.hydratedFor !== identity) {
    if (state.items.length === 0) {
      return { bands: null, items: null, hydratedFor: state.hydratedFor };
    }
    return {
      bands: hydrateGroupBands(state.bands, state.items),
      items: null,
      hydratedFor: identity,
    };
  }
  const items = stampGroupBands(state.items, state.bands);
  return {
    bands: null,
    items: items === state.items ? null : items,
    hydratedFor: state.hydratedFor,
  };
}
