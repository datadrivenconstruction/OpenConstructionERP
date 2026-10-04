// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Where each record of the buying chain lives, as a URL, and which contract or
 * purchase order an award produced.
 *
 * A bill is put out to tender, the bids are compared, one is awarded, and the
 * award drafts a contract and a purchase order. Each of those screens knew the
 * id of the record next to it and still sent the reader to the bare module
 * list, so the reader had to find by hand what the app had already
 * identified. The sibling `changeChainLinks` does the same job for the change
 * chain (variation, change order, contract); this file is the buying half.
 *
 * Every destination here is one a page really consumes:
 *
 * - `/tendering?package=<id>` - TenderingPage opens that package once the list
 *   has loaded (the BOQ editor's "Send to tender" already used it).
 * - `/bid-management?highlight=<id>` - BidManagementPage opens that package's
 *   drawer and drops the param when the drawer is closed.
 * - `/boq/<id>` and `/boq/<id>?highlight=<positionId>` - the BOQ editor, with
 *   the row scrolled to and flashed.
 * - `/boq?positionId=<id>` - BOQListPage resolves the bill that owns a
 *   position and redirects to the editor on that row. Used where only the
 *   position id is known.
 * - `/finance?tab=budgets` - the budget lines, where an approved change order
 *   writes its revised-budget row.
 * - `/procurement?po=<id>` - ProcurementPage opens the purchase-order tab and
 *   scrolls to and marks that order, or names it when it is not on the page.
 * - `/rfq-bidding?rfq=<id>` - RFQBiddingPage opens the tab that RFQ lives on
 *   (Awards once it is awarded) and marks it.
 *
 * The bare `PROCUREMENT_LINK` stays for the places that know no order id yet.
 */

const encode = (id: string): string => encodeURIComponent(id);

/** The tender register, open on one tender package. */
export function tenderPackageDeepLink(tenderPackageId: string): string {
  return `/tendering?package=${encode(tenderPackageId)}`;
}

/** The bid-management register, open on one bid package. */
export function bidPackageDeepLink(bidPackageId: string): string {
  return `/bid-management?highlight=${encode(bidPackageId)}`;
}

/** The BOQ editor on one bill, optionally scrolled to one row of it. */
export function boqDeepLink(boqId: string, positionId?: string | null): string {
  const base = `/boq/${encode(boqId)}`;
  return positionId ? `${base}?highlight=${encode(positionId)}` : base;
}

/** The BOQ editor on the bill that owns a position, resolved from the position alone. */
export function boqPositionDeepLink(positionId: string): string {
  return `/boq?positionId=${encode(positionId)}`;
}

/** The project's budget lines. */
export const FINANCE_BUDGETS_LINK = '/finance?tab=budgets';

/** The purchase-order register, with no order in focus. */
export const PROCUREMENT_LINK = '/procurement';

/** The purchase-order register, open on one order. */
export function purchaseOrderDeepLink(poId: string): string {
  return `/procurement?po=${encode(poId)}`;
}

/** The request-for-quotation register. */
export const RFQ_LINK = '/rfq-bidding';

/** The request-for-quotation register, open on one RFQ. */
export function rfqDeepLink(rfqId: string): string {
  return `/rfq-bidding?rfq=${encode(rfqId)}`;
}

/* ── Which record an award produced ─────────────────────────────────────── */

/**
 * The metadata keys an award stamps on the contract and the purchase order it
 * drafts. The tender path writes `tender_package_id`; the bid-management path
 * writes `bid_package_id` and, when its package is linked to a tender package,
 * `tender_package_id` as well. That shared key is how the two paths converge on
 * one contract and one order for one logical award (see
 * `bid_management/award_contract.py` and `procurement/events.py`).
 */
export interface AwardKeys {
  tender_package_id?: string | null;
  /** Several bid packages can point at one tender package. */
  bid_package_ids?: readonly (string | null | undefined)[];
}

/** A row that can carry an award stamp: a contract or a purchase order. */
export interface AwardStampedRow {
  status: string;
  metadata?: Record<string, unknown> | null;
}

/**
 * A contract in this status no longer stands for the award: the server drafts
 * a new one on a re-award rather than finding it (`_RETIRED_CONTRACT_STATUSES`).
 */
export const RETIRED_AWARD_CONTRACT_STATUSES: ReadonlySet<string> = new Set(['terminated']);

/**
 * A cancelled order does not count either: re-awarding requires cancelling the
 * order first, and the re-award then raises a new one (`_find_existing_po`).
 */
export const RETIRED_AWARD_ORDER_STATUSES: ReadonlySet<string> = new Set(['cancelled']);

/**
 * The row an award produced, or `null` when none in `rows` carries its stamp.
 *
 * Mirrors the server's own lookup: a match on any non-empty key counts, and a
 * retired row is passed over. The rows are taken in the order given, so a
 * caller that lists newest first gets the newest live record.
 *
 * `null` means "not among these rows", not "the award produced nothing". A
 * caller that read a truncated page has to say so rather than draw the absence.
 */
export function findAwardRecord<T extends AwardStampedRow>(
  rows: readonly T[],
  keys: AwardKeys,
  retiredStatuses: ReadonlySet<string>,
): T | null {
  const tender = keys.tender_package_id || null;
  const bids = new Set((keys.bid_package_ids ?? []).filter((id): id is string => Boolean(id)));
  if (!tender && bids.size === 0) return null;
  for (const row of rows) {
    if (retiredStatuses.has(row.status)) continue;
    const md: Record<string, unknown> = row.metadata && typeof row.metadata === 'object' ? row.metadata : {};
    const rowTender = md.tender_package_id;
    const rowBid = md.bid_package_id;
    if (tender && typeof rowTender === 'string' && rowTender === tender) return row;
    if (typeof rowBid === 'string' && bids.has(rowBid)) return row;
  }
  return null;
}

/**
 * The live purchase order an RFQ award drafted, or `null` when none in `rows`
 * carries the RFQ's stamp.
 *
 * The RFQ path (`procurement/rfq_award.py`) stamps `origin: 'rfq_award'` and
 * `rfq_id`. A cancelled order is passed over: a re-award retires the earlier
 * draft by cancelling it, and the order that stands for the RFQ is the live
 * one. As with `findAwardRecord`, `null` means "not among these rows".
 */
export function findRfqAwardOrder<T extends AwardStampedRow>(rows: readonly T[], rfqId: string): T | null {
  if (!rfqId) return null;
  for (const row of rows) {
    if (RETIRED_AWARD_ORDER_STATUSES.has(row.status)) continue;
    const md: Record<string, unknown> = row.metadata && typeof row.metadata === 'object' ? row.metadata : {};
    if (md.origin === 'rfq_award' && md.rfq_id === rfqId) return row;
  }
  return null;
}

/** The RFQ a purchase order was drafted from, each field only when present. */
export interface OrderSource {
  rfqId: string | null;
  rfqNumber: string | null;
}

/**
 * Read the origin an RFQ award stamped onto the order it drafted. An order
 * raised by hand, or drafted from a tender, carries no RFQ and both fields are
 * `null`, so the caller draws no link.
 */
export function orderSource(metadata: Record<string, unknown> | null | undefined): OrderSource {
  const md: Record<string, unknown> = metadata && typeof metadata === 'object' ? metadata : {};
  const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() !== '' ? v : null);
  if (md.origin !== 'rfq_award') return { rfqId: null, rfqNumber: null };
  return { rfqId: str(md.rfq_id), rfqNumber: str(md.rfq_number) };
}

