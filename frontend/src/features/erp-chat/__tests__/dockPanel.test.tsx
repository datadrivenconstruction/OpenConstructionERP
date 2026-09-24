// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Behaviour of the AI dock as a component: which mode it renders in, what it
// tells the page, when Escape and Alt+A act, how it leaves, and how the
// resize handle answers the keyboard. The arithmetic behind the modes is
// pinned separately in dockGeometry.test.ts; this file checks the wiring.
//
// jsdom notes: `innerWidth` defaults to 1024 (overlay with the full
// sidebar), so each test sets the width it needs and fires `resize`. jsdom
// never fires `animationend`, which is exactly the case the exit fallback
// timer exists for. The drag arithmetic is pinned by the pure
// `widthFromDrag` tests; the pointer tests here check the wiring (preview,
// resize mode on <html>, one commit on release) with MouseEvents that carry
// a pointer id and a hand-run frame queue.
//
// Run:  npx vitest run src/features/erp-chat/__tests__/dockPanel.test.tsx

import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { act, cleanup, fireEvent, render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// The renderer registry pulls in charts, grids and viewers that no assertion
// here reaches; the two network calls are stubbed so the panel settles.
vi.mock('../full-page/right/renderers', () => ({ RENDERER_REGISTRY: {} }));
vi.mock('../api', () => ({
  fetchChatSessions: () => Promise.resolve({ items: [], total: 0 }),
}));
vi.mock('@/features/ai/api', () => ({
  aiApi: { getSettings: () => Promise.resolve({ ai_ready: true }) },
}));
vi.mock('@/features/ai-estimator/useAiReadiness', () => ({ hasLlmKey: () => true }));

type PanelModule = typeof import('../FloatingChatPanel');
type ButtonModule = typeof import('../FloatingChatButton');
type StoreModule = typeof import('../useFloatingChat');

let FloatingChatPanel: PanelModule['FloatingChatPanel'];
let FloatingChatButton: ButtonModule['FloatingChatButton'];
let store: StoreModule;

let reducedMotion = false;

function installMatchMedia() {
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
}

beforeAll(async () => {
  installMatchMedia();
  ({ FloatingChatPanel } = await import('../FloatingChatPanel'));
  ({ FloatingChatButton } = await import('../FloatingChatButton'));
  store = await import('../useFloatingChat');
  const { useAuthStore } = await import('@/stores/useAuthStore');
  useAuthStore.setState({ isAuthenticated: true, accessToken: 'test-token' });
  // The panel module graph is large (DOMPurify brings a DOM of its own); a
  // cold transform next to a full parallel suite takes minutes, far past
  // the default 10s hook timeout.
}, 300_000);

function setViewport(width: number) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: width });
  window.dispatchEvent(new Event('resize'));
}

const root = () => document.documentElement;
const offset = () => root().style.getPropertyValue('--oe-ai-dock-offset');
const widgetOffset = () => root().style.getPropertyValue('--oe-ai-dock-widget-offset');

beforeEach(() => {
  reducedMotion = false;
  setViewport(1600);
  root().dir = 'ltr';
  root().style.removeProperty('--oe-sidebar-width');
  store.useFloatingChatStore.setState({
    isOpen: false,
    activeSessionId: null,
    pendingPrompt: null,
    width: store.DOCK_DEFAULT_WIDTH,
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  root().dir = '';
});

/** Let the panel's 80ms "focus the composer after opening" timer run out. */
async function settleOpeningFocus() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 150));
  });
}

/**
 * Let the AI-settings probe that every opening starts come back. The panel
 * asks `aiApi.getSettings()` each time the dock opens, and the answer sets
 * state one microtask after the event that opened it, outside that event's
 * act(). A test that opens the dock and stops there leaves the answer to
 * land after its last assertion, and React reports it as an update not
 * wrapped in act().
 */
async function settleAiProbe() {
  await act(async () => {
    await Promise.resolve();
  });
}

