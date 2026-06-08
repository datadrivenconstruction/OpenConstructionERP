/**
 * <ErrorState> — a small, explanatory error block for use inside a
 * drawer, form, or panel.
 *
 * Most modules today surface a raw `e.message`. This renders the two
 * things a user actually needs: WHY it failed (`title`) and what to do
 * about it (`hint`), plus an optional Retry and a support link. It is
 * the inline companion to <RecoveryCard> (which owns full-page,
 * status-aware fetch failures); reach for ErrorState when the
 * surrounding screen should stay visible.
 *
 * `title` and `hint` arrive pre-translated. When a backend error
 * envelope (`{ reason_key, fix_key, retryable }`) is wired up, resolve
 * those keys at the call site and pass the strings in; until then a
 * generic `error_explain.*` fallback is fine.
 */

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { AlertTriangle, LifeBuoy, RefreshCw } from 'lucide-react';
import { Button } from './Button';

export interface ErrorStateProps {
  /** Plain-language reason it failed (pre-translated). */
  title: string;
  /** Plain-language fix / next step (pre-translated). */
  hint?: string;
  onRetry?: () => void;
  /** Optional support target (mailto: or URL). */
  supportHref?: string;
  /** Single-line dense variant for tight inline placement. */
  compact?: boolean;
  className?: string;
}

export function ErrorState({
  title,
  hint,
  onRetry,
  supportHref,
  compact = false,
  className,
}: ErrorStateProps) {
  const { t } = useTranslation();

  return (
    <div
      role="alert"
      className={clsx(
        'rounded-md border border-semantic-error/30 bg-semantic-error-bg',
        compact ? 'flex items-start gap-2 px-3 py-2' : 'p-4',
        className,
      )}
    >
      <div className={clsx('flex gap-2.5', compact ? 'flex-1' : 'items-start')}>
        <AlertTriangle size={compact ? 15 : 18} className="mt-0.5 shrink-0 text-semantic-error" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-content-primary">{title}</p>
          {hint && <p className="mt-0.5 text-xs leading-relaxed text-content-secondary">{hint}</p>}
          {(onRetry || supportHref) && (
            <div className="mt-2.5 flex flex-wrap items-center gap-2">
              {onRetry && (
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<RefreshCw size={13} />}
                  onClick={onRetry}
                >
                  {t('error_explain.retry', { defaultValue: 'Retry' })}
                </Button>
              )}
              {supportHref && (
                <a
                  href={supportHref}
                  className="inline-flex items-center gap-1 text-xs font-medium text-oe-blue-text hover:underline"
                >
                  <LifeBuoy size={13} />
                  {t('error_explain.contact_support', { defaultValue: 'Contact support' })}
                </a>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
