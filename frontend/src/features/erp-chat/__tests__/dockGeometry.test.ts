// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The AI dock is a side panel that either PUSHES the page aside (wide
// screens) or floats OVER it with a backdrop (everything else). These tests
// pin the arithmetic that decides which, how wide the dock may be, what the
// page and the fixed widgets are told through `--oe-ai-dock-offset` and
// `--oe-ai-dock-widget-offset`, and which keystroke toggles it.
//
// One rule carries most of the weight: the mode depends on the SCREEN, never
// on the width the user dragged the dock to. If it depended on the dragged
// width, a drag past some point would flip the dock from push to overlay
// under the cursor - a backdrop would appear, focus would be trapped and the
// page would jump back to full width mid-gesture. In push mode the dock
// gives up width instead; the page keeps its 560px floor.
//
// Run:  npx vitest run src/features/erp-chat/__tests__/dockGeometry.test.ts

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  DOCK_DEFAULT_WIDTH,
  DOCK_MIN_WIDTH,
  DOCK_MAX_WIDTH,
  DOCK_MIN_PAGE_WIDTH,
  DOCK_KEYBOARD_STEP,
  DOCK_WIDTH_STORAGE_KEY,
  DOCK_OFFSET_VAR,
  DOCK_WIDGET_OFFSET_VAR,
  DOCK_MODE_ATTR,
  applyDockLayout,
  clampDockWidth,
  clearDockLayout,
  computeDockMode,
  dockMaxWidth,
  dockOffsetFor,
  dockWidgetOffsetFor,
  isDockShortcut,
  isFloatingChatHiddenOn,
  readDockWidth,
  readSidebarWidthPx,
  resolveDockGeometry,
  widthFromDrag,
  widthFromKey,
  useFloatingChatStore,
} from '../useFloatingChat';

const FULL_SIDEBAR = 248;
const ICON_SIDEBAR = 64;

describe('clampDockWidth', () => {
  it('keeps a width inside the bounds untouched', () => {
    expect(clampDockWidth(500)).toBe(500);
  });

  it('raises a width below the minimum to the minimum', () => {
    expect(clampDockWidth(100)).toBe(DOCK_MIN_WIDTH);
  });

  it('lowers a width above the maximum to the maximum', () => {
    expect(clampDockWidth(5000)).toBe(DOCK_MAX_WIDTH);
  });

  it('rounds to whole pixels', () => {
    expect(clampDockWidth(450.6)).toBe(451);
  });

  it('turns garbage into the default instead of NaN', () => {
    expect(clampDockWidth(Number.NaN)).toBe(DOCK_DEFAULT_WIDTH);
    expect(clampDockWidth('wide')).toBe(DOCK_DEFAULT_WIDTH);
    expect(clampDockWidth(undefined)).toBe(DOCK_DEFAULT_WIDTH);
    expect(clampDockWidth(Number.POSITIVE_INFINITY)).toBe(DOCK_DEFAULT_WIDTH);
  });

  it('honours a tighter cap from the screen', () => {
    expect(clampDockWidth(700, 500)).toBe(500);
  });

  it('lets the minimum win when the cap is smaller than the minimum', () => {
    // A 700px window: half of it is 350, below the 360 floor. The dock is
    // full width below 640 anyway; between 640 and 719 the floor holds.
    expect(clampDockWidth(700, 350)).toBe(DOCK_MIN_WIDTH);
  });
});

