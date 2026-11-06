// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// useSpeechInput - dictation for a text box. The browser's own speech
// recognition is the first choice (no server cost, live interim text); where it
// is missing (Firefox) and the person allowed it, a short recording goes to the
// server's speech-to-text and comes back as text. Either way the text is handed
// to `onFinal`, which puts it in the composer for the person to edit and send.

import { useCallback, useEffect, useRef, useState } from 'react';
import { transcribeDictation } from './api';

export type SpeechEngine = 'browser' | 'server' | 'none';
export type SpeechStatus = 'idle' | 'starting' | 'listening' | 'transcribing' | 'error';
export type SpeechErrorCode =
  | 'denied'
  | 'unsupported'
  | 'no_speech'
  | 'network'
  | 'server_unavailable'
  | 'failed';

interface RecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: RecognitionEventLike) => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}

interface RecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }>;
}

type RecognitionCtor = new () => RecognitionLike;

/** The browser's own speech recognition, when it has one. */
export function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

function canRecord(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === 'function' &&
    typeof MediaRecorder !== 'undefined'
  );
}

// Regions where a bare language would pick the wrong variant or none at all.
const SPEECH_REGION: Record<string, string> = {
  en: 'en-US',
  zh: 'zh-CN',
  no: 'nb-NO',
  fil: 'fil-PH',
  pt: 'pt-PT',
  es: 'es-ES',
  ar: 'ar-SA',
};

/** BCP-47 tag the recogniser understands for an app language (`de` -> `de`, `zh` -> `zh-CN`). */
export function speechLang(appLanguage: string | undefined): string {
  const tag = (appLanguage || 'en').replace('_', '-');
  if (tag.includes('-')) return tag;
  return SPEECH_REGION[tag] ?? tag;
}

/** Which engine this browser uses, given whether server transcription may be used. */
export function pickEngine(opts: { allowServer: boolean; serverAvailable: boolean | null }): SpeechEngine {
  if (recognitionCtor()) return 'browser';
  if (opts.allowServer && opts.serverAvailable !== false && canRecord()) return 'server';
  return 'none';
}

function errorFromRecognition(code: string | undefined): SpeechErrorCode | null {
  switch (code) {
    case 'not-allowed':
    case 'service-not-allowed':
    case 'audio-capture':
      return 'denied';
    case 'no-speech':
      return 'no_speech';
    case 'network':
      return 'network';
    case 'aborted':
      return null;
    case 'language-not-supported':
      return 'unsupported';
    default:
      return 'failed';
  }
}

const REC_TYPES: readonly { mime: string; ext: string }[] = [
  { mime: 'audio/webm', ext: 'webm' },
  { mime: 'audio/mp4', ext: 'mp4' },
];

export interface UseSpeechInputOptions {
  /** App language; the recogniser and the server transcribe in it. */
  language: string;
  /** The person allowed sending audio to the server when the browser cannot transcribe. */
  allowServer: boolean;
  /** Server speech-to-text is configured (null: not asked yet). */
  serverAvailable: boolean | null;
  /** The final text of one dictation, trimmed and non-empty. */
  onFinal: (text: string) => void;
  /** Hard stop for one dictation, in seconds. */
  maxSeconds?: number;
}

export interface UseSpeechInput {
  engine: SpeechEngine;
  status: SpeechStatus;
  /** Live text while listening (final parts plus the current guess). */
  interim: string;
  /** Input level from 0 to 1 for the meter. */
  level: number;
  seconds: number;
  error: SpeechErrorCode | null;
  active: boolean;
  start: () => Promise<void>;
  /** Finish and hand the text over. */
  stop: () => void;
  /** Drop what was said. */
  cancel: () => void;
  toggle: () => void;
  clearError: () => void;
}

