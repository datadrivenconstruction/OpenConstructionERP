import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createInstance, type i18n } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.unmock('react-i18next');
vi.mock('@/shared/ui', () => ({ ModuleGuideButton: () => null }));
const chatApi = vi.hoisted(() => ({
  fetchChatSessions: vi.fn(),
  fetchSessionMessages: vi.fn(),
  deleteChatSession: vi.fn(),
}));
vi.mock('../api', () => chatApi);
vi.mock('@/features/ai/api', () => ({
  aiApi: { getSettings: () => Promise.resolve({ ai_ready: true }) },
}));
vi.mock('@/features/ai-estimator/useAiReadiness', () => ({ hasLlmKey: () => true }));

import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useChatFullPage } from '../full-page/useChatFullPage';
import ChatHistory from '../full-page/left/ChatHistory';
import InputBar from '../full-page/left/InputBar';

const localeDir = resolve(process.cwd(), 'src/app/locales');
const keys = [
  'chat.history.title', 'chat.history.just_now', 'chat.history.loading',
  'chat.history.empty', 'chat.history.untitled', 'chat.history.delete',
  'chat.suggestion.projects', 'chat.suggestion.boq', 'chat.suggestion.validation',
  'chat.suggestion.risks', 'chat.suggestion.costs',
];

// Read the actual catalogue values without importing forty full TS bundles.
function labels(locale: string): Record<string, string> {
  const source = readFileSync(resolve(localeDir, `${locale}.ts`), 'utf8');
  const result: Record<string, string> = {};
  for (const key of keys) {
    const escaped = key.replaceAll('.', '\\.');
    const match = source.match(new RegExp(`"${escaped}"\\s*:\\s*("(?:[^"\\\\]|\\\\.)*")`));
    if (match) result[key] = JSON.parse(match[1]!);
  }
  return result;
}

const resources = Object.fromEntries(['en', 'ru', 'ar'].map((locale) => [locale, { translation: labels(locale) }]));

function Harness() {
  const chat = useChatFullPage();
  return <>
    <output data-testid="ready">{String(chat.aiConfigured)}</output>
    <output data-testid="session">{chat.sessionId ?? ''}</output>
    <ChatHistory
      sessions={chat.sessions} sessionsTotal={chat.sessionsTotal}
      sessionsLoading={chat.sessionsLoading} loadingSessionId={chat.loadingSessionId}
      activeSessionId={chat.sessionId} onLoad={chat.loadSession}
      onDelete={chat.removeSession} onNew={chat.clearChat}
    />
    <InputBar onSend={chat.sendMessage} onClear={chat.clearChat}
      hasMessages={chat.messages.length > 0} isStreaming={chat.isStreaming}
      suggestions={chat.suggestions} />
    <button onClick={chat.clearChat}>reset-test</button>
    <button onClick={() => void chat.loadSession('s-1')}>load-test</button>
    <button onClick={() => void chat.removeSession('s-1')}>delete-test</button>
  </>;
}

async function mount(locale: string): Promise<i18n> {
  const instance = createInstance();
  await instance.init({ lng: locale, fallbackLng: 'en', resources, interpolation: { escapeValue: false } });
  render(<I18nextProvider i18n={instance}><Harness /></I18nextProvider>);
  await waitFor(() => expect(screen.getByTestId('ready')).toHaveTextContent('true'));
  return instance;
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ isAuthenticated: true, accessToken: 'test-token' });
  useProjectContextStore.setState({ activeProjectId: null, activeProjectName: '' });
  chatApi.fetchChatSessions.mockResolvedValue({ items: [], total: 0 });
  chatApi.fetchSessionMessages.mockResolvedValue([]);
  chatApi.deleteChatSession.mockResolvedValue(undefined);
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true, status: 200,
    headers: new Headers({ 'content-type': 'text/event-stream' }),
    body: { getReader: () => ({ read: async () => ({ done: true, value: undefined }) }) },
  })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('full-page chat owns translated defaults', () => {
  it.each(['ru', 'ar'])('renders and sends %s prompts, then restores them after clear', async (locale) => {
    const text = labels(locale);
    await mount(locale);
    expect(screen.getByText(text['chat.history.title']!)).toBeInTheDocument();
    for (const key of keys.filter((key) => key.startsWith('chat.suggestion.'))) {
      expect(screen.getByRole('button', { name: text[key] })).toBeInTheDocument();
    }
    fireEvent.click(screen.getByText(text['chat.history.title']!));
    await screen.findByText(text['chat.history.empty']!);
    fireEvent.click(screen.getByRole('button', { name: text['chat.suggestion.projects'] }));
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    const request = JSON.parse(String(vi.mocked(fetch).mock.calls[0]![1]!.body));
    expect(request.message).toBe(text['chat.suggestion.projects']);
    expect(request.locale).toBe(locale);
    expect(screen.queryByRole('button', { name: text['chat.suggestion.projects'] })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'reset-test' }));
    expect(screen.getByRole('button', { name: text['chat.suggestion.projects'] })).toBeInTheDocument();
  });

  it('switches language after mount and keeps loaded-session prompts hidden until active deletion', async () => {
    const instance = await mount('ru');
    const ru = labels('ru');
    const ar = labels('ar');
    await act(() => instance.changeLanguage('ar'));
    expect(screen.queryByRole('button', { name: ru['chat.suggestion.boq'] })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: ar['chat.suggestion.boq'] })).toBeInTheDocument();
    expect(screen.getByText(ar['chat.history.title']!)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'load-test' }));
    await waitFor(() => expect(screen.getByTestId('session')).toHaveTextContent('s-1'));
    expect(screen.queryByRole('button', { name: ar['chat.suggestion.boq'] })).not.toBeInTheDocument();
    await act(() => instance.changeLanguage('ru'));
    expect(screen.queryByRole('button', { name: ru['chat.suggestion.boq'] })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'delete-test' }));
    await waitFor(() => expect(screen.getByRole('button', { name: ru['chat.suggestion.boq'] })).toBeInTheDocument());
    expect(chatApi.deleteChatSession).toHaveBeenCalledWith('s-1');
  });

  it('ships every history and exact prompt key in every base catalogue', () => {
    const baseLocales = readdirSync(localeDir).filter((name) => name.endsWith('.ts') && !name.includes('-'));
    expect(baseLocales.length).toBeGreaterThanOrEqual(38);
    const en = labels('en');
    for (const file of baseLocales) {
      const locale = file.slice(0, -3);
      const translated = labels(locale);
      expect(Object.keys(translated).sort(), locale).toEqual([...keys].sort());
      for (const key of keys) {
        expect(translated[key]?.trim(), `${locale}:${key}`).toBeTruthy();
        if (locale !== 'en') expect(translated[key], `${locale}:${key}`).not.toBe(en[key]);
      }
    }
  });
});