async function mount({
  path = '/',
  open = true,
  settle = true,
}: { path?: string; open?: boolean; settle?: boolean } = {}) {
  if (open) store.useFloatingChatStore.setState({ isOpen: true });
  const view = render(
    <MemoryRouter initialEntries={[path]}>
      <button type="button" data-testid="page-button">
        page
      </button>
      <FloatingChatButton />
      <FloatingChatPanel />
    </MemoryRouter>,
  );
  await act(async () => {
    await Promise.resolve();
  });
  // Without this, the composer can grab focus in the middle of a test that
  // has just put focus in the page, and the test measures the timer.
  if (settle) await settleOpeningFocus();
  const q = (sel: string) => view.container.querySelector<HTMLElement>(sel);
  return {
    view,
    dialog: () => q('[role="dialog"][data-testid="floating-chat-panel"]'),
    backdrop: () => q('[data-testid="floating-chat-backdrop"]'),
    handle: () => q('[data-testid="floating-chat-resize-handle"]'),
    fab: () => q('[data-testid="floating-chat-button"]'),
    composer: () => q('[data-testid="floating-chat-input"]') as HTMLTextAreaElement | null,
    titleInput: () => q('[role="dialog"] input[aria-label]') as HTMLInputElement | null,
    pageButton: () => q('[data-testid="page-button"]')!,
  };
}

function pressAltA(target: Element = document.body) {
  fireEvent.keyDown(target, { key: 'a', code: 'KeyA', altKey: true });
}

/**
 * Stands in for the shared ConfirmDialog as the action cards render it:
 * portalled to <body>, outside the dock, `aria-modal="true"`.
 */
function layeredConfirm() {
  const dialog = document.createElement('div');
  dialog.setAttribute('role', 'alertdialog');
  dialog.setAttribute('aria-modal', 'true');
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = 'OK';
  dialog.appendChild(button);
  document.body.appendChild(dialog);
  return { button, remove: () => dialog.remove() };
}

describe('push mode on a wide screen', () => {
  it('docks beside the page: no backdrop, not modal, the page makes room', async () => {
    const ui = await mount();
    const dialog = ui.dialog();
    expect(dialog).not.toBeNull();
    expect(dialog!.getAttribute('data-dock-mode')).toBe('push');
    expect(dialog!.getAttribute('aria-modal')).toBe('false');
    expect(ui.backdrop()).toBeNull();
    expect(dialog!.style.width).toBe('440px');
    expect(offset()).toBe('440px');
    expect(widgetOffset()).toBe('440px');
    expect(root().getAttribute('data-ai-dock')).toBe('push');
  });

  it('keeps role=dialog named by the title, and the title input first', async () => {
    const ui = await mount();
    expect(ui.dialog()!.getAttribute('aria-label')).toBe('AI assistant');
    expect(ui.titleInput()!.getAttribute('aria-label')).toBe('Conversation title');
  });

  it('gives the page its width back when closed', async () => {
    await mount();
    act(() => store.useFloatingChatStore.getState().close());
    expect(offset()).toBe('0px');
    expect(widgetOffset()).toBe('0px');
    expect(root().hasAttribute('data-ai-dock')).toBe(false);
  });

  it('does not trap focus: Tab may leave the dock for the page', async () => {
    const ui = await mount();
    const last = ui.handle()!;
    last.focus();
    // fireEvent returns true when no listener called preventDefault().
    expect(fireEvent.keyDown(last, { key: 'Tab' })).toBe(true);
  });
});

