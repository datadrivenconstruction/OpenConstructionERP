// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Landing page of the accounting provider's OAuth redirect. The provider sends
 * the browser back with `code` and `state` (the connection id, set when the
 * authorisation started); QuickBooks also sends `realmId`, its company id. The
 * page hands them to the backend, which exchanges the code for tokens, and then
 * returns to the connection.
 */
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Card } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { completeOAuth, oauthRedirectUri, syncKeys } from './api';

export function OAuthCallbackPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  const code = params.get('code');
  const connectionId = params.get('state');
  const tenantId = params.get('realmId') ?? undefined;
  const denied = params.get('error');

  useEffect(() => {
    if (started.current || !code || !connectionId) return;
    started.current = true; // the code is single use: never post it twice
    completeOAuth(connectionId, { code, redirect_uri: oauthRedirectUri(), tenant_id: tenantId })
      .then(async () => {
        await qc.invalidateQueries({ queryKey: syncKeys.all });
        addToast({ type: 'success', title: t('accountingSync.oauth.done', { defaultValue: 'Connection authorised' }) });
        navigate(`/accounting-sync?connection=${encodeURIComponent(connectionId)}`, { replace: true });
      })
      .catch((e: unknown) => setError(getErrorMessage(e)));
  }, [code, connectionId, tenantId, qc, addToast, navigate, t]);

  const failure = denied
    ? t('accountingSync.oauth.denied', { defaultValue: 'Access was not granted in the accounting software.' })
    : !code || !connectionId
      ? t('accountingSync.oauth.missing', { defaultValue: 'The authorisation response is incomplete.' })
      : error;

  return (
    <div className="mx-auto max-w-lg py-10" data-testid="accounting-sync-oauth">
      <Card padding="lg" className="space-y-3 text-center">
        {failure ? (
          <>
            <h2 className="text-base font-semibold text-content-primary">{t('accountingSync.oauth.failed', { defaultValue: 'Authorisation failed' })}</h2>
            <p className="text-sm text-content-secondary">{failure}</p>
            <Link to="/accounting-sync">
              <Button variant="secondary">{t('accountingSync.oauth.back', { defaultValue: 'Back to accounting sync' })}</Button>
            </Link>
          </>
        ) : (
          <p className="text-sm text-content-secondary">{t('accountingSync.oauth.working', { defaultValue: 'Finishing the connection...' })}</p>
        )}
      </Card>
    </div>
  );
}
