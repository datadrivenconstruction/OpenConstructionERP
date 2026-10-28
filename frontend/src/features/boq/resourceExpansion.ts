// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Which BOQ positions can show resource sub-rows, and whether they all are.
 *
 * Backs the toolbar's show/hide-all-resources toggle. The point of extracting
 * it is that the answer MUST agree with the per-row chevron: expand-all has to
 * open exactly the rows that render a chevron, or the toggle reports "all
 * expanded" while rows sit closed, or it opens rows that offer no way back.
 *
 * So the predicate here is deliberately the chevron's own, from
 * ``ExpandCellRenderer``: a non-section position whose ``metadata.resources``
 * is a non-empty array. Note in particular that this is NOT
 * :func:`hasContributingResources` - that one asks whether resources carry
 * quantity and drives PRICING. A position whose resources are all blank still
 * gets a chevron, because the user has to be able to open it and type the
 * quantities in. Swapping the two predicates would hide exactly the rows that
 * need attention most.
 *
 * Lives in its own module rather than in ``boqHelpers`` because it needs
 * ``isSection`` from ``./api``, and ``api.ts`` already imports ``boqHelpers``.
 */

import { isSection, type Position } from './api';

/** True when this position renders an expand chevron in the grid. */
export function hasExpandableResources(pos: Position): boolean {
  if (isSection(pos)) return false;
  const resources = (pos.metadata as { resources?: unknown } | undefined)?.resources;
  return Array.isArray(resources) && resources.length > 0;
}

/**
 * Ids of every position that can be expanded to reveal resources, in list
 * order. Empty when the BOQ has no priced positions, which the toolbar uses to
 * disable the toggle rather than offer a control that would do nothing.
 */
export function expandableResourcePositionIds(positions: Position[]): string[] {
  return positions.filter(hasExpandableResources).map((pos) => pos.id);
}

/** How many expandable positions there are, and how many are open right now. */
export interface ResourceExpansionState {
  /** Positions that can show resources at all. */
  expandable: number;
  /**
   * Expandable positions currently open. Counted against the expandable set on
   * purpose: an id can linger in the expanded set after its resources are
   * deleted or the BOQ is refetched, and counting the raw set would then report
   * more open rows than exist and strand the toggle in the "all open" state.
   */
  expanded: number;
}

export function resourceExpansionState(
  positions: Position[],
  expandedIds: ReadonlySet<string>,
): ResourceExpansionState {
  const ids = expandableResourcePositionIds(positions);
  let expanded = 0;
  for (const id of ids) {
    if (expandedIds.has(id)) expanded += 1;
  }
  return { expandable: ids.length, expanded };
}

/**
 * Whether the toggle should read as "on". A BOQ with nothing to expand is
 * never "all expanded", so the button does not sit lit up over an empty grid.
 */
export function allResourcesExpanded(state: ResourceExpansionState): boolean {
  return state.expandable > 0 && state.expanded === state.expandable;
}
