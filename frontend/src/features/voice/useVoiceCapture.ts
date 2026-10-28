// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// useVoiceCapture - the shared brain behind the voice-to-structured-entry flow.
// It owns live microphone capture (MediaRecorder), file upload, and the call to
// POST /voice/draft, and holds an editable working copy of the returned draft so
// a target feature can drop in voice capture with one hook + one component.
//
// Nothing is auto-saved: the hook produces a reviewable draft; the consuming
// component confirms it and the target feature saves it through its own API.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getErrorMessage } from '@/shared/lib/api';
import { requestVoiceDraft } from './api';
import type { VoiceDraft, VoiceTargetType } from './types';

/** idle -> recording -> processing -> review, or -> error at any point. */
export type VoicePhase = 'idle' | 'recording' | 'processing' | 'review' | 'error';

/** Which slow step is running, so the UI can say "Transcribing" vs "Structuring". */
export type ProcessingKind = 'transcribing' | 'structuring';

// Container formats a speech-to-text provider takes directly. Ogg is excluded on
// purpose - the backend accepts webm/mp4 (among others) but not ogg.
const REC_TYPES: readonly { mime: string; ext: string }[] = [
  { mime: 'audio/webm', ext: 'webm' },
  { mime: 'audio/mp4', ext: 'mp4' },
];

// Hard cap on a single recording so a forgotten "stop" cannot run past the
// backend's 25 MB upload limit. Five minutes of speech is well under it.
const MAX_RECORD_SECONDS = 300;

function pickRecordingType(): { mime: string; ext: string } | null {
  if (typeof MediaRecorder === 'undefined' || typeof MediaRecorder.isTypeSupported !== 'function') {
    return null;
  }
  for (const t of REC_TYPES) {
    if (MediaRecorder.isTypeSupported(t.mime)) return t;
  }
  return null;
}

export interface UseVoiceCaptureOptions {
  projectId: string;
  target: VoiceTargetType;
  /** Working language the draft is written in (translates a foreign note). */
  targetLanguage?: string;
}

export interface UseVoiceCapture {
  phase: VoicePhase;
  /** True when live mic capture is possible in this browser. */
  micSupported: boolean;
  isRecording: boolean;
  /** Elapsed seconds of the current recording. */
  seconds: number;
  processingKind: ProcessingKind | null;
  draft: VoiceDraft | null;
  /** Editable working copy of the draft fields. */
  fields: Record<string, string>;
  /** Editable working copy of the transcript. */
  transcript: string;
  error: string | null;
  startRecording: () => Promise<void>;
  stopRecording: () => void;
  uploadFile: (file: File) => void;
  /** Structure a typed/edited transcript with no audio (also used to re-run). */
  structureText: (text: string) => void;
  setField: (name: string, value: string) => void;
  setTranscript: (text: string) => void;
  reset: () => void;
}

