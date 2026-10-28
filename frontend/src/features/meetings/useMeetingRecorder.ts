// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// useMeetingRecorder - microphone capture for a whole meeting, plus optional
// live speech recognition in the browser. The audio goes to the server for
// transcription when a speech provider is configured; when none is, the
// browser's own recognition (where the browser has it) produces the transcript
// and no audio needs to leave the device at all.

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  maxRecordSeconds,
  pickRecordingType,
  RECORDING_BITS_PER_SECOND,
  speechRecognitionCtor,
  type SpeechRecognitionLike,
} from './audioLogic';

export type RecorderError = 'unsupported' | 'mic_blocked' | 'empty';

export interface RecorderResult {
  file: File | null;
  liveText: string;
}

export interface UseMeetingRecorder {
  micSupported: boolean;
  speechSupported: boolean;
  recording: boolean;
  seconds: number;
  maxSeconds: number;
  liveText: string;
  interimText: string;
  error: RecorderError | null;
  /** True once the recording reached the upload size limit; the caller should stop. */
  limitReached: boolean;
  /** Start capture. `keepAudio` false runs recognition only, nothing is recorded. */
  start: (opts: { keepAudio: boolean; liveRecognition: boolean; language?: string }) => Promise<void>;
  stop: () => Promise<RecorderResult>;
  cancel: () => void;
}

export function useMeetingRecorder(maxUploadMb: number): UseMeetingRecorder {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [liveText, setLiveText] = useState('');
  const [interimText, setInterimText] = useState('');
  const [error, setError] = useState<RecorderError | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const keepListeningRef = useRef(false);
  const liveRef = useRef('');
  const typeRef = useRef<{ mime: string; ext: string } | null>(null);
  const stopResolveRef = useRef<((r: RecorderResult) => void) | null>(null);

  const maxSeconds = maxRecordSeconds(maxUploadMb);
  const micSupported =
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === 'function' &&
    pickRecordingType() !== null;
  const speechSupported = speechRecognitionCtor() !== null;

  const teardown = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    keepListeningRef.current = false;
    try {
      recognitionRef.current?.stop();
    } catch {
      // already stopped
    }
    recognitionRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const startRecognition = useCallback((language?: string) => {
    const Ctor = speechRecognitionCtor();
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = language || (typeof navigator !== 'undefined' ? navigator.language : 'en');
    rec.continuous = true;
    rec.interimResults = true;
    rec.onresult = (event) => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i]!;
        const text = result[0].transcript.trim();
        if (!text) continue;
        if (result.isFinal) {
          liveRef.current = liveRef.current ? `${liveRef.current}\n${text}` : text;
          setLiveText(liveRef.current);
        } else {
          interim = interim ? `${interim} ${text}` : text;
        }
      }
      setInterimText(interim);
    };
    rec.onerror = () => {
      // A recognition hiccup must not end the recording; onend restarts it.
    };
    // Browsers end continuous recognition after a pause; keep it going until stop.
    rec.onend = () => {
      if (keepListeningRef.current) {
        try {
          rec.start();
        } catch {
          keepListeningRef.current = false;
        }
      }
    };
    recognitionRef.current = rec;
    keepListeningRef.current = true;
    try {
      rec.start();
    } catch {
      keepListeningRef.current = false;
    }
  }, []);

  const start = useCallback<UseMeetingRecorder['start']>(
    async ({ keepAudio, liveRecognition, language }) => {
      setError(null);
      liveRef.current = '';
      setLiveText('');
      setInterimText('');
      setSeconds(0);
      chunksRef.current = [];
      const recType = pickRecordingType();
      if (keepAudio && (!micSupported || !recType)) {
        setError('unsupported');
        return;
      }
      if (!keepAudio && !speechSupported) {
        setError('unsupported');
        return;
      }
      if (keepAudio && recType) {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          streamRef.current = stream;
          typeRef.current = recType;
          const recorder = new MediaRecorder(stream, {
            mimeType: recType.mime,
            audioBitsPerSecond: RECORDING_BITS_PER_SECOND,
          });
          recorder.ondataavailable = (e: BlobEvent) => {
            if (e.data.size > 0) chunksRef.current.push(e.data);
          };
          recorder.onstop = () => {
            const type = typeRef.current ?? recType;
            const blob = new Blob(chunksRef.current, { type: type.mime.split(';')[0] });
            chunksRef.current = [];
            const file =
              blob.size > 0
                ? new File([blob], `meeting.${type.ext}`, { type: type.mime.split(';')[0] })
                : null;
            if (!file && !liveRef.current) setError('empty');
            stopResolveRef.current?.({ file, liveText: liveRef.current });
            stopResolveRef.current = null;
          };
          recorderRef.current = recorder;
          recorder.start(10_000);
        } catch {
          teardown();
          setError('mic_blocked');
          return;
        }
      }
      if (liveRecognition) startRecognition(language);
      setRecording(true);
      // The caller watches `limitReached` and stops, so the file is handed back.
      timerRef.current = setInterval(() => setSeconds((prev) => prev + 1), 1000);
    },
    [micSupported, speechSupported, startRecognition, teardown],
  );

  const stop = useCallback<UseMeetingRecorder['stop']>(() => {
    const recorder = recorderRef.current;
    recorderRef.current = null;
    setRecording(false);
    setInterimText('');
    if (recorder && recorder.state !== 'inactive') {
      const done = new Promise<RecorderResult>((resolve) => {
        stopResolveRef.current = resolve;
      });
      recorder.stop();
      teardown();
      return done;
    }
    teardown();
    if (!liveRef.current) setError('empty');
    return Promise.resolve({ file: null, liveText: liveRef.current });
  }, [teardown]);

  const cancel = useCallback(() => {
    const recorder = recorderRef.current;
    recorderRef.current = null;
    if (recorder && recorder.state !== 'inactive') {
      recorder.onstop = null;
      recorder.stop();
    }
    chunksRef.current = [];
    teardown();
    setRecording(false);
    setSeconds(0);
    setInterimText('');
  }, [teardown]);

  useEffect(
    () => () => {
      const recorder = recorderRef.current;
      if (recorder && recorder.state !== 'inactive') {
        recorder.onstop = null;
        recorder.stop();
      }
      teardown();
    },
    [teardown],
  );

  return {
    micSupported,
    speechSupported,
    recording,
    seconds,
    maxSeconds,
    liveText,
    interimText,
    error,
    limitReached: recording && seconds >= maxSeconds,
    start,
    stop,
    cancel,
  };
}