describe('overlay mode', () => {
  it('floats over the page with a backdrop and is modal when the page would be too narrow', async () => {
    setViewport(1100);
    const ui = await mount();
    const dialog = ui.dialog()!;
    expect(dialog.getAttribute('data-dock-mode')).toBe('overlay');
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(ui.backdrop()).not.toBeNull();
    expect(offset()).toBe('0px');
    // The page stays put, but the widgets above the backdrop step aside.
    expect(widgetOffset()).toBe('440px');
    expect(root().getAttribute('data-ai-dock')).toBe('overlay');
  });

  it('pulls focus into the dock when it opens as a modal', async () => {
    setViewport(1100);
    // Read before the composer's own delayed focus, so this sees the pull.
    const ui = await mount({ settle: false });
    expect(ui.dialog()!.contains(document.activeElement)).toBe(true);
  });

  it('keeps Tab inside the dock', async () => {
    setViewport(1100);
    const ui = await mount();
    const last = ui.handle()!;
    last.focus();
    // fireEvent returns false when a listener called preventDefault().
    expect(fireEvent.keyDown(last, { key: 'Tab' })).toBe(false);
    expect(ui.dialog()!.contains(document.activeElement)).toBe(true);
  });

  it('leaves Tab to a dialog opened over it, such as a confirm from a card', async () => {
    setViewport(1100);
    await mount();
    const confirm = layeredConfirm();
    try {
      confirm.button.focus();
      expect(fireEvent.keyDown(confirm.button, { key: 'Tab' })).toBe(true);
      expect(document.activeElement).toBe(confirm.button);
    } finally {
      confirm.remove();
    }
  });

  it('closes on a backdrop click', async () => {
    setViewport(1100);
    const ui = await mount();
    fireEvent.click(ui.backdrop()!);
    expect(store.useFloatingChatStore.getState().isOpen).toBe(false);
  });

  it('covers the whole screen on a phone and offers no resize handle', async () => {
    setViewport(390);
    const ui = await mount();
    expect(ui.dialog()!.style.width).toBe('100%');
    expect(ui.handle()).toBeNull();
    expect(widgetOffset()).toBe('0px');
  });

  it('switches mode when the window shrinks, without closing', async () => {
    const ui = await mount();
    expect(ui.dialog()!.getAttribute('data-dock-mode')).toBe('push');
    act(() => setViewport(1100));
    expect(ui.dialog()!.getAttribute('data-dock-mode')).toBe('overlay');
    expect(store.useFloatingChatStore.getState().isOpen).toBe(true);
    expect(offset()).toBe('0px');
  });
});

describe('Escape', () => {
  it('does nothing in push mode while focus is in the page', async () => {
    const ui = await mount();
    ui.pageButton().focus();
    fireEvent.keyDown(ui.pageButton(), { key: 'Escape' });
    expect(store.useFloatingChatStore.getState().isOpen).toBe(true);
  });

  it('closes the dock when focus is inside it', async () => {
    const ui = await mount();
    ui.titleInput()!.focus();
    fireEvent.keyDown(ui.titleInput()!, { key: 'Escape' });
    expect(store.useFloatingChatStore.getState().isOpen).toBe(false);
  });

  it('leaves the dock alone when something inside consumed the key', async () => {
    const ui = await mount();
    const input = ui.titleInput()!;
    input.focus();
    input.addEventListener('keydown', (e) => e.preventDefault(), { once: true });
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(store.useFloatingChatStore.getState().isOpen).toBe(true);
  });

  it('closes the sessions menu first, then the dock', async () => {
    const ui = await mount();
    const toggle = ui.view.container.querySelector<HTMLElement>(
      '[data-testid="floating-chat-sessions-toggle"]',
    )!;
    fireEvent.click(toggle);
    await act(async () => {
      await Promise.resolve();
    });
    expect(ui.view.container.querySelector('[role="menu"]')).not.toBeNull();
    toggle.focus();
    fireEvent.keyDown(toggle, { key: 'Escape' });
    expect(ui.view.container.querySelector('[role="menu"]')).toBeNull();
    expect(store.useFloatingChatStore.getState().isOpen).toBe(true);
    fireEvent.keyDown(toggle, { key: 'Escape' });
    expect(store.useFloatingChatStore.getState().isOpen).toBe(false);
  });

  it('hands focus back to where it was before the dock opened', async () => {
    const ui = await mount({ open: false });
    ui.pageButton().focus();
    act(() => store.useFloatingChatStore.getState().open());
    ui.titleInput()!.focus();
    fireEvent.keyDown(ui.titleInput()!, { key: 'Escape' });
    expect(document.activeElement).toBe(ui.pageButton());
  });

  it('still hands focus back there after a confirm over the dock had it for a while', async () => {
    const ui = await mount({ open: false });
    ui.pageButton().focus();
    act(() => store.useFloatingChatStore.getState().open());
    const confirm = layeredConfirm();
    confirm.button.focus();
    // The confirm closes and gives focus back to the card inside the dock.
    confirm.remove();
    ui.titleInput()!.focus();
    fireEvent.keyDown(ui.titleInput()!, { key: 'Escape' });
    expect(document.activeElement).toBe(ui.pageButton());
  });
});

