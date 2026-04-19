import { Info } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';

interface AIDisclaimerBannerProps {
  variant?: 'full' | 'compact';
  className?: string;
}

/**
 * Legal disclaimer shown on AI-powered features. Ensures users understand
 * that AI output is advisory only, shifting contractual liability back to
 * the estimator. Referenced by TERMS.md §4 and NOTICE (AI section).
 */
export function AIDisclaimerBanner({ variant = 'full', className }: AIDisclaimerBannerProps) {
  const { t } = useTranslation();
  const isCompact = variant === 'compact';
  return (
    <div
      role="note"
      aria-label="AI disclaimer"
      className={clsx(
        'flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-50/60 text-amber-900 dark:border-amber-400/20 dark:bg-amber-900/10 dark:text-amber-200',
        isCompact ? 'px-3 py-2 text-[11px]' : 'px-4 py-3 text-xs',
        className,
      )}
    >
      <Info size={isCompact ? 12 : 14} className="mt-0.5 shrink-0" strokeWidth={1.8} />
      <p className="leading-snug">
        {isCompact
          ? t(
              'ai.disclaimer_compact',
              'AI output is preliminary — verify before contractual use.',
            )
          : t(
              'ai.disclaimer_full',
              'AI suggestions are preliminary estimates. A qualified estimator must verify all quantities, classifications, and costs before contractual or tender use.',
            )}
      </p>
    </div>
  );
}
