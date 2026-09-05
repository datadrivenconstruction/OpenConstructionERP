/**
 * What the cost-base browser shows when the catalogue request fails.
 *
 * `useBaseCatalog` runs with `retry: false`, so a failed request leaves `data`
 * undefined forever. Every page that renders the browser used to treat that as
 * "still loading" and spin indefinitely, which told the user nothing: the same
 * frame meant "wait a moment" and "this is never going to arrive". This states
 * what failed, quotes the reason the server gave, and offers the retry, so the
 * panel is honest instead of blank.
 */

import { AlertTriangle, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui';

interface BaseCatalogErrorProps {
  /** The React Query error. `apiGet` already reduces the server body to a sentence. */
  error: unknown;
  onRetry: () => void;
}

export function BaseCatalogError({ error, onRetry }: BaseCatalogErrorProps) {
  const { t } = useTranslation();
  const reason = error instanceof Error && error.message ? error.message : null;

  return (
    <div className="flex flex-col items-center gap-3 py-12 text-center">
      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-semantic-error-bg">
        <AlertTriangle size={20} className="text-semantic-error" />
      </div>
      <div className="max-w-md">
        <h3 className="text-base font-semibold text-content-primary">
          {t('costs.base_catalog_failed', { defaultValue: 'Cost bases could not be loaded' })}
        </h3>
        {reason && <p className="mt-1 text-sm text-content-secondary">{reason}</p>}
        <p className="mt-1 text-sm text-content-tertiary">
          {t('costs.base_catalog_failed_hint', {
            defaultValue:
              'The list of cost bases comes from the server. Check that the backend is running and reachable, then try again.',
          })}
        </p>
      </div>
      <Button variant="secondary" size="sm" onClick={onRetry}>
        <RefreshCw size={14} />
        {t('common.retry', { defaultValue: 'Retry' })}
      </Button>
    </div>
  );
}
