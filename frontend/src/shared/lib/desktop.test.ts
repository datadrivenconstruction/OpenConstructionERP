// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Tests for the desktop "open in your browser" bridge.
 *
 * This helper had no coverage at all, and it shipped a bug that no gate could
 * see: it returned a truthy result from every branch a desktop user could
 * reach, so the `if (!ok)` guard at both call sites was dead and a failed open
 * was completely silent. A user reported it against 11.2.0 and the code was
 * still identical in 14.x.
 *
 * The load-bearing case here is "reports failure when the native command
 * fails". The second is that no `window.open` fallback comes back: one used to
 * run after a failed invoke, and because it only ever executes inside the
 * webview - which swallows target navigation - it opened nothing and returned
 * success anyway. Deleting it was the fix, so its absence is pinned.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

type TauriWindow = { __TAURI__?: unknown };

/**
 * `isTauri` is evaluated once when the module is first loaded, so each case has
 * to install its own global and then import the module fresh.
 */
async function loadDesktop(tauriGlobal?: unknown) {
  vi.resetModules();
  const w = window as unknown as TauriWindow;
  if (tauriGlobal === undefined) {
    delete w.__TAURI__;
  } else {
    w.__TAURI__ = tauriGlobal;
  }
  return import('./desktop');
}

afterEach(() => {
  delete (window as unknown as TauriWindow).__TAURI__;
  vi.restoreAllMocks();
});

describe('openAppInBrowser', () => {
  it('reports the native failure reason instead of claiming success', async () => {
    const invoke = vi.fn().mockRejectedValue('The app is still starting. Please try again in a moment.');
    const { openAppInBrowser } = await loadDesktop({ core: { invoke } });
    vi.spyOn(console, 'warn').mockImplementation(() => {});

    const result = await openAppInBrowser();

    expect(result.ok).toBe(false);
    expect(result.reason).toBe('The app is still starting. Please try again in a moment.');
  });

  it('never falls back to window.open when the native command fails', async () => {
    const invoke = vi.fn().mockRejectedValue('nope');
    const { openAppInBrowser } = await loadDesktop({ core: { invoke } });
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const open = vi.spyOn(window, 'open').mockReturnValue(null);

    await openAppInBrowser();

    // A webview swallows target navigation, so this fallback could only ever
    // run where it cannot work. It opened nothing and reported success, which
    // is what made the failure silent.
    expect(open).not.toHaveBeenCalled();
  });

  it('succeeds when the shell accepts the request', async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    const { openAppInBrowser } = await loadDesktop({ core: { invoke } });

    const result = await openAppInBrowser('/boq');

    expect(result.ok).toBe(true);
    expect(result.reason).toBeUndefined();
    expect(invoke).toHaveBeenCalledWith('open_app_in_browser', { path: '/boq' });
  });

  it('fails honestly when the bridge is missing rather than pretending', async () => {
    const { openAppInBrowser } = await loadDesktop({});

    const result = await openAppInBrowser();

    expect(result.ok).toBe(false);
    expect(result.reason).toBeTruthy();
  });

  it('fails outside the desktop shell', async () => {
    const { openAppInBrowser } = await loadDesktop(undefined);

    const result = await openAppInBrowser();

    expect(result.ok).toBe(false);
  });

  it('drops a path that could leave the local origin', async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    const { openAppInBrowser } = await loadDesktop({ core: { invoke } });

    await openAppInBrowser('//evil.example.com/');

    // Unsafe paths are ignored and the home page is opened instead, so no path
    // argument reaches the native side at all.
    expect(invoke).toHaveBeenCalledWith('open_app_in_browser', {});
  });
});

/**
 * The toast store as the freshly loaded `desktop` module sees it.
 *
 * `loadDesktop` resets the module registry, so a store imported at the top of
 * this file would be a different instance from the one the code under test
 * writes to, and every assertion here would read an empty list and pass.
 */
async function toastsRaised() {
  const { useToastStore } = await import('@/stores/useToastStore');
  return useToastStore.getState().toasts;
}

/** `openLink` starts the open and returns; let the rejection land. */
async function settle() {
  await new Promise((resolve) => {
    setTimeout(resolve, 0);
  });
}

const LINK = 'https://openconstructionerp.com/docs';

