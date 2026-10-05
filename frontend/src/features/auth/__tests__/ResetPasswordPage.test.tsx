// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

/**
 * The page the password-reset email opens.
 *
 * Before it existed the email linked to `/auth/reset?token=...`, no route
 * matched, and the catch-all inside the signed-in shell sent a signed-out
 * visitor to a sign-in form with the live token parked in `next=`. These
 * cases pin what the page does with the token it now receives: read it, send
 * it with the new password, take it out of the address bar, and never print
 * it.
 *
 * `t` echoes the key, so an assertion names the branch that ran rather than a
 * sentence a copy edit could move.
 */

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

vi.mock('@/app/i18n', () => ({
  SUPPORTED_LANGUAGES: [{ code: 'en', name: 'English', flag: 'gb', country: 'gb' }],
  getLanguageByCode: () => ({ code: 'en', name: 'English', flag: 'gb', country: 'gb' }),
}));

vi.mock('../AuthBackground', () => ({
  AuthBackground: () => null,
}));

import { ResetPasswordPage } from '../ResetPasswordPage';
import { useAuthStore } from '@/stores/useAuthStore';

const TOKEN = 'eyJhbGciOiJIUzI1NiJ9.reset-payload.sig-4f9c';
const RESET_ENDPOINT = '/api/v1/users/auth/reset-password/';

/** Renders the current location so a case can assert what the address bar holds. */
function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

function renderAt(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/auth/reset" element={<ResetPasswordPage />} />
        <Route path="/login" element={<div>LOGIN</div>} />
        <Route path="/forgot-password" element={<div>FORGOT</div>} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  );
}

function stubFetch(response: { status: number; body?: unknown }) {
  const fn = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({
    ok: response.status >= 200 && response.status < 300,
    status: response.status,
    json: async () => response.body ?? {},
  }));
  vi.stubGlobal('fetch', fn);
  return fn;
}

function fillAndSubmit(password: string, confirm: string) {
  fireEvent.change(screen.getByLabelText('auth.reset_new_password'), { target: { value: password } });
  fireEvent.change(screen.getByLabelText('auth.confirm_password'), { target: { value: confirm } });
  fireEvent.click(screen.getByRole('button', { name: /auth.reset_submit/ }));
}

const consoleSpies: ReturnType<typeof vi.spyOn>[] = [];

beforeEach(() => {
  for (const method of ['log', 'info', 'warn', 'error', 'debug'] as const) {
    consoleSpies.push(vi.spyOn(console, method));
  }
});

afterEach(() => {
  // Whatever happened in the case, the token never reached the console.
  for (const spy of consoleSpies) {
    for (const call of spy.mock.calls) {
      expect(JSON.stringify(call)).not.toContain(TOKEN);
    }
    spy.mockRestore();
  }
  consoleSpies.length = 0;
  vi.unstubAllGlobals();
});

