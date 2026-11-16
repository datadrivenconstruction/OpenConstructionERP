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

/**
 * Every outbound link in the header menus, on both builds.
 *
 * The bug menu was reported with all of its links dead on the desktop app. The
 * menus reach the outside world two ways: buttons that call `openLink`, and
 * plain anchors that rely on the capture-phase handler from
 * `installDesktopExternalLinks`. Both are pinned here, because the handler had
 * no test at all and a regression in it would silence every anchor at once.
 */
describe('outbound links from the header menus', () => {
  const MAIL =
    'mailto:info@datadrivenconstruction.io?subject=OpenConstructionERP%20Issue&body=I%20clicked%20Install';
  const FORM = 'https://openconstructionerp.com/contact.html?report=true&app_version=18.5.0';
  const ISSUE = 'https://github.com/datadrivenconstruction/OpenConstructionERP/issues/new?title=x&body=y';

  it('hands every external link and mail link to the OS opener on desktop', async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    const { openLink } = await loadDesktop({ core: { invoke } });

    for (const url of [MAIL, FORM, ISSUE]) openLink(url);
    await settle();

    expect(invoke.mock.calls).toEqual([
      ['open_external_url', { url: MAIL }],
      ['open_external_url', { url: FORM }],
      ['open_external_url', { url: ISSUE }],
    ]);
  });

  it('opens a real tab in the web build and never asks a bridge that is not there', async () => {
    const { openLink } = await loadDesktop(undefined);
    const clicked: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(`${this.target} ${this.href}`);
    });

    openLink(FORM);

    expect(clicked).toEqual([`_blank ${FORM}`]);
  });

  it('routes plain anchors through the opener on desktop and leaves app routes alone', async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    const { installDesktopExternalLinks } = await loadDesktop({ core: { invoke } });
    delete (window as { __oeExternalLinks?: boolean }).__oeExternalLinks;
    installDesktopExternalLinks();

    const links: Array<[string, string]> = [
      ['https://openconstructionerp.com/docs', '_blank'],
      ['https://github.com/datadrivenconstruction/OpenConstructionERP', '_blank'],
      ['mailto:info@datadrivenconstruction.io?subject=OpenConstructionERP%20Issue%20Report', ''],
      ['/how-it-works', ''],
    ];
    const anchors = links.map(([href, target]) => {
      const a = document.createElement('a');
      a.href = href;
      if (target) a.target = target;
      // Clicks land on the icon or the label inside the anchor, not on it.
      const label = document.createElement('span');
      a.appendChild(label);
      document.body.appendChild(a);
      return label;
    });

    const prevented = anchors.map((label) => {
      const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
      label.dispatchEvent(event);
      return event.defaultPrevented;
    });
    await settle();

    expect(prevented).toEqual([true, true, true, false]);
    expect(invoke.mock.calls.map((call) => (call[1] as { url: string }).url)).toEqual([
      'https://openconstructionerp.com/docs',
      'https://github.com/datadrivenconstruction/OpenConstructionERP',
      'mailto:info@datadrivenconstruction.io?subject=OpenConstructionERP%20Issue%20Report',
    ]);
    anchors.forEach((label) => label.parentElement?.remove());
  });
});

/**
 * The shell plugin injects its own link opener into every page of the window:
 * a bubble-phase click listener on <body> that hands any target="_blank" http,
 * https, mailto or tel anchor to `plugin:shell|open`, whether or not the click
 * was already handled. The application window is a remote origin that is not
 * granted that command, so each such click raised "shell.open not allowed" and
 * a same-origin link such as the manual did nothing else at all. This stands in
 * for that listener, with the plugin's own test.
 */
function installShellPluginLinkOpener(invoke: (cmd: string, args: unknown) => void) {
  const listener = (e: Event) => {
    const a = (e.target as Element | null)?.closest?.('a') as HTMLAnchorElement | null;
    if (!a) return;
    if (a.href !== '' && ['http://', 'https://', 'mailto:', 'tel:'].some((v) => a.href.startsWith(v)) && a.target === '_blank') {
      invoke('plugin:shell|open', { path: a.href });
      e.preventDefault();
    }
  };
  document.body.addEventListener('click', listener);
  return () => document.body.removeEventListener('click', listener);
}

describe('the shell plugin link opener in the application window', () => {
  it('never sees a link the application already handed to its own command', async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    const { installDesktopExternalLinks } = await loadDesktop({ core: { invoke } });
    delete (window as { __oeExternalLinks?: boolean }).__oeExternalLinks;
    installDesktopExternalLinks();
    const pluginCalls: string[] = [];
    const uninstall = installShellPluginLinkOpener((cmd) => pluginCalls.push(cmd));

    const make = (href: string) => {
      const a = document.createElement('a');
      a.href = href;
      a.target = '_blank';
      const closeMenu = vi.fn();
      a.addEventListener('click', closeMenu);
      document.body.appendChild(a);
      return { a, closeMenu };
    };
    const external = make('https://openconstructionerp.com/docs');
    const manual = make(`${window.location.origin}/docs/user-manual.pdf`);
    for (const { a } of [external, manual]) {
      a.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    }
    await settle();

    expect(pluginCalls).toEqual([]);
    expect(invoke.mock.calls.map((call) => call[0])).toEqual(['open_external_url', 'open_app_in_browser']);
    expect(invoke.mock.calls[1]?.[1]).toEqual({ path: '/docs/user-manual.pdf' });
    // The component's own handler (closing the menu) still runs, and the anchor keeps its target.
    expect(external.closeMenu).toHaveBeenCalledTimes(1);
    expect(manual.closeMenu).toHaveBeenCalledTimes(1);
    expect(external.a.target).toBe('_blank');
    uninstall();
    external.a.remove();
    manual.a.remove();
  });
});
