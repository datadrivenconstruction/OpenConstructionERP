// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * OIDC callback handler. The OIDC provider redirects here with an
 * authorization code in the URL. We POST it to the backend, which
 * exchanges it for tokens and returns local JWT credentials.
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { takeOidcLogin } from './oidcPkce';
import { readRememberChoice, useAuthStore } from '@/stores/useAuthStore';

export function OidcCallback() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const setTokens = useAuthStore((s) => s.setTokens);
  const [error, setError] = useState('');
  const { t } = useTranslation();
  const started = useRef(false); // StrictMode re-runs effects; the pending login is single-use

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const oidcError = searchParams.get('error');
    if (oidcError) {
      const desc = searchParams.get('error_description') || oidcError;
      setError(desc);
      return;
    }

    const code = searchParams.get('code');
    if (!code) {
      setError(t('auth.oidc_errors.no_code', { defaultValue: 'No authorization code received from the identity provider.' }));
      return;
    }
    const pending = takeOidcLogin(searchParams.get('state'));
    if (!pending) {
      setError(t('auth.oidc_errors.state_mismatch', { defaultValue: 'The sign-in request expired or did not start here. Please try again.' }));
      return;
    }

    fetch('/api/v1/users/auth/oidc/callback/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        code,
        redirect_uri: `${window.location.origin}/auth/oidc/callback`,
        code_verifier: pending.verifier,
        nonce: pending.nonce,
      }),
    })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          const detail = body?.detail;
          if (detail && typeof detail === 'object' && detail.message_key) {
            throw new Error(t(detail.message_key, { defaultValue: detail.message }));
          }
          throw new Error(typeof detail === 'string' ? detail : t('auth.oidc_errors.failed', { defaultValue: 'SSO login failed' }));
        }
        return res.json();
      })
      .then((data) => {
        setTokens(data.access_token, data.refresh_token, readRememberChoice());
        navigate('/', { replace: true });
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : t('auth.oidc_errors.failed', { defaultValue: 'SSO login failed' }));
      });
  }, [searchParams, navigate, setTokens, t]);

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
