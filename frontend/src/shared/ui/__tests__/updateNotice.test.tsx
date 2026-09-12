// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The update notice reads GET /api/system/version-check, our own backend,
// rather than calling api.github.com from the browser. Four properties are
// pinned here, and they fail differently.
//
// * The answer comes from the server. The browser used to ask GitHub itself
//   on the anonymous per-IP limit, so an office behind one address got 403
//   for the rest of the hour and an air-gapped install needed a build flag to
//   stop it trying. The backend caches for four hours and answers offline.
//
// * A refusal is not re-asked. This is the property the old localStorage
//   cache existed for (see updateCheckerNegativeCache.test.ts, replaced by
//   this file); it now lives in the query's staleTime and retry:false, and it
//   still has to hold or the retry storm comes back.
//
// * Whether the build can upgrade itself is the server's answer, not the
//   client's guess. A frozen build has no pip, and it can be read from an
//   ordinary browser where the isTauri guess says otherwise, so a pip command
//   would be advice that cannot work (issue #403).
//
// * A dismissal is scoped to the version it dismissed, so the next release
//   speaks up again.
//
// Run:  npx vitest run src/shared/ui/__tests__/updateNotice.test.tsx
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { UpdateNotification } from '../UpdateChecker';

const DISMISS_KEY = 'oe_update_dismissed_version_session';
const ENDPOINT = '/api/system/version-check';

/** What the endpoint answers, with only the interesting field varied. */
function versionCheck(over: Record<string, unknown> = {}) {
  return {
    current_version: '15.0.0',
    latest_version: '15.1.0',
    update_available: true,
    release_url: 'https://github.com/datadrivenconstruction/OpenConstructionERP/releases/tag/v15.1.0',
    release_notes: '',
    published_at: '2026-08-19T09:00:00Z',
    assets: [],
    self_upgrade_supported: true,
    upgrade_command: 'pip install --upgrade openconstructionerp',
    ...over,
  };
}

function answering(body: unknown, status = 200): ReturnType<typeof vi.fn> {
  return vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }));
}

/** One client per render unless a test deliberately shares it, so a cached
 *  answer never leaks between cases. */
function renderNotice(client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <UpdateNotification />
      </QueryClientProvider>,
    ),
  };
}

/** Every URL the component asked for, in order. */
function urlsAsked(mock: ReturnType<typeof vi.fn>): string[] {
  return mock.mock.calls.map((c) => String(c[0]));
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('where the update notice gets its answer', () => {
  it('asks our own backend and never api.github.com', async () => {
    const fetchMock = answering(versionCheck());
    vi.stubGlobal('fetch', fetchMock);

    renderNotice();

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(urlsAsked(fetchMock)).toContain(ENDPOINT);
    expect(urlsAsked(fetchMock).some((u) => u.includes('api.github.com'))).toBe(false);
  });

  it('shows the newer version the server names', async () => {
    vi.stubGlobal('fetch', answering(versionCheck()));

    renderNotice();

    expect(await screen.findByText(/v15\.0\.0.*v15\.1\.0/)).toBeTruthy();
  });

  it('says nothing at all when the server says there is no update', async () => {
    vi.stubGlobal('fetch', answering(versionCheck({ update_available: false })));

    const { container } = renderNotice();

    await waitFor(() => expect(container.textContent).toBe(''));
  });

  it('says nothing when the endpoint fails, and does not ask again', async () => {
    const fetchMock = answering({ detail: 'nope' }, 500);
    vi.stubGlobal('fetch', fetchMock);

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const first = renderNotice(client);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(first.container.textContent).toBe('');
    first.unmount();

    // A second mount inside the stale window - another route, the About page -
    // reads the answer already held rather than repeating a request that an
    // air-gapped install will never be able to satisfy.
    renderNotice(client);
    await waitFor(() => expect(screen.queryByText(/15\.1\.0/)).toBeNull());
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('survives a refused connection with nothing on screen', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }));

    const { container } = renderNotice();

    await waitFor(() => expect(container.textContent).toBe(''));
  });

  it('does not draw half an arrow when the running version is missing', async () => {
    // Everything else about the answer is usable, so the notice still shows -
    // but "v → v15.1.0" is not a sentence, and the version the reader is on
    // is the half we can do without.
    vi.stubGlobal('fetch', answering(versionCheck({ current_version: '' })));

    renderNotice();

    await screen.findByText('v15.1.0');
    expect(document.body.textContent).not.toContain('v →');
  });

  it('ignores a body that is not the shape it expects', async () => {
    // A proxy answering 200 with its own login page, or an endpoint that
    // changed under us. Nothing renders rather than "v undefined".
    vi.stubGlobal('fetch', answering({ hello: 'world' }));

    const { container } = renderNotice();

    await waitFor(() => expect(container.textContent).toBe(''));
  });
});

