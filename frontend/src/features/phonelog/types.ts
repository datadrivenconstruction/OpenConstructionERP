// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Wire types for the phone-log capture API. A phone log turns a verbal, phoned,
// or chatted instruction into a structured, dispute-ready record: a canonical
// direction and channel, a clean party list, a duration, a short summary, and
// the instruction-bearing sentences pulled out of the transcript. The raw
// transcript is kept verbatim as the underlying evidence.

export type PhoneDirection = 'inbound' | 'outbound' | 'internal' | 'unknown';
export type PhoneChannel = 'phone' | 'voice_note' | 'chat' | 'other';

export interface PhoneLog {
  id: string;
  project_id: string;
  direction: PhoneDirection;
  channel: PhoneChannel;
  parties: string[];
  occurred_at: string | null;
  duration_seconds: number | null;
  transcript: string;
  summary: string;
  instructions: string[];
  word_count: number;
  audio_storage_key: string;
  status: string;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

// The raw capture posted to the API. Everything except the project is optional
// and free-form: the server normalizes parties, direction, channel, duration,
// summary, and instructions before storing.
export interface PhoneLogCreate {
  project_id: string;
  raw_parties?: string;
  direction?: string;
  channel?: string;
  started_at?: string | null;
  ended_at?: string | null;
  duration_seconds?: number | null;
  transcript?: string;
  summary?: string;
  metadata?: Record<string, unknown>;
}

// A single action item pulled out of a recorded conversation: what must be done,
// who owns it, and when it is due (only when a date or timeframe was stated).
export interface ProtocolActionItem {
  owner: string;
  task: string;
  due: string | null;
}

// The structured, dispute-ready protocol built from a recording. Lives under
// PhoneLog.metadata.protocol. participants / summary / instructions mirror the
// canonical record columns; decisions and action_items are the richer extraction
// produced when an LLM provider is configured (ai_generated tells you which).
export interface CallProtocol {
  participants: string[];
  summary: string;
  decisions: string[];
  action_items: ProtocolActionItem[];
  instructions: string[];
  confidence: number | null;
  ai_generated: boolean;
}

// How the recording was transcribed. Lives under PhoneLog.metadata.transcription.
// available is false when no provider was configured or the call failed - the
// recording is still stored so a transcript can be pasted by hand.
export interface TranscriptionMeta {
  available: boolean;
  model: string | null;
  language: string | null;
  error: string | null;
}

// The reviewed, human-confirmed payload that turns a recording draft into a
// normal logged phone-log record. Sent as a PATCH to /phonelog/{id}.
export interface PhoneLogFinalize {
  direction?: string;
  channel?: string;
  raw_parties?: string | string[];
  occurred_at?: string | null;
  duration_seconds?: number | null;
  transcript?: string;
  summary?: string;
  instructions?: string[];
  protocol?: Record<string, unknown>;
}
