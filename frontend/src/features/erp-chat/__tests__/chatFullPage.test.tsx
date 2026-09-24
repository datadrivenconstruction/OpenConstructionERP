// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The full-page chat (/chat) and the assistant's proposed changes. The dock is
// pinned in dockActions.test.tsx; this file holds the same promises for the
// page, which has its own stream loop, its own history loader and a data
// panel on the right that the dock does not have:
//
// - the stream request tells the server the reader's language and the page
//   the question was asked on;
// - a past conversation comes back with its proposals as tool calls that
//   carry the card data, whether the server stored the results as a list or
//   as an object keyed by call id;
// - a proposal is an answer in the conversation, with its buttons, and never
//   an entry of the data panel, neither live nor read back from history;
// - the rebuilt message renders its proposal as the card on the page, and the
//   card re-reads the status it has now;
// - `ToolCallCard` shows a proposal as the proposal card, not as the
//   expandable row with raw JSON that a lookup gets.
//
// Run:  npx vitest run src/features/erp-chat/__tests__/chatFullPage.test.tsx

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, cleanup, render, renderHook, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// The suite-wide mock of react-i18next (src/test/setup.ts) reports 'en' as
// the language, which is also what a hook that ignored the language would be
// expected to send. German here makes the locale assertion able to fail.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (typeof opts === 'object' && opts !== null && typeof opts.defaultValue === 'string') {
        const template =
          'count' in opts && opts.count !== 1 && typeof opts.defaultValue_other === 'string'
            ? opts.defaultValue_other
            : opts.defaultValue;
        return template.replace(/\{\{(\w+)\}\}/g, (_match: string, name: string) =>
          name in opts ? String(opts[name]) : `{{${name}}}`,
        );
      }
      return key;
    },
    i18n: { language: 'de', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: unknown }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

const chatApi = vi.hoisted(() => ({
  fetchChatSessions: vi.fn(),
  fetchSessionMessages: vi.fn(),
  deleteChatSession: vi.fn(),
  submitFeedback: vi.fn(),
}));
vi.mock('../api', () => chatApi);

vi.mock('../actions/api', () => ({
  listChatActions: vi.fn(),
  getChatAction: vi.fn(),
  patchChatAction: vi.fn(),
  applyChatAction: vi.fn(),
  rejectChatAction: vi.fn(),
  applyChatActionsBatch: vi.fn(),
  revertChatAction: vi.fn(),
}));

// The real proposal card, and nothing of the charts and grids of the full
// registry.
vi.mock('../full-page/right/renderers', async () => {
  const { ActionProposalRenderer } = await import('../actions/ActionProposalCard');
  return { RENDERER_REGISTRY: { action_proposal: ActionProposalRenderer } };
});
vi.mock('@/features/ai/api', () => ({
  aiApi: { getSettings: () => Promise.resolve({ ai_ready: true }) },
}));
vi.mock('@/features/ai-estimator/useAiReadiness', () => ({ hasLlmKey: () => true }));

import * as actionsApi from '../actions/api';
import { appliedAction, makeAction } from '../actions/__tests__/fixtures';
import type { ChatAction } from '../actions/types';
import type { ToolCallInfo } from '../types';
import { useChatFullPage } from '../full-page/useChatFullPage';
import ToolCallCard from '../full-page/left/ToolCallCard';
import MessageBubble from '../full-page/left/MessageBubble';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

const now = () => new Date().toISOString();

/** A proposal as it streams in: fresh, so its card needs no re-read. */
function liveProposal(overrides: Partial<ChatAction> = {}): ChatAction {
  const at = now();
  return makeAction({ created_at: at, updated_at: at, ...overrides });
}

/**
 * A `fetch` for the chat stream that answers with the given SSE events in
 * one chunk and then ends.
 */
function stubStream(events: [string, unknown][] = []) {
  const text = events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join('');
  const chunks = [new TextEncoder().encode(text)];
  const reader = {
    read: async () => {
      const value = chunks.shift();
      return value ? { done: false, value } : { done: true, value: undefined };
    },
  };
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => ({
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'text/event-stream' }),
    body: { getReader: () => reader },
    text: async () => '',
  }));
  vi.stubGlobal('fetch', fetchMock);
  return {
    fetchMock,
    body: (n = 0) => JSON.parse(String(fetchMock.mock.calls[n]?.[1]?.body ?? '{}')) as Record<string, unknown>,
  };
}

