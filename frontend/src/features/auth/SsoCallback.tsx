// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Return leg of a per-provider sign-in.
 * - `/auth/sso/complete#code=...` (SAML): the backend validated the assertion and
 *   left a 60-second single-use code in the fragment; exchange it for tokens.
 * - `/auth/sso/oidc/callback?code=...&state=...` (OIDC): check state, post the code.
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { takeOidcLogin } from './oidcPkce';
import { SSO_OIDC_CALLBACK } from './SsoButtons';
import { readRememberChoice, useAuthStore } from '@/stores/useAuthStore';

export function SsoCallback({ mode }: { mode: 'saml' | 'oidc' }) {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const setTokens = useAuthStore((s) => s.setTokens);
  const { t } = useTranslation();
  const [error, setError] = useState('');
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const fail = (code: string) =>
      setError(t(`sso.errors.${code}`, { defaultValue: t('sso.errors.failed', { defaultValue: 'Single sign-on failed.' }) }));

    let request: Promise<Response>;
    if (mode === 'saml') {
      const err = searchParams.get('error');
      if (err) return fail(err);
      const code = new URLSearchParams(window.location.hash.replace(/^#/, '')).get('code');
      window.history.replaceState(null, '', window.location.pathname);
      if (!code) return fail('handoff_invalid');
      request = fetch('/api/v1/sso/handoff/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      });
    } else {
      if (searchParams.get('error')) return fail('idp_refused');
      const code = searchParams.get('code');
      const pending = takeOidcLogin(searchParams.get('state'));
      if (!code || !pending?.provider) return fail('state_mismatch');
      request = fetch(`/api/v1/sso/oidc/${encodeURIComponent(pending.provider)}/callback/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code,
          code_verifier: pending.verifier,
          nonce: pending.nonce,
          redirect_uri: `${window.location.origin}${SSO_OIDC_CALLBACK}`,
        }),
      });
    }
    request
      .then(async (res) => {
        const body = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(body?.detail?.code || 'failed');
        setTokens(body.access_token, body.refresh_token, readRememberChoice());
        navigate('/', { replace: true });
      })
      .catch((e: unknown) => fail(e instanceof Error ? e.message : 'failed'));
  }, [mode, searchParams, navigate, setTokens, t]);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface-primary">
        <div className="rounded-xl border border-semantic-error/30 bg-semantic-error/10 px-6 py-4 text-sm text-semantic-error max-w-md text-center">
          <p className="font-semibold mb-1">{t('sso.errors.failed', { defaultValue: 'Single sign-on failed.' })}</p>
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
