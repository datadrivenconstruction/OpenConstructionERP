// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Procurement API clients - typed wrappers over fetch.
 *
 * Wave 2 / T4 introduces two read endpoints (3-way match status + supplier
 * scorecard) that the procurement UI surfaces. The existing list / create
 * calls still live inline in `ProcurementPage.tsx`; this module is a
 * landing pad for the new clients and any future additions.
 */

import { ApiError, apiDelete, apiGet, apiPost, type Page } from '@/shared/lib/api';

/* ── Removing a purchase order ────────────────────────────────────────── */

/**
 * The kinds of record the backend will name when it refuses to remove a PO.
 *
 * Mirrors `_PO_HOLDER_LABELS` in `procurement/service.py`. The wire carries
 * the kind, not a sentence, so the UI can say it in the reader's language
 * instead of showing an English string the server happened to build.
 */
export type POHolderKind =
  | 'goods_receipt'
  | 'payable_invoice'
  | 'retainage_release'
  | 'requisition';

export interface RemovalHolder {
  kind: string;
  count: number;
}

/**
 * The structured 409 body a refused cancel or delete returns:
 *
 *     {"detail": {"code", "message", "remediation", "holders": [...]}}
 *
 * `holders` is empty when the refusal is about the PO's own state (already
 * cancelled, already issued) rather than about something pointing at it.
 */
export interface RemovalRefusal {
  code: string;
  message: string;
  remediation: string;
  holders: RemovalHolder[];
}

/**
 * Pull the structured refusal out of a thrown error, or null if this is not
 * one.
 *
 * Anything that is not a 409 carrying the agreed shape returns null and the
 * caller falls back to `getErrorMessage`, which already renders `detail.message`
 * readably. So a caller that forgets to handle the structure still shows a
 * sentence rather than "[object Object]".
 */
export function parseRemovalRefusal(err: unknown): RemovalRefusal | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null;
  const body = err.body as { detail?: unknown } | null | undefined;
  const detail = body?.detail;
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return null;
  const d = detail as Record<string, unknown>;
  if (typeof d.code !== 'string' || typeof d.message !== 'string') return null;
  const holders = Array.isArray(d.holders)
    ? d.holders.flatMap((h): RemovalHolder[] => {
        if (!h || typeof h !== 'object') return [];
        const entry = h as Record<string, unknown>;
        if (typeof entry.kind !== 'string' || typeof entry.count !== 'number') return [];
        return [{ kind: entry.kind, count: entry.count }];
      })
    : [];
  return {
    code: d.code,
    message: d.message,
    remediation: typeof d.remediation === 'string' ? d.remediation : '',
    holders,
  };
}

/**
 * Void a purchase order. The row and its `po_number` survive; the status
 * becomes `cancelled`. This is the removal verb for anything that has been
 * approved or issued - the number stays out of circulation because a gap in
 * the sequence is what an auditor asks about.
 */
export function cancelPurchaseOrder(poId: string, reason: string): Promise<unknown> {
  return apiPost(`/v1/procurement/${poId}/cancel/`, { reason: reason || null });
}

/**
 * Delete a draft purchase order that never left draft. The backend refuses
 * with 409 for anything else, including a draft that was once issued and
 * later reopened.
 */
export function deletePurchaseOrder(poId: string): Promise<void> {
  return apiDelete(`/v1/procurement/${poId}`);
}

/* ── 3-way match status ───────────────────────────────────────────────── */

export type POLineMatchTag =
  | 'ok'
  | 'partial'
  | 'over_received'
  | 'over_invoiced'
  | 'unmatched';

export interface POLineMatchStatus {
  line_id: string;
  description: string;
  ordered_qty: string;
  received_qty: string;
  invoiced_qty: string;
  match_status: POLineMatchTag;
}

export interface POMatchStatusResponse {
  po_id: string;
  po_number: string;
  overall_status: POLineMatchTag;
  lines: POLineMatchStatus[];
}

export function getPOMatchStatus(poId: string): Promise<POMatchStatusResponse> {
  return apiGet<POMatchStatusResponse>(`/v1/procurement/${poId}/match-status/`);
}

/* ── Supplier scorecard ───────────────────────────────────────────────── */

export interface SupplierScorecardResponse {
  supplier_contact_id: string;
  supplier_name: string | null;
  project_id: string | null;
  period_days: number;
  total_po_count: number;
  total_po_value: string;
  currency: string;
  on_time_delivery_pct: number;
  qty_variance_pct: number;
  gr_rejection_rate: number;
  total_gr_count: number;
  // Numerator of on_time_delivery_pct - GRs delivered on/before their PO's
  // delivery_date. The backend returns it so the UI can show "X of Y on time".
  on_time_count: number;
  // GRs whose parent PO carried no delivery_date - excluded from the on-time
  // denominator. Without surfacing this, a supplier whose deliveries are all
  // unscheduled shows a misleading 0% on-time figure (see SupplierScorecardModal).
  unscheduled_count: number;
  // Whether the supplier is still qualified to buy from. Empty when the
  // caller sees none of this supplier's orders.
  prequalification_status?: string | null;
  qualified_until?: string | null;
  qualification_state?: 'expired' | 'expiring' | 'valid' | 'not_stated';
  compliance_reasons?: string[];
  unconfirmed_po_count?: number;
}

