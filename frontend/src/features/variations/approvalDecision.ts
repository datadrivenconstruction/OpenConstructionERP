// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The commercial approval boundary of a variation request, as the screen has
 * to reason about it (Issue #435).
 *
 * Approving a variation at the amount it was priced at and approving it at an
 * amount somebody negotiated are two different acts, and the record has to be
 * able to tell them apart afterwards. The server already can: it writes down
 * an `agreed_basis` of `negotiated`, `priced_boq` or `headline_estimate` and
 * refuses a negotiated figure that departs from the submitted bill total with
 * nothing said about why. What it cannot do is guess which act the approver
 * meant, so the two are two choices on the screen rather than one amount box
 * that is sometimes prefilled.
 *
 * The logic lives here, apart from the drawer that renders it, because the
 * part worth testing is which payload leaves the browser rather than which
 * controls appear.
 */

import type { ApproveVRPayload, VariationRequest } from './api';

/** Which of the two acts the approver is performing. */
export type ApprovalMode = 'as_submitted' | 'negotiated';

/**
 * Two figures may agree without being equal to the last binary place.
 *
 * Mirrors `_MONEY_EPSILON` in the variations service, which is what decides
 * server-side whether a named amount counts as a departure. A looser value
 * here would let the screen submit something the server then refuses with a
 * 422 the approver had no way to see coming.
 */
export const AGREED_AMOUNT_EPSILON = 0.01;

/** What an approval is being measured against, and which figure that is. */
export interface ApprovalBaseline {
  amount: number | null;
  source: 'submitted_boq' | 'headline_estimate';
}

/**
 * The figure a negotiated amount departs from.
 *
 * `submitted_boq_total` where the request carries a bill, because that is the
 * number the approver was looking at and the one the server compares against.
 * Otherwise the headline estimate, which is then the only figure there has
 * ever been.
 *
 * Falling back to the headline makes the screen stricter than the API in one
 * case: the server asks for a reason only when a bill was submitted, so a
 * request with no bill can be agreed at any amount over the API with nothing
 * said. That case is exactly as unauditable later as the one the server
 * refuses, and stricter-than-the-API cannot produce a refusal the approver did
 * not see coming, where laxer-than-the-API can.
 */
export function approvalBaseline(request: VariationRequest): ApprovalBaseline {
  const submitted = request.submitted_boq_total;
  if (submitted !== null && submitted !== undefined && String(submitted).trim() !== '') {
    const parsed = Number(submitted);
    if (Number.isFinite(parsed)) return { amount: parsed, source: 'submitted_boq' };
  }
  const headline = Number(request.estimated_cost_impact);
  return {
    amount: Number.isFinite(headline) ? headline : null,
    source: 'headline_estimate',
  };
}

/** Whether a typed amount is a departure from what was submitted. */
export function departsFromBaseline(amount: string, baseline: ApprovalBaseline): boolean {
  const typed = Number(amount.trim());
  if (!Number.isFinite(typed) || amount.trim() === '') return false;
  if (baseline.amount === null) return false;
  return Math.abs(typed - baseline.amount) >= AGREED_AMOUNT_EPSILON;
}

export interface ApprovalDraft {
  mode: ApprovalMode;
  /** The amount as typed, not as parsed. */
  agreedAmount: string;
  varianceNote: string;
  decisionNotes: string;
}

/**
 * Why the approval cannot be sent yet, or null when it can.
 *
 * Approving on the submitted pricing state is never blocked: it names no
 * amount, so there is no departure to explain.
 */
export function approvalBlockReason(
  draft: ApprovalDraft,
  baseline: ApprovalBaseline,
): 'amount_missing' | 'variance_note_missing' | null {
  if (draft.mode !== 'negotiated') return null;
  const typed = draft.agreedAmount.trim();
  if (typed === '' || !Number.isFinite(Number(typed))) return 'amount_missing';
  if (departsFromBaseline(typed, baseline) && draft.varianceNote.trim() === '') {
    return 'variance_note_missing';
  }
  return null;
}

/**
 * The body the approve route reads, with nothing in it that was not decided.
 *
 * Keys are omitted rather than sent as undefined. An approval on the submitted
 * pricing state sends no amount at all, which is what makes the server record
 * `priced_boq` or `headline_estimate` instead of `negotiated`: a mode that
 * sent the bill total back as a named figure would file every approval as a
 * negotiation and lose the distinction this whole boundary exists for.
 */
export function buildApprovalPayload(draft: ApprovalDraft): ApproveVRPayload {
  const payload: ApproveVRPayload = {};
  const notes = draft.decisionNotes.trim();
  if (notes !== '') payload.decision_notes = notes;
  if (draft.mode !== 'negotiated') return payload;

  const amount = draft.agreedAmount.trim();
  if (amount !== '') payload.decided_amount = amount;
  const variance = draft.varianceNote.trim();
  if (variance !== '') payload.agreed_variance_note = variance;
  return payload;
}
