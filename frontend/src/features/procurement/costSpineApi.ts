// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The project's cost spine, read so a buyer can order against a bill position.
 *
 * The buyer picks a position, not a cost line. What the picker actually lists
 * is the cost spine, because a spine line generated from the bill carries the
 * position's code, description, unit and estimate, and it is the set of
 * positions an order can be attributed to. A position with no spine line is
 * not offered, since ordering against it would record no money link at all.
 *
 * What goes back to the server is the `boq_position_id`, not the cost line, so
 * the link is resolved server-side at the moment the order line is written.
 * Sending the cost line we happen to be holding would freeze whatever this
 * page loaded, which may already be stale.
 * `backend/app/modules/procurement/cost_spine.py` sets out why.
 *
 * Narrowing happens on the server, not here. A bill can run to thousands of
 * positions and the endpoint serves at most two hundred at a time, so a filter
 * that could only see what had been loaded would answer "no such position" for
 * a position the register holds, which is a worse answer than an error. The
 * three parameters below exist for that: `search` reaches the whole bill,
 * `linked_to_position` makes the returned rows and their count describe the
 * same set, and `boq_position_id` resolves a selection that sorts past the
 * page so an already attributed line can still be named.
 *
 * The one thing that stays partial is the unsearched list, which is a page of
 * a possibly longer register. `truncated` says so, and the picker prints it.
 */

import { apiGet } from '@/shared/lib/api';

/** One cost line as `GET /v1/costmodel/projects/{id}/spine/lines/` returns it. */
export interface CostSpineLine {
  id: string;
  project_id: string;
  code: string;
  description: string;
  unit: string | null;
  source: string;
  boq_position_id: string | null;
  boq_id: string | null;
  estimate_quantity: string;
  estimate_unit_rate: string;
  estimate_amount: string;
  currency: string;
  status: string;
}

/** The largest page the endpoint serves. Larger values are rejected with a 422. */
export const SPINE_PAGE_SIZE = 200;

/** A page of bill positions, and whether it is the whole of what matched. */
export interface BillPositionPage {
  positions: CostSpineLine[];
  /**
   * The server filled the page exactly, so there is very likely more behind it.
   * A full page is not proof of more (the register may hold exactly this many)
   * but it is the strongest thing a caller can know without a count, and
   * over-warning here is safe where under-warning is not.
   */
  truncated: boolean;
}

function spineUrl(projectId: string, params: URLSearchParams): string {
  return `/v1/costmodel/projects/${projectId}/spine/lines/?${params.toString()}`;
}

/**
 * Sort a page the way a bill reads: 1.2 before 1.10, not after it.
 *
 * The server orders by code as text, which is right for paging and wrong for
 * reading. This reorders within the page it was given and never across pages,
 * so the set on screen is exactly the set the server chose.
 */
function inBillOrder(lines: CostSpineLine[]): CostSpineLine[] {
  return [...lines].sort((a, b) => a.code.localeCompare(b.code, undefined, { numeric: true }));
}

/**
 * The bill positions an order line can be attributed to.
 *
 * `search` is sent only when something was typed. The endpoint declares the
 * parameter with `min_length=1`, so posting an empty string for a cleared
 * filter box would answer 422 and turn "show me everything again" into an
 * error.
 */
export async function fetchBillPositions(projectId: string, search = ''): Promise<BillPositionPage> {
  const params = new URLSearchParams({
    status: 'active',
    linked_to_position: 'true',
    offset: '0',
    limit: String(SPINE_PAGE_SIZE),
  });
  const term = search.trim();
  if (term) params.set('search', term);

  const lines = await apiGet<CostSpineLine[]>(spineUrl(projectId, params));
  return { positions: inBillOrder(lines), truncated: lines.length >= SPINE_PAGE_SIZE };
}

/**
 * The one spine line a position resolves to, or null when it is off the spine.
 *
 * Used to name a selection the picker was opened on. An order raised months ago
 * against position 900 of a 2000-line bill would otherwise load a page that
 * does not contain it, and a control that cannot find its own value falls back
 * to showing none, which is how a saved attribution gets silently dropped on
 * the next save.
 *
 * Deliberately unfiltered by status, unlike the list above. The list offers
 * choices, so it offers live ones. This names a choice already made, and the
 * line it was made against can since have been closed -- `CostLineUpdate`
 * carries `status`, so any PATCH can do it. Filtering here would answer "no
 * such line" for a link the order really holds and reintroduce the blank
 * control this function exists to prevent.
 */
export async function fetchPositionLine(
  projectId: string,
  boqPositionId: string,
): Promise<CostSpineLine | null> {
  const params = new URLSearchParams({
    boq_position_id: boqPositionId,
    offset: '0',
    limit: '1',
  });
  const lines = await apiGet<CostSpineLine[]>(spineUrl(projectId, params));
  return lines[0] ?? null;
}
