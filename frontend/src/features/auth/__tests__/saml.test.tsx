import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}));

vi.mock('@/app/i18n', () => ({
  SUPPORTED_LANGUAGES: [{ code: 'en', name: 'English', flag: 'gb', country: 'gb' }],
}));

vi.mock('@/shared/ui', () => ({
  Button: ({ children, onClick }: { children: React.ReactNode; onClick?: () => void }) => (
    <button onClick={onClick}>{children}</button>
  ),
}));

import { SamlSignInButton } from '../SamlSignInButton';
import { SamlCallback } from '../SamlCallback';
import { useAuthStore } from '@/stores/useAuthStore';

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, '', '/');
});

function stubConfig(body: unknown, ok = true) {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok, json: async () => body })));
}

describe('SamlSignInButton', () => {
  it('shows the button when the server enables SAML', async () => {
    stubConfig({ enabled: true });
    render(<SamlSignInButton />);
    expect(await screen.findByText('auth.saml_login')).toBeTruthy();
  });

  it('renders nothing when SAML is disabled', async () => {
    stubConfig({ enabled: false });
    const { container } = render(<SamlSignInButton />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(container.textContent).toBe('');
  });

  it('renders nothing when the config request fails', async () => {
    stubConfig({}, false);
    const { container } = render(<SamlSignInButton />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(container.textContent).toBe('');
  });
});

describe('SamlCallback', () => {
  it('stores the tokens from the URL fragment and clears it', async () => {
    const setTokens = vi.fn();
    useAuthStore.setState({ setTokens } as never);
    window.history.replaceState(null, '', '/auth/saml/callback#access_token=a1&refresh_token=r1');
    render(
      <MemoryRouter>
        <SamlCallback />
      </MemoryRouter>,
    );
    await waitFor(() => expect(setTokens).toHaveBeenCalled());
    expect(setTokens.mock.calls[0].slice(0, 2)).toEqual(['a1', 'r1']);
    expect(window.location.hash).toBe('');
  });

  it('shows an error when no tokens arrive', async () => {
    const setTokens = vi.fn();
    useAuthStore.setState({ setTokens } as never);
    window.history.replaceState(null, '', '/auth/saml/callback');
    render(
      <MemoryRouter>
        <SamlCallback />
      </MemoryRouter>,
    );
    expect(await screen.findByText('auth.saml_errors.no_tokens')).toBeTruthy();
    expect(setTokens).not.toHaveBeenCalled();
  });
});
