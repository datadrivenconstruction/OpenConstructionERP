// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// <VoiceDictation> - the microphone of a composer. Click to talk and click
// again to finish, or hold to talk while pressed; Alt+V does the same from the
// keyboard inside `scopeRef`. While listening a strip above the composer shows
// the level, the time and the words as they are recognised. The text goes to
// `onTranscript`, never straight to the assistant unless the person turned on
// "send when I stop".

import { useCallback, useEffect, useId, useRef, useState, type RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Check, Loader2, Mic, Settings2, X } from 'lucide-react';
import clsx from 'clsx';
import { fetchVoiceCapabilities } from './api';
import { recognitionCtor, useSpeechInput, type SpeechErrorCode } from './useSpeechInput';
import { useVoiceSettings } from './voiceSettings';

/** Held longer than this, a press (or Alt+V) is push-to-talk and release finishes. */
export const HOLD_TO_TALK_MS = 400;

/** Alt+V (Option+V), without other modifiers. `code` so the Mac's "√" does not hide it. */
export function isVoiceShortcut(e: Pick<KeyboardEvent, 'altKey' | 'ctrlKey' | 'metaKey' | 'shiftKey' | 'code'>) {
  return e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey && e.code === 'KeyV';
}

/** A finished dictation appended to whatever is already typed. */
export function appendDictation(current: string, text: string): string {
  return current.trim() ? `${current.replace(/\s+$/, '')} ${text}` : text;
}

