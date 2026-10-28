// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure graph helpers for the architecture map's "highlight what's connected"
 * interaction. Kept React-Flow-free (plain ids in, plain Sets out) so the
 * neighbour math is trivial to unit test without booting a canvas;
 * ArchitectureMapPage.tsx turns the result into node/edge styling.
 */

/** The minimal edge shape the neighbourhood math needs. */
export interface GraphEdgeRef {
  id: string;
  source: string;
  target: string;
}

export interface Neighborhood {
  /** The active node plus every node directly joined to it by an edge. */
  nodeIds: Set<string>;
  /** Every edge incident to the active node (either direction). */
  edgeIds: Set<string>;
}

/**
 * Direct neighbourhood of `activeId`: the node itself, its immediate graph
 * neighbours (following edges in either direction) and the edges that join
 * them. This is what turns the dense "hairball" into a readable star - the
 * caller keeps this set at full strength and dims everything else.
 *
 * A null/undefined/empty active id yields empty sets, so "nothing selected"
 * naturally means "highlight nothing" (the whole map stays at full strength).
 */
export function computeNeighborhood(
  edges: ReadonlyArray<GraphEdgeRef>,
  activeId: string | null | undefined,
): Neighborhood {
  const nodeIds = new Set<string>();
  const edgeIds = new Set<string>();
  if (!activeId) return { nodeIds, edgeIds };
  nodeIds.add(activeId);
  for (const e of edges) {
    if (e.source === activeId) {
      nodeIds.add(e.target);
      edgeIds.add(e.id);
    } else if (e.target === activeId) {
      nodeIds.add(e.source);
      edgeIds.add(e.id);
    }
  }
  return { nodeIds, edgeIds };
}

/** Count of direct neighbours (excludes the active node itself), for a
 *  "{{n}} connected" readout. */
export function neighborCount(neighborhood: Neighborhood): number {
  return Math.max(0, neighborhood.nodeIds.size - 1);
}
