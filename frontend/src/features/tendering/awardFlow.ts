// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure helpers for the package header and the steps after the award.
 */

import type { PackageHeader, PackageHeaderInput, RejectionsPreview } from './api';

export const HEADER_DATE_FIELDS = ['issue_date', 'questions_until', 'bids_due', 'award_planned'] as const;
export const HEADER_ROLE_FIELDS = ['buyer_id', 'estimator_id', 'site_manager_id', 'approver_id'] as const;

export type HeaderForm = Required<{ [K in keyof PackageHeaderInput]: string }>;

export function headerForm(h: PackageHeader | undefined, deadline?: string | null): HeaderForm {
  // A package created before the header existed keeps its deadline as the bids-due date.
  const due = h?.bids_due ?? (deadline && /^\d{4}-\d{2}-\d{2}/.test(deadline) ? deadline.slice(0, 10) : '');
  return {
    legal_entity_id: h?.legal_entity_id ?? '',
    trade: h?.trade ?? '',
    cost_line_id: h?.cost_line_id ?? '',
    issue_date: h?.issue_date ?? '',
    questions_until: h?.questions_until ?? '',
    bids_due: due,
    award_planned: h?.award_planned ?? '',
    buyer_id: h?.buyer_id ?? '',
    estimator_id: h?.estimator_id ?? '',
    site_manager_id: h?.site_manager_id ?? '',
    approver_id: h?.approver_id ?? '',
  };
}

/** Only the fields that changed, blanks sent as null. */
export function headerChanges(before: HeaderForm, after: HeaderForm): PackageHeaderInput {
  const out: Record<string, string | null> = {};
  for (const key of Object.keys(after) as (keyof HeaderForm)[]) {
    if (after[key] !== before[key]) out[key] = after[key].trim() || null;
  }
  return out as PackageHeaderInput;
}

/** Date order problems in the form, the same codes the server returns. */
export function dateOrderWarnings(form: HeaderForm): string[] {
  const present = HEADER_DATE_FIELDS.filter((k) => form[k]).map((k) => [k, form[k]] as const);
  const out: string[] = [];
  for (let i = 1; i < present.length; i++) {
    const [a, da] = present[i - 1]!;
    const [b, db] = present[i]!;
    if (da > db) out.push(`${a}_after_${b}`);
  }
  return out;
}

/** Rejected bidders who still need a letter and can be sent one. */
export function rejectionsToSend(preview: RejectionsPreview | undefined): number {
  if (!preview?.awarded) return 0;
  return preview.rows.filter((r) => r.state === 'pending' || r.state === 'failed').length;
}