export function useVoiceCapture(options: UseVoiceCaptureOptions): UseVoiceCapture {
  const { projectId, target, targetLanguage } = options;

  const [phase, setPhase] = useState<VoicePhase>('idle');
  const [seconds, setSeconds] = useState(0);
  const [processingKind, setProcessingKind] = useState<ProcessingKind | null>(null);
  const [draft, setDraft] = useState<VoiceDraft | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [transcript, setTranscriptState] = useState('');
  const [error, setError] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const recTypeRef = useRef<{ mime: string; ext: string } | null>(null);

  const micSupported = useMemo(
    () =>
      typeof navigator !== 'undefined' &&
      !!navigator.mediaDevices &&
      typeof navigator.mediaDevices.getUserMedia === 'function' &&
      pickRecordingType() !== null,
    [],
  );

  const stopTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const stopStream = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
  }, []);

  // Turn raw text (or a file) into a structured draft. Kept generic so the mic,
  // upload and typed paths all funnel through one request + one review handoff.
  const runDraft = useCallback(
    (payload: { file?: File; text?: string }) => {
      if (!projectId) {
        setError('No project selected.');
        setPhase('error');
        return;
      }
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setError(null);
      setProcessingKind(payload.file ? 'transcribing' : 'structuring');
      setPhase('processing');

      requestVoiceDraft(projectId, target, {
        file: payload.file,
        transcript: payload.text,
        targetLanguage,
        signal: controller.signal,
      })
        .then((result) => {
          if (controller.signal.aborted) return;
          setDraft(result);
          setFields({ ...result.fields });
          setTranscriptState(result.transcript);
          setProcessingKind(null);
          setPhase('review');
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          setError(getErrorMessage(err));
          setProcessingKind(null);
          setPhase('error');
        });
    },
    [projectId, target, targetLanguage],
  );

  const startRecording = useCallback(async () => {
    const recType = pickRecordingType();
    if (!micSupported || !recType) {
      setError('Recording is not supported in this browser. Upload a file or type the note.');
      setPhase('error');
      return;
    }
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      recTypeRef.current = recType;
      chunksRef.current = [];
      const recorder = new MediaRecorder(stream, { mimeType: recType.mime });
      recorder.ondataavailable = (e: BlobEvent) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        stopTimer();
        stopStream();
        const type = recTypeRef.current ?? recType;
        const blob = new Blob(chunksRef.current, { type: type.mime });
        chunksRef.current = [];
        if (blob.size === 0) {
          setError('The recording was empty. Please try again.');
          setPhase('error');
          return;
        }
        const file = new File([blob], `note.${type.ext}`, { type: type.mime });
        runDraft({ file });
      };
      recorderRef.current = recorder;
      recorder.start();
      setSeconds(0);
      setPhase('recording');
      stopTimer();
      timerRef.current = setInterval(() => {
        setSeconds((prev) => {
          const next = prev + 1;
          // Auto-stop at the cap; onstop then kicks off transcription.
          if (next >= MAX_RECORD_SECONDS && recorderRef.current?.state === 'recording') {
            recorderRef.current.stop();
          }
          return next;
        });
      }, 1000);
    } catch {
      stopStream();
      setError('Microphone access was blocked. Allow the microphone, upload a file, or type the note.');
      setPhase('error');
    }
  }, [micSupported, runDraft, stopStream, stopTimer]);

  const stopRecording = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop(); // onstop builds the file and calls runDraft
    } else {
      stopTimer();
      stopStream();
    }
  }, [stopStream, stopTimer]);

  const uploadFile = useCallback(
    (file: File) => {
      runDraft({ file });
    },
    [runDraft],
  );

  const structureText = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) {
        setError('Type or edit the note text first.');
        setPhase('error');
        return;
      }
      runDraft({ text: trimmed });
    },
    [runDraft],
  );

  const setField = useCallback((name: string, value: string) => {
    setFields((prev) => ({ ...prev, [name]: value }));
  }, []);

  const setTranscript = useCallback((text: string) => {
    setTranscriptState(text);
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      recorder.onstop = null;
      recorder.stop();
    }
    recorderRef.current = null;
    stopTimer();
    stopStream();
    chunksRef.current = [];
    setPhase('idle');
    setSeconds(0);
    setProcessingKind(null);
    setDraft(null);
    setFields({});
    setTranscriptState('');
    setError(null);
  }, [stopStream, stopTimer]);

  // Tear down any live capture / in-flight request on unmount.
  useEffect(
    () => () => {
      abortRef.current?.abort();
      const recorder = recorderRef.current;
      if (recorder && recorder.state !== 'inactive') {
        recorder.onstop = null;
        recorder.stop();
      }
      if (timerRef.current !== null) clearInterval(timerRef.current);
      if (streamRef.current) streamRef.current.getTracks().forEach((track) => track.stop());
    },
    [],
  );

  return {
    phase,
    micSupported,
    isRecording: phase === 'recording',
    seconds,
    processingKind,
    draft,
    fields,
    transcript,
    error,
    startRecording,
    stopRecording,
    uploadFile,
    structureText,
    setField,
    setTranscript,
    reset,
  };
}