describe('ResetPasswordPage', () => {
  it('reads the token from the query and takes it out of the address bar', async () => {
    stubFetch({ status: 200, body: { message: 'ok' } });
    renderAt(`/auth/reset?token=${TOKEN}`);

    expect(screen.getByText('auth.reset_title')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/auth/reset'));
  });

  it('keeps unrelated query parameters when it strips the token', async () => {
    stubFetch({ status: 200 });
    renderAt(`/auth/reset?token=${TOKEN}&lang=de`);
    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/auth/reset?lang=de'));
  });

  it('sends the token it read, even after the address bar no longer has it', async () => {
    const fetchMock = stubFetch({ status: 200, body: { message: 'ok' } });
    renderAt(`/auth/reset?token=${TOKEN}`);
    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/auth/reset'));

    fillAndSubmit('newpass123', 'newpass123');

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toBe(RESET_ENDPOINT);
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual({ token: TOKEN, new_password: 'newpass123' });
  });

  it('refuses mismatched passwords without calling the server', async () => {
    const fetchMock = stubFetch({ status: 200 });
    renderAt(`/auth/reset?token=${TOKEN}`);

    fillAndSubmit('newpass123', 'newpass124');

    expect(await screen.findByText('auth.passwords_no_match')).toBeInTheDocument();
    // The confirm field says so too, beside the field that differs.
    expect(screen.getByText('auth.passwords_mismatch')).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuses a password the server rules would reject without calling the server', async () => {
    const fetchMock = stubFetch({ status: 200 });
    renderAt(`/auth/reset?token=${TOKEN}`);

    fillAndSubmit('onlyletters', 'onlyletters');

    expect(await screen.findByRole('alert')).toHaveTextContent('auth.password_requirements');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('shows the success message and a way to sign in', async () => {
    stubFetch({ status: 200, body: { message: 'Password has been reset successfully.' } });
    renderAt(`/auth/reset?token=${TOKEN}`);

    fillAndSubmit('newpass123', 'newpass123');

    expect(await screen.findByText('auth.reset_success_title')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /auth.back_to_login/ })).toHaveAttribute('href', '/login');
    expect(screen.queryByLabelText('auth.reset_new_password')).not.toBeInTheDocument();
  });

  it('drops a signed-in session once the reset succeeds, and not before', async () => {
    const logout = vi.fn();
    const before = useAuthStore.getState();
    useAuthStore.setState({ isAuthenticated: true, logout });
    try {
      stubFetch({ status: 200, body: { message: 'ok' } });
      renderAt(`/auth/reset?token=${TOKEN}`);

      // Opening the link alone must not end anybody's session.
      expect(screen.getByText('auth.reset_title')).toBeInTheDocument();
      expect(logout).not.toHaveBeenCalled();

      fillAndSubmit('newpass123', 'newpass123');

      expect(await screen.findByText('auth.reset_success_title')).toBeInTheDocument();
      expect(logout).toHaveBeenCalledTimes(1);
    } finally {
      useAuthStore.setState({ isAuthenticated: before.isAuthenticated, logout: before.logout });
    }
  });

  it('sends an expired or used token to a fresh request, not to a retry', async () => {
    stubFetch({ status: 400, body: { detail: 'Invalid or expired reset token' } });
    renderAt(`/auth/reset?token=${TOKEN}`);

    fillAndSubmit('newpass123', 'newpass123');

    expect(await screen.findByText('auth.reset_link_invalid_title')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /auth.reset_request_new_link/ })).toHaveAttribute(
      'href',
      '/forgot-password',
    );
    // The server's English wording is not what the reader sees.
    expect(screen.queryByText('Invalid or expired reset token')).not.toBeInTheDocument();
  });

  it('treats a 422 on the token field as a broken link', async () => {
    stubFetch({
      status: 422,
      body: { detail: [{ loc: ['body', 'token'], msg: 'String should have at most 512 characters' }] },
    });
    renderAt(`/auth/reset?token=${TOKEN}`);

    fillAndSubmit('newpass123', 'newpass123');

    expect(await screen.findByText('auth.reset_link_invalid_title')).toBeInTheDocument();
  });

  it('explains a 422 on the password as a password the server will not take', async () => {
    stubFetch({
      status: 422,
      body: { detail: [{ loc: ['body', 'new_password'], msg: 'Value error, Password is too common' }] },
    });
    renderAt(`/auth/reset?token=${TOKEN}`);

    fillAndSubmit('password1', 'password1');

    expect(await screen.findByRole('alert')).toHaveTextContent('auth.password_too_common');
    // Still on the form, so the reader can pick another one with the same link.
    expect(screen.getByLabelText('auth.reset_new_password')).toBeInTheDocument();
  });

  it('opens on the broken-link state when the link carries no token', () => {
    const fetchMock = stubFetch({ status: 200 });
    renderAt('/auth/reset');

    expect(screen.getByText('auth.reset_link_invalid_title')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /auth.reset_request_new_link/ })).toHaveAttribute(
      'href',
      '/forgot-password',
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('reports a network failure as one, and keeps the form', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }));
    renderAt(`/auth/reset?token=${TOKEN}`);

    fillAndSubmit('newpass123', 'newpass123');

    expect(await screen.findByRole('alert')).toHaveTextContent('auth.server_error');
    expect(screen.getByLabelText('auth.reset_new_password')).toBeInTheDocument();
  });
});
