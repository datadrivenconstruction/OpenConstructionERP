// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * <RecoveryCard> — error recovery surface for data-fetch failures.
 *
 * Replaces the previous pattern of rendering a generic empty state when
 * a query fails, which silently hid auth/permission errors behind a
 * "No items yet" message. ``RecoveryCard`` inspects the error's HTTP
 * status (when available) and renders a contextually correct CTA:
 *
 *   - 401 → "Sign in again" (link to /login with redirect param)
 *   - 403 → "Request access" (mailto + onRetry)
 *   - 4xx/5xx/other → "Retry" (or a developer-readable message)
 *
 * Errors thrown by the shared API client are ``ApiError`` instances
 * with a ``status`` field. Anything else is treated as a network or
 * unknown error.
 */

import { useMemo } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, LogIn, Lock, RefreshCw } from 'lucide-react';
import { EmptyState } from './EmptyState';
import { Button } from './Button';
import { getErrorMessage } from '@/shared/lib/api';

export interface RecoveryCardProps {
  /** The unknown error caught from a query, mutation, or fetch. */
  error: unknown;
  /** Optional retry callback. When provided, a Retry button is shown. */
  onRetry?: () => void;
  /** Optional override of the page-level redirect on sign-in (defaults to the current pathname). */
  redirectTo?: string;
}

function extractStatus(error: unknown): number | undefined {
  if (!error || typeof error !== 'object') return undefined;
  const e = error as { status?: unknown; response?: { status?: unknown } };
  if (typeof e.status === 'number') return e.status;
  if (e.response && typeof e.response.status === 'number') return e.response.status;
  return undefined;
}

export function RecoveryCard({ error, onRetry, redirectTo }: RecoveryCardProps) {
  const { t } = useTranslation();
  const location = useLocation();
  const status = useMemo(() => extractStatus(error), [error]);
  const message = useMemo(() => getErrorMessage(error), [error]);

  if (status === 401) {
    const next = encodeURIComponent(redirectTo ?? location.pathname + location.search);
    return (
      <EmptyState
        icon={<LogIn size={28} strokeWidth={1.5} />}
        title={t('recovery.signed_out_title', { defaultValue: 'Your session has expired' })}
        description={t('recovery.signed_out_desc', {
          defaultValue:
            'You were signed out or your session timed out. Sign in again to continue.',
        })}
        action={
          <Link
            to={`/login?next=${next}`}
            className="inline-flex h-10 items-center justify-center rounded-md bg-oe-blue px-4 text-sm font-medium text-white hover:bg-oe-blue/90 transition-colors"
          >
            {t('recovery.sign_in_again', { defaultValue: 'Sign in again' })}
          </Link>
        }
      />
    );
  }

  if (status === 403) {
    return (
      <EmptyState
        icon={<Lock size={28} strokeWidth={1.5} />}
        title={t('recovery.no_access_title', { defaultValue: 'You don’t have access here' })}
        description={t('recovery.no_access_desc', {
          defaultValue:
            'Your role is missing the permission needed to view this. Ask a project administrator to grant you access.',
        })}
        action={
          <a
            href="mailto:info@datadrivenconstruction.io?subject=Access%20request"
            className="inline-flex h-10 items-center justify-center rounded-md border border-border bg-surface-primary px-4 text-sm font-medium text-content-primary hover:bg-surface-secondary transition-colors"
          >
            {t('recovery.request_access', { defaultValue: 'Request access' })}
          </a>
        }
      />
    );
  }

  return (
    <EmptyState
      icon={<AlertTriangle size={28} strokeWidth={1.5} />}
      title={t('recovery.load_failed_title', { defaultValue: 'Couldn’t load this' })}
      description={message}
      action={
        onRetry ? (
          <Button variant="secondary" onClick={onRetry} icon={<RefreshCw size={14} />}>
            {t('common.retry', { defaultValue: 'Retry' })}
          </Button>
        ) : undefined
      }
    />
  );
}