describe('computeDockMode', () => {
  it('overlays below the lg breakpoint even when there would be room', () => {
    expect(computeDockMode({ viewportWidth: 1023, sidebarWidth: 0 })).toBe('overlay');
  });

  it('pushes from the lg breakpoint when the icon sidebar leaves room', () => {
    // 1024 - 64 - 360 = 600 >= 560
    expect(computeDockMode({ viewportWidth: 1024, sidebarWidth: ICON_SIDEBAR })).toBe('push');
  });

  it('overlays at 1024 with the full sidebar, the page would be too narrow', () => {
    // 1024 - 248 - 360 = 416 < 560
    expect(computeDockMode({ viewportWidth: 1024, sidebarWidth: FULL_SIDEBAR })).toBe('overlay');
  });

  it('flips exactly where the page keeps its 560px floor next to the narrowest dock', () => {
    const threshold = FULL_SIDEBAR + DOCK_MIN_WIDTH + DOCK_MIN_PAGE_WIDTH; // 1168
    expect(computeDockMode({ viewportWidth: threshold, sidebarWidth: FULL_SIDEBAR })).toBe('push');
    expect(computeDockMode({ viewportWidth: threshold - 1, sidebarWidth: FULL_SIDEBAR })).toBe(
      'overlay',
    );
  });

  it('pushes on an ordinary laptop with the full sidebar', () => {
    expect(computeDockMode({ viewportWidth: 1366, sidebarWidth: FULL_SIDEBAR })).toBe('push');
  });

  it('does not read the text direction: RTL gives the same answer', () => {
    const before = document.documentElement.dir;
    try {
      document.documentElement.dir = 'rtl';
      expect(computeDockMode({ viewportWidth: 1366, sidebarWidth: FULL_SIDEBAR })).toBe('push');
      expect(computeDockMode({ viewportWidth: 1100, sidebarWidth: FULL_SIDEBAR })).toBe('overlay');
    } finally {
      document.documentElement.dir = before;
    }
  });
});

describe('dockMaxWidth and resolveDockGeometry', () => {
  it('in push mode gives up width so the page keeps 560px', () => {
    // 1280 - 248 - 560 = 472, tighter than 720 and than 50vw (640).
    expect(dockMaxWidth({ viewportWidth: 1280, sidebarWidth: FULL_SIDEBAR, mode: 'push' })).toBe(
      472,
    );
  });

  it('never exceeds 720 on a very wide screen', () => {
    expect(dockMaxWidth({ viewportWidth: 2560, sidebarWidth: FULL_SIDEBAR, mode: 'push' })).toBe(
      DOCK_MAX_WIDTH,
    );
  });

  it('in overlay mode is half the screen at most', () => {
    expect(dockMaxWidth({ viewportWidth: 1000, sidebarWidth: FULL_SIDEBAR, mode: 'overlay' })).toBe(
      500,
    );
  });

  it('never drops below the minimum', () => {
    expect(dockMaxWidth({ viewportWidth: 700, sidebarWidth: FULL_SIDEBAR, mode: 'overlay' })).toBe(
      DOCK_MIN_WIDTH,
    );
  });

  it('shows the preferred width when it fits and the cap when it does not', () => {
    const roomy = resolveDockGeometry({
      viewportWidth: 1920,
      sidebarWidth: FULL_SIDEBAR,
      preferredWidth: 600,
    });
    expect(roomy).toMatchObject({ mode: 'push', width: 600, fullWidth: false });

    const tight = resolveDockGeometry({
      viewportWidth: 1280,
      sidebarWidth: FULL_SIDEBAR,
      preferredWidth: 600,
    });
    expect(tight).toMatchObject({ mode: 'push', width: 472, maxWidth: 472 });
  });

  it('goes full width below 640', () => {
    const phone = resolveDockGeometry({
      viewportWidth: 390,
      sidebarWidth: FULL_SIDEBAR,
      preferredWidth: 440,
    });
    expect(phone).toMatchObject({ mode: 'overlay', fullWidth: true });
  });

  it('no preferred width, however large, turns push into overlay', () => {
    for (const preferred of [DOCK_MIN_WIDTH, 440, 472, 600, DOCK_MAX_WIDTH, 5000]) {
      const g = resolveDockGeometry({
        viewportWidth: 1280,
        sidebarWidth: FULL_SIDEBAR,
        preferredWidth: preferred,
      });
      expect(g.mode).toBe('push');
      expect(1280 - FULL_SIDEBAR - g.width).toBeGreaterThanOrEqual(DOCK_MIN_PAGE_WIDTH);
    }
  });
});

