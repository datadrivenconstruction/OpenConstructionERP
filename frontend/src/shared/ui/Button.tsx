import { forwardRef, type ButtonHTMLAttributes } from 'react';
import clsx from 'clsx';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
type ButtonSize = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: React.ReactNode;
  iconPosition?: 'left' | 'right';
}

const variantStyles: Record<ButtonVariant, string> = {
  primary: clsx(
    'bg-oe-blue text-content-inverse',
    'hover:bg-oe-blue-hover active:bg-oe-blue-active',
    'shadow-xs hover:shadow-sm',
    'border border-transparent',
  ),
  secondary: clsx(
    'bg-surface-primary text-content-primary',
    'border border-border',
    'hover:bg-surface-secondary active:bg-surface-tertiary',
    'shadow-xs',
  ),
  ghost: clsx(
    'bg-transparent text-content-secondary',
    'hover:bg-surface-secondary active:bg-surface-tertiary',
    'border border-transparent',
  ),
  danger: clsx(
    'bg-semantic-error text-content-inverse',
    'hover:opacity-90 active:opacity-80',
    'shadow-xs hover:shadow-sm',
    'border border-transparent',
  ),
};

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-xs gap-1.5 rounded-md',
  md: 'h-9 px-4 text-sm gap-2 rounded-lg',
  lg: 'h-11 px-6 text-base gap-2.5 rounded-xl',
};

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = 'primary',
      size = 'md',
      loading = false,
      icon,
      iconPosition = 'left',
      disabled,
      className,
      children,
      ...props
    },
    ref,
  ) => {
    const isDisabled = disabled || loading;

    return (
      <button
        ref={ref}
        disabled={isDisabled}
        className={clsx(
          'inline-flex items-center justify-center',
          'font-medium whitespace-nowrap select-none',
          'transition-all duration-fast ease-oe',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2',
          variantStyles[variant],
          sizeStyles[size],
          isDisabled && 'opacity-40 pointer-events-none',
          className,
        )}
        {...props}
      >
        {loading ? (
          <Spinner size={size} />
        ) : (
          <>
            {icon && iconPosition === 'left' && <span className="shrink-0">{icon}</span>}
            {children && <span>{children}</span>}
            {icon && iconPosition === 'right' && <span className="shrink-0">{icon}</span>}
          </>
        )}
      </button>
    );
  },
);

Button.displayName = 'Button';
export { Button };
export type { ButtonProps };

/* ── Spinner ──────────────────────────────────────────────────────────── */

function Spinner({ size = 'md' }: { size?: ButtonSize }) {
  const sizeMap = { sm: 'h-3.5 w-3.5', md: 'h-4 w-4', lg: 'h-5 w-5' };
  return (
    <svg
      className={clsx('animate-spin', sizeMap[size])}
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
      />
    </svg>
  );
}
