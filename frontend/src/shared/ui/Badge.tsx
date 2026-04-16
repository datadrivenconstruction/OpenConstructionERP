import clsx from 'clsx';
import type { ReactNode } from 'react';

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';
type BadgeSize = 'sm' | 'md';

interface BadgeProps {
  variant?: BadgeVariant;
  size?: BadgeSize;
  dot?: boolean;
  children: ReactNode;
  className?: string;
}

const variantStyles: Record<BadgeVariant, string> = {
  neutral: 'bg-surface-secondary text-content-secondary',
  blue: 'bg-oe-blue-subtle text-oe-blue',
  success: 'bg-semantic-success-bg text-semantic-success',
  warning: 'bg-semantic-warning-bg text-[#b45309]',
  error: 'bg-semantic-error-bg text-semantic-error',
};

const dotColors: Record<BadgeVariant, string> = {
  neutral: 'bg-content-tertiary',
  blue: 'bg-oe-blue',
  success: 'bg-semantic-success',
  warning: 'bg-semantic-warning',
  error: 'bg-semantic-error',
};

const sizeStyles: Record<BadgeSize, string> = {
  sm: 'h-5 px-1.5 text-2xs gap-1',
  md: 'h-6 px-2 text-xs gap-1.5',
};

export function Badge({ variant = 'neutral', size = 'md', dot, children, className }: BadgeProps) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full font-medium whitespace-nowrap',
        'animate-scale-in',
        'transition-colors duration-fast ease-oe',
        variantStyles[variant],
        sizeStyles[size],
        className,
      )}
    >
      {dot && <span className={clsx('h-1.5 w-1.5 rounded-full shrink-0', dotColors[variant])} />}
      {children}
    </span>
  );
}