describe('resizing by pointer and by keyboard', () => {
  it('widens the dock when the handle is dragged away from its edge (LTR: to the left)', () => {
    expect(
      widthFromDrag({ startWidth: 440, startX: 1000, currentX: 950, rtl: false, maxWidth: 700 }),
    ).toBe(490);
  });

  it('mirrors the drag in RTL, where the dock sits on the left', () => {
    expect(
      widthFromDrag({ startWidth: 440, startX: 400, currentX: 450, rtl: true, maxWidth: 700 }),
    ).toBe(490);
    expect(
      widthFromDrag({ startWidth: 440, startX: 400, currentX: 350, rtl: true, maxWidth: 700 }),
    ).toBe(390);
  });

  it('clamps a drag to the cap and the floor', () => {
    expect(
      widthFromDrag({ startWidth: 440, startX: 1000, currentX: 0, rtl: false, maxWidth: 472 }),
    ).toBe(472);
    expect(
      widthFromDrag({ startWidth: 440, startX: 1000, currentX: 2000, rtl: false, maxWidth: 472 }),
    ).toBe(DOCK_MIN_WIDTH);
  });

  it('moves 16px per arrow key, towards the page widens', () => {
    expect(widthFromKey('ArrowLeft', { width: 440, maxWidth: 700, rtl: false })).toBe(
      440 + DOCK_KEYBOARD_STEP,
    );
    expect(widthFromKey('ArrowRight', { width: 440, maxWidth: 700, rtl: false })).toBe(
      440 - DOCK_KEYBOARD_STEP,
    );
  });

  it('inverts the arrows in RTL', () => {
    expect(widthFromKey('ArrowLeft', { width: 440, maxWidth: 700, rtl: true })).toBe(424);
    expect(widthFromKey('ArrowRight', { width: 440, maxWidth: 700, rtl: true })).toBe(456);
  });

  it('jumps to the bounds with Home and End', () => {
    expect(widthFromKey('Home', { width: 440, maxWidth: 472, rtl: false })).toBe(DOCK_MIN_WIDTH);
    expect(widthFromKey('End', { width: 440, maxWidth: 472, rtl: false })).toBe(472);
  });

  it('ignores keys that are not resize keys', () => {
    expect(widthFromKey('Enter', { width: 440, maxWidth: 700, rtl: false })).toBeNull();
    expect(widthFromKey('a', { width: 440, maxWidth: 700, rtl: false })).toBeNull();
  });
});

