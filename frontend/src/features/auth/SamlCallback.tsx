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
    // Drop the tokens from the address bar and history right away.
    window.history.replaceState(null, '', window.location.pathname);
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
