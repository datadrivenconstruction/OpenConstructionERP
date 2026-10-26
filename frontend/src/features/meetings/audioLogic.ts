// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pure helpers behind the meeting recording panel: browser capability checks,
// speaker labels, proposal grouping and the review payload. No React, no
// network, so every rule is unit-tested on plain values.

import type {
  LinkedEntity,
  Proposal,
  ProposalEdit,
  ProposalKind,
  SpeakerInfo,
  TranscriptSegment,
} from './audioApi';

/** Containers the speech providers accept directly (ogg is not one of them). */
const REC_TYPES: readonly { mime: string; ext: string }[] = [
  { mime: 'audio/webm;codecs=opus', ext: 'webm' },
  { mime: 'audio/webm', ext: 'webm' },
  { mime: 'audio/mp4', ext: 'mp4' },
];

/** Low bitrate speech keeps a long meeting under the 25 MB upload cap. */
export const RECORDING_BITS_PER_SECOND = 24_000;

export function pickRecordingType(): { mime: string; ext: string } | null {
  if (typeof MediaRecorder === 'undefined' || typeof MediaRecorder.isTypeSupported !== 'function') {
    return null;
  }
  for (const t of REC_TYPES) {
    if (MediaRecorder.isTypeSupported(t.mime)) return t;
  }
  return null;
}

/** Longest recording that fits the upload cap at the recording bitrate, in seconds. */
export function maxRecordSeconds(maxUploadMb: number): number {
  const bytes = maxUploadMb * 1024 * 1024 * 0.95;
  return Math.max(60, Math.floor((bytes * 8) / RECORDING_BITS_PER_SECOND));
}

type RecognitionCtor = new () => SpeechRecognitionLike;

export interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

export interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }>;
}

/** The browser's own speech recognition, when it has one. */
export function speechRecognitionCtor(): RecognitionCtor | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/** "Name: text" lines become segments; other lines are unlabelled. */
export function segmentsFromText(text: string): TranscriptSegment[] {
  const out: TranscriptSegment[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const m = /^([^:]{1,50}):\s+(.+)$/.exec(line);
    if (m && !/^\d{1,2}$/.test(m[1]!)) {
      out.push({ start: null, end: null, speaker: m[1]!.trim(), text: m[2]!.trim() });
    } else {
      out.push({ start: null, end: null, speaker: '', text: line });
    }
  }
  return out;
}

/** Distinct speaker labels, in order of first appearance. */
export function speakerLabels(segments: TranscriptSegment[]): string[] {
  const seen: string[] = [];
  for (const s of segments) {
    const label = (s.speaker || '').trim();
    if (label && !seen.includes(label)) seen.push(label);
  }
  return seen;
}

/** The person a label stands for, else the label. */
export function speakerName(label: string, speakers: Record<string, SpeakerInfo>): string {
  const name = speakers[label]?.name?.trim();
  return name || label;
}

/** mm:ss, or h:mm:ss past an hour. */
export function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`;
}

/** Retention choices offered: common windows up to the server maximum, plus the default. */
export function retentionOptions(defaultDays: number, maxDays: number): number[] {
  const base = [7, 30, 90, 365].filter((d) => d <= maxDays);
  if (defaultDays > 0 && !base.includes(defaultDays)) base.push(defaultDays);
  return base.sort((a, b) => a - b);
}

export const PROPOSAL_ORDER: ProposalKind[] = ['summary', 'decision', 'action', 'question', 'correction'];

/** Proposals grouped by kind in reading order; empty groups are left out. */
export function groupProposals(items: Proposal[]): { kind: ProposalKind; items: Proposal[] }[] {
  return PROPOSAL_ORDER.map((kind) => ({ kind, items: items.filter((i) => i.kind === kind) })).filter(
    (g) => g.items.length > 0,
  );
}

/** What a reviewer can change on a proposal before confirming it. */
export interface ProposalDraft {
  text: string;
  owner_name: string;
  owner_contact_id: string | null;
  due_date: string;
  linked_entity: LinkedEntity | null;
  heard: string;
  term: string;
}

export function draftFor(p: Proposal): ProposalDraft {
  return {
    text: p.text ?? '',
    owner_name: p.owner_name ?? '',
    owner_contact_id: p.owner_contact_id ?? null,
    due_date: p.due_date ?? '',
    linked_entity: p.linked_entity ?? null,
    heard: p.heard ?? '',
    term: p.term ?? '',
  };
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export type ActionProblem = 'text' | 'owner' | 'due';

/** Why a proposed action cannot be confirmed yet (mirrors the server rule). */
export function actionProblems(d: ProposalDraft): ActionProblem[] {
  const problems: ActionProblem[] = [];
  if (!d.text.trim()) problems.push('text');
  if (!d.owner_name.trim() && !d.owner_contact_id) problems.push('owner');
  if (!ISO_DATE.test(d.due_date)) problems.push('due');
  return problems;
}

export function canConfirm(p: Proposal, d: ProposalDraft): boolean {
  if (p.kind === 'action') return actionProblems(d).length === 0;
  if (p.kind === 'correction') return !!d.heard.trim() && !!d.term.trim();
  return !!d.text.trim();
}

/** One review entry: the verdict plus only the fields that make sense for the kind. */
export function reviewEntry(p: Proposal, d: ProposalDraft, decision: 'confirm' | 'reject'): ProposalEdit {
  if (decision === 'reject') return { id: p.id, decision };
  const entry: ProposalEdit = { id: p.id, decision, text: d.text.trim() };
  if (p.kind === 'action') {
    entry.owner_name = d.owner_name.trim();
    entry.owner_contact_id = d.owner_contact_id;
    entry.due_date = d.due_date;
    entry.linked_entity = d.linked_entity;
  }
  if (p.kind === 'correction') {
    entry.heard = d.heard.trim();
    entry.term = d.term.trim();
  }
  return entry;
}

/** Match a typed owner name to a known person to carry their contact id. */
export function resolveOwner(
  name: string,
  people: { name: string; contact_id: string | null }[],
): { owner_name: string; owner_contact_id: string | null } {
  const key = name.trim().toLocaleLowerCase();
  const hit = people.find((p) => p.name.trim().toLocaleLowerCase() === key);
  return { owner_name: name, owner_contact_id: hit?.contact_id ?? null };
}

/** Language label in the reader's own language, e.g. "German" / "Deutsch". */
export function languageLabel(code: string, uiLanguage: string): string {
  try {
    const names = new Intl.DisplayNames([uiLanguage], { type: 'language' });
    return names.of(code) ?? code;
  } catch {
    return code;
  }
}

/** Meeting rules the recording panel shows; minutes readiness belongs to the minutes dialog. */
export const MEETING_RULES = [
  'meetings.recording_consent',
  'meetings.audio_retention',
  'meetings.proposals_reviewed',
  'meetings.action_ownership',
] as const;

export type MeetingRuleId = (typeof MEETING_RULES)[number];

/** Distinct failing rules with their worst severity, known rules only. */
export function failingRules(
  results: { rule_id: string; severity: string; passed: boolean }[],
): { rule: MeetingRuleId; severity: 'error' | 'warning' }[] {
  const out: { rule: MeetingRuleId; severity: 'error' | 'warning' }[] = [];
  for (const rule of MEETING_RULES) {
    const failed = results.filter((r) => r.rule_id === rule && !r.passed);
    if (!failed.length) continue;
    out.push({ rule, severity: failed.some((r) => r.severity === 'error') ? 'error' : 'warning' });
  }
  return out;
}
