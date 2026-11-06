// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Dictation: the browser's recogniser first, the server only when the person
 * allowed it, and every refusal turned into a code the composer can explain.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, renderHook, screen } from '@testing-library/react';

vi.mock('../api', () => ({
  transcribeDictation: vi.fn(),
  fetchVoiceCapabilities: vi.fn(),
}));

import * as api from '../api';
import { pickEngine, speechLang, useSpeechInput } from '../useSpeechInput';
import { HOLD_TO_TALK_MS, VoiceDictation, isVoiceShortcut } from '../VoiceDictation';
import { useVoiceSettings } from '../voiceSettings';

class FakeRecognition {
  static last: FakeRecognition | null = null;
  lang = '';
  continuous = false;
  interimResults = false;
  onresult: ((e: unknown) => void) | null = null;
  onerror: ((e: { error?: string }) => void) | null = null;
  onend: (() => void) | null = null;
  started = false;
  constructor() {
    FakeRecognition.last = this;
  }
  start() {
    this.started = true;
  }
  stop() {
    this.onend?.();
  }
  abort() {
    this.onerror?.({ error: 'aborted' });
    this.onend?.();
  }
  // Like the real list: final results stay, the trailing guess is replaced.
  results: { isFinal: boolean; 0: { transcript: string } }[] = [];
  say(parts: { text: string; final: boolean }[]) {
    while (this.results.length && !this.results[this.results.length - 1]?.isFinal) this.results.pop();
    const resultIndex = this.results.length;
    this.results.push(...parts.map((p) => ({ isFinal: p.final, 0: { transcript: p.text } })));
    this.onresult?.({ resultIndex, results: this.results });
  }
}

class FakeRecorder {
  static last: FakeRecorder | null = null;
  static isTypeSupported = (mime: string) => mime === 'audio/webm';
  state: 'inactive' | 'recording' = 'inactive';
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  constructor(
    public stream: unknown,
    public opts: { mimeType: string },
  ) {
    FakeRecorder.last = this;
  }
  start() {
    this.state = 'recording';
  }
  stop() {
    this.state = 'inactive';
    this.ondataavailable?.({ data: new Blob(['abc'], { type: 'audio/webm' }) });
    this.onstop?.();
  }
}

const track = { stop: vi.fn() };
const stream = { getTracks: () => [track] };
const getUserMedia = vi.fn();
const w = window as unknown as Record<string, unknown>;

function withBrowserRecognition(on: boolean) {
  if (on) w.webkitSpeechRecognition = FakeRecognition;
  else delete w.webkitSpeechRecognition;
  delete w.SpeechRecognition;
}

beforeEach(() => {
  FakeRecognition.last = null;
  FakeRecorder.last = null;
  getUserMedia.mockReset().mockResolvedValue(stream);
  Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia }, configurable: true });
  w.MediaRecorder = FakeRecorder;
  withBrowserRecognition(true);
  vi.mocked(api.transcribeDictation).mockReset();
  vi.mocked(api.fetchVoiceCapabilities).mockReset().mockResolvedValue({
    server_transcription: true,
    provider: 'hosted',
    max_upload_bytes: 1,
    max_seconds: 120,
  });
  useVoiceSettings.setState({ sendOnStop: false, allowServer: false });
});

afterEach(() => {
  withBrowserRecognition(false);
  delete w.MediaRecorder;
  vi.useRealTimers();
});

describe('language and engine', () => {
  it('recognises in the app language, with a region where a bare language is ambiguous', () => {
    expect(speechLang('de')).toBe('de');
    expect(speechLang('pt-BR')).toBe('pt-BR');
    expect(speechLang('zh')).toBe('zh-CN');
    expect(speechLang('en')).toBe('en-US');
    expect(speechLang(undefined)).toBe('en-US');
  });

  it('prefers the browser, uses the server only when allowed, and otherwise has none', () => {
    expect(pickEngine({ allowServer: false, serverAvailable: null })).toBe('browser');
    withBrowserRecognition(false);
    expect(pickEngine({ allowServer: false, serverAvailable: true })).toBe('none');
    expect(pickEngine({ allowServer: true, serverAvailable: true })).toBe('server');
    expect(pickEngine({ allowServer: true, serverAvailable: false })).toBe('none');
  });
});

