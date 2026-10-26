// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Bidder​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ compliance chips: which bill revision a bid was priced on and which addenda it missed.

export interface BidComplianceInput {
  boq_revision_no?: number | null;
  current_boq_revision?: number | null;
  revision_current?: boolean;
  missing_addenda?: number[];
  compliant?: boolean;
}

export interface BidComplianceChip {
  /** Stable code the caller turns into a localized label. */
  kind: 'revision_stale' | 'missing_addenda' | 'compliant';
  tone: 'warning' | 'error' | 'success';
  revision?: number;
  missing?: number[];
}

/**
 * The chips shown next to a bid total. Nothing is returned for an older
 * backend that does not report compliance, so no claim is made without data.
 */
export function bidComplianceChips(bid: BidComplianceInput): BidComplianceChip[] {
  if (bid.compliant === undefined && bid.revision_current === undefined && !bid.missing_addenda) return [];
  const chips: BidComplianceChip[] = [];
  if (bid.revision_current === false) {
    chips.push({ kind: 'revision_stale', tone: 'warning', revision: bid.boq_revision_no ?? 0 });
  }
  const missing = bid.missing_addenda ?? [];
  if (missing.length > 0) chips.push({ kind: 'missing_addenda', tone: 'error', missing });
  if (chips.length === 0 && bid.compliant !== false) chips.push({ kind: 'compliant', tone: 'success' });
  return chips;
}
