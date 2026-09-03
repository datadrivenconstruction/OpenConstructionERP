// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * API client for the Comms Intelligence backend module
 * (`/api/v1/comms-intelligence/`).
 */

import { apiGet, apiPatch, apiPost } from '@/shared/lib/api';

export interface ExtractedPrice {
  amount: string;
  currency: string;
  context: string;
}

export interface ExtractedFacts {
  prices: ExtractedPrice[];
  quote_number: string | null;
  reference_numbers: string[];
  dates: { response_requested_by: string | null; event_date: string | null };
  commitments: { who: string; what: string; when: string | null }[];
}

export interface AnalysisSuggestions {
  set_status: string | null;
  response_required_by: string | null;
  link_rfi_id: string | null;
  correspondence_type: string | null;
}

export interface Analysis {
  id: string;
  project_id: string;
  correspondence_id: string;
  reference_number: string;
  category: string;
  confidence: number;
  summary: string;
  extracted: ExtractedFacts;
  suggestions: AnalysisSuggestions;
  reply_needed: boolean;
  status: 'suggested' | 'confirmed' | 'dismissed';
  reviewed_by: string | null;
  reviewed_at: string | null;
  applied: Record<string, string>;
  source: 'heuristic' | 'ai';
  model_name: string;
  prompt_version: string;
  tokens_used: number;
  created_at?: string;
  updated_at?: string;
}

export interface Draft {
  id: string;
  project_id: string;
  correspondence_id: string;
  kind: 'reply' | 'chaser';
  subject: string;
  body: string;
  confidence: number;
  status: 'suggested' | 'accepted' | 'dismissed';
  source: 'ai' | 'template';
  model_name: string;
  created_at?: string;
}

export interface DashboardEntry {
  correspondence_id: string;
  reference_number: string;
  subject: string;
  direction: string;
  status: string;
  response_required_by: string | null;
  days_until_due: number | null;
  from_contact_id: string | null;
  category: string | null;
  confidence: number | null;
}

export interface Dashboard {
  project_id: string;
  pending_review: number;
  reply_needed: number;
  overdue: DashboardEntry[];
  due_soon: DashboardEntry[];
  awaiting_response: DashboardEntry[];
  categories: Record<string, number>;
}

export interface ConfirmBody {
  apply_status: boolean;
  apply_response_required_by: boolean;
  apply_link_rfi: boolean;
  apply_type: boolean;
}

const BASE = '/v1/comms-intelligence';

/** The list routes answer with a page envelope. */
interface CommsPage<T> {
  items?: T[];
  total?: number;
}

export async function fetchAnalyses(
  projectId: string,
  status?: 'suggested' | 'confirmed' | 'dismissed',
): Promise<Analysis[]> {
  const qs = new URLSearchParams({ project_id: projectId, limit: '200' });
  if (status) qs.set('status', status);
  return (await apiGet<CommsPage<Analysis>>(`${BASE}/analyses?${qs.toString()}`)).items ?? [];
}

export function fetchDashboard(projectId: string): Promise<Dashboard> {
  return apiGet<Dashboard>(`${BASE}/dashboard?project_id=${encodeURIComponent(projectId)}`);
}

export function runAnalysis(correspondenceId: string, useAi: boolean): Promise<Analysis> {
  return apiPost<Analysis, { use_ai: boolean }>(
    `${BASE}/analyses/${correspondenceId}/analyze`,
    { use_ai: useAi },
    // The AI pass can legitimately take a minute against a slow provider.
    { longRunning: true },
  );
}

export function confirmAnalysis(analysisId: string, body: ConfirmBody): Promise<Analysis> {
  return apiPost<Analysis, ConfirmBody>(`${BASE}/analyses/${analysisId}/confirm`, body);
}

export function dismissAnalysis(analysisId: string): Promise<Analysis> {
  return apiPost<Analysis>(`${BASE}/analyses/${analysisId}/dismiss`);
}

export async function fetchDrafts(correspondenceId: string): Promise<Draft[]> {
  return (
    await apiGet<CommsPage<Draft>>(`${BASE}/drafts?correspondence_id=${encodeURIComponent(correspondenceId)}`)
  ).items ?? [];
}

export function createDraft(
  correspondenceId: string,
  kind: 'reply' | 'chaser',
  instructions: string,
  useAi: boolean,
): Promise<Draft> {
  return apiPost<Draft, { kind: string; instructions: string; use_ai: boolean }>(
    `${BASE}/drafts/${correspondenceId}`,
    { kind, instructions, use_ai: useAi },
    { longRunning: true },
  );
}

export function setDraftStatus(draftId: string, status: 'accepted' | 'dismissed'): Promise<Draft> {
  return apiPatch<Draft, { status: string }>(`${BASE}/drafts/${draftId}`, { status });
}

// ── Outlook bridge (/api/v1/outlook-bridge/) ─────────────────────────────

export interface EmailPreview {
  correspondence_id: string;
  reference_number: string;
  to: string[];
  cc: string[];
  subject: string;
  html: string;
  notified: { name: string; date: string }[];
}

const OUTLOOK = '/v1/outlook-bridge';

export function fetchBridgeStatus(): Promise<{ outlook_possible: boolean }> {
  return apiGet<{ outlook_possible: boolean }>(`${OUTLOOK}/`);
}

export function previewEmail(correspondenceId: string, extraTo: string[]): Promise<EmailPreview> {
  return apiPost<EmailPreview, { extra_to: string[] }>(
    `${OUTLOOK}/preview/${correspondenceId}`,
    { extra_to: extraTo },
  );
}

export function openOutlookDraft(correspondenceId: string, extraTo: string[]): Promise<{ opened: boolean }> {
  return apiPost<{ opened: boolean }, { extra_to: string[] }>(
    `${OUTLOOK}/draft/${correspondenceId}`,
    { extra_to: extraTo },
    { longRunning: true },
  );
}

export function emlDownloadUrl(correspondenceId: string): string {
  return `/api${OUTLOOK}/eml/${correspondenceId}`;
}

// Inbound mailbox capture (sweep / swept-message listing / file / ignore) is
// deliberately not part of this build — the register is fed by hand-filed
// replies instead, so nothing here reads a mailbox.