describe('browser recognition', () => {
  it('shows the words as they come and hands over the final text on stop', async () => {
    const onFinal = vi.fn();
    const { result } = renderHook(() =>
      useSpeechInput({ language: 'de', allowServer: false, serverAvailable: null, onFinal }),
    );
    await act(async () => {
      await result.current.start();
    });
    const rec = FakeRecognition.last!;
    expect(rec.started && rec.continuous && rec.interimResults).toBe(true);
    expect(rec.lang).toBe('de');
    expect(result.current.status).toBe('listening');

    act(() => rec.say([{ text: 'Setze den Einheitspreis', final: true }]));
    act(() => rec.say([{ text: 'von Position 01.10', final: false }]));
    expect(result.current.interim).toBe('Setze den Einheitspreis von Position 01.10');

    act(() => rec.say([{ text: 'auf 200', final: true }]));
    act(() => result.current.stop());
    expect(onFinal).toHaveBeenCalledWith('Setze den Einheitspreis auf 200');
    expect(result.current.status).toBe('idle');
    expect(track.stop).toHaveBeenCalled();
  });

  it('cancel drops what was said', async () => {
    const onFinal = vi.fn();
    const { result } = renderHook(() =>
      useSpeechInput({ language: 'en', allowServer: false, serverAvailable: null, onFinal }),
    );
    await act(async () => {
      await result.current.start();
    });
    act(() => FakeRecognition.last!.say([{ text: 'delete everything', final: true }]));
    act(() => result.current.cancel());
    expect(onFinal).not.toHaveBeenCalled();
    expect(result.current.status).toBe('idle');
  });

  it('a blocked microphone is "denied" and the recogniser never starts', async () => {
    getUserMedia.mockRejectedValueOnce(Object.assign(new Error('no'), { name: 'NotAllowedError' }));
    const { result } = renderHook(() =>
      useSpeechInput({ language: 'en', allowServer: false, serverAvailable: null, onFinal: vi.fn() }),
    );
    await act(async () => {
      await result.current.start();
    });
    expect(result.current.status).toBe('error');
    expect(result.current.error).toBe('denied');
    expect(FakeRecognition.last).toBeNull();
  });

  it('silence ends as "no_speech" without handing over anything', async () => {
    const onFinal = vi.fn();
    const { result } = renderHook(() =>
      useSpeechInput({ language: 'en', allowServer: false, serverAvailable: null, onFinal }),
    );
    await act(async () => {
      await result.current.start();
    });
    act(() => {
      FakeRecognition.last!.onerror?.({ error: 'no-speech' });
      FakeRecognition.last!.onend?.();
    });
    expect(result.current.error).toBe('no_speech');
    expect(onFinal).not.toHaveBeenCalled();
  });
});

