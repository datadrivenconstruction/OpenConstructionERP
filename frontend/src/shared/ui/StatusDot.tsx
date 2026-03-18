import clsx from 'clsx';

type StatusDotVariant = 'success' | 'warning' | 'error' | 'neutral' | 'info';

interface StatusDotProps {
  variant: StatusDotVariant;
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

export function StatusDot({ variant, label, pulse, className }: StatusDotProps) {
  return (
    <span className={clsx('inline-flex items-center gap-2', className)}>
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
      {label && <span className="text-sm text-content-secondary">{label}</span>}
    </span>
  );
}
