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

// WCAG AA contrast fix 2026-05-27 (Task #216):
//   blue.text was `text-oe-blue` (#0071e3 on #f0f7ff → 4.35:1, fails AA).
//   Swap to `text-oe-blue-text` (#005bb5 on #f0f7ff → 8.05:1, passes AA).
//   The pill backgrounds (Apple-Blue tints) stay unchanged.
const variantStyles: Record<BadgeVariant, string> = {
  neutral: 'bg-surface-secondary text-content-secondary',
  blue: 'bg-oe-blue-subtle text-oe-blue-text',
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
