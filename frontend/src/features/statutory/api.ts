// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { apiGet, apiPost } from '@/shared/lib/api';

export type ClaimantRole = 'direct_contractor' | 'subcontractor' | 'supplier';
export type OwnerSector = 'public' | 'private';
export type NoticeStatus = 'upcoming' | 'due_today' | 'overdue';

export interface NoticeRuleSummary {
  code: string;
  name: string;
  kind: string;
  source: string;
  source_url?: string | null;
}

export interface JurisdictionSummary {
  code: string;
  name: string;
  country: string;
  verify_note: string;
  sectors: string[];
  claimant_roles: string[];
  events: string[];
  monthly_notices: boolean;
  notice_rules: NoticeRuleSummary[];
}

export interface NoticeDeadline {
  code: string;
  name: string;
  kind: string;
  due_date: string;
  event: string;
  event_date: string;
  period: string | null;
  status: NoticeStatus;
  days_left: number;
  source: string;
  source_url: string | null;
}

export interface RetentionVerdict {
  retention_pct: string | null;
  cap_pct: string | null;
  cap_source: string | null;
  cap_amount: string | null;
  over_cap: boolean;
  needs_agreement_date: boolean;
}

export interface StatutoryFinding {
  rule_id: string;
  check: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
  source: string;
}

export interface StatutoryOutcome {
  jurisdiction: string;
  name: string;
  notices: NoticeDeadline[];
  retention: RetentionVerdict | null;
  findings: StatutoryFinding[];
  verify_note: string;
}

export interface StatutoryFacts {
  jurisdiction: string;
  sector?: OwnerSector | null;
  contract_value?: string | null;
  retention?: { payment_amount?: string | null; retention_amount?: string | null } | null;
  notices?: { role?: ClaimantRole | null; events: Record<string, string> } | null;
}

/** Jurisdictions the loaded packs carry statutory tables for (ISO 3166 codes). */
export function fetchJurisdictions(): Promise<string[]> {
  return apiGet<string[]>('/v1/statutory/jurisdictions/');
}

export function fetchJurisdiction(code: string): Promise<JurisdictionSummary> {
  return apiGet<JurisdictionSummary>(`/v1/statutory/jurisdictions/${encodeURIComponent(code)}/`);
}

export function evaluateStatutory(facts: StatutoryFacts): Promise<StatutoryOutcome> {
  return apiPost<StatutoryOutcome, StatutoryFacts>('/v1/statutory/evaluate/', facts);
}