describe('the advice matches the build the reader is running', () => {
  it('does not print a pip command to a build that has no pip', async () => {
    vi.stubGlobal(
      'fetch',
      answering(
        versionCheck({
          self_upgrade_supported: false,
          upgrade_command: 'Download and run the latest installer',
        }),
      ),
    );

    renderNotice();

    const card = await screen.findByRole('button', { name: /15\.1\.0/ });
    fireEvent.click(card);

    await screen.findByText('update.method_installer');
    expect(document.body.textContent).not.toContain('pip install');
  });

  it('gives the desktop reader a route and not only a sentence', async () => {
    // The remedy for a frozen build is a page, so the instruction has to carry
    // the way there. A link in the footer labelled "Release notes" is not it:
    // somebody told to download an installer should not have to work out that
    // the notes link is the page holding it.
    vi.stubGlobal(
      'fetch',
      answering(
        versionCheck({
          self_upgrade_supported: false,
          release_url: 'https://github.com/datadrivenconstruction/OpenConstructionERP/releases',
        }),
      ),
    );

    renderNotice();

    const card = await screen.findByRole('button', { name: /15\.1\.0/ });
    fireEvent.click(card);

    const advice = await screen.findByText('update.method_installer_advice');
    const section = advice.closest('section');
    const link = section?.querySelector('a[href]');
    expect(link?.getAttribute('href')).toBe(
      'https://github.com/datadrivenconstruction/OpenConstructionERP/releases',
    );
  });

  it('prints the command the server gave when the build can upgrade itself', async () => {
    vi.stubGlobal('fetch', answering(versionCheck()));

    renderNotice();

    const card = await screen.findByRole('button', { name: /15\.1\.0/ });
    fireEvent.click(card);

    await waitFor(() =>
      expect(document.body.textContent).toContain('pip install --upgrade openconstructionerp'),
    );
  });
});

describe('the excerpt reads as prose', () => {
  // A release body is a paragraph followed by the list GitHub generates from
  // the commits. The highlight parser drops a bullet longer than 280
  // characters, and a generated line carrying a commit subject and a compare
  // link runs past that easily - so this body parses to no highlights at all
  // and falls through to the excerpt, which is where the raw line would be
  // read back to the user as if it were a sentence.
  const LONG_BULLET =
    '* fix(gaeb): see https://github.com/datadrivenconstruction/OpenConstructionERP/pull/1 - ' +
    'the export summary stops claiming prices a bill does not have. '.repeat(4);

  it('quotes the paragraph without the generated commit list', async () => {
    const notes = ['## [15.1.0] - 2026-08-19', '', 'A maintenance release. Nothing in it changes how a bill is priced.', '', LONG_BULLET].join(
      '\n',
    );
    vi.stubGlobal('fetch', answering(versionCheck({ release_notes: notes })));

    renderNotice();

    const card = await screen.findByRole('button', { name: /15\.1\.0/ });
    fireEvent.click(card);

    const paragraph = await screen.findByText(/A maintenance release/);
    expect(paragraph.textContent).not.toContain('://');
    expect(paragraph.textContent).not.toContain('fix(gaeb)');
    // The sentence was whole in the body, so it is whole on screen.
    expect(paragraph.textContent).toContain('how a bill is priced.');
  });
});