describe('leaving', () => {
  it('stays mounted while it animates out, then unmounts', async () => {
    const ui = await mount();
    vi.useFakeTimers();
    act(() => store.useFloatingChatStore.getState().close());
    const leaving = ui.dialog();
    expect(leaving).not.toBeNull();
    expect(leaving!.getAttribute('data-state')).toBe('closing');
    expect(leaving!.getAttribute('aria-hidden')).toBe('true');
    expect(leaving!.hasAttribute('inert')).toBe(true);
    act(() => {
      vi.advanceTimersByTime(store.DOCK_ANIMATION_MS + 200);
    });
    expect(ui.dialog()).toBeNull();
  });

  it('ends the exit on its own animationend', async () => {
    const ui = await mount();
    act(() => store.useFloatingChatStore.getState().close());
    const leaving = ui.dialog()!;
    fireEvent.animationEnd(leaving);
    expect(ui.dialog()).toBeNull();
  });

  it('ignores an animationend bubbling up from inside', async () => {
    const ui = await mount();
    act(() => store.useFloatingChatStore.getState().close());
    fireEvent.animationEnd(ui.titleInput()!);
    expect(ui.dialog()).not.toBeNull();
  });

  it('leaves at once when the reader asked for reduced motion', async () => {
    reducedMotion = true;
    const ui = await mount();
    act(() => store.useFloatingChatStore.getState().close());
    expect(ui.dialog()).toBeNull();
  });

  it('comes back mid-exit without unmounting (the conversation survives)', async () => {
    const ui = await mount();
    act(() => store.useFloatingChatStore.getState().close());
    const leaving = ui.dialog();
    act(() => store.useFloatingChatStore.getState().open());
    expect(ui.dialog()).toBe(leaving);
    expect(ui.dialog()!.getAttribute('data-state')).toBe('open');
    expect(ui.dialog()!.hasAttribute('inert')).toBe(false);
    await settleAiProbe();
  });

  it('clears what it wrote on the page when the shell unmounts', async () => {
    const ui = await mount();
    expect(offset()).toBe('440px');
    ui.view.unmount();
    expect(offset()).toBe('');
    expect(widgetOffset()).toBe('');
    expect(root().hasAttribute('data-ai-dock')).toBe(false);
  });
});