async function mountHook() {
  const view = renderHook(() => useChatFullPage());
  // The AI-settings probe and the session list settle before anything is sent.
  await waitFor(() => expect(view.result.current.aiConfigured).toBe(true));
  await waitFor(() => expect(view.result.current.sessionsLoading).toBe(false));
  return view;
}

async function send(view: Awaited<ReturnType<typeof mountHook>>, text: string) {
  act(() => view.result.current.sendMessage(text));
  // A finished turn also refreshes the session list; both settle here.
  await waitFor(() => {
    expect(view.result.current.isStreaming).toBe(false);
    expect(view.result.current.sessionsLoading).toBe(false);
  });
}

/** The stored conversation: a lookup and a proposal in one assistant turn. */
function storedConversation(snapshot: ChatAction, toolResults: 'list' | 'dict') {
  const lookup = {
    tool: 'search_boq_positions',
    id: 'c-1',
    result: { renderer: 'semantic_search', data: { hits: ['03.012'] }, summary: '1 position' },
  };
  const proposal = {
    tool: 'propose_update_boq_position',
    id: 'c-2',
    result: { renderer: 'action_proposal', data: snapshot },
  };
  return [
    {
      id: 'm-1',
      session_id: 's-1',
      role: 'user',
      content: 'Set position 03.012 to 120 m3',
      tool_calls: null,
      tool_results: null,
      renderer: null,
      renderer_data: null,
      created_at: '2020-01-01T10:00:00Z',
    },
    {
      id: 'm-2',
      session_id: 's-1',
      role: 'assistant',
      content: 'I prepared the change.',
      tool_calls: [
        { name: 'search_boq_positions', args: { query: 'slab' }, id: 'c-1' },
        { name: 'propose_update_boq_position', args: { quantity: 120 }, id: 'c-2' },
      ],
      tool_results: toolResults === 'list' ? [lookup, proposal] : { 'c-1': lookup, 'c-2': proposal },
      renderer: 'action_proposal',
      renderer_data: snapshot,
      created_at: '2020-01-01T10:00:01Z',
    },
  ];
}

beforeEach(() => {
  useAuthStore.setState({ isAuthenticated: true, accessToken: 'test-token' });
  useProjectContextStore.setState({ activeProjectId: null, activeProjectName: '' });
  chatApi.fetchChatSessions.mockReset().mockResolvedValue({ items: [], total: 0 });
  chatApi.fetchSessionMessages.mockReset();
  chatApi.deleteChatSession.mockReset();
  vi.mocked(actionsApi.getChatAction).mockReset();
  window.history.pushState({}, '', '/chat');
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.pushState({}, '', '/');
});

