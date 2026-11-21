// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The three workspace settings that ride the branding record: where a bug report
 * is sent, whether the footers point at /legal, and whether this workspace asks
 * the internet which release is newest.
 *
 * All three are server-backed and none belongs in the localStorage mirror, and the
 * interesting failure is not a wrong value - it is a right value that never
 * arrives. `hydrateFromServer` compares the four mirrored brand fields and
 * returns early when they are unchanged, which is the common case: an operator
 * who sets a support destination has usually not touched the logo. Anything
 * applied after that comparison is silently dropped on every load, so the first
 * tests below hydrate with the brand deliberately unchanged.
 *
 * The version check is the one of the three that defaults to off, and its
 * ambiguity rule is the mirror image of the Legal link's: only an exact `true`
 * starts it. A browser that remembered "on" would keep asking after an
 * administrator turned it off, which is why it is server-backed like the other
 * two and mirrored like neither.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiGet = vi.hoisted(() => vi.fn());
const apiPut = vi.hoisted(() => vi.fn());

vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/api')>();
  return { ...actual, apiGet, apiPut };
});

import { useBrandingStore, type SupportDestination } from '../useBrandingStore';

const STORAGE_KEY = 'oe_custom_branding_v1';
const MAILBOX: SupportDestination = { kind: 'email', value: 'support@builder.example' };

/** The four mirrored brand fields, held constant so only the settings can move. */
const UNCHANGED_BRAND = {
  mode: 'text' as const,
  logoDataUrl: null,
  logoPngDataUrl: null,
  companyName: 'Meridian Construction',
};

/** The same brand as the server spells it. Both must agree or `hydrateFromServer`
 *  sees a brand change, skips its early return, and the two settings would be
 *  applied by the fall-through path - passing the test while proving nothing
 *  about the case that actually happens in the field. */
const UNCHANGED_BRAND_ON_SERVER = {
  mode: 'text',
  logo_data_url: null,
  logo_png_data_url: null,
  company_name: 'Meridian Construction',
};

function serve(payload: Record<string, unknown>) {
  apiGet.mockResolvedValue({ ...UNCHANGED_BRAND_ON_SERVER, ...payload });
}

beforeEach(() => {
  localStorage.clear();
  apiGet.mockReset();
  apiPut.mockReset();
  apiPut.mockResolvedValue(undefined);
  useBrandingStore.setState({
    ...UNCHANGED_BRAND,
    supportDestination: null,
    legalLinkVisible: true,
    updateCheckEnabled: false,
  });
});

