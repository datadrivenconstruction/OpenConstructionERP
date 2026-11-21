// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One outbound connection, one switch for it, and one sentence that says which
 * way the switch is.
 *
 * Asking PyPI and GitHub which release is newest used to happen in every install
 * nobody had configured, because both switches that stopped it - an operator's
 * `OE_DISABLE_UPDATE_CHECK` and the desktop launcher's opt-out file - were
 * opt-outs somebody had to find first. The workspace setting is an opt-in now, and
 * the backend holds that down in
 * `backend/tests/unit/test_the_version_check_is_off_until_an_administrator_turns_it_on.py`.
 *
 * What only a browser-side test can hold down is the other three quarters of it:
 *
 *   * that the two places which describe the behaviour - About, where every user is
 *     told, and Settings, where an administrator decides - render the same sentence
 *     and not two paraphrases that drift apart. A privacy statement that has drifted
 *     is worse than one that is missing, because it is still read as accurate;
 *   * that the switch is an administrator's and that a refused write is taken back.
 *     A box that stays ticked after the server said no tells one administrator the
 *     workspace is asking when it is not;
 *   * and that "off" means no request is made at all, not even to our own backend.
 *     The server would answer it without reaching anywhere, so this is the difference
 *     between "nothing leaves" and "nothing leaves past us" - and About promises the
 *     first.
 *
 * The i18n mock in src/test/setup.ts returns the defaultValue with its
 * placeholders filled in, so the English copy below is what renders here.
 */
import type { ReactElement } from 'react';
import { beforeEach, describe, expect, it, vi, afterEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const apiPut = vi.hoisted(() => vi.fn());
const apiGet = vi.hoisted(() => vi.fn());
const fetchMock = vi.hoisted(() => vi.fn());

// Partial mock, as in CompanyDocumentsSettings.test.tsx: the shared UI barrel
// drags in components that read API_BASE or ApiError at module-eval time, and the
// branding store's server sync goes through these. Nothing here reaches a network
// except through `fetchMock`, which is the point of the last test.
vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/api')>();
  return { ...actual, apiGet, apiPut };
});

import { AboutPage } from '@/features/about/AboutPage';
import { UpdateCheckCard } from '@/features/settings/UpdateCheckCard';
import { useUpdateCheck } from '@/shared/ui/UpdateChecker';
import { useAuthStore } from '@/stores/useAuthStore';
import { useBrandingStore } from '@/stores/useBrandingStore';
import { useToastStore } from '@/stores/useToastStore';

const OFF = 'This installation does not check the internet for a newer version of the product.';
const ON = 'Asks PyPI and GitHub which version is the latest. Nothing about you is sent.';

