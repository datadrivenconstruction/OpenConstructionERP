// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Public surface of the shared voice-capture feature. A target feature adds
// voice-to-structured-entry with a single import:
//
//   import { VoiceEntry } from '@/features/voice';
//   <VoiceEntry projectId={id} target="defect" onConfirm={(d) => create(map(d))} />

export { VoiceEntry } from './VoiceEntry';
export type { VoiceEntryProps } from './VoiceEntry';

export { useVoiceCapture } from './useVoiceCapture';
export type {
  UseVoiceCapture,
  UseVoiceCaptureOptions,
  VoicePhase,
  ProcessingKind,
} from './useVoiceCapture';

export { requestVoiceDraft, fetchVoiceTargets } from './api';
export type { VoiceDraftOptions } from './api';

export { VOICE_TARGETS, voiceTargetDef, getField, humanizeToken } from './targets';
export type { VoiceTargetDef, VoiceFieldDef, VoiceFieldKind } from './targets';

export type {
  VoiceTargetType,
  VoiceDraft,
  VoiceTranscriptionInfo,
  ConfirmedVoiceDraft,
} from './types';

export { VoiceDictation, appendDictation, isVoiceShortcut, HOLD_TO_TALK_MS } from './VoiceDictation';
export type { VoiceDictationProps } from './VoiceDictation';
export { useSpeechInput, speechLang, pickEngine, recognitionCtor } from './useSpeechInput';
export type { UseSpeechInput, UseSpeechInputOptions, SpeechEngine, SpeechStatus, SpeechErrorCode } from './useSpeechInput';
export { useVoiceSettings } from './voiceSettings';
export { transcribeDictation, fetchVoiceCapabilities, VoiceHttpError } from './api';
export type { VoiceCapabilities, DictationResult } from './api';