describe('the page offset writer', () => {
  let root: HTMLElement;
  beforeEach(() => {
    root = document.createElement('div');
  });

  it('asks the page for the dock width only when open in push mode', () => {
    expect(dockOffsetFor({ open: true, mode: 'push', width: 440 })).toBe('440px');
    expect(dockOffsetFor({ open: true, mode: 'overlay', width: 440 })).toBe('0px');
    expect(dockOffsetFor({ open: false, mode: 'push', width: 440 })).toBe('0px');
  });

  // Overlay mode leaves the page alone, but the widgets that paint above the
  // backdrop (upload pills, prompts, toasts) would sit on the dock itself.
  it('moves the fixed widgets aside in both modes, except when the dock fills the screen', () => {
    expect(dockWidgetOffsetFor({ open: true, mode: 'push', width: 440 })).toBe('440px');
    expect(dockWidgetOffsetFor({ open: true, mode: 'overlay', width: 440 })).toBe('440px');
    expect(dockWidgetOffsetFor({ open: false, mode: 'overlay', width: 440 })).toBe('0px');
    expect(
      dockWidgetOffsetFor({ open: true, mode: 'overlay', width: 390, fullWidth: true }),
    ).toBe('0px');
  });

  it('writes both variables and the mode attribute while open', () => {
    applyDockLayout(root, { open: true, mode: 'push', width: 512 });
    expect(root.style.getPropertyValue(DOCK_OFFSET_VAR)).toBe('512px');
    expect(root.style.getPropertyValue(DOCK_WIDGET_OFFSET_VAR)).toBe('512px');
    expect(root.getAttribute(DOCK_MODE_ATTR)).toBe('push');

    applyDockLayout(root, { open: true, mode: 'overlay', width: 512 });
    expect(root.style.getPropertyValue(DOCK_OFFSET_VAR)).toBe('0px');
    expect(root.style.getPropertyValue(DOCK_WIDGET_OFFSET_VAR)).toBe('512px');
    expect(root.getAttribute(DOCK_MODE_ATTR)).toBe('overlay');
  });

  it('zeroes both variables and drops the attribute when closed', () => {
    applyDockLayout(root, { open: true, mode: 'push', width: 512 });
    applyDockLayout(root, { open: false, mode: 'push', width: 512 });
    expect(root.style.getPropertyValue(DOCK_OFFSET_VAR)).toBe('0px');
    expect(root.style.getPropertyValue(DOCK_WIDGET_OFFSET_VAR)).toBe('0px');
    expect(root.hasAttribute(DOCK_MODE_ATTR)).toBe(false);
  });

  it('leaves nothing behind on cleanup', () => {
    applyDockLayout(root, { open: true, mode: 'push', width: 512 });
    clearDockLayout(root);
    expect(root.style.getPropertyValue(DOCK_OFFSET_VAR)).toBe('');
    expect(root.style.getPropertyValue(DOCK_WIDGET_OFFSET_VAR)).toBe('');
    expect(root.hasAttribute(DOCK_MODE_ATTR)).toBe(false);
  });
});

describe('readSidebarWidthPx', () => {
  it('reads the width the sidebar wrote on the root element', () => {
    const root = document.createElement('div');
    root.style.setProperty('--oe-sidebar-width', '64px');
    expect(readSidebarWidthPx(root)).toBe(64);
  });

  it('falls back to the stylesheet default when nothing was written', () => {
    const root = document.createElement('div');
    expect(readSidebarWidthPx(root)).toBe(FULL_SIDEBAR);
  });
});

describe('the dock width is remembered', () => {
  beforeEach(() => {
    localStorage.removeItem(DOCK_WIDTH_STORAGE_KEY);
    localStorage.removeItem('oe_floating_chat_v1');
    useFloatingChatStore.setState({ width: DOCK_DEFAULT_WIDTH });
  });

  it('starts at the default when nothing is stored', () => {
    expect(readDockWidth()).toBe(DOCK_DEFAULT_WIDTH);
  });

  it('round-trips a width through storage', () => {
    useFloatingChatStore.getState().setWidth(512);
    expect(useFloatingChatStore.getState().width).toBe(512);
    expect(localStorage.getItem(DOCK_WIDTH_STORAGE_KEY)).toBe('512');
    expect(readDockWidth()).toBe(512);
  });

  it('clamps what it stores and what it reads back', () => {
    useFloatingChatStore.getState().setWidth(9999);
    expect(useFloatingChatStore.getState().width).toBe(DOCK_MAX_WIDTH);
    localStorage.setItem(DOCK_WIDTH_STORAGE_KEY, '12');
    expect(readDockWidth()).toBe(DOCK_MIN_WIDTH);
    localStorage.setItem(DOCK_WIDTH_STORAGE_KEY, 'not-a-number');
    expect(readDockWidth()).toBe(DOCK_DEFAULT_WIDTH);
  });

  it('can skip the storage write while a drag is still moving', () => {
    useFloatingChatStore.getState().setWidth(480, { persist: false });
    expect(useFloatingChatStore.getState().width).toBe(480);
    expect(localStorage.getItem(DOCK_WIDTH_STORAGE_KEY)).toBeNull();
  });

  it('resets to the default', () => {
    useFloatingChatStore.getState().setWidth(600);
    useFloatingChatStore.getState().resetWidth();
    expect(useFloatingChatStore.getState().width).toBe(DOCK_DEFAULT_WIDTH);
    expect(localStorage.getItem(DOCK_WIDTH_STORAGE_KEY)).toBe(String(DOCK_DEFAULT_WIDTH));
  });

  it('keeps the session key untouched, the width lives in its own key', () => {
    useFloatingChatStore.getState().setWidth(512);
    expect(localStorage.getItem('oe_floating_chat_v1')).toBeNull();
  });
});