/* ── What a contract was drafted from ───────────────────────────────────── */

/** The ids a contract's metadata names as its origin, each only when present. */
export interface ContractSource {
  tenderPackageId: string | null;
  bidPackageId: string | null;
  boqId: string | null;
}

/**
 * Read the origin an award stamped onto a contract it drafted.
 *
 * Only string ids are taken. A contract written by hand carries none of these
 * keys, and every field is then `null`, so a caller draws no pill rather than
 * a pill to a bare register.
 */
export function contractSource(metadata: Record<string, unknown> | null | undefined): ContractSource {
  const md: Record<string, unknown> = metadata && typeof metadata === 'object' ? metadata : {};
  const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() !== '' ? v : null);
  return {
    tenderPackageId: str(md.tender_package_id),
    bidPackageId: str(md.bid_package_id),
    boqId: str(md.boq_id),
  };
}

/* ── Where an approved change order landed ──────────────────────────────── */

/** Where the approval of a change order wrote its scope and its money. */
export interface ChangeOrderWriteback {
  /** The bill the approved scope was written into, with its section row. */
  boqId: string | null;
  boqSectionId: string | null;
  /** The revised-budget row the approval created or updated. */
  budgetRowId: string | null;
}

/**
 * Read `metadata.writeback`, which the approval stamps on the order.
 *
 * Orders approved before the stamp existed carry none, and every field is
 * then `null`: the record does not say where it landed, so the page does not
 * guess.
 */
export function changeOrderWriteback(metadata: Record<string, unknown> | null | undefined): ChangeOrderWriteback {
  const md: Record<string, unknown> = metadata && typeof metadata === 'object' ? metadata : {};
  const raw = md.writeback;
  const wb: Record<string, unknown> = raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
  const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() !== '' ? v : null);
  return {
    boqId: str(wb.boq_id),
    boqSectionId: str(wb.boq_section_id),
    budgetRowId: str(wb.budget_row_id),
  };
}