describe('without browser recognition', () => {
  beforeEach(() => withBrowserRecognition(false));

  it('says "unsupported" when the person has not allowed the server', async () => {
    const { result } = renderHook(() =>
      useSpeechInput({ language: 'en', allowServer: false, serverAvailable: true, onFinal: vi.fn() }),
    );
    await act(async () => {
      await result.current.start();
    });
    expect(result.current.error).toBe('unsupported');
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it('records, sends the recording once, and hands over the server text', async () => {
    vi.mocked(api.transcribeDictation).mockResolvedValue({
      text: 'add a task for tomorrow',
      language: 'pt',
      available: true,
      error: null,
    });
    const onFinal = vi.fn();
    const { result } = renderHook(() =>
      useSpeechInput({ language: 'pt-BR', allowServer: true, serverAvailable: true, onFinal }),
    );
    await act(async () => {
      await result.current.start();
    });
    expect(FakeRecorder.last?.opts.mimeType).toBe('audio/webm');
    await act(async () => {
      result.current.stop();
    });
    expect(api.transcribeDictation).toHaveBeenCalledTimes(1);
    const [file, opts] = vi.mocked(api.transcribeDictation).mock.calls[0] ?? [];
    expect((file as File).name).toBe('dictation.webm');
    expect(opts?.language).toBe('pt-BR');
    expect(onFinal).toHaveBeenCalledWith('add a task for tomorrow');
  });

  it('a server without speech-to-text reads as "server_unavailable"', async () => {
    vi.mocked(api.transcribeDictation).mockRejectedValue(Object.assign(new Error('x'), { status: 503 }));
    const { result } = renderHook(() =>
      useSpeechInput({ language: 'en', allowServer: true, serverAvailable: null, onFinal: vi.fn() }),
    );
    await act(async () => {
      await result.current.start();
    });
    await act(async () => {
      result.current.stop();
    });
    expect(result.current.error).toBe('server_unavailable');
  });
});

describe('<VoiceDictation>', () => {
  it('Alt+V is the shortcut, without other modifiers', () => {
    expect(isVoiceShortcut({ altKey: true, ctrlKey: false, metaKey: false, shiftKey: false, code: 'KeyV' })).toBe(true);
    expect(isVoiceShortcut({ altKey: true, ctrlKey: true, metaKey: false, shiftKey: false, code: 'KeyV' })).toBe(false);
    expect(isVoiceShortcut({ altKey: false, ctrlKey: false, metaKey: false, shiftKey: false, code: 'KeyV' })).toBe(false);
  });

  it('click to talk, live words in a polite live region, Done puts the text in the composer', async () => {
    const onTranscript = vi.fn();
    render(<VoiceDictation onTranscript={onTranscript} language="en" />);
    const mic = screen.getByTestId('voice-dictation-mic');
    expect(mic).toHaveAttribute('aria-pressed', 'false');

    await act(async () => {
      fireEvent.pointerDown(mic, { button: 0 });
    });
    fireEvent.pointerUp(mic);
    expect(mic).toHaveAttribute('aria-pressed', 'true');
    act(() => FakeRecognition.last!.say([{ text: 'move the slab pour by two days', final: true }]));
    const live = screen.getByTestId('voice-dictation-interim');
    expect(live).toHaveAttribute('aria-live', 'polite');
    expect(live).toHaveTextContent('move the slab pour by two days');

    fireEvent.click(screen.getByTestId('voice-dictation-done'));
    expect(onTranscript).toHaveBeenCalledWith('move the slab pour by two days', { send: false });
    expect(screen.queryByTestId('voice-dictation-strip')).toBeNull();
  });

  it('holding the button is push-to-talk, and "send when I stop" sends', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    useVoiceSettings.setState({ sendOnStop: true });
    const onTranscript = vi.fn();
    render(<VoiceDictation onTranscript={onTranscript} language="en" />);
    const mic = screen.getByTestId('voice-dictation-mic');
    await act(async () => {
      fireEvent.pointerDown(mic, { button: 0 });
    });
    act(() => FakeRecognition.last!.say([{ text: 'add a task for tomorrow', final: true }]));
    vi.setSystemTime(Date.now() + HOLD_TO_TALK_MS + 50);
    act(() => {
      fireEvent.pointerUp(mic);
    });
    expect(onTranscript).toHaveBeenCalledWith('add a task for tomorrow', { send: true });
  });

  it('explains a browser without voice input instead of failing silently', async () => {
    withBrowserRecognition(false);
    render(<VoiceDictation onTranscript={vi.fn()} language="en" />);
    await act(async () => {
      fireEvent.pointerDown(screen.getByTestId('voice-dictation-mic'), { button: 0 });
    });
    expect(screen.getByRole('alert')).toHaveTextContent(/voice input|speech recognition/i);
  });
});