describe('the /chat page, sending', () => {
  it('tells the server the language and the page the question was asked on', async () => {
    useProjectContextStore.setState({ activeProjectId: 'p-1', activeProjectName: 'Residential House' });
    window.history.pushState({}, '', '/chat/deep-link');
    const stream = stubStream();
    const view = await mountHook();
    await send(view, 'Set position 03.012 to 120 m3');

    expect(stream.fetchMock).toHaveBeenCalledTimes(1);
    expect(stream.fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/erp_chat/stream/');
    expect(stream.body()).toEqual({
      message: 'Set position 03.012 to 120 m3',
      session_id: null,
      project_id: 'p-1',
      locale: 'de',
      client_context: { route: '/chat/deep-link', project_id: 'p-1' },
    });
  });

  it('sends a null project in the context when none is selected', async () => {
    const stream = stubStream();
    const view = await mountHook();
    await send(view, 'Show all projects');
    expect(stream.body().client_context).toEqual({ route: '/chat', project_id: null });
  });
});

describe('the /chat page, a streamed proposal', () => {
  it('stays in the conversation and out of the data panel, where the lookup still goes', async () => {
    const proposal = liveProposal();
    stubStream([
      ['session_id', { session_id: 's-1' }],
      ['tool_start', { tool: 'search_boq_positions', args: { query: 'slab' } }],
      ['tool_result', { tool: 'search_boq_positions', result: { renderer: 'semantic_search', data: { hits: [] }, summary: '1 position' } }],
      ['tool_start', { tool: 'propose_update_boq_position', args: { quantity: 120 } }],
      ['tool_result', { tool: 'propose_update_boq_position', result: { renderer: 'action_proposal', data: proposal, summary: 'Proposed' } }],
      ['text', { content: 'I prepared the change for your review.' }],
      ['done', { message_id: 'm-2' }],
    ]);
    const view = await mountHook();
    await send(view, 'Set position 03.012 to 120 m3');

    const { dataPanelEntries, activePanelIndex, messages } = view.result.current;
    expect(dataPanelEntries.map((e) => e.renderer)).toEqual(['semantic_search']);
    expect(activePanelIndex).toBe(0);

    const answer = messages.find((m) => m.role === 'assistant')!;
    expect(answer.toolCalls?.map((tc) => [tc.name, tc.status, tc.result?.renderer])).toEqual([
      ['search_boq_positions', 'done', 'semantic_search'],
      ['propose_update_boq_position', 'done', 'action_proposal'],
    ]);
    expect((answer.toolCalls?.[1]?.result?.data as ChatAction).id).toBe('act-1');
  });

  it('keeps a refused proposal out of the data panel too', async () => {
    stubStream([
      ['tool_start', { tool: 'propose_create_task', args: {} }],
      ['tool_result', { tool: 'propose_create_task', result: { renderer: 'error', data: { error: 'invalid_arguments', message: 'A task needs a title.' } } }],
    ]);
    const view = await mountHook();
    await send(view, 'Create a task');

    expect(view.result.current.dataPanelEntries).toEqual([]);
    expect(view.result.current.activePanelIndex).toBe(-1);
    const answer = view.result.current.messages.find((m) => m.role === 'assistant')!;
    expect(answer.toolCalls?.[0]?.status).toBe('error');
  });
});

describe('the /chat page, a past conversation', () => {
  it.each(['list', 'dict'] as const)(
    'comes back with its proposal as a tool call carrying the card data (results stored as a %s)',
    async (shape) => {
      chatApi.fetchSessionMessages.mockResolvedValue(storedConversation(makeAction(), shape));
      const view = await mountHook();
      await act(async () => {
        await view.result.current.loadSession('s-1');
      });

      expect(chatApi.fetchSessionMessages).toHaveBeenCalledWith('s-1');
      const { messages, sessionId } = view.result.current;
      expect(sessionId).toBe('s-1');
      expect(messages.map((m) => [m.role, m.content])).toEqual([
        ['user', 'Set position 03.012 to 120 m3'],
        ['assistant', 'I prepared the change.'],
      ]);
      const calls = messages[1]!.toolCalls ?? [];
      expect(calls.map((tc) => [tc.name, tc.status, tc.result?.renderer])).toEqual([
        ['search_boq_positions', 'done', 'semantic_search'],
        ['propose_update_boq_position', 'done', 'action_proposal'],
      ]);
      expect(calls[1]!.input).toEqual({ quantity: 120 });
      expect((calls[1]!.result?.data as ChatAction).id).toBe('act-1');
    },
  );

  it('renders the rebuilt proposal as its card in the message, showing the status it has now', async () => {
    // Stored while it waited; applied since. The card re-reads it on mount.
    const snapshot = makeAction({ created_at: '2020-01-01T10:00:00Z', updated_at: '2020-01-01T10:00:00Z' });
    vi.mocked(actionsApi.getChatAction).mockResolvedValue(appliedAction({ updated_at: '2020-01-02T09:00:00Z' }));
    chatApi.fetchSessionMessages.mockResolvedValue(storedConversation(snapshot, 'dict'));
    const view = await mountHook();
    await act(async () => {
      await view.result.current.loadSession('s-1');
    });

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
    });
    const page = render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <MessageBubble message={view.result.current.messages[1]!} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const card = () => document.getElementById('erp-chat-action-act-1');
    expect(card()).not.toBeNull();
    expect(page.container.textContent).toContain('I prepared the change.');
    await waitFor(() => expect(card()!.getAttribute('data-action-status')).toBe('applied'));
    expect(actionsApi.getChatAction).toHaveBeenCalledWith('act-1');
  });

  it('keeps its proposal out of the data panel and shows the turn lookup there instead', async () => {
    chatApi.fetchSessionMessages.mockResolvedValue(storedConversation(makeAction(), 'dict'));
    const view = await mountHook();
    await act(async () => {
      await view.result.current.loadSession('s-1');
    });

    const { dataPanelEntries, activePanelIndex } = view.result.current;
    expect(dataPanelEntries).toHaveLength(1);
    expect(dataPanelEntries[0]).toMatchObject({
      renderer: 'semantic_search',
      toolName: 'search_boq_positions',
      data: { hits: ['03.012'] },
      summary: '1 position',
    });
    expect(activePanelIndex).toBe(0);
  });

  it('leaves the data panel empty for a turn that only proposed', async () => {
    const snapshot = makeAction();
    chatApi.fetchSessionMessages.mockResolvedValue([
      {
        id: 'm-2',
        session_id: 's-1',
        role: 'assistant',
        content: 'I prepared the change.',
        tool_calls: [{ name: 'propose_update_boq_position', args: { quantity: 120 }, id: 'c-2' }],
        tool_results: [{ tool: 'propose_update_boq_position', id: 'c-2', result: { renderer: 'action_proposal', data: snapshot } }],
        renderer: 'action_proposal',
        renderer_data: snapshot,
        created_at: '2020-01-01T10:00:01Z',
      },
    ]);
    const view = await mountHook();
    await act(async () => {
      await view.result.current.loadSession('s-1');
    });

    expect(view.result.current.messages[0]!.toolCalls?.[0]?.result?.renderer).toBe('action_proposal');
    expect(view.result.current.dataPanelEntries).toEqual([]);
    expect(view.result.current.activePanelIndex).toBe(-1);
  });
});

