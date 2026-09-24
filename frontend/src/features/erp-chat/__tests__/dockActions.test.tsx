// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The dock as the place where the assistant's proposed changes are reviewed:
// the Chat / Changes tabs, the proposal cards and the review tray a streamed
// proposal brings, what the stream request tells the server, a past
// conversation read back with its cards, and the round button counting what
// waits while the dock is closed.
//
// The layout and focus mechanics of the dock itself are pinned in
// dockPanel.test.tsx; this file checks what sits inside it.
//
// Run:  npx vitest run src/features/erp-chat/__tests__/dockActions.test.tsx

import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const chatApi = vi.hoisted(() => ({
  fetchChatSessions: vi.fn(),
  fetchSessionMessages: vi.fn(),
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

// The real proposal card (it is what this file is about) and one stand-in
// lookup renderer; the charts and grids of the full registry stay out.
vi.mock('../full-page/right/renderers', async () => {
  const { ActionProposalRenderer } = await import('../actions/ActionProposalCard');
  return {
    RENDERER_REGISTRY: {
      action_proposal: ActionProposalRenderer,
      semantic_search: () => <div data-testid="lookup-renderer">3 positions found</div>,
    },
  };
});
vi.mock('@/features/ai/api', () => ({
  aiApi: { getSettings: () => Promise.resolve({ ai_ready: true }) },
}));
vi.mock('@/features/ai-estimator/useAiReadiness', () => ({ hasLlmKey: () => true }));

import * as actionsApi from '../actions/api';
import { appliedAction, makeAction } from '../actions/__tests__/fixtures';
import type { ChatAction } from '../actions/types';

type PanelModule = typeof import('../FloatingChatPanel');
type ButtonModule = typeof import('../FloatingChatButton');
type StoreModule = typeof import('../useFloatingChat');
type ActionStoreModule = typeof import('../actions/useChatActions');
type ProjectStoreModule = typeof import('@/stores/useProjectContextStore');

let FloatingChatPanel: PanelModule['FloatingChatPanel'];
let FloatingChatButton: ButtonModule['FloatingChatButton'];
let store: StoreModule;
let actionStore: ActionStoreModule;
let projectStore: ProjectStoreModule;

let reducedMotion = false;

beforeAll(async () => {
  window.matchMedia = ((query: string) => ({
    matches: query.includes('prefers-reduced-motion') ? reducedMotion : false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
  ({ FloatingChatPanel } = await import('../FloatingChatPanel'));
  ({ FloatingChatButton } = await import('../FloatingChatButton'));
  store = await import('../useFloatingChat');
  actionStore = await import('../actions/useChatActions');
  projectStore = await import('@/stores/useProjectContextStore');
  const { useAuthStore } = await import('@/stores/useAuthStore');
  useAuthStore.setState({ isAuthenticated: true, accessToken: 'test-token' });
  // A cold transform of the panel's module graph next to a parallel suite
  // takes minutes (see dockPanel.test.tsx).
}, 300_000);

function setViewport(width: number) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: width });
  window.dispatchEvent(new Event('resize'));
}

const now = () => new Date().toISOString();

/** A proposal as it streams in: fresh, so its card needs no re-read. */
function liveProposal(overrides: Partial<ChatAction> = {}): ChatAction {
  const at = now();
  return makeAction({ created_at: at, updated_at: at, ...overrides });
}

beforeEach(() => {
  reducedMotion = false;
  setViewport(1600);
  document.documentElement.dir = 'ltr';
  store.useFloatingChatStore.setState({
    isOpen: false,
    activeSessionId: null,
    pendingPrompt: null,
    width: store.DOCK_DEFAULT_WIDTH,
    conversationActionIds: [],
    unreadCount: 0,
  });
  actionStore.useChatActionStore.getState().reset();
  projectStore.useProjectContextStore.setState({ activeProjectId: null, activeProjectName: '' });
  chatApi.fetchChatSessions.mockReset().mockResolvedValue({ items: [], total: 0 });
  chatApi.fetchSessionMessages.mockReset();
  vi.mocked(actionsApi.listChatActions).mockReset().mockResolvedValue({
    items: [],
    total: 0,
    counts: { proposed: 0, applied: 0, rejected: 0, failed: 0, reverted: 0 },
  });
  vi.mocked(actionsApi.getChatAction).mockReset();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  document.documentElement.dir = '';
});

// ── The stream, controlled by the test ─────────────────────────────────────

/**
 * A `fetch` for the chat stream whose SSE events the test pushes one by one,
 * so it can act between them (close the dock, look at the tray).
 */
function stubStream() {
  const encoder = new TextEncoder();
  const queue: { done: boolean; value?: Uint8Array }[] = [];
  let wake: (() => void) | null = null;
  const flush = () => {
    const w = wake;
    wake = null;
    w?.();
  };
  const reader = {
    read: () =>
      new Promise<{ done: boolean; value?: Uint8Array }>((resolve) => {
        const next = () => {
          const item = queue.shift();
          if (item) resolve(item);
          else wake = next;
        };
        next();
      }),
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
    /** The JSON body of the n-th stream request. */
    body: (n = 0) => JSON.parse(String(fetchMock.mock.calls[n]?.[1]?.body ?? '{}')) as Record<string, unknown>,
    push: async (event: string, data: unknown) => {
      queue.push({ done: false, value: encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`) });
      await act(async () => {
        flush();
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    },
    end: async () => {
      queue.push({ done: true });
      await act(async () => {
        flush();
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    },
  };
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

async function mount({ path = '/', open = true }: { path?: string; open?: boolean } = {}) {
  if (open) store.useFloatingChatStore.setState({ isOpen: true });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <LocationProbe />
        <FloatingChatButton />
        <FloatingChatPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  // Let the settings probe land and the composer's opening focus run.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 120));
  });
  const q = <T extends HTMLElement = HTMLElement>(sel: string) =>
    document.querySelector<T>(sel);
  const byTestId = <T extends HTMLElement = HTMLElement>(id: string) => q<T>(`[data-testid="${id}"]`);
  return {
    view,
    q,
    byTestId,
    composer: () => byTestId<HTMLTextAreaElement>('floating-chat-input')!,
    send: async (text: string) => {
      const composer = byTestId<HTMLTextAreaElement>('floating-chat-input')!;
      fireEvent.change(composer, { target: { value: text } });
      fireEvent.click(byTestId('floating-chat-send')!);
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    },
  };
}

// ── Tabs ───────────────────────────────────────────────────────────────────

describe('the Chat and Changes tabs', () => {
  it('are a labelled tablist whose tabs control panels that exist', async () => {
    const ui = await mount();
    const tablist = ui.q('[role="tablist"]')!;
    expect(tablist.getAttribute('aria-label')).toBe('Assistant views');
    const tabs = Array.from(tablist.querySelectorAll<HTMLElement>('[role="tab"]'));
    expect(tabs.map((tab) => tab.textContent)).toEqual(['Chat', 'Changes']);
    for (const tab of tabs) {
      const panel = document.getElementById(tab.getAttribute('aria-controls') ?? '');
      expect(panel?.getAttribute('role')).toBe('tabpanel');
      expect(panel?.getAttribute('aria-labelledby')).toBe(tab.id);
    }
    expect(tabs[0]!.getAttribute('aria-selected')).toBe('true');
    expect(tabs[0]!.tabIndex).toBe(0);
    expect(tabs[1]!.tabIndex).toBe(-1);
  });

  it('asks for the Changes list only when that tab is first opened, then keeps it', async () => {
    const ui = await mount();
    expect(ui.byTestId('changes-view')).toBeNull();
    expect(actionsApi.listChatActions).not.toHaveBeenCalled();

    fireEvent.click(ui.byTestId('floating-chat-tab-changes')!);
    await waitFor(() => expect(actionsApi.listChatActions).toHaveBeenCalledTimes(1));
    expect(ui.byTestId('changes-view')).not.toBeNull();
    expect(ui.byTestId('floating-chat-chat-panel')!.hidden).toBe(true);
    expect(ui.byTestId('floating-chat-changes-panel')!.hidden).toBe(false);

    fireEvent.click(ui.byTestId('floating-chat-tab-chat')!);
    expect(ui.byTestId('floating-chat-chat-panel')!.hidden).toBe(false);
    expect(ui.byTestId('floating-chat-changes-panel')!.hidden).toBe(true);
    // Still mounted, filters and all, and not asked again.
    expect(ui.byTestId('changes-view')).not.toBeNull();
    fireEvent.click(ui.byTestId('floating-chat-tab-changes')!);
    await act(async () => {
      await Promise.resolve();
    });
    expect(actionsApi.listChatActions).toHaveBeenCalledTimes(1);
  });

  it('move with the arrow keys, and focus moves with the selection', async () => {
    const ui = await mount();
    const chatTab = ui.byTestId('floating-chat-tab-chat')!;
    chatTab.focus();
    fireEvent.keyDown(chatTab, { key: 'ArrowRight' });
    const changesTab = ui.byTestId('floating-chat-tab-changes')!;
    expect(changesTab.getAttribute('aria-selected')).toBe('true');
    expect(document.activeElement).toBe(changesTab);
    fireEvent.keyDown(changesTab, { key: 'Home' });
    expect(chatTab.getAttribute('aria-selected')).toBe('true');
    expect(document.activeElement).toBe(chatTab);
  });

  it('name the active project, and the chip opens it', async () => {
    projectStore.useProjectContextStore.setState({ activeProjectId: 'p-1', activeProjectName: 'Residential House' });
    const ui = await mount();
    const chip = ui.byTestId('floating-chat-project-chip')!;
    expect(chip.textContent).toBe('Residential House');
    expect(chip.getAttribute('aria-label')).toBe('Open project Residential House');
    fireEvent.click(chip);
    expect(ui.byTestId('location')!.textContent).toBe('/projects/p-1');
  });

  it('say so when no project is selected', async () => {
    const ui = await mount();
    const chip = ui.byTestId('floating-chat-project-chip')!;
    expect(chip.textContent).toBe('No project selected');
    expect(chip.getAttribute('data-has-project')).toBe('false');
  });
});

// ── The empty state ────────────────────────────────────────────────────────

describe('the empty state', () => {
  it('fills the composer with an example instruction instead of sending it', async () => {
    const stream = stubStream();
    const ui = await mount({ path: '/boq/boq-9' });
    const example = ui.byTestId('floating-chat-suggestion-do-0')!;
    expect(example.textContent).toContain('Add a position');
    fireEvent.click(example);
    expect(ui.composer().value).toBe(example.textContent);
    expect(stream.fetchMock).not.toHaveBeenCalled();
  });

  it('keeps the page questions above the ones that work anywhere, and sends them at once', async () => {
    const stream = stubStream();
    const ui = await mount({ path: '/boq/boq-9' });
    const label = ui.byTestId('floating-chat-contextual-label')!;
    const generic = ui.byTestId('floating-chat-suggestion-generic-0')!;
    expect(label.compareDocumentPosition(generic) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(ui.byTestId('floating-chat-suggestion-generic-5')).not.toBeNull();
    fireEvent.click(ui.byTestId('floating-chat-suggestion-ctx-0')!);
    await act(async () => {
      await Promise.resolve();
    });
    expect(stream.fetchMock).toHaveBeenCalledTimes(1);
  });

  it('locks no suggestion for any role', async () => {
    // A viewer: the old lock greyed out every example that read like a write
    // for anyone below manager.
    const { useAuthStore } = await import('@/stores/useAuthStore');
    useAuthStore.setState({ userRole: 'viewer' });
    try {
      const ui = await mount({ path: '/projects/p-1' });
      const chips = Array.from(document.querySelectorAll('[data-testid^="floating-chat-suggestion-"]'));
      expect(chips.length).toBeGreaterThan(0);
      for (const chip of chips) {
        expect(chip.getAttribute('aria-disabled')).toBeNull();
        expect(chip.getAttribute('data-locked')).toBeNull();
      }
      expect(ui.byTestId('floating-chat-do-chips')!.textContent).toContain('Create a task');
    } finally {
      useAuthStore.setState({ userRole: null });
    }
  });
});

// ── The stream ─────────────────────────────────────────────────────────────

describe('a message to the assistant', () => {
  it('tells the server the language and the page it was sent from', async () => {
    projectStore.useProjectContextStore.setState({ activeProjectId: 'p-1', activeProjectName: 'Residential House' });
    const stream = stubStream();
    const ui = await mount({ path: '/boq/boq-9' });
    await ui.send('Set position 03.012 to 120 m3');
    expect(stream.fetchMock).toHaveBeenCalledTimes(1);
    expect(stream.fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/erp_chat/stream/');
    expect(stream.body()).toEqual({
      message: 'Set position 03.012 to 120 m3',
      session_id: null,
      project_id: 'p-1',
      locale: 'en',
      client_context: { route: '/boq/boq-9', project_id: 'p-1' },
    });
    await stream.end();
  });

  it('starts a new conversation after a reload instead of continuing one the person cannot see', async () => {
    // What a reload leaves behind: the store names the last conversation, the transcript is gone.
    store.useFloatingChatStore.setState({ activeSessionId: 's-old' });
    const stream = stubStream();
    const ui = await mount();
    await ui.send('Add a task for the site team');
    expect(stream.body().session_id).toBeNull();
    await stream.push('session_id', { session_id: 's-new' });
    expect(store.useFloatingChatStore.getState().activeSessionId).toBe('s-new');
    await stream.end();
    expect(chatApi.fetchSessionMessages).not.toHaveBeenCalled();
  });

  it('shows a streamed proposal as its card and pins the review tray above the composer', async () => {
    const stream = stubStream();
    const ui = await mount();
    await ui.send('Set position 03.012 to 120 m3');
    await stream.push('session_id', { session_id: 's-1' });
    await stream.push('tool_start', { tool: 'propose_update_boq_position', args: { quantity: 120 } });
    expect(document.body.textContent).toContain('Preparing a change: Change a BOQ position');
    await stream.push('tool_result', {
      tool: 'propose_update_boq_position',
      result: { renderer: 'action_proposal', data: liveProposal(), summary: 'Proposed: Update BOQ position' },
    });
    await stream.push('text', { content: 'I prepared the change for your review.' });
    await stream.end();

    const card = document.getElementById('erp-chat-action-act-1');
    expect(card).not.toBeNull();
    expect(card!.getAttribute('data-action-status')).toBe('proposed');
    // The card, not its payload.
    expect(document.body.textContent).not.toContain('"action_type"');

    const tray = ui.byTestId('actions-review-tray')!;
    expect(tray).not.toBeNull();
    expect(ui.byTestId('actions-review-tray-count')!.textContent).toBe('1 change is waiting for your review');
    // Between the transcript and the composer.
    const transcript = ui.byTestId('floating-chat-transcript')!;
    expect(transcript.compareDocumentPosition(tray) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(tray.compareDocumentPosition(ui.composer()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(ui.byTestId('floating-chat-changes-count')!.textContent).toBe('1');

    // Review takes the reader to the waiting card.
    fireEvent.click(ui.byTestId('actions-review-tray-review')!);
    expect(document.activeElement).toBe(card);
  });

  it('drops the tray once the change is decided, wherever that happened', async () => {
    const stream = stubStream();
    const ui = await mount();
    await ui.send('Set position 03.012 to 120 m3');
    await stream.push('tool_start', { tool: 'propose_update_boq_position', args: {} });
    const proposal = liveProposal();
    await stream.push('tool_result', {
      tool: 'propose_update_boq_position',
      result: { renderer: 'action_proposal', data: proposal },
    });
    await stream.end();
    expect(ui.byTestId('actions-review-tray')).not.toBeNull();
    act(() => {
      actionStore.useChatActionStore
        .getState()
        .upsert(appliedAction({ updated_at: new Date(Date.parse(proposal.updated_at) + 1000).toISOString() }));
    });
    expect(ui.byTestId('actions-review-tray')).toBeNull();
    expect(ui.byTestId('floating-chat-changes-count')).toBeNull();
  });

  it('shows a refused proposal as a calm row with the reason, not as an error of the chat', async () => {
    const stream = stubStream();
    const ui = await mount();
    await ui.send('Add a task');
    await stream.push('tool_start', { tool: 'propose_create_task', args: {} });
    await stream.push('tool_result', {
      tool: 'propose_create_task',
      result: {
        renderer: 'error',
        data: { error: 'invalid_arguments', message: 'A task needs a title.', i18n_key: 'erp_chat.action.error.test_only' },
        summary: 'Error: A task needs a title. Nothing was proposed; fix the arguments or ask the user, then call the tool again.',
      },
    });
    await stream.push('text', { content: 'What should the task be called?' });
    await stream.end();

    expect(ui.byTestId('floating-chat-error-card')).toBeNull();
    const row = ui.q('[data-testid="floating-chat-tool"][data-tool="propose_create_task"]')!;
    expect(row.getAttribute('data-tool-status')).toBe('error');
    expect(row.textContent).toContain('Change not prepared: Create a task');
    expect(row.textContent).toContain('A task needs a title.');
    // The instruction meant for the model stays with the model.
    expect(row.textContent).not.toContain('call the tool again');
  });

  it('shows a lookup as one closed line that opens onto what was found', async () => {
    const stream = stubStream();
    const ui = await mount();
    await ui.send('Find the slab positions');
    await stream.push('tool_start', { tool: 'search_boq_positions', args: { query: 'slab' } });
    await stream.push('tool_result', {
      tool: 'search_boq_positions',
      result: { renderer: 'semantic_search', data: { hits: [] }, summary: '3 positions' },
    });
    await stream.end();

    const row = ui.q('[data-testid="floating-chat-tool"][data-tool="search_boq_positions"]')!;
    const toggle = row.querySelector('button')!;
    expect(toggle.textContent).toContain('Looked up: BOQ position search');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(ui.byTestId('lookup-renderer')).toBeNull();
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(ui.byTestId('lookup-renderer')).not.toBeNull();
  });
});

// ── The round button ───────────────────────────────────────────────────────

describe('the round button while the dock is closed', () => {
  it('counts a proposal that arrived after the dock was closed, apart from the unread badge', async () => {
    // The dock leaves at once, so the proposal lands in a closed dock.
    reducedMotion = true;
    const stream = stubStream();
    const ui = await mount();
    await ui.send('Set position 03.012 to 120 m3');
    act(() => store.useFloatingChatStore.getState().close());
    expect(ui.byTestId('floating-chat-panel')).toBeNull();

    await stream.push('tool_start', { tool: 'propose_update_boq_position', args: {} });
    const proposal = liveProposal();
    await stream.push('tool_result', {
      tool: 'propose_update_boq_position',
      result: { renderer: 'action_proposal', data: proposal },
    });
    await stream.end();

    const badge = ui.byTestId('floating-chat-pending-badge')!;
    expect(badge).not.toBeNull();
    expect(badge.textContent).toBe('1');
    expect(badge.getAttribute('aria-label')).toBe('1 change is waiting for your review');
    const fab = ui.byTestId('floating-chat-button')!;
    expect(fab.getAttribute('aria-describedby')).toBe(badge.id);
    // The finished answer is also unread; the two badges stay apart.
    const unread = fab.querySelector('[aria-label="1 new"]');
    expect(unread).not.toBeNull();
    expect(unread).not.toBe(badge);

    // Applied from elsewhere (the Changes view of another tab): no longer waiting.
    act(() => {
      actionStore.useChatActionStore
        .getState()
        .upsert(appliedAction({ updated_at: new Date(Date.parse(proposal.updated_at) + 1000).toISOString() }));
    });
    expect(ui.byTestId('floating-chat-pending-badge')).toBeNull();
  });

  it('shows no pending badge while the dock is open', async () => {
    const stream = stubStream();
    const ui = await mount();
    await ui.send('Set position 03.012 to 120 m3');
    await stream.push('tool_start', { tool: 'propose_update_boq_position', args: {} });
    await stream.push('tool_result', {
      tool: 'propose_update_boq_position',
      result: { renderer: 'action_proposal', data: liveProposal() },
    });
    await stream.end();
    expect(ui.byTestId('floating-chat-pending-badge')).toBeNull();
  });
});

// ── Following a link out of the dock ───────────────────────────────────────

describe("an applied change's Open", () => {
  async function openAppliedChange(width: number) {
    setViewport(width);
    const stream = stubStream();
    const ui = await mount();
    await ui.send('Set position 03.012 to 120 m3');
    await stream.push('tool_start', { tool: 'propose_update_boq_position', args: {} });
    const proposal = liveProposal();
    await stream.push('tool_result', {
      tool: 'propose_update_boq_position',
      result: { renderer: 'action_proposal', data: proposal },
    });
    await stream.end();
    act(() => {
      actionStore.useChatActionStore
        .getState()
        .upsert(appliedAction({ updated_at: new Date(Date.parse(proposal.updated_at) + 1000).toISOString() }));
    });
    fireEvent.click(ui.byTestId('action-open')!);
    await act(async () => {
      await Promise.resolve();
    });
    return ui;
  }

  it('takes the overlay out of the way of the page it opens', async () => {
    const ui = await openAppliedChange(700);
    expect(ui.byTestId('location')!.textContent).toBe('/boq/boq-9');
    expect(store.useFloatingChatStore.getState().isOpen).toBe(false);
  });

  it('leaves a docked panel open, the page is visible beside it', async () => {
    const ui = await openAppliedChange(1600);
    expect(ui.byTestId('location')!.textContent).toBe('/boq/boq-9');
    expect(store.useFloatingChatStore.getState().isOpen).toBe(true);
  });
});

// ── Confirmations over the dock ────────────────────────────────────────────

describe('the Apply-all confirmation', () => {
  it('is a modal the dock yields to: Escape closes it and leaves the dock open', async () => {
    const stream = stubStream();
    const ui = await mount();
    await ui.send('Two changes please');
    for (const id of ['act-1', 'act-2']) {
      await stream.push('tool_start', { tool: 'propose_update_boq_position', args: {} });
      await stream.push('tool_result', {
        tool: 'propose_update_boq_position',
        result: { renderer: 'action_proposal', data: liveProposal({ id }) },
      });
    }
    await stream.end();
    expect(ui.byTestId('actions-review-tray-count')!.textContent).toBe('2 changes are waiting for your review');

    fireEvent.click(ui.byTestId('actions-review-tray-apply-all')!);
    const confirm = document.querySelector<HTMLElement>('[role="alertdialog"]')!;
    expect(confirm).not.toBeNull();
    expect(confirm.getAttribute('aria-modal')).toBe('true');

    // Alt+A does not pull focus out from under it (it would land in the composer).
    const focused = document.activeElement;
    expect(confirm.contains(focused)).toBe(true);
    fireEvent.keyDown(document.body, { key: 'a', code: 'KeyA', altKey: true });
    expect(document.activeElement).toBe(focused);

    fireEvent.keyDown(confirm, { key: 'Escape' });
    expect(document.querySelector('[role="alertdialog"]')).toBeNull();
    expect(store.useFloatingChatStore.getState().isOpen).toBe(true);
    expect(actionsApi.applyChatActionsBatch).not.toHaveBeenCalled();
  });
});

// ── History ────────────────────────────────────────────────────────────────

/** Yesterday's conversation, stored with its results keyed by call id. */
function storedConversation(snapshot: ChatAction) {
  return [
    // Stored in the same flush as the question: same timestamp, listed first.
    {
      id: 'm-2',
      session_id: 's-1',
      role: 'assistant',
      content: 'I prepared the change.',
      tool_calls: [
        { name: 'search_boq_positions', args: { query: 'slab' }, id: 'c-1' },
        { name: 'propose_update_boq_position', args: { quantity: 120 }, id: 'c-2' },
      ],
      tool_results: {
        'c-1': { tool: 'search_boq_positions', id: 'c-1', result: { renderer: 'semantic_search', data: { hits: [] }, summary: '1 position' } },
        'c-2': { tool: 'propose_update_boq_position', id: 'c-2', result: { renderer: 'action_proposal', data: snapshot } },
      },
      renderer: 'action_proposal',
      renderer_data: snapshot,
      tokens_used: 0,
      created_at: '2020-01-01T10:00:00Z',
    },
    {
      id: 'm-1',
      session_id: 's-1',
      role: 'user',
      content: 'Set position 03.012 to 120 m3',
      tool_calls: null,
      tool_results: null,
      renderer: null,
      renderer_data: null,
      tokens_used: 0,
      created_at: '2020-01-01T10:00:00Z',
    },
  ];
}

async function pickStoredSession(ui: Awaited<ReturnType<typeof mount>>) {
  fireEvent.click(ui.byTestId('floating-chat-sessions-toggle')!);
  await act(async () => {
    await Promise.resolve();
  });
  fireEvent.click(ui.byTestId('floating-chat-session-s-1')!);
}

describe('a past conversation', () => {
  beforeEach(() => {
    chatApi.fetchChatSessions.mockResolvedValue({
      items: [
        { id: 's-1', project_id: 'p-1', title: 'Level 3 slab', created_at: '2020-01-01T10:00:00Z', updated_at: '2020-01-01T10:00:00Z' },
      ],
      total: 1,
    });
  });

  it('comes back with its messages in order and its proposal as a card showing the current status', async () => {
    // Stored while it waited; applied since. The card re-reads it.
    const snapshot = makeAction({ created_at: '2020-01-01T10:00:00Z', updated_at: '2020-01-01T10:00:00Z' });
    vi.mocked(actionsApi.getChatAction).mockResolvedValue(appliedAction({ updated_at: '2020-01-02T09:00:00Z' }));
    let resolveRows: (rows: unknown[]) => void = () => {};
    chatApi.fetchSessionMessages.mockReturnValue(
      new Promise<unknown[]>((resolve) => {
        resolveRows = resolve;
      }),
    );
    const ui = await mount();
    await pickStoredSession(ui);

    expect(chatApi.fetchSessionMessages).toHaveBeenCalledWith('s-1');
    expect(ui.byTestId('floating-chat-history-loading')).not.toBeNull();
    expect(ui.composer().disabled).toBe(true);
    expect(store.useFloatingChatStore.getState().activeSessionId).toBe('s-1');

    await act(async () => {
      resolveRows(storedConversation(snapshot));
      await Promise.resolve();
    });

    expect(ui.byTestId('floating-chat-history-loading')).toBeNull();
    expect(ui.composer().disabled).toBe(false);
    const text = ui.byTestId('floating-chat-transcript')!.textContent ?? '';
    expect(text.indexOf('Set position 03.012 to 120 m3')).toBeGreaterThanOrEqual(0);
    expect(text.indexOf('Set position 03.012 to 120 m3')).toBeLessThan(text.indexOf('I prepared the change.'));
    expect(text).toContain('Looked up: BOQ position search');

    const card = () => document.getElementById('erp-chat-action-act-1');
    expect(card()).not.toBeNull();
    await waitFor(() => expect(card()!.getAttribute('data-action-status')).toBe('applied'));
    expect(actionsApi.getChatAction).toHaveBeenCalledWith('act-1');
    // Nothing waits any more, so nothing asks for review.
    expect(ui.byTestId('actions-review-tray')).toBeNull();
  });

  it('says when it could not be loaded, and tries again on request', async () => {
    chatApi.fetchSessionMessages.mockRejectedValueOnce(new Error('503'));
    const ui = await mount();
    await pickStoredSession(ui);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(ui.byTestId('floating-chat-history-error')).not.toBeNull();

    chatApi.fetchSessionMessages.mockResolvedValueOnce([
      { id: 'm-1', session_id: 's-1', role: 'user', content: 'Hello again', created_at: '2020-01-01T10:00:00Z' },
    ]);
    fireEvent.click(ui.byTestId('floating-chat-history-retry')!);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(ui.byTestId('floating-chat-history-error')).toBeNull();
    expect(ui.byTestId('floating-chat-transcript')!.textContent).toContain('Hello again');
    expect(chatApi.fetchSessionMessages).toHaveBeenCalledTimes(2);
  });
});