describe('resize handle, by keyboard', () => {
  it('is a labelled vertical separator reporting the width', async () => {
    const ui = await mount();
    const handle = ui.handle()!;
    expect(handle.getAttribute('role')).toBe('separator');
    expect(handle.getAttribute('aria-orientation')).toBe('vertical');
    expect(handle.getAttribute('aria-valuenow')).toBe('440');
    expect(handle.getAttribute('aria-valuemin')).toBe(String(store.DOCK_MIN_WIDTH));
    expect(handle.getAttribute('aria-valuemax')).toBe('720');
    expect(handle.getAttribute('aria-controls')).toBe(ui.dialog()!.id);
    expect(handle.getAttribute('tabindex')).toBe('0');
  });

  it('widens by 16px with the arrow that points at the page', async () => {
    const ui = await mount();
    fireEvent.keyDown(ui.handle()!, { key: 'ArrowLeft' });
    expect(store.useFloatingChatStore.getState().width).toBe(456);
    expect(ui.handle()!.getAttribute('aria-valuenow')).toBe('456');
    expect(ui.dialog()!.style.width).toBe('456px');
    expect(offset()).toBe('456px');
    fireEvent.keyDown(ui.handle()!, { key: 'ArrowRight' });
    expect(store.useFloatingChatStore.getState().width).toBe(440);
  });

  it('swaps the arrows in RTL, where the dock sits on the left', async () => {
    root().dir = 'rtl';
    const ui = await mount();
    fireEvent.keyDown(ui.handle()!, { key: 'ArrowLeft' });
    expect(store.useFloatingChatStore.getState().width).toBe(424);
    fireEvent.keyDown(ui.handle()!, { key: 'ArrowRight' });
    fireEvent.keyDown(ui.handle()!, { key: 'ArrowRight' });
    expect(store.useFloatingChatStore.getState().width).toBe(456);
  });

  it('never turns push into overlay, End stops where the page keeps 560px', async () => {
    setViewport(1280);
    const ui = await mount();
    fireEvent.keyDown(ui.handle()!, { key: 'End' });
    expect(ui.handle()!.getAttribute('aria-valuenow')).toBe('472');
    expect(ui.handle()!.getAttribute('aria-valuemax')).toBe('472');
    expect(ui.dialog()!.getAttribute('data-dock-mode')).toBe('push');
    expect(ui.dialog()!.getAttribute('aria-modal')).toBe('false');
    for (let i = 0; i < 20; i += 1) fireEvent.keyDown(ui.handle()!, { key: 'ArrowLeft' });
    expect(ui.dialog()!.getAttribute('data-dock-mode')).toBe('push');
    expect(offset()).toBe('472px');
  });

  it('jumps to the narrowest with Home and resets on double-click', async () => {
    const ui = await mount();
    fireEvent.keyDown(ui.handle()!, { key: 'Home' });
    expect(store.useFloatingChatStore.getState().width).toBe(store.DOCK_MIN_WIDTH);
    fireEvent.doubleClick(ui.handle()!);
    expect(store.useFloatingChatStore.getState().width).toBe(store.DOCK_DEFAULT_WIDTH);
  });
});

describe('resize handle, by pointer', () => {
  // Frames are queued by hand, so the test decides when "the next frame" is.
  let frames: FrameRequestCallback[] = [];
  let realRequestFrame: typeof window.requestAnimationFrame;
  let realCancelFrame: typeof window.cancelAnimationFrame;

  beforeEach(() => {
    frames = [];
    realRequestFrame = window.requestAnimationFrame;
    realCancelFrame = window.cancelAnimationFrame;
    window.requestAnimationFrame = (cb: FrameRequestCallback) => {
      frames.push(cb);
      return frames.length;
    };
    window.cancelAnimationFrame = () => {};
    localStorage.removeItem(store.DOCK_WIDTH_STORAGE_KEY);
  });

  afterEach(() => {
    window.requestAnimationFrame = realRequestFrame;
    window.cancelAnimationFrame = realCancelFrame;
  });

  function runFrames() {
    const pending = frames;
    frames = [];
    act(() => {
      pending.forEach((cb) => cb(0));
    });
  }

  // A MouseEvent carries clientX and button in every jsdom version; the
  // pointer id is added by hand, so the test does not lean on jsdom's
  // PointerEvent support.
  function pointer(target: Element, type: string, clientX: number) {
    const event = new MouseEvent(type, { bubbles: true, cancelable: true, clientX, button: 0 });
    Object.defineProperty(event, 'pointerId', { value: 1 });
    act(() => {
      target.dispatchEvent(event);
    });
  }

  const resizing = () => root().hasAttribute('data-ai-dock-resizing');

  it('previews the drag, with the page transitions off, and stores the width once on release', async () => {
    const ui = await mount();
    const handle = ui.handle()!;
    pointer(handle, 'pointerdown', 1000);
    expect(resizing()).toBe(true);
    expect(handle.getAttribute('data-dragging')).toBe('true');

    // 100px towards the page in LTR widens the dock by 100px.
    pointer(handle, 'pointermove', 900);
    runFrames();
    expect(ui.dialog()!.style.width).toBe('540px');
    expect(offset()).toBe('540px');
    expect(widgetOffset()).toBe('540px');
    expect(store.useFloatingChatStore.getState().width).toBe(440);
    expect(localStorage.getItem(store.DOCK_WIDTH_STORAGE_KEY)).toBeNull();

    pointer(handle, 'pointerup', 900);
    expect(resizing()).toBe(false);
    expect(ui.handle()!.hasAttribute('data-dragging')).toBe(false);
    expect(store.useFloatingChatStore.getState().width).toBe(540);
    expect(localStorage.getItem(store.DOCK_WIDTH_STORAGE_KEY)).toBe('540');
    expect(ui.dialog()!.style.width).toBe('540px');
  });

  it('does not leave the page in resize mode when the dock closes mid-drag', async () => {
    const ui = await mount();
    pointer(ui.handle()!, 'pointerdown', 1000);
    pointer(ui.handle()!, 'pointermove', 800);
    expect(resizing()).toBe(true);
    act(() => store.useFloatingChatStore.getState().close());
    expect(ui.handle()).toBeNull();
    expect(resizing()).toBe(false);
    expect(offset()).toBe('0px');
    expect(store.useFloatingChatStore.getState().width).toBe(440);
  });
});