describe('the branding store carries the three workspace settings', () => {
  it('applies a support destination when nothing about the brand changed', async () => {
    serve({ support_destination: MAILBOX });

    await useBrandingStore.getState().hydrateFromServer();

    expect(useBrandingStore.getState().supportDestination).toEqual(MAILBOX);
    // And the early return really was the path taken: it skips the write to
    // localStorage, so an untouched cache is the observable proof that the brand
    // looked unchanged and only the setting moved.
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('applies a Legal-link change on its own, with the brand unchanged', async () => {
    serve({ legal_link_visible: false });

    await useBrandingStore.getState().hydrateFromServer();

    expect(useBrandingStore.getState().legalLinkVisible).toBe(false);
  });

  it('keeps all three out of the localStorage mirror', async () => {
    // With a brand change as well, so the mirror is genuinely written: what the
    // test is about is what lands in that cache, not whether it lands at all.
    serve({
      company_name: 'Changed Name',
      support_destination: MAILBOX,
      legal_link_visible: false,
      update_check_enabled: true,
    });

    await useBrandingStore.getState().hydrateFromServer();

    const raw = localStorage.getItem(STORAGE_KEY);
    expect(raw).not.toBeNull();
    const cached = JSON.parse(raw!) as Record<string, unknown>;
    // Exactly the four brand fields. A workspace decision cached in one browser
    // can outlive the decision itself, and would then be served to the next
    // person who signs in on that machine before the fetch lands.
    expect(Object.keys(cached).sort()).toEqual(['companyName', 'logoDataUrl', 'logoPngDataUrl', 'mode']);
    expect(cached.companyName).toBe('Changed Name');
    // ...while both settings did reach the store, so this is not passing because
    // hydration silently dropped everything.
    expect(useBrandingStore.getState().supportDestination).toEqual(MAILBOX);
    expect(useBrandingStore.getState().legalLinkVisible).toBe(false);
    expect(useBrandingStore.getState().updateCheckEnabled).toBe(true);
  });

  it('sends all three in the PUT that makes a change workspace-wide', async () => {
    useBrandingStore.setState({
      supportDestination: MAILBOX,
      legalLinkVisible: false,
      updateCheckEnabled: true,
    });

    const ok = await useBrandingStore.getState().persistToServer();

    expect(ok).toBe(true);
    expect(apiPut).toHaveBeenCalledTimes(1);
    const [path, body] = apiPut.mock.calls[0]! as [string, Record<string, unknown>];
    expect(path).toBe('/v1/branding/');
    expect(body.support_destination).toEqual(MAILBOX);
    expect(body.legal_link_visible).toBe(false);
    expect(body.update_check_enabled).toBe(true);
    // The brand still travels with them: the server merges by fields set, so a
    // payload that omitted the logo would not clear it, but one that omits these
    // three would leave a stale destination in place.
    expect(body.company_name).toBe(UNCHANGED_BRAND.companyName);
  });

  it('treats a destination it cannot use as no destination at all', async () => {
    for (const junk of [
      { kind: 'gopher', value: 'gopher://builder.example' },
      { kind: 'url', value: '   ' },
      { kind: 'url' },
      { value: 'https://support.builder.example' },
      'https://support.builder.example',
    ]) {
      serve({ support_destination: junk });
      await useBrandingStore.getState().hydrateFromServer();
      // Null hides the channel. Rendering a channel that cannot carry a report
      // is worse than no channel: it invites the user to write one.
      expect(useBrandingStore.getState().supportDestination).toBeNull();
    }
  });

  it('hides the Legal link only on an exact false', async () => {
    // Anything ambiguous falls to the safe default, which is to show the link:
    // the licence position is not something a corrupt file gets to decide.
    for (const odd of [undefined, null, 'no', 0, 'false']) {
      serve({ legal_link_visible: odd });
      await useBrandingStore.getState().hydrateFromServer();
      expect(useBrandingStore.getState().legalLinkVisible).toBe(true);
    }
    serve({ legal_link_visible: false });
    await useBrandingStore.getState().hydrateFromServer();
    expect(useBrandingStore.getState().legalLinkVisible).toBe(false);
  });

  it('asks only on an exact true, which is the Legal link rule read backwards', async () => {
    // Anything ambiguous leaves the product silent. The direction that needs
    // permission here is the outbound one, so a missing key, a hand-edited "yes"
    // and a number all answer off - the opposite of the flag above, on purpose.
    for (const odd of [undefined, null, 'yes', 1, 'true']) {
      serve({ update_check_enabled: odd });
      await useBrandingStore.getState().hydrateFromServer();
      expect(useBrandingStore.getState().updateCheckEnabled).toBe(false);
    }
    serve({ update_check_enabled: true });
    await useBrandingStore.getState().hydrateFromServer();
    expect(useBrandingStore.getState().updateCheckEnabled).toBe(true);
  });

  it('applies a version-check change on its own, with the brand unchanged', async () => {
    serve({ update_check_enabled: true });

    await useBrandingStore.getState().hydrateFromServer();

    expect(useBrandingStore.getState().updateCheckEnabled).toBe(true);
    // The early return was still the path taken, so this is the case that happens
    // in the field: an administrator turned one setting on and touched no logo.
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('leaves all three alone when the server cannot be reached', async () => {
    useBrandingStore.setState({
      supportDestination: MAILBOX,
      legalLinkVisible: false,
      updateCheckEnabled: true,
    });
    apiGet.mockRejectedValue(new Error('offline'));

    await expect(useBrandingStore.getState().hydrateFromServer()).resolves.toBeUndefined();

    // The desktop build and an offline laptop both land here. Keeping what was
    // already known beats resetting a workspace setting to its default because
    // one fetch failed.
    expect(useBrandingStore.getState().supportDestination).toEqual(MAILBOX);
    expect(useBrandingStore.getState().legalLinkVisible).toBe(false);
    expect(useBrandingStore.getState().updateCheckEnabled).toBe(true);
  });

  it('says a change did not reach the workspace when the PUT is refused', async () => {
    apiPut.mockRejectedValue(new Error('403'));
    useBrandingStore.setState({ legalLinkVisible: false });

    const ok = await useBrandingStore.getState().persistToServer();

    expect(ok).toBe(false);
  });
});
