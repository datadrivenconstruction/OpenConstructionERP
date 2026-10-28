// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// API client for minutes from audio: speech capabilities, the project meeting
// glossary, meeting recordings, AI proposals and their review. The recording
// upload is a raw multipart fetch (like the voice capture) so the boundary is
// set by the browser; everything else goes through the shared JSON helpers.

import type { Page } from '@/shared/lib/apiHelpers';
import {
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  extractErrorMessageFromBody,
  getAuthToken,
} from '@/shared/lib/api';

const BASE = '/v1/meetings';

export interface SpeechCapabilities {
  server_transcription: boolean;
  provider: string | null;
  llm_available: boolean;
  max_upload_mb: number;
  accepted_formats: string[];
  default_retention_days: number;
  max_retention_days: number;
}

export type GlossaryKind = 'person' | 'company' | 'abbreviation' | 'term' | 'boq' | 'place';

export interface GlossaryTerm {
  id: string;
  project_id: string;
  term: string;
  kind: GlossaryKind;
  expansion: string | null;
  aliases: string[];
  source: string;
  contact_id: string | null;
  created_at: string;
}

export interface GlossaryTermInput {
  term?: string;
  kind?: GlossaryKind;
  expansion?: string | null;
  aliases?: string[];
}

export interface GlossarySeedResult {
  added: number;
  by_source: Record<string, number>;
  terms: GlossaryTerm[];
}

export interface TranscriptSegment {
  start: number | null;
  end: number | null;
  text: string;
  speaker: string;
}

export interface SpeakerInfo {
  name: string;
  contact_id: string | null;
}

export type ProposalKind = 'summary' | 'decision' | 'action' | 'question' | 'correction';
export type ProposalStatus = 'pending' | 'confirmed' | 'rejected';

export interface LinkedEntity {
  type: 'rfi' | 'boq_position' | 'task';
  id: string;
  label: string;
}

export interface Proposal {
  id: string;
  kind: ProposalKind;
  status: ProposalStatus;
  text: string;
  confidence: number;
  source_quote?: string;
  owner_name?: string;
  owner_contact_id?: string | null;
  owner_confidence?: number;
  due_date?: string | null;
  due_hint?: string | null;
  linked_entity?: LinkedEntity | null;
  heard?: string;
  term?: string;
  applied?: Record<string, unknown>;
}

export interface ProposalSet {
  generated_at?: string;
  ai_generated?: boolean;
  language?: string | null;
  items?: Proposal[];
}

export type RecordingSource = 'upload' | 'browser_record' | 'browser_speech' | 'manual';

export interface MeetingRecording {
  id: string;
  project_id: string;
  meeting_id: string;
  source: RecordingSource;
  status: 'pending' | 'transcribed' | 'awaiting_transcript' | 'failed';
  has_audio: boolean;
  audio_filename: string | null;
  audio_size_bytes: number | null;
  duration_seconds: number | null;
  audio_expires_at: string | null;
  audio_deleted_at: string | null;
  delete_audio_after_transcription: boolean;
  consent_confirmed_at: string | null;
  language: string | null;
  transcript: string;
  segments: TranscriptSegment[];
  speakers: Record<string, SpeakerInfo>;
  provider: string | null;
  transcription_error: string | null;
  proposals: ProposalSet;
  glossary_replacements: number;
  created_at: string;
}

export interface CreateRecordingInput {
  file?: File | null;
  transcript?: string;
  segments?: TranscriptSegment[];
  source: RecordingSource;
  language?: string;
  consentConfirmed: boolean;
  deleteAudioAfterTranscription: boolean;
  retentionDays?: number | null;
}

export interface ProposalEdit {
  id: string;
  decision: 'confirm' | 'reject';
  text?: string;
  owner_name?: string;
  owner_contact_id?: string | null;
  due_date?: string | null;
  linked_entity?: LinkedEntity | null;
  heard?: string;
  term?: string;
}

export interface ProposalReviewResult {
  recording: MeetingRecording;
  confirmed: number;
  rejected: number;
  actions_created: string[];
  tasks_created: string[];
  errors: { id: string; error: string }[];
}

export interface MeetingValidationResult {
  rule_id: string;
  severity: string;
  passed: boolean;
  message: string;
  element_ref: string | null;
}

export interface MeetingValidation {
  status: string;
  score: number | null;
  errors: number;
  warnings: number;
  results: MeetingValidationResult[];
}

