// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { Sparkles, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

const DISMISS_LS_PREFIX = 'beta-banner-dismissed:';

export interface BetaBannerProps {
  moduleKey: string;
  title?: string;
  description?: string;
  feedbackUrl?: string;
  className?: string;
}

export function BetaBanner({
  moduleKey,
  title,
  description,
  feedbackUrl = 'https://github.com/datadrivenconstruction/OpenConstructionERP/issues/new',
  className = '',
}: BetaBannerProps) {
  const { t } = useTranslation();
  const lsKey = `${DISMISS_LS_PREFIX}${moduleKey}`;
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(lsKey) === '1';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    if (dismissed) {
      try {
        localStorage.setItem(lsKey, '1');
      } catch {
        /* ignore */
      }
    }
  }, [dismissed, lsKey]);

  if (dismissed) return null;

  const resolvedTitle =
    title ??
    t('common.beta_module.title', {
      defaultValue: 'New module, work in progress',
    });
  const resolvedDescription =
    description ??
    t('common.beta_module.description', {
      defaultValue:
        'This module is still being polished. We would be grateful for your feedback, or check back in the next versions for a more complete experience.',
    });

  return (
    <div
      role="status"
      // NO own margin (same family as audit S1/S2): the page root's space-y-5
      // owns the vertical rhythm; a built-in mb-5 stacked a double gap on it.
      className={`flex items-start gap-3 rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-amber-900 dark:border-amber-700/60 dark:bg-amber-950/30 dark:text-amber-100 ${className}`}
      data-testid={`beta-banner-${moduleKey}`}
    >
      <Sparkles size={16} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
      <div className="flex-1 text-sm">
        <p className="font-medium">{resolvedTitle}</p>
        <p className="mt-0.5 text-xs opacity-90">
          {resolvedDescription}{' '}
          <a
            href={feedbackUrl}
            target="_blank"
            rel="noreferrer"
            className="underline underline-offset-2 hover:text-amber-700 dark:hover:text-amber-200"
          >
            {t('common.beta_module.feedback_link', {
              defaultValue: 'Send feedback',
            })}
          </a>
        </p>
      </div>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        className="rounded p-1 text-amber-700 hover:bg-amber-100 dark:text-amber-300 dark:hover:bg-amber-900/40"
        aria-label={t('common.dismiss', { defaultValue: 'Dismiss' })}
      >
        <X size={14} />
      </button>
    </div>
  );
}