describe('a link that the shell refuses to open', () => {
  it('reaches the user instead of dying on the console', async () => {
    // What a refusal actually looks like: the application is served from a
    // loopback address, Tauri calls that a remote origin, and a command the
    // access control list does not grant to that origin is rejected before it
    // runs. Every outbound link in the product behaved this way, and the only
    // trace was a console warning nobody is reading.
    const invoke = vi.fn().mockRejectedValue('Command open_external_url not allowed by ACL');
    const { openLink } = await loadDesktop({ core: { invoke } });
    vi.spyOn(console, 'warn').mockImplementation(() => {});

    openLink(LINK);
    await settle();

    const raised = await toastsRaised();
    expect(raised).toHaveLength(1);
    // The address is the load-bearing part: it is what the user can act on.
    expect(raised[0]).toMatchObject({ type: 'warning', message: LINK });
  });

  it('offers the address for copying, so the click is recoverable', async () => {
    const invoke = vi.fn().mockRejectedValue('nope');
    const { openLink } = await loadDesktop({ core: { invoke } });
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });

    openLink(LINK);
    await settle();

    const action = (await toastsRaised())[0]?.action;
    expect(action).toBeDefined();
    action?.onClick();
    expect(writeText).toHaveBeenCalledWith(LINK);
  });

  it('reports a missing bridge too, which used to return false in silence', async () => {
    const { openLink } = await loadDesktop({});

    openLink(LINK);
    await settle();

    expect(await toastsRaised()).toHaveLength(1);
  });

  it('says nothing at all when the link opens', async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    const { openLink } = await loadDesktop({ core: { invoke } });

    openLink(LINK);
    await settle();

    // A message on the happy path would be worse than the silence it replaces.
    expect(invoke).toHaveBeenCalledWith('open_external_url', { url: LINK });
    expect(await toastsRaised()).toHaveLength(0);
  });

  it('leaves the web build alone, where an anchor already opens a tab', async () => {
    const { openLink } = await loadDesktop(undefined);

    openLink(LINK);
    await settle();

    expect(await toastsRaised()).toHaveLength(0);
  });
});

const FILE_PATH = 'C:\\Users\\someone\\.openestimate\\files\\project\\drawing.pdf';

/**
 * The file manager's "Open in OS" button, which was refused and said nothing.
 *
 * It called the shell plugin's own `open`. The application window is bound to
 * the `app-window` capability, which grants no shell plugin permission at all,
 * so every click was rejected by the access control list before it ran; the
 * catch wrote the refusal to the console and returned false, and the button
 * did nothing with nothing on screen. The refusal text reached us in a user's
 * bug report, which is the only place it was ever visible.
 *
 * These pin both halves of the fix: the call goes to the granted first-party
 * command, and a refusal is put in front of the person who clicked.
 */
describe('revealing a file in the OS file manager', () => {
  it('asks the granted command, not the shell plugin the window may not call', async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    const { revealPathInOS } = await loadDesktop({ core: { invoke } });

    const ok = await revealPathInOS(FILE_PATH);

    expect(ok).toBe(true);
    expect(invoke).toHaveBeenCalledWith('reveal_path_in_os', { path: FILE_PATH });
    // The name matters more than the call: plugin:shell|open is exactly what
    // the capability refuses, and reaching for it again is the whole bug.
    expect(invoke).not.toHaveBeenCalledWith('plugin:shell|open', expect.anything());
    expect(await toastsRaised()).toHaveLength(0);
  });

  it('puts a refusal on screen rather than only on the console', async () => {
    const invoke = vi
      .fn()
      .mockRejectedValue('Command plugin:shell|open not allowed by ACL');
    const { revealPathInOS } = await loadDesktop({ core: { invoke } });
    vi.spyOn(console, 'warn').mockImplementation(() => {});

    const ok = await revealPathInOS(FILE_PATH);
    await settle();

    expect(ok).toBe(false);
    const raised = await toastsRaised();
    expect(raised).toHaveLength(1);
    expect(raised[0]).toMatchObject({ type: 'warning' });
  });

  it('shows the reason the native command gave, not a generic warning', async () => {
    // "Only files inside this workspace can be shown" and "That file is not on
    // this computer" ask the reader to do different things, so the sentence is
    // passed through rather than replaced.
    const reason = 'Only files inside this workspace can be shown';
    const invoke = vi.fn().mockRejectedValue(reason);
    const { revealPathInOS } = await loadDesktop({ core: { invoke } });
    vi.spyOn(console, 'warn').mockImplementation(() => {});

    await revealPathInOS(FILE_PATH);
    await settle();

    expect((await toastsRaised())[0]).toMatchObject({ message: reason });
  });

  it('offers the path for copying, so the click is recoverable', async () => {
    const invoke = vi.fn().mockRejectedValue('nope');
    const { revealPathInOS } = await loadDesktop({ core: { invoke } });
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });

    await revealPathInOS(FILE_PATH);
    await settle();

    const action = (await toastsRaised())[0]?.action;
    expect(action).toBeDefined();
    action?.onClick();
    expect(writeText).toHaveBeenCalledWith(FILE_PATH);
  });

  it('reports a missing bridge too, which used to return false in silence', async () => {
    const { revealPathInOS } = await loadDesktop({});

    expect(await revealPathInOS(FILE_PATH)).toBe(false);
    await settle();

    expect(await toastsRaised()).toHaveLength(1);
  });

  it('does nothing in the web build, where there is no OS file manager to reach', async () => {
    const { revealPathInOS } = await loadDesktop(undefined);

    expect(await revealPathInOS(FILE_PATH)).toBe(false);
    await settle();

    expect(await toastsRaised()).toHaveLength(0);
  });
});
