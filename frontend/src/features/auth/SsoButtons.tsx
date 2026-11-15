// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Login page buttons for the identity providers an admin configured in
 * Settings > Identity. SAML goes through the backend (SP-initiated); OIDC runs
 * in the browser with state, nonce and PKCE.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ShieldCheck } from 'lucide-react';
import { Button } from '@/shared/ui';
import { beginOidcLogin } from './oidcPkce';

interface PublicProvider {
  slug: string;
  display_name: string;
  protocol: 'oidc' | 'saml';
  login_url: string | null;
}

// Same path the earlier server-wide OIDC used, so redirect URIs registered at the IdP stay valid.
export const SSO_OIDC_CALLBACK = '/auth/oidc/callback';

async function startOidc(slug: string): Promise<void> {
  const res = await fetch(`/api/v1/sso/oidc/${encodeURIComponent(slug)}/start/`);
  if (!res.ok) throw new Error(String(res.status));
  const cfg = (await res.json()) as { authorization_endpoint: string; client_id: string; scopes: string };
  const { state, nonce, codeChallenge } = await beginOidcLogin(slug);
  const params = new URLSearchParams({
    client_id: cfg.client_id,
    response_type: 'code',
    scope: cfg.scopes,
    redirect_uri: `${window.location.origin}${SSO_OIDC_CALLBACK}`,
    state,
    nonce,
    code_challenge: codeChallenge,
    code_challenge_method: 'S256',
  });
  window.location.href = `${cfg.authorization_endpoint}?${params}`;
}

export function SsoButtons({ showDivider }: { showDivider: boolean }) {
  const { t } = useTranslation();
  const [providers, setProviders] = useState<PublicProvider[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    fetch('/api/v1/sso/providers/')
      .then((r) => (r.ok ? r.json() : { providers: [] }))
      .then((d: { providers?: PublicProvider[] }) => setProviders(d.providers ?? []))
      .catch(() => setProviders([]));
  }, []);

  if (providers.length === 0) return null;

  const go = async (p: PublicProvider) => {
    setBusy(p.slug);
    setError('');
    try {
      if (p.protocol === 'saml' && p.login_url) {
        window.location.href = p.login_url;
        return;
      }
      await startOidc(p.slug);
    } catch {
      setError(t('sso.errors.provider_unreachable', { defaultValue: 'Could not reach the identity provider.' }));
      setBusy(null);
    }
  };

  return (
    <div className="mt-3 space-y-2" data-testid="sso-buttons">
      {showDivider && (
        <div className="flex items-center gap-2 mb-3">
          <div className="flex-1 border-t border-border-light" />
          <span className="text-2xs text-content-tertiary">{t('auth.or', { defaultValue: 'or' })}</span>
          <div className="flex-1 border-t border-border-light" />
        </div>
      )}
      {providers.map((p) => (
        <Button
          key={p.slug}
          variant="secondary"
          size="lg"
          className="w-full"
          icon={<ShieldCheck size={16} />}
          loading={busy === p.slug}
          onClick={() => void go(p)}
        >
          {t('sso.login_with', { defaultValue: 'Sign in with {{name}}', name: p.display_name })}
        </Button>
      ))}
      {error && <p className="text-xs text-semantic-error">{error}</p>}
    </div>
  );
}
