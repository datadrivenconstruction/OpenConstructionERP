// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Wire types for the shared voice-capture flow. A worker speaks (or types) a
// rough site note; the backend transcribes it, refines and translates it, and
// returns a structured DRAFT shaped for the chosen target (a daily-diary note,
// a defect, or a task). The draft is reviewed and confirmed in the UI before it
// is saved through the target feature's own create endpoint - nothing here is
// auto-saved.

/** The kinds of structured entry a spoken note can be turned into. */
export type VoiceTargetType = 'diary_note' | 'defect' | 'task';

/** How the recording was transcribed. `available` is false when no speech-to-
 *  text provider was configured or the call failed - the typed-note path still
 *  works, so the feature stays usable. */
export interface VoiceTranscriptionInfo {
  available: boolean;
  model: string | null;
  language: string | null;
  error: string | null;
}

/** A structured draft returned from POST /voice/draft. `fields` is a flat map of
 *  the target's field names to cleaned string values (enum fields already
 *  clamped to a value the target accepts). `ai_generated` is false on the
 *  graceful-degradation path (no/failed LLM) where `confidence` is null. */
export interface VoiceDraft {
  target_type: VoiceTargetType;
  fields: Record<string, string>;
  transcript: string;
  refined_text: string;
  confidence: number | null;
  ai_generated: boolean;
  detected_language: string | null;
  target_language: string | null;
  transcription: VoiceTranscriptionInfo;
}

/** The reviewed, human-confirmed payload handed to a target feature's onConfirm.
 *  The target page maps `fields` onto its own create request. */
export interface ConfirmedVoiceDraft {
  target: VoiceTargetType;
  fields: Record<string, string>;
  transcript: string;
  confidence: number | null;
  aiGenerated: boolean;
}
