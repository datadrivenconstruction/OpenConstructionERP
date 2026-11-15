import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { name?: string }) => (opts?.name ? `${key}:${opts.name}` : key),
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

vi.mock('@/shared/ui', () => ({
  Button: ({ children, onClick }: { children: React.ReactNode; onClick?: () => void }) => (
    <button onClick={onClick}>{children}</button>
  ),
}));

import { SsoButtons, SSO_OIDC_CALLBACK } from '../SsoButtons';
import { SsoCallback } from '../SsoCallback';
import { useAuthStore } from '@/stores/useAuthStore';

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, '', '/');
});

function stubFetch(body: unknown, ok = true) {
  const fn = vi.fn(() => Promise.resolve({ ok, json: async () => body }));
  vi.stubGlobal('fetch', fn);
  return fn;
}

describe('SsoButtons', () => {
  it('shows one button per enabled provider', async () => {
    stubFetch({
      providers: [
        { slug: 'corp', display_name: 'Corp', protocol: 'saml', login_url: '/api/v1/sso/saml/corp/login/' },
        { slug: 'oidc', display_name: 'Entra', protocol: 'oidc', login_url: null },
      ],
    });
    render(<SsoButtons showDivider />);
    expect(await screen.findByText('sso.login_with:Corp')).toBeTruthy();
    expect(screen.getByText('sso.login_with:Entra')).toBeTruthy();
  });

  it('renders nothing without providers or when the request fails', async () => {
    stubFetch({}, false);
    const { container } = render(<SsoButtons showDivider />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(container.textContent).toBe('');
  });

  it('keeps the redirect URI that IdP registrations already use', () => {
    expect(SSO_OIDC_CALLBACK).toBe('/auth/oidc/callback');
  });
});

describe('SsoCallback', () => {
  it('exchanges the SAML hand-off code and stores the tokens', async () => {
    const setTokens = vi.fn();
    useAuthStore.setState({ setTokens } as never);
    const fetchFn = stubFetch({ access_token: 'a', refresh_token: 'r' });
    window.history.replaceState(null, '', '/auth/sso/complete#code=corp.abcdefghijklmnop');
    render(
      <MemoryRouter initialEntries={['/auth/sso/complete']}>
        <SsoCallback mode="saml" />
      </MemoryRouter>,
    );
    await waitFor(() => expect(setTokens).toHaveBeenCalled());
    expect(setTokens.mock.calls[0]!.slice(0, 2)).toEqual(['a', 'r']);
    expect(fetchFn).toHaveBeenCalledWith('/api/v1/sso/handoff/', expect.objectContaining({ method: 'POST' }));
    expect(window.location.hash).toBe('');
  });

  it('shows the translated error the ACS sent back', async () => {
    stubFetch({});
    render(
      <MemoryRouter initialEntries={['/auth/sso/complete?error=account_link_refused']}>
        <SsoCallback mode="saml" />
      </MemoryRouter>,
    );
    expect(await screen.findByText('sso.errors.account_link_refused')).toBeTruthy();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('refuses an OIDC return whose state did not start here', async () => {
    stubFetch({});
    render(
      <MemoryRouter initialEntries={['/auth/oidc/callback?code=x&state=unknown']}>
        <SsoCallback mode="oidc" />
      </MemoryRouter>,
    );
    expect(await screen.findByText('sso.errors.state_mismatch')).toBeTruthy();
  });
});