describe('ToolCallCard on /chat', () => {
  function renderCard(tool: ToolCallInfo) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
    });
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <ToolCallCard tool={tool} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it('renders a proposal as the proposal card, with no raw payload row', () => {
    const view = renderCard({
      id: 't-1',
      name: 'propose_update_boq_position',
      status: 'done',
      input: { quantity: 120 },
      result: { renderer: 'action_proposal', data: liveProposal(), summary: 'Proposed' },
      startedAt: 0,
    });
    const card = document.getElementById('erp-chat-action-act-1');
    expect(card).not.toBeNull();
    expect(card!.getAttribute('data-action-status')).toBe('proposed');
    expect(view.container.textContent).toContain('Set position 03.012 to 120 m3');
    // The expandable INPUT / OUTPUT row is what a lookup gets, not a proposal:
    // every toggle on screen belongs to the card itself.
    const toggles = Array.from(view.container.querySelectorAll('button[aria-expanded]'));
    expect(toggles.every((b) => card!.contains(b))).toBe(true);
    expect(view.container.textContent).not.toContain('"quantity"');
  });

  it('renders a lookup as the closed row that expands onto its data (the control)', () => {
    const view = renderCard({
      id: 't-2',
      name: 'search_boq_positions',
      status: 'done',
      result: { renderer: 'semantic_search', data: { hits: [] }, summary: '1 position' },
      startedAt: 0,
    });
    expect(document.querySelector('[id^="erp-chat-action-"]')).toBeNull();
    const toggle = view.container.querySelector('button[aria-expanded]');
    expect(toggle).not.toBeNull();
    expect(toggle!.getAttribute('aria-expanded')).toBe('false');
    expect(view.container.textContent).toContain('BOQ position search');
  });

  it('names a refused proposal as a change not prepared, with the reason for people', () => {
    const view = renderCard({
      id: 't-3',
      name: 'propose_create_task',
      status: 'error',
      result: { renderer: 'error', data: { error: 'invalid_arguments', message: 'A task needs a title.' } },
      startedAt: 0,
    });
    expect(document.querySelector('[id^="erp-chat-action-"]')).toBeNull();
    expect(view.container.textContent).toContain('Change not prepared: Create a task');
    expect(view.container.textContent).toContain('A task needs a title.');
  });
});