export function getSupplierScorecard(
  contactId: string,
  options: { projectId?: string; periodDays?: number } = {},
): Promise<SupplierScorecardResponse> {
  const params = new URLSearchParams();
  if (options.projectId) params.set('project_id', options.projectId);
  if (options.periodDays) params.set('period_days', String(options.periodDays));
  const qs = params.toString();
  const suffix = qs ? `?${qs}` : '';
  return apiGet<SupplierScorecardResponse>(
    `/v1/procurement/suppliers/${contactId}/scorecard/${suffix}`,
  );
}

/* ── Vendor prequalification status (TOP-30 #20) ──────────────────────── */

export interface VendorEligibility {
  contact_id: string;
  known: boolean;
  subcontractor_id: string | null;
  legal_name: string | null;
  awardable: boolean;
  prequalification_status: string | null;
  is_blocked: boolean;
  rating_score: string | null;
  reasons: string[];
}

/**
 * Resolve a PO vendor's prequalification / block status from its CRM
 * contact id. Returns ``known=false`` for an ad-hoc supplier that is not a
 * registered subcontractor (no badge shown).
 */
export function getVendorEligibility(
  contactId: string,
): Promise<VendorEligibility> {
  return apiGet<VendorEligibility>(
    `/v1/subcontractors/vendors/by-contact/${contactId}/eligibility`,
  );
}

/* ── Retainage (Gap F) ─────────────────────────────────────────────────── */

export interface PORetainageRelease {
  id: string;
  po_id: string;
  release_date: string;
  release_amount: string;
  release_reason: string | null;
  released_by_id: string | null;
  created_at: string;
}

export interface PORetainageReleaseList {
  items: PORetainageRelease[];
  total: number;
}

export function listPORetainageReleases(
  poId: string,
): Promise<PORetainageReleaseList> {
  return apiGet<PORetainageReleaseList>(
    `/v1/procurement/${poId}/retainage-releases/`,
  );
}

export function releasePORetainage(
  poId: string,
  body: { amount: string; reason?: string },
): Promise<PORetainageRelease> {
  return apiPost<PORetainageRelease, { amount: string; reason?: string }>(
    `/v1/procurement/${poId}/release-retainage/`,
    body,
  );
}

/* ── PO retainage reconciliation report (Gap F) ────────────────────────── */

export interface RetainageReportRow {
  po_id: string;
  po_number: string;
  vendor_name: string;
  issue_date: string | null;
  status: string;
  amount_total: string;
  currency: string;
  retention_percent: string;
  retainage_withheld: string;
  retainage_released_ytd: string;
  retainage_held: string;
}

export interface RetainageReportSummary {
  total_committed: string;
  total_withheld: string;
  total_released: string;
  total_held: string;
  currency: string;
  mixed_currency: boolean;
}

export interface RetainageReconciliationReport {
  report_type: string;
  project_id: string;
  project_name: string;
  period_start: string;
  period_end: string;
  currencies: string[];
  summary: RetainageReportSummary;
  summary_by_currency: Record<
    string,
    {
      total_committed: string;
      total_withheld: string;
      total_released: string;
      total_held: string;
    }
  >;
  po_rows: RetainageReportRow[];
}

/** Committed quantities per BOQ position through the cost spine (PO -> CostLine -> Position). */
export interface CommittedByPosition {
  boq_position_id: string;
  committed_qty: string;
  committed_value: string;
}


/**
 * A page of the rollup, typed as the shared `Page` rather than a local copy of
 * it. `total` counts the positions the project has commitments against, not
 * the rows on this page, so a caller comparing the rollup with the bill can
 * tell whether it has seen all of it, and `isTruncated` answers that the same
 * way for every register instead of once per call site.
 */
export function getCommittedByPosition(
  projectId: string,
  options: { offset?: number; limit?: number } = {}
): Promise<Page<CommittedByPosition>> {
  const query = new URLSearchParams();
  if (options.offset !== undefined) query.set('offset', String(options.offset));
  if (options.limit !== undefined) query.set('limit', String(options.limit));
  // The `?` is written into the route rather than folded into the suffix, and
  // that is not a style choice. check_page_envelope_consumers reads the route
  // out of the string literal and cuts it at the first `?`, so a suffix that
  // carries its own `?` leaves the literal reading as a path segment and the
  // endpoint cannot be guarded at all. `/v1/transmittals/?${qs}` is the same
  // shape for the same reason. An empty query leaves a bare trailing `?`,
  // which is a valid empty query string and is what makes the route visible.
  return apiGet<Page<CommittedByPosition>>(
    `/v1/procurement/project/${projectId}/committed-by-position/?${query.toString()}`,
  );
}

export function getRetainageReconciliation(options: {
  projectId: string;
  periodStart: string;
  periodEnd: string;
}): Promise<RetainageReconciliationReport> {
  const params = new URLSearchParams({
    project_id: options.projectId,
    period_start: options.periodStart,
    period_end: options.periodEnd,
  });
  return apiGet<RetainageReconciliationReport>(
    `/v1/reporting/po-retainage-reconciliation/?${params.toString()}`,
  );
}
