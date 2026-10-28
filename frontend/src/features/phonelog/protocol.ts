// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Safe readers for the structured protocol and transcription metadata that the
// recording-to-protocol path stores under PhoneLog.metadata. The backend keeps
// these as free-form JSON, so we parse defensively and never trust the shape.

import type { CallProtocol, PhoneLog, ProtocolActionItem, TranscriptionMeta } from './types';

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string' && item.trim() !== '');
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function asActionItems(value: unknown): ProtocolActionItem[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((raw): ProtocolActionItem => {
      const obj = asRecord(raw) ?? {};
      return {
        owner: typeof obj.owner === 'string' ? obj.owner : '',
        task: typeof obj.task === 'string' ? obj.task : '',
        due: typeof obj.due === 'string' ? obj.due : null,
      };
    })
    .filter((item) => item.task.trim() !== '');
}

/** Read the structured protocol from a phone log, or null when there is none. */
export function readProtocol(log: PhoneLog): CallProtocol | null {
  const raw = asRecord(log.metadata?.protocol);
  if (!raw) return null;
  return {
    participants: asStringArray(raw.participants),
    summary: typeof raw.summary === 'string' ? raw.summary : '',
    decisions: asStringArray(raw.decisions),
    action_items: asActionItems(raw.action_items),
    instructions: asStringArray(raw.instructions),
    confidence: typeof raw.confidence === 'number' ? raw.confidence : null,
    ai_generated: raw.ai_generated === true,
  };
}

/** Read the transcription metadata from a phone log, or null when there is none. */
export function readTranscription(log: PhoneLog): TranscriptionMeta | null {
  const raw = asRecord(log.metadata?.transcription);
  if (!raw) return null;
  return {
    available: raw.available === true,
    model: typeof raw.model === 'string' ? raw.model : null,
    language: typeof raw.language === 'string' ? raw.language : null,
    error: typeof raw.error === 'string' ? raw.error : null,
  };
}

/** True when a log came from an uploaded recording (has a stored audio file). */
export function hasRecording(log: PhoneLog): boolean {
  return typeof log.audio_storage_key === 'string' && log.audio_storage_key.trim() !== '';
}

/** True while a recording draft is still awaiting human review and confirmation. */
export function isRecordingDraft(log: PhoneLog): boolean {
  return log.status === 'draft' || log.status === 'awaiting_transcript';
}