function formatSeconds(total: number): string {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export interface VoiceDictationProps {
  /** One finished dictation. `send` is true when the person wants it sent at once. */
  onTranscript: (text: string, opts: { send: boolean }) => void;
  /** Alt+V works while focus is inside this element. */
  scopeRef?: RefObject<HTMLElement | null>;
  disabled?: boolean;
  /** App language to recognise; defaults to the i18n language. */
  language?: string;
  className?: string;
}

const BARS = [0.55, 0.85, 1, 0.8, 0.5];

export function VoiceDictation({ onTranscript, scopeRef, disabled, language, className }: VoiceDictationProps) {
  const { t, i18n } = useTranslation();
  const sendOnStop = useVoiceSettings((s) => s.sendOnStop);
  const allowServer = useVoiceSettings((s) => s.allowServer);
  const setSendOnStop = useVoiceSettings((s) => s.setSendOnStop);
  const setAllowServer = useVoiceSettings((s) => s.setAllowServer);
  const [serverAvailable, setServerAvailable] = useState<boolean | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const statusId = useId();
  const settingsId = useId();
  const hasBrowserEngine = recognitionCtor() !== null;

  const onTranscriptRef = useRef(onTranscript);
  onTranscriptRef.current = onTranscript;
  const sendRef = useRef(sendOnStop);
  sendRef.current = sendOnStop;

  const voice = useSpeechInput({
    language: language ?? i18n.language,
    allowServer,
    serverAvailable,
    onFinal: (text) => onTranscriptRef.current(text, { send: sendRef.current }),
  });

  // Only a browser without its own recogniser needs to know about the server.
  const ensureCapabilities = useCallback(() => {
    if (hasBrowserEngine || serverAvailable !== null) return;
    fetchVoiceCapabilities()
      .then((caps) => setServerAvailable(caps.server_transcription))
      .catch(() => setServerAvailable(false));
  }, [hasBrowserEngine, serverAvailable]);

  // The level meter re-renders this component often; the handlers read the
  // latest hook state through a ref so the key listeners are not re-bound.
  const voiceRef = useRef(voice);
  voiceRef.current = voice;
  const pressRef = useRef<{ at: number; stopOnRelease: boolean } | null>(null);

  const press = useCallback(() => {
    if (disabled) return;
    if (voiceRef.current.active) {
      pressRef.current = { at: Date.now(), stopOnRelease: true };
      return;
    }
    ensureCapabilities();
    pressRef.current = { at: Date.now(), stopOnRelease: false };
    void voiceRef.current.start();
  }, [disabled, ensureCapabilities]);

  const release = useCallback(() => {
    const pressed = pressRef.current;
    pressRef.current = null;
    if (!pressed) return;
    if (pressed.stopOnRelease || Date.now() - pressed.at >= HOLD_TO_TALK_MS) voiceRef.current.stop();
  }, []);

  // Alt+V inside the scope: press on keydown, release on keyup.
  useEffect(() => {
    const scope = scopeRef?.current;
    if (!scope) return;
    const down = (e: KeyboardEvent) => {
      if (!isVoiceShortcut(e)) return;
      e.preventDefault();
      if (e.repeat) return;
      press();
    };
    const up = (e: KeyboardEvent) => {
      if (e.code !== 'KeyV' || !pressRef.current) return;
      release();
    };
    scope.addEventListener('keydown', down);
    scope.addEventListener('keyup', up);
    return () => {
      scope.removeEventListener('keydown', down);
      scope.removeEventListener('keyup', up);
    };
  }, [scopeRef, press, release]);

  // Escape while listening drops the dictation, not the panel around it.
  const { active: voiceActive, cancel: cancelVoice } = voice;
  useEffect(() => {
    if (!voiceActive) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      e.stopPropagation();
      cancelVoice();
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [voiceActive, cancelVoice]);

  const errorText = (code: SpeechErrorCode): string => {
    switch (code) {
      case 'denied':
        return t('voice.dictation.error.denied', {
          defaultValue: "Microphone access is blocked. Allow it in the browser's site settings, then try again.",
        });
      case 'unsupported':
        return serverAvailable && !allowServer
          ? t('voice.dictation.error.unsupported_server', {
              defaultValue:
                'This browser has no built-in speech recognition. Turn on server transcription in the voice settings.',
            })
          : t('voice.dictation.error.unsupported', {
              defaultValue: 'Voice input is not available in this browser. Use Chrome, Edge or Safari, or type the message.',
            });
      case 'no_speech':
        return t('voice.dictation.error.no_speech', {
          defaultValue: 'No speech was heard. Try again a little closer to the microphone.',
        });
      case 'network':
        return t('voice.dictation.error.network', {
          defaultValue: 'The speech service could not be reached. Check the connection and try again.',
        });
      case 'server_unavailable':
        return t('voice.dictation.error.server_unavailable', {
          defaultValue: 'Server transcription is not set up. Ask an administrator, or use a browser with voice input.',
        });
      default:
        return t('voice.dictation.error.failed', { defaultValue: 'Voice input stopped unexpectedly. Try again.' });
    }
  };

  const listening = voice.status === 'listening' || voice.status === 'starting';
  const showStrip = listening || voice.status === 'transcribing' || voice.status === 'error';
  const startLabel = t('voice.dictation.start', { defaultValue: 'Dictate (Alt+V)' });
  const stopLabel = t('voice.dictation.stop', { defaultValue: 'Stop and insert the text' });
  const engineLine = hasBrowserEngine
    ? t('voice.dictation.engine_browser', { defaultValue: 'Speech is recognised by your browser.' })
    : allowServer && serverAvailable !== false
      ? t('voice.dictation.engine_server', { defaultValue: 'Speech is transcribed by the server.' })
      : t('voice.dictation.engine_none', { defaultValue: 'Voice input is not available in this browser.' });

  return (
    <div className={clsx('relative flex items-center gap-0.5', className)} data-testid="voice-dictation">
      {showStrip && (
        <div
          className="absolute bottom-full end-0 z-10 mb-2 flex w-[min(26rem,calc(100vw-2rem))] items-start gap-2 rounded-xl border border-border-light bg-surface-elevated p-2.5 text-sm shadow-lg"
          data-testid="voice-dictation-strip"
          data-status={voice.status}
        >
          {voice.status === 'error' && voice.error ? (
            <>
              <AlertTriangle size={16} className="mt-0.5 shrink-0 text-semantic-warning" aria-hidden />
              <p role="alert" className="min-w-0 flex-1 text-content-primary" data-testid="voice-dictation-error">
                {errorText(voice.error)}
              </p>
              <button
                type="button"
                onClick={voice.clearError}
                aria-label={t('voice.dictation.dismiss', { defaultValue: 'Dismiss' })}
                className="shrink-0 rounded-md p-1 text-content-secondary hover:bg-surface-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
              >
                <X size={14} aria-hidden />
              </button>
            </>
          ) : (
            <>
              <div className="flex shrink-0 flex-col items-center gap-1 pt-0.5">
                {voice.status === 'transcribing' ? (
                  <Loader2 size={16} className="animate-spin text-oe-blue" aria-hidden />
                ) : (
                  <span className="flex h-4 items-end gap-[2px]" aria-hidden data-testid="voice-level">
                    {BARS.map((weight, i) => (
                      <span
                        key={i}
                        className="w-[3px] rounded-full bg-semantic-error transition-[height] duration-75"
                        style={{ height: `${Math.max(3, Math.round(16 * Math.min(1, voice.level * weight * 1.6)))}px` }}
                      />
                    ))}
                  </span>
                )}
                <span className="text-[11px] tabular-nums text-content-secondary">{formatSeconds(voice.seconds)}</span>
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-content-secondary">
                  {voice.status === 'transcribing'
                    ? t('voice.dictation.transcribing', { defaultValue: 'Transcribing...' })
                    : t('voice.dictation.listening', { defaultValue: 'Listening...' })}
                </p>
                <p
                  id={statusId}
                  aria-live="polite"
                  className="mt-0.5 max-h-24 overflow-y-auto break-words text-content-primary"
                  data-testid="voice-dictation-interim"
                >
                  {voice.interim}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  onClick={voice.cancel}
                  aria-label={t('voice.dictation.cancel', { defaultValue: 'Discard' })}
                  title={t('voice.dictation.cancel', { defaultValue: 'Discard' })}
                  className="rounded-md p-1.5 text-content-secondary hover:bg-surface-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
                  data-testid="voice-dictation-cancel"
                >
                  <X size={15} aria-hidden />
                </button>
                {listening && (
                  <button
                    type="button"
                    onClick={voice.stop}
                    aria-label={stopLabel}
                    title={stopLabel}
                    className="rounded-md bg-oe-blue p-1.5 text-oe-on-accent hover:bg-oe-blue-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-1"
                    data-testid="voice-dictation-done"
                  >
                    <Check size={15} aria-hidden />
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      )}

      <button
        type="button"
        disabled={disabled || voice.status === 'transcribing'}
        aria-pressed={listening}
        aria-label={listening ? stopLabel : startLabel}
        aria-describedby={listening ? statusId : undefined}
        title={
          listening
            ? stopLabel
            : `${startLabel}. ${t('voice.dictation.hold_hint', { defaultValue: 'Hold to talk, or click to start and click again to finish.' })}`
        }
        onPointerDown={(e) => {
          if (e.button !== 0) return;
          e.preventDefault();
          press();
        }}
        onPointerUp={release}
        onPointerLeave={() => {
          if (pressRef.current && !pressRef.current.stopOnRelease) release();
        }}
        onClick={(e) => {
          // Keyboard activation (Enter / Space) has no pointer events before it.
          if (e.detail === 0) {
            if (listening) voice.stop();
            else {
              ensureCapabilities();
              void voice.start();
            }
          }
        }}
        data-testid="voice-dictation-mic"
        data-recording={listening || undefined}
        className={clsx(
          'relative inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-1',
          'disabled:cursor-not-allowed disabled:opacity-50',
          listening
            ? 'bg-semantic-error text-white'
            : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
        )}
      >
        {listening && (
          <span
            aria-hidden
            className="pointer-events-none absolute inset-0 rounded-lg ring-2 ring-semantic-error/40"
            style={{ transform: `scale(${1 + voice.level * 0.35})`, transition: 'transform 80ms linear' }}
          />
        )}
        <Mic size={16} strokeWidth={2.1} aria-hidden />
      </button>

      <button
        type="button"
        onClick={() => {
          setSettingsOpen((v) => !v);
          ensureCapabilities();
        }}
        aria-expanded={settingsOpen}
        aria-controls={settingsId}
        aria-label={t('voice.dictation.settings', { defaultValue: 'Voice settings' })}
        title={t('voice.dictation.settings', { defaultValue: 'Voice settings' })}
        className="inline-flex h-8 w-6 shrink-0 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
        data-testid="voice-dictation-settings-toggle"
      >
        <Settings2 size={13} aria-hidden />
      </button>

      {settingsOpen && (
        <div
          id={settingsId}
          role="group"
          aria-label={t('voice.dictation.settings', { defaultValue: 'Voice settings' })}
          className="absolute bottom-full start-0 z-20 mb-2 w-72 rounded-xl border border-border-light bg-surface-elevated p-3 text-sm shadow-lg"
          data-testid="voice-dictation-settings"
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              e.stopPropagation();
              setSettingsOpen(false);
            }
          }}
        >
          <p className="mb-2 text-xs text-content-secondary">{engineLine}</p>
          <label className="flex cursor-pointer items-start gap-2 py-1">
            <input
              type="checkbox"
              checked={sendOnStop}
              onChange={(e) => setSendOnStop(e.target.checked)}
              className="mt-0.5"
              data-testid="voice-setting-send-on-stop"
            />
            <span className="text-content-primary">
              {t('voice.dictation.send_on_stop', { defaultValue: 'Send the message when I stop talking' })}
            </span>
          </label>
          {!hasBrowserEngine && (
            <label className="flex cursor-pointer items-start gap-2 py-1">
              <input
                type="checkbox"
                checked={allowServer}
                disabled={serverAvailable === false}
                onChange={(e) => setAllowServer(e.target.checked)}
                className="mt-0.5"
                data-testid="voice-setting-allow-server"
              />
              <span>
                <span className="block text-content-primary">
                  {t('voice.dictation.allow_server', {
                    defaultValue: 'Use server transcription when the browser has none',
                  })}
                </span>
                <span className="block text-xs text-content-secondary">
                  {serverAvailable === false
                    ? t('voice.dictation.error.server_unavailable', {
                        defaultValue:
                          'Server transcription is not set up. Ask an administrator, or use a browser with voice input.',
                      })
                    : t('voice.dictation.allow_server_hint', {
                        defaultValue: 'Audio goes to the configured speech service, is transcribed and is not stored.',
                      })}
                </span>
              </span>
            </label>
          )}
        </div>
      )}
    </div>
  );
}