export function fetchMeetingValidation(meetingId: string): Promise<MeetingValidation> {
  return apiGet<MeetingValidation>(`${BASE}/${meetingId}/validation/`);
}

export function fetchSpeechCapabilities(): Promise<SpeechCapabilities> {
  return apiGet<SpeechCapabilities>(`${BASE}/speech/capabilities/`);
}

export function fetchMinutesPdfLanguages(): Promise<string[]> {
  return apiGet<string[]>(`${BASE}/minutes/pdf-languages/`);
}

export function fetchGlossary(projectId: string): Promise<GlossaryTerm[]> {
  return apiGet<Page<GlossaryTerm>>(`${BASE}/glossary/?project_id=${encodeURIComponent(projectId)}`).then(
    (page) => page.items,
  );
}

export function addGlossaryTerm(projectId: string, input: GlossaryTermInput): Promise<GlossaryTerm> {
  return apiPost<GlossaryTerm>(`${BASE}/glossary/?project_id=${encodeURIComponent(projectId)}`, input);
}

export function updateGlossaryTerm(termId: string, input: GlossaryTermInput): Promise<GlossaryTerm> {
  return apiPatch<GlossaryTerm>(`${BASE}/glossary/${termId}`, input);
}

export function deleteGlossaryTerm(termId: string): Promise<void> {
  return apiDelete(`${BASE}/glossary/${termId}`);
}

export function seedGlossary(projectId: string): Promise<GlossarySeedResult> {
  return apiPost<GlossarySeedResult>(`${BASE}/glossary/seed/?project_id=${encodeURIComponent(projectId)}`);
}

export function fetchRecordings(meetingId: string): Promise<MeetingRecording[]> {
  return apiGet<Page<MeetingRecording>>(`${BASE}/${meetingId}/recordings/`).then((page) => page.items);
}

export async function createRecording(
  meetingId: string,
  input: CreateRecordingInput,
): Promise<MeetingRecording> {
  const form = new FormData();
  if (input.file) form.append('file', input.file);
  form.append('transcript', input.transcript ?? '');
  if (input.segments && input.segments.length) form.append('segments', JSON.stringify(input.segments));
  form.append('source', input.source);
  form.append('language', input.language ?? '');
  form.append('consent_confirmed', input.consentConfirmed ? 'true' : 'false');
  form.append('delete_audio_after_transcription', input.deleteAudioAfterTranscription ? 'true' : 'false');
  if (input.retentionDays != null) form.append('retention_days', String(input.retentionDays));

  const token = getAuthToken();
  const res = await fetch(`/api${BASE}/${meetingId}/recordings/`, {
    method: 'POST',
    headers: { 'X-DDC-Client': 'OE/1.0', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: form,
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      detail = extractErrorMessageFromBody(await res.json()) ?? detail;
    } catch {
      // not JSON; keep the status
    }
    throw new Error(detail);
  }
  return (await res.json()) as MeetingRecording;
}

export function updateRecording(
  recordingId: string,
  input: {
    transcript?: string;
    segments?: TranscriptSegment[];
    speakers?: Record<string, SpeakerInfo>;
    language?: string;
  },
): Promise<MeetingRecording> {
  return apiPatch<MeetingRecording>(`${BASE}/recordings/${recordingId}`, input);
}

export function retranscribeRecording(recordingId: string): Promise<MeetingRecording> {
  return apiPost<MeetingRecording>(`${BASE}/recordings/${recordingId}/transcribe/`);
}

export function proposeMinutes(recordingId: string): Promise<MeetingRecording> {
  return apiPost<MeetingRecording>(`${BASE}/recordings/${recordingId}/propose/`);
}

export function reviewProposals(
  recordingId: string,
  items: ProposalEdit[],
  createTasks: boolean,
): Promise<ProposalReviewResult> {
  return apiPost<ProposalReviewResult>(`${BASE}/recordings/${recordingId}/review/`, {
    items,
    create_tasks: createTasks,
  });
}

export function deleteRecordingAudio(recordingId: string): Promise<MeetingRecording> {
  return apiDelete<MeetingRecording>(`${BASE}/recordings/${recordingId}/audio`);
}

export function deleteRecording(recordingId: string): Promise<void> {
  return apiDelete(`${BASE}/recordings/${recordingId}`);
}

export function getRecordingAudioUrl(recordingId: string): string {
  return `/api${BASE}/recordings/${recordingId}/audio`;
}
