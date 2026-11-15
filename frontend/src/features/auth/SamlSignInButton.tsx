/**
 * "Sign in with SAML" button. Renders nothing unless the server reports SAML
 * as enabled; the click hands the browser to the backend, which redirects to
 * the identity provider.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ShieldCheck } from 'lucide-react';
import { Button } from '@/shared/ui';

export function SamlSignInButton() {
  const { t } = useTranslation();
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    fetch('/api/v1/users/auth/saml/config/')
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { enabled?: boolean } | null) => setEnabled(d?.enabled === true))
      .catch(() => setEnabled(false));
  }, []);

  if (!enabled) return null;

  return (
    <div className="mt-3">
    <Button
      variant="secondary"
      size="lg"
      className="w-full"
      icon={<ShieldCheck size={16} />}
      onClick={() => {
        window.location.href = '/api/v1/users/auth/saml/login/';
      }}
    >
      {t('auth.saml_login', { defaultValue: 'Sign in with SAML' })}
    </Button>
    </div>
  );
}
