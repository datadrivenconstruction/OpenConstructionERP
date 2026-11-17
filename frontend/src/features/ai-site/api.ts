// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Site assistants: typed client for /api/v1/ai-agents/site/*.

import { apiGet, apiPost, apiPut } from '@/shared/lib/api';

const BASE = '/v1/ai-agents/site';

/** Every assistant answers with this envelope. */
export interface SiteEnvelope<TItem> {
  proposal_id?: string;
  provider_used: string | null;
  degraded: boolean;
  items: TItem[];
  confidence: number;
  status?: string;
}

export type BriefingSection = 'weather' | 'rfis' | 'inspections' | 'deliveries' | 'diary';

export interface BriefingEntry {
  ref?: string | null;
  title?: string | null;
  due?: string | null;
  materials?: string | null;
  conditions?: string | null;
  temperature_c?: number | null;
  wind_kmh?: number | null;
  precipitation_mm?: number | null;
  date?: string;
  labour?: number;
  equipment?: number;
  notes?: string | null;
}

export interface BriefingItem {
  id: 'weather' | 'rfis_overdue' | 'rfis_open' | 'inspections_due' | 'deliveries_today' | 'diary_yesterday';
  section: BriefingSection;
  count: number;
  entries: BriefingEntry[];
  confidence: number;
}

export interface BriefingEnvelope extends SiteEnvelope<BriefingItem> {
  narrative?: string | null;
  day?: string;
  exists?: boolean;
  is_today?: boolean;
}

export interface SitePrefs {
  project_id: string;
  enabled: boolean;
  briefing_time: string;
  enabled_sections: BriefingSection[];
  available_sections: BriefingSection[];
}

export interface DiaryDraftItem {
  id: string;
  source: 'photos' | 'transcript' | 'ai';
  time: string | null;
  time_to: string | null;
  photo_count: number;
  activity: string;
  raw?: string;
  trade: string | null;
  crew_count: number | null;
  weather_notes: string | null;
  confidence: number;
  status?: string;
}

export interface DiaryDraftEnvelope extends SiteEnvelope<DiaryDraftItem> {
  diary_date: string;
}

export interface RfiCheckItem {
  id: string;
  status: 'ok' | 'warn' | 'fail';
  source: 'rule' | 'ai';
  params: Record<string, string | number>;
  confidence: number;
}

export interface RfiCheckEnvelope extends SiteEnvelope<RfiCheckItem> {
  checks: RfiCheckItem[];
  score: number;
  has_fail: boolean;
}

export interface MeetingActionItem {
  id: string;
  text: string;
  owner_name: string | null;
  owner_id: string | null;
  due: string | null;
  confidence: number;
  source_span: { start: number; end: number } | null;
  status?: string;
}

export interface MeetingActionsEnvelope extends SiteEnvelope<MeetingActionItem> {
  meeting_id: string;
  allowed_owners: string[];
}

export interface ConfirmSelection {
  id: string;
  edits?: Record<string, unknown>;
}

export interface ConfirmResult {
  proposal_id: string;
  status: string;
  results: { id: string; status: 'accepted' | 'error'; detail?: unknown; record_id?: string }[];
}

export const fetchLatestBriefing = (projectId: string) =>
  apiGet<BriefingEnvelope>(`${BASE}/briefing/latest?project_id=${encodeURIComponent(projectId)}`);

export const runBriefing = (projectId: string, refresh: boolean) =>
  apiPost<BriefingEnvelope>(`${BASE}/briefing/run`, { project_id: projectId, refresh });

export const fetchSitePrefs = (projectId: string) =>
  apiGet<SitePrefs>(`${BASE}/prefs?project_id=${encodeURIComponent(projectId)}`);

export const saveSitePrefs = (prefs: Omit<SitePrefs, 'available_sections'>) =>
  apiPut<SitePrefs>(`${BASE}/prefs`, prefs);

export const draftDiary = (projectId: string, diaryDate: string, transcripts: string[]) =>
  apiPost<DiaryDraftEnvelope>(`${BASE}/diary-draft`, {
    project_id: projectId,
    diary_date: diaryDate,
    transcripts,
  });

export const checkRfi = (rfiId: string) => apiPost<RfiCheckEnvelope>(`${BASE}/rfi-check/${rfiId}`);

export const overrideRfiCheck = (rfiId: string, reason: string, proposalId?: string) =>
  apiPost<{ recorded: boolean }>(`${BASE}/rfi-check/${rfiId}/override`, {
    reason,
    proposal_id: proposalId ?? null,
  });

export const extractMeetingActions = (meetingId: string) =>
  apiPost<MeetingActionsEnvelope>(`${BASE}/meeting-actions/${meetingId}`);

export const confirmProposal = (proposalId: string, items: ConfirmSelection[]) =>
  apiPost<ConfirmResult>(`${BASE}/proposals/${proposalId}/confirm`, { items });

export const rejectProposal = (proposalId: string, reason?: string) =>
  apiPost<{ status: string }>(`${BASE}/proposals/${proposalId}/reject`, { reason: reason ?? null });