describe('Alt+A', () => {
  it('opens a closed dock', async () => {
    await mount({ open: false });
    pressAltA();
    expect(store.useFloatingChatStore.getState().isOpen).toBe(true);
    await settleAiProbe();
  });

  it('moves focus into an open dock when focus is in the page, without closing it', async () => {
    const ui = await mount();
    ui.pageButton().focus();
    pressAltA(ui.pageButton());
    expect(store.useFloatingChatStore.getState().isOpen).toBe(true);
    expect(document.activeElement).toBe(ui.composer());
  });

  it('closes the dock when pressed inside it', async () => {
    const ui = await mount();
    ui.titleInput()!.focus();
    pressAltA(ui.titleInput()!);
    expect(store.useFloatingChatStore.getState().isOpen).toBe(false);
  });

  it('stays out of the way while another modal is open', async () => {
    const ui = await mount({ open: false });
    const modal = document.createElement('div');
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    document.body.appendChild(modal);
    try {
      pressAltA();
      expect(store.useFloatingChatStore.getState().isOpen).toBe(false);
    } finally {
      modal.remove();
    }
    expect(ui.dialog()).toBeNull();
  });
});

describe('the full-page chat route', () => {
  it('keeps the dock closed on /chat without forgetting it was open', async () => {
    const ui = await mount({ path: '/chat' });
    expect(ui.dialog()).toBeNull();
    expect(offset()).toBe('0px');
    expect(root().hasAttribute('data-ai-dock')).toBe(false);
    expect(store.useFloatingChatStore.getState().isOpen).toBe(true);
  });

  it('ignores Alt+A there', async () => {
    const ui = await mount({ path: '/chat', open: false });
    pressAltA();
    expect(store.useFloatingChatStore.getState().isOpen).toBe(false);
    expect(ui.dialog()).toBeNull();
  });

  it('hides the round button there', async () => {
    const ui = await mount({ path: '/chat', open: false });
    expect(ui.fab()).toBeNull();
  });
});

describe('the round button', () => {
  it('is shown while the dock is closed and names its shortcut', async () => {
    const ui = await mount({ open: false });
    const fab = ui.fab()!;
    expect(fab.className).toContain('flex');
    expect(fab.className).not.toMatch(/(^|\s)hidden(\s|$)/);
    expect(fab.getAttribute('aria-keyshortcuts')).toBe('Alt+A');
    expect(fab.getAttribute('title')).toContain('Alt+A');
  });

  it('is hidden while the dock is open, it would sit in the same corner', async () => {
    const ui = await mount();
    expect(ui.fab()!.className).toMatch(/(^|\s)hidden(\s|$)/);
  });

  it('opens the dock', async () => {
    const ui = await mount({ open: false });
    fireEvent.click(ui.fab()!);
    expect(store.useFloatingChatStore.getState().isOpen).toBe(true);
    expect(ui.dialog()).not.toBeNull();
    await settleAiProbe();
  });
});
