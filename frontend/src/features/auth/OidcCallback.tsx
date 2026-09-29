// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * OIDC callback handler. The OIDC provider redirects here with an
 * authorization code in the URL. We POST it to the backend, which
 * exchanges it for tokens and returns local JWT credentials.
 */
import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { readRememberChoice, useAuthStore } from '@/stores/useAuthStore';

export function OidcCallback() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const setTokens = useAuthStore((s) => s.setTokens);
  const [error, setError] = useState('');

  useEffect(() => {
    const oidcError = searchParams.get('error');
    if (oidcError) {
      const desc = searchParams.get('error_description') || oidcError;
      setError(desc);
      return;
    }

    const code = searchParams.get('code');
    if (!code) {
      setError('No authorization code received from the identity provider.');
      return;
    }

    fetch('/api/v1/users/auth/oidc/callback/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        code,
        redirect_uri: `${window.location.origin}/auth/oidc/callback`,
      }),
    })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: 'Authentication failed' }));
          throw new Error(body.detail || 'Authentication failed');
        }
        return res.json();
      })
      .then((data) => {
        setTokens(data.access_token, data.refresh_token, readRememberChoice());
        navigate('/', { replace: true });
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'SSO login failed');
      });
  }, [searchParams, navigate, setTokens]);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface-primary">
        <div className="rounded-xl border border-semantic-error/30 bg-semantic-error/10 px-6 py-4 text-sm text-semantic-error max-w-md text-center">
          <p className="font-semibold mb-1">SSO login failed</p>
          <p>{error}</p>
          <a href="/login" className="mt-3 inline-block text-oe-blue hover:underline text-xs">
            Back to login
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-primary">
      <div className="flex items-center gap-2 text-sm text-content-secondary">
        <Loader2 size={16} className="animate-spin" />
        Completing SSO login...
      </div>
    </div>
  );
}
