// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import clsx from 'clsx';

type StatusDotVariant = 'success' | 'warning' | 'error' | 'neutral' | 'info';

interface StatusDotProps {
  variant: StatusDotVariant;
  /**
   * Visible text label rendered next to the dot. Strongly encouraged
   * for WCAG 1.4.1 (color is not the only indicator). When omitted we
   * still render an sr-only fallback derived from the variant so
   * screen-reader users get a non-color signal — but sighted users
   * with colour-blindness will only see a coloured circle, so prefer
   * passing an explicit label when space allows.
   */
  label?: string;
  pulse?: boolean;
  className?: string;
}

const dotStyles: Record<StatusDotVariant, string> = {
  success: 'bg-semantic-success',
  warning: 'bg-semantic-warning',
  error: 'bg-semantic-error',
  info: 'bg-semantic-info',
  neutral: 'bg-content-tertiary',
};

const variantSrLabels: Record<StatusDotVariant, string> = {
  success: 'Success',
  warning: 'Warning',
  error: 'Error',
  info: 'Info',
  neutral: 'Neutral',
};

export function StatusDot({ variant, label, pulse, className }: StatusDotProps) {
  const srFallback = variantSrLabels[variant];
  return (
    <span
      className={clsx('inline-flex items-center gap-2', className)}
      role="status"
    >
      <span className="relative flex h-2.5 w-2.5">
        {pulse && (
          <span
            className={clsx(
              'absolute inline-flex h-full w-full animate-ping rounded-full opacity-40',
              dotStyles[variant],
            )}
          />
        )}
        <span
          className={clsx('relative inline-flex h-2.5 w-2.5 rounded-full', dotStyles[variant])}
        />
      </span>
      {label ? (
        <span className="text-sm text-content-secondary">{label}</span>
      ) : (
        // sr-only fallback so the variant is announced even when no
        // visible label is supplied (RunDock and similar dense rows).
        <span className="sr-only">{srFallback}</span>
      )}
    </span>
  );
}
