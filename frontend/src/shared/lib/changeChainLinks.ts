// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Where each record of a commercial change chain lives, as a URL (Issue #435).
 *
 * One change runs through up to five registers - a management-of-change
 * entry, a variation request, a variation order, a change order and the
 * contract it amends - and each register's screen used to hold the id of the
 * record next to it and then navigate to the bare module list, leaving the
 * reader to find by hand the record the app had already identified. These
 * helpers are the one place that knows how to land on the record itself.
 *
 * `?highlight=<id>` is the house convention for list screens (`/boq/:id`,
 * `/inspections`, `/subcontractors`, `/changeorders`): the register reads the
 * param once on mount, opens on that record, and drops the param when the
 * record is closed so a later remount does not re-open what was just closed.
 * The variations page is five registers behind five tabs, so its link also
 * names the tab; a highlight with no tab would be an id the page has to guess
 * the kind of.
 *
 * Kept in `shared/lib` rather than inside any one feature because the four
 * pages that call them would otherwise import each other. A helper pulled out
 * of `VariationsPage` would drag that page, and its bundle chunk, into the
 * change-order and management-of-change chunks.
 */

const encode = (id: string): string => encodeURIComponent(id);

/** The change-order register, open on one change order. */
export function changeOrderDeepLink(changeOrderId: string): string {
  return `/changeorders?highlight=${encode(changeOrderId)}`;
}

/** The contract register, open on one contract. */
export function contractDeepLink(contractId: string): string {
  return `/contracts?highlight=${encode(contractId)}`;
}

/** The variations workspace, on the requests tab, open on one request. */
export function variationRequestDeepLink(variationRequestId: string): string {
  return `/variations?tab=requests&highlight=${encode(variationRequestId)}`;
}

/** The variations workspace, on the orders tab, open on one order. */
export function variationOrderDeepLink(variationOrderId: string): string {
  return `/variations?tab=orders&highlight=${encode(variationOrderId)}`;
}

/**
 * The variation bill of quantities, in the ordinary BOQ editor.
 *
 * A variation bill is an ordinary bill, so it is edited at `/boq/:boqId` -
 * positions, assemblies, markups, revisions and every export work on it
 * unchanged. That is the whole argument for making it a real bill instead of
 * a second, thinner pricing screen inside the variations module.
 */
export function variationBoqDeepLink(boqId: string): string {
  return `/boq/${encode(boqId)}`;
}

/**
 * The variation a record is linked to, order first.
 *
 * A management-of-change entry and a mirrored change order both carry the
 * request id and the order id when both exist. The order is the later and the
 * contractual record, so it is where a reader following the chain forward
 * wants to land; the request is the answer only while no order exists yet.
 * `null` when the record links to no variation at all, so a caller renders no
 * pill rather than a pill to the bare register.
 */
export function linkedVariationDeepLink(links: {
  variation_order_id?: string | null;
  variation_request_id?: string | null;
}): string | null {
  if (links.variation_order_id) return variationOrderDeepLink(links.variation_order_id);
  if (links.variation_request_id) return variationRequestDeepLink(links.variation_request_id);
  return null;
}