export function useSpeechInput(options: UseSpeechInputOptions): UseSpeechInput {
  const { language, allowServer, serverAvailable, maxSeconds = 120 } = options;
  const engine = pickEngine({ allowServer, serverAvailable });

  const [status, setStatus] = useState<SpeechStatus>('idle');
  const [interim, setInterim] = useState('');
  const [level, setLevel] = useState(0);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<SpeechErrorCode | null>(null);

  const onFinalRef = useRef(options.onFinal);
  onFinalRef.current = options.onFinal;
  const recognitionRef = useRef<RecognitionLike | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const rafRef = useRef<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const finalTextRef = useRef('');
  const cancelledRef = useRef(false);
  const errorRef = useRef<SpeechErrorCode | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const stopRef = useRef<() => void>(() => undefined);

  const teardownAudio = useCallback(() => {
    if (rafRef.current !== null && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    if (timerRef.current !== null) clearInterval(timerRef.current);
    timerRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    const ctx = audioCtxRef.current;
    audioCtxRef.current = null;
    if (ctx && ctx.state !== 'closed') void ctx.close().catch(() => undefined);
    setLevel(0);
  }, []);

  const fail = useCallback(
    (code: SpeechErrorCode) => {
      errorRef.current = code;
      setError(code);
      setStatus('error');
      teardownAudio();
    },
    [teardownAudio],
  );

  // A level meter on the microphone stream, at most ~15 updates a second.
  const startMeter = useCallback((stream: MediaStream) => {
    const Ctx =
      typeof window !== 'undefined'
        ? (window.AudioContext ??
          (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext)
        : undefined;
    if (!Ctx || typeof requestAnimationFrame !== 'function') return;
    try {
      const ctx = new Ctx();
      audioCtxRef.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      ctx.createMediaStreamSource(stream).connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      let last = 0;
      const tick = (now: number) => {
        analyser.getByteTimeDomainData(samples);
        if (now - last > 66) {
          last = now;
          let sum = 0;
          for (const s of samples) {
            const v = (s - 128) / 128;
            sum += v * v;
          }
          setLevel(Math.min(1, Math.sqrt(sum / samples.length) * 3));
        }
        rafRef.current = requestAnimationFrame(tick);
      };
      rafRef.current = requestAnimationFrame(tick);
    } catch {
      // A meter is a nicety; dictation works without it.
    }
  }, []);

  const startTimer = useCallback(() => {
    setSeconds(0);
    if (timerRef.current !== null) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setSeconds((prev) => {
        const next = prev + 1;
        if (next >= maxSeconds) stopRef.current();
        return next;
      });
    }, 1000);
  }, [maxSeconds]);

  const deliver = useCallback((text: string) => {
    const clean = text.replace(/\s+/g, ' ').trim();
    if (clean) onFinalRef.current(clean);
  }, []);

  const startBrowser = useCallback(
    async (Ctor: RecognitionCtor) => {
      // Ask for the microphone first: a clear "denied" and a stream for the meter.
      if (canRecord()) {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          if (cancelledRef.current) {
            stream.getTracks().forEach((t) => t.stop());
            return;
          }
          streamRef.current = stream;
          startMeter(stream);
        } catch (err) {
          const name = (err as { name?: string })?.name;
          if (name === 'NotAllowedError' || name === 'SecurityError' || name === 'NotFoundError') {
            fail('denied');
            return;
          }
        }
      }
      const rec = new Ctor();
      rec.lang = speechLang(language);
      rec.continuous = true;
      rec.interimResults = true;
      rec.onresult = (event) => {
        let guess = '';
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          const result = event.results[i];
          if (!result) continue;
          if (result.isFinal) finalTextRef.current += `${result[0].transcript} `;
          else guess += result[0].transcript;
        }
        setInterim(`${finalTextRef.current}${guess}`.trimStart());
      };
      rec.onerror = (event) => {
        const code = errorFromRecognition(event.error);
        if (code) {
          errorRef.current = code;
          setError(code);
        }
      };
      rec.onend = () => {
        recognitionRef.current = null;
        teardownAudio();
        const said = finalTextRef.current;
        finalTextRef.current = '';
        setInterim('');
        if (cancelledRef.current) {
          setStatus('idle');
          return;
        }
        if (errorRef.current && !said.trim()) {
          setStatus('error');
          return;
        }
        errorRef.current = null;
        setError(null);
        setStatus('idle');
        deliver(said);
      };
      recognitionRef.current = rec;
      try {
        rec.start();
      } catch {
        recognitionRef.current = null;
        fail('failed');
        return;
      }
      setStatus('listening');
      startTimer();
    },
    [deliver, fail, language, startMeter, startTimer, teardownAudio],
  );

  const startServer = useCallback(async () => {
    const type = REC_TYPES.find((t) => typeof MediaRecorder.isTypeSupported !== 'function' || MediaRecorder.isTypeSupported(t.mime));
    if (!type) {
      fail('unsupported');
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      fail('denied');
      return;
    }
    if (cancelledRef.current) {
      stream.getTracks().forEach((t) => t.stop());
      return;
    }
    streamRef.current = stream;
    startMeter(stream);
    const chunks: Blob[] = [];
    const recorder = new MediaRecorder(stream, { mimeType: type.mime });
    recorder.ondataavailable = (e: BlobEvent) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    };
    recorder.onstop = () => {
      recorderRef.current = null;
      teardownAudio();
      if (cancelledRef.current) {
        setStatus('idle');
        return;
      }
      const blob = new Blob(chunks, { type: type.mime });
      if (blob.size === 0) {
        fail('no_speech');
        return;
      }
      setStatus('transcribing');
      const controller = new AbortController();
      abortRef.current = controller;
      transcribeDictation(new File([blob], `dictation.${type.ext}`, { type: type.mime }), {
        language,
        signal: controller.signal,
      })
        .then((result) => {
          if (controller.signal.aborted) return;
          if (!result.text) {
            fail(result.available ? 'no_speech' : 'failed');
            return;
          }
          setStatus('idle');
          deliver(result.text);
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          fail((err as { status?: number })?.status === 503 ? 'server_unavailable' : 'network');
        });
    };
    recorderRef.current = recorder;
    recorder.start();
    setStatus('listening');
    startTimer();
  }, [deliver, fail, language, startMeter, startTimer, teardownAudio]);

  const start = useCallback(async () => {
    if (status === 'listening' || status === 'starting' || status === 'transcribing') return;
    cancelledRef.current = false;
    errorRef.current = null;
    finalTextRef.current = '';
    setError(null);
    setInterim('');
    const Ctor = recognitionCtor();
    if (Ctor) {
      setStatus('starting');
      await startBrowser(Ctor);
      return;
    }
    if (engine === 'server') {
      setStatus('starting');
      await startServer();
      return;
    }
    fail('unsupported');
  }, [engine, fail, startBrowser, startServer, status]);

  const stop = useCallback(() => {
    const rec = recognitionRef.current;
    if (rec) {
      rec.stop();
      return;
    }
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop();
      return;
    }
    teardownAudio();
  }, [teardownAudio]);
  stopRef.current = stop;

  const cancel = useCallback(() => {
    cancelledRef.current = true;
    abortRef.current?.abort();
    abortRef.current = null;
    const rec = recognitionRef.current;
    if (rec) rec.abort();
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== 'inactive') recorder.stop();
    teardownAudio();
    finalTextRef.current = '';
    errorRef.current = null;
    setInterim('');
    setError(null);
    setStatus('idle');
  }, [teardownAudio]);

  const active = status === 'starting' || status === 'listening';

  const toggle = useCallback(() => {
    if (active) stop();
    else void start();
  }, [active, start, stop]);

  const clearError = useCallback(() => {
    errorRef.current = null;
    setError(null);
    setStatus((prev) => (prev === 'error' ? 'idle' : prev));
  }, []);

  useEffect(
    () => () => {
      cancelledRef.current = true;
      abortRef.current?.abort();
      recognitionRef.current?.abort();
      const recorder = recorderRef.current;
      if (recorder && recorder.state !== 'inactive') recorder.stop();
      teardownAudio();
    },
    [teardownAudio],
  );

  return { engine, status, interim, level, seconds, error, active, start, stop, cancel, toggle, clearError };
}
