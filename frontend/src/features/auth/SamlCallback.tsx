/**
 * SAML callback page. The backend ACS endpoint validates the identity
 * provider's response and redirects here with the local JWT pair in the URL
 * fragment; we store it exactly as the OIDC callback does.
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { readRememberChoice, useAuthStore } from '@/stores/useAuthStore';

const ERROR_KEYS: Record<string, [string, string]> = {
  invalid_saml_response: ['auth.saml_errors.invalid_response', 'The identity provider response could not be verified.'],
  saml_library_missing: ['auth.saml_errors.library_missing', 'SAML sign-in is not available on this server: the optional SAML package is not installed.'],
  missing_claims: ['auth.oidc_errors.missing_claims', 'The identity provider did not return a user id or email.'],
  account_not_found: ['auth.oidc_errors.account_not_found', 'No account exists for this sign-in and automatic account creation is off. Ask your administrator to invite you.'],
  account_link_refused: ['auth.oidc_errors.account_link_refused', 'An account with this email already exists and cannot be linked to this sign-in. Ask your administrator.'],
  account_disabled: ['auth.saml_errors.account_disabled', 'This account is disabled. Contact your administrator.'],
  not_enabled: ['auth.saml_errors.not_enabled', 'SAML sign-in is not enabled on this server.'],
};

export function SamlCallback() {
  const navigate = useNavigate();
  const setTokens = useAuthStore((s) => s.setTokens);
  const [error, setError] = useState('');
  const { t } = useTranslation();
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
    const access = params.get('access_token');
    const refresh = params.get('refresh_token');
    const code = params.get('error');
    // Drop the tokens from the address bar and history right away.
    window.history.replaceState(null, '', window.location.pathname);
    if (code) {
      const [key, fallback] = ERROR_KEYS[code] ?? ['auth.saml_errors.failed', 'SAML sign-in failed. Please try again.'];
      setError(t(key, { defaultValue: fallback }));
      return;
    }
    if (!access || !refresh) {
      setError(t('auth.saml_errors.no_tokens', { defaultValue: 'The identity provider did not return a sign-in. Please try again.' }));
      return;
    }
    setTokens(access, refresh, readRememberChoice());
    navigate('/', { replace: true });
  }, [navigate, setTokens, t]);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface-primary">
        <div className="rounded-xl border border-semantic-error/30 bg-semantic-error/10 px-6 py-4 text-sm text-semantic-error max-w-md text-center">
          <p className="font-semibold mb-1">{t('auth.oidc_errors.failed', { defaultValue: 'SSO login failed' })}</p>
          <p>{error}</p>
          <a href="/login" className="mt-3 inline-block text-oe-blue hover:underline text-xs">
            {t('auth.oidc_back_to_login', { defaultValue: 'Back to login' })}
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-primary">
      <div className="flex items-center gap-2 text-sm text-content-secondary">
        <Loader2 size={16} className="animate-spin" />
        {t('auth.oidc_completing', { defaultValue: 'Completing SSO login...' })}
      </div>
    </div>
  );
}