describe('the store reads the stored width at start-up', () => {
  afterEach(() => {
    localStorage.removeItem(DOCK_WIDTH_STORAGE_KEY);
    vi.resetModules();
  });

  it('opens at the width the user left it at', async () => {
    localStorage.setItem(DOCK_WIDTH_STORAGE_KEY, '536');
    vi.resetModules();
    const fresh = await import('../useFloatingChat');
    expect(fresh.useFloatingChatStore.getState().width).toBe(536);
  });

  it('clamps a stored width that is out of range', async () => {
    localStorage.setItem(DOCK_WIDTH_STORAGE_KEY, '99999');
    vi.resetModules();
    const fresh = await import('../useFloatingChat');
    expect(fresh.useFloatingChatStore.getState().width).toBe(DOCK_MAX_WIDTH);
  });
});

describe('isDockShortcut (Alt+A)', () => {
  const plain = { key: 'a', code: 'KeyA', altKey: true };
  const env = { applePlatform: false, typingInField: false };

  it('accepts Alt+A', () => {
    expect(isDockShortcut(plain, env)).toBe(true);
  });

  it('accepts the physical key on layouts that print another letter there', () => {
    expect(isDockShortcut({ key: 'q', code: 'KeyA', altKey: true }, env)).toBe(true);
  });

  it('accepts Option+A on a Mac, which reports a different character', () => {
    expect(
      isDockShortcut({ key: 'å', code: 'KeyA', altKey: true }, { ...env, applePlatform: true }),
    ).toBe(true);
  });

  it('rejects AltGr, which types letters on many layouts', () => {
    // Windows reports AltGr as Ctrl+Alt.
    expect(isDockShortcut({ ...plain, ctrlKey: true }, env)).toBe(false);
    expect(
      isDockShortcut({ ...plain, getModifierState: (k: string) => k === 'AltGraph' }, env),
    ).toBe(false);
  });

  it('rejects other chords that include Alt+A', () => {
    expect(isDockShortcut({ ...plain, shiftKey: true }, env)).toBe(false);
    expect(isDockShortcut({ ...plain, metaKey: true }, env)).toBe(false);
  });

  it('rejects A without Alt', () => {
    expect(isDockShortcut({ key: 'a', code: 'KeyA' }, env)).toBe(false);
  });

  it('rejects auto-repeat and IME composition', () => {
    expect(isDockShortcut({ ...plain, repeat: true }, env)).toBe(false);
    expect(isDockShortcut({ ...plain, isComposing: true }, env)).toBe(false);
  });

  it('leaves Option+A to the text field on a Mac, where it types a letter', () => {
    expect(
      isDockShortcut(
        { key: 'å', code: 'KeyA', altKey: true },
        { applePlatform: true, typingInField: true },
      ),
    ).toBe(false);
  });

  it('still fires inside a text field elsewhere, where Alt+A types nothing', () => {
    expect(isDockShortcut(plain, { applePlatform: false, typingInField: true })).toBe(true);
  });
});

describe('routes that host their own chat', () => {
  it('hides the dock on the full-page chat', () => {
    expect(isFloatingChatHiddenOn('/chat')).toBe(true);
    expect(isFloatingChatHiddenOn('/chat/abc')).toBe(true);
  });

  it('keeps it everywhere else', () => {
    expect(isFloatingChatHiddenOn('/')).toBe(false);
    expect(isFloatingChatHiddenOn('/boq/123')).toBe(false);
    expect(isFloatingChatHiddenOn('/change-orders')).toBe(false);
  });
});