function renderIn(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

/** What the sidebar's badge renders, so the query under test really runs. */
function UpdateCheckProbe() {
  useUpdateCheck();
  return null;
}

/** The version a notice would offer, or `none` when there is nothing to offer. */
function OfferedVersion() {
  const update = useUpdateCheck();
  return <span data-testid="offered">{update ? update.latest_version : 'none'}</span>;
}

function switchOf(): HTMLInputElement {
  const input = screen.getByTestId('update-check-enabled');
  if (!(input instanceof HTMLInputElement)) throw new Error('the switch is not an input');
  return input;
}

beforeEach(() => {
  vi.clearAllMocks();
  apiPut.mockResolvedValue(undefined);
  apiGet.mockResolvedValue({});
  fetchMock.mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ current_version: '1.0.0', latest_version: '1.0.0', update_available: false }),
  });
  vi.stubGlobal('fetch', fetchMock);
  useAuthStore.setState({ userRole: 'admin' });
  useBrandingStore.setState({
    supportDestination: null,
    legalLinkVisible: true,
    updateCheckEnabled: false,
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('the version check is off until the workspace asks', () => {
  it('says so on About, plainly', () => {
    renderIn(<AboutPage />);

    expect(screen.getByTestId('about-update-check').textContent).toBe(OFF);
  });

  it('says the same sentence in Settings, because it is the same string', () => {
    renderIn(<UpdateCheckCard />);

    expect(screen.getByTestId('update-check-disclosure').textContent).toBe(OFF);
    expect(screen.getByTestId('update-check-enabled')).not.toBeChecked();
  });

  it('says what it asks in both places once the workspace has asked', () => {
    useBrandingStore.setState({ updateCheckEnabled: true });

    const about = renderIn(<AboutPage />);
    expect(about.getByTestId('about-update-check').textContent).toBe(ON);
    about.unmount();

    const settings = renderIn(<UpdateCheckCard />);
    expect(settings.getByTestId('update-check-disclosure').textContent).toBe(ON);
    expect(settings.getByTestId('update-check-enabled')).toBeChecked();
  });

  it('gives the switch to an administrator and leaves a viewer a readable page', () => {
    useAuthStore.setState({ userRole: 'viewer' });
    renderIn(<UpdateCheckCard />);

    // Not hidden: a viewer who cannot see the setting cannot check the disclosure
    // against it, and a greyed-out box beside the sentence says who decides.
    expect(switchOf()).toBeDisabled();
    expect(screen.getByTestId('update-check-disclosure').textContent).toBe(OFF);
  });

  it('lets a manager read it and not move it, as the server would', () => {
    useAuthStore.setState({ userRole: 'manager' });
    renderIn(<UpdateCheckCard />);

    expect(switchOf()).toBeDisabled();
  });

  it('takes the switch back when the workspace refuses it', async () => {
    apiPut.mockRejectedValue(new Error('403'));
    const addToast = vi.spyOn(useToastStore.getState(), 'addToast');
    renderIn(<UpdateCheckCard />);

    await act(async () => {
      fireEvent.click(switchOf());
    });

    // Left ticked, this would tell one administrator that the workspace is asking
    // when the workspace said no - the same reason a refused Legal-link change is
    // reverted rather than kept locally.
    await waitFor(() => expect(switchOf()).not.toBeChecked());
    expect(useBrandingStore.getState().updateCheckEnabled).toBe(false);
    expect(addToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'warning' }));
  });

  it('keeps the switch when the workspace accepts it', async () => {
    const addToast = vi.spyOn(useToastStore.getState(), 'addToast');
    renderIn(<UpdateCheckCard />);

    await act(async () => {
      fireEvent.click(switchOf());
    });

    await waitFor(() => expect(switchOf()).toBeChecked());
    expect(apiPut).toHaveBeenCalledWith(
      '/v1/branding/',
      expect.objectContaining({ update_check_enabled: true }),
    );
    expect(addToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' }));
  });

  it('makes no request at all while the setting is off', async () => {
    renderIn(<UpdateCheckProbe />);

    // Not "no request leaves the server": no request leaves this browser, so the
    // backend is never asked and never gets the chance to ask PyPI or GitHub.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 25));
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('asks its own backend once the workspace has asked', async () => {
    useBrandingStore.setState({ updateCheckEnabled: true });
    renderIn(<UpdateCheckProbe />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const url = String(fetchMock.mock.calls[0]![0]);
    expect(url).toContain('/api/system/version-check');
  });

  it('takes an update already offered away when the workspace turns the check off', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ current_version: '18.1.0', latest_version: '18.2.0', update_available: true }),
    });
    useBrandingStore.setState({ updateCheckEnabled: true });
    renderIn(<OfferedVersion />);

    await waitFor(() => expect(screen.getByTestId('offered').textContent).toBe('18.2.0'));
    const asked = fetchMock.mock.calls.length;

    // Disabling a query stops the next fetch and leaves the cached answer where it
    // is, so a notice that survived the switch would be a notice outliving the
    // decision that stopped it.
    await act(async () => {
      useBrandingStore.setState({ updateCheckEnabled: false });
    });

    expect(screen.getByTestId('offered').textContent).toBe('none');
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 25));
    });
    expect(fetchMock.mock.calls.length).toBe(asked);
  });
});