describe('a dismissal is about one version', () => {
  it('stays hidden for the version that was dismissed', async () => {
    vi.stubGlobal('fetch', answering(versionCheck()));

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const first = renderNotice(client);
    await screen.findByText(/v15\.1\.0/);

    // The test setup's i18n mock renders a key's defaultValue, so this button
    // reads "Dismiss" rather than its key.
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    await waitFor(() => expect(screen.queryByText(/v15\.1\.0/)).toBeNull());
    expect(localStorage.getItem(DISMISS_KEY)).toBe('15.1.0');
    first.unmount();

    renderNotice(client);
    await waitFor(() => expect(screen.queryByText(/v15\.1\.0/)).toBeNull());
  });

  it('speaks up again when a later version appears', async () => {
    localStorage.setItem(DISMISS_KEY, '15.1.0');
    vi.stubGlobal('fetch', answering(versionCheck({ latest_version: '15.2.0' })));

    renderNotice();

    expect(await screen.findByText(/v15\.2\.0/)).toBeTruthy();
  });
});

describe('the download offered is the one this machine can run', () => {
  // A release carries every platform at once, so "open the release page" asks
  // somebody who cannot upgrade in place to work out which of six files is
  // theirs. Picking it is the whole point, and picking it wrongly is worse
  // than not picking: a file that will not run, chosen by us, on their behalf.
  const REAL_UA = navigator.userAgent;

  function usingUserAgent(ua: string): void {
    Object.defineProperty(window.navigator, 'userAgent', {
      value: ua,
      configurable: true,
    });
  }

  /** The installer link inside the "how to update" card, or null. */
  async function downloadHref(): Promise<string | null> {
    const card = await screen.findByRole('button', { name: /15\.1\.0/ });
    fireEvent.click(card);
    await screen.findByText('update.method_installer');
    const label = screen.queryByText('update.download_installer');
    return label ? (label.closest('a')?.getAttribute('href') ?? null) : null;
  }

  /** The release page link inside the same card. Reads only, so a test that
   *  wants both hrefs calls `downloadHref` first and leaves the card open. */
  function releasePageHref(): string | null {
    const label = screen.queryByText('update.open_release_page');
    return label ? (label.closest('a')?.getAttribute('href') ?? null) : null;
  }

  /** Every asset Desktop Release can produce for one version. Declared as its
   *  own const rather than inline, so a test can hand over a subset and still
   *  be type checked: `versionCheck` takes loose overrides, and an asset list
   *  built inside that call arrives as an array of nothing in particular. */
  const ALL_ASSETS = [
    { name: 'OpenConstructionERP_15.1.0_aarch64.app.tar.gz', url: 'https://x.test/mac-updater', size: 700 },
    { name: 'OpenConstructionERP_15.1.0_aarch64.dmg', url: 'https://x.test/mac-dmg', size: 734003200 },
    { name: 'OpenConstructionERP_15.1.0_x64-setup.exe.sig', url: 'https://x.test/win-sig', size: 500 },
    { name: 'OpenConstructionERP_15.1.0_x64-setup.exe', url: 'https://x.test/win-exe', size: 629145600 },
    { name: 'open-construction-erp_15.1.0_amd64.deb', url: 'https://x.test/linux-deb', size: 650000000 },
    { name: 'OpenConstructionERP_15.1.0_amd64.AppImage', url: 'https://x.test/linux-appimage', size: 660000000 },
    { name: 'open-construction-erp-15.1.0.x86_64.rpm', url: 'https://x.test/linux-rpm', size: 655000000 },
  ];

  /** A release that published exactly these assets and nothing else. */
  function releaseWith(assets: typeof ALL_ASSETS) {
    return versionCheck({ self_upgrade_supported: false, assets });
  }

  /** A release that published every asset Desktop Release can produce. */
  function fullRelease() {
    return releaseWith(ALL_ASSETS);
  }

  afterEach(() => {
    Object.defineProperty(window.navigator, 'userAgent', {
      value: REAL_UA,
      configurable: true,
    });
  });

  it('hands a Mac the .dmg and not the updater bundle beside it', async () => {
    // `.app.tar.gz` is what the updater consumes, not what a person installs.
    // A substring test for "dmg" would be fine here and a suffix test is not
    // the same thing: it is the one that keeps the tarball from answering.
    usingUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15');
    vi.stubGlobal('fetch', answering(fullRelease()));

    renderNotice();

    expect(await downloadHref()).toBe('https://x.test/mac-dmg');
  });

  it('hands Windows the installer and not the signature next to it', async () => {
    usingUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36');
    vi.stubGlobal('fetch', answering(fullRelease()));

    renderNotice();

    expect(await downloadHref()).toBe('https://x.test/win-exe');
  });

  it('prefers the AppImage on Linux, where one button has three candidates', async () => {
    // `.deb` is Debian and Ubuntu; the AppImage runs anywhere, so it is the
    // one choice that cannot be wrong for a distribution we did not ask about.
    usingUserAgent('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36');
    vi.stubGlobal('fetch', answering(fullRelease()));

    renderNotice();

    expect(await downloadHref()).toBe('https://x.test/linux-appimage');
  });

  it('offers no download at all when the release published none', async () => {
    // An older backend answers no assets, and a release can genuinely carry
    // none. Both have to end at the release page rather than at a button
    // pointing nowhere.
    usingUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36');
    vi.stubGlobal('fetch', answering(versionCheck({ self_upgrade_supported: false })));

    renderNotice();

    expect(await downloadHref()).toBeNull();
    expect(await screen.findByText('update.method_installer_advice')).toBeTruthy();
    expect(releasePageHref()).toContain('/releases/tag/v15.1.0');
  });

  it('takes the package that is there when the preferred one is not', async () => {
    // The .rpm is allowed to be missing from a release: its build can run for
    // hours and is permitted to miss the deadline. The same is true of any
    // one package, so the Linux list is a preference and not a promise, and
    // the proof of that is a release where the first choice is simply absent.
    usingUserAgent('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36');
    const noAppImage = ALL_ASSETS.filter((a) => !a.name.endsWith('.AppImage'));
    vi.stubGlobal('fetch', answering(releaseWith(noAppImage)));

    renderNotice();

    expect(await downloadHref()).toBe('https://x.test/linux-deb');
  });

  it('sends a reader whose platform published nothing to the release page', async () => {
    // Not the same case as a release with no assets at all: here the loop runs
    // over six real files and matches none of them. It has to end where the
    // empty release ends, at a working link, rather than at a button wired to
    // undefined.
    usingUserAgent('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36');
    const noLinux = ALL_ASSETS.filter((a) => !/\.(AppImage|deb|rpm)$/.test(a.name));
    vi.stubGlobal('fetch', answering(releaseWith(noLinux)));

    renderNotice();

    expect(await downloadHref()).toBeNull();
    expect(releasePageHref()).toContain('/releases/tag/v15.1.0');
    expect(screen.getByText('update.method_installer_advice')).toBeTruthy();
  });

  it('offers no download to a phone, whose user agent names a desktop OS', async () => {
    // An iPhone's user agent contains "Mac OS X" and an Android's contains
    // "Linux". Matched in the wrong order, both are handed an installer for a
    // computer they are not sitting at.
    usingUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15');
    vi.stubGlobal('fetch', answering(fullRelease()));

    renderNotice();

    expect(await downloadHref()).toBeNull();
  });
});
