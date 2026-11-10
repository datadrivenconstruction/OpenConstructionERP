// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { createContext, forwardRef, useContext, type ButtonHTMLAttributes } from 'react';
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

// One control system for the whole platform: every size shares the same 8px
// radius (pills are for chips and badges only), and no hover scaling.
const variantStyles: Record<ButtonVariant, string> = {
  primary: clsx(
    'bg-oe-blue text-content-inverse',
    'hover:bg-oe-blue-hover active:bg-oe-blue-active',
    'shadow-xs',
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
    'hover:bg-surface-secondary hover:text-content-primary active:bg-surface-tertiary',
    'border border-transparent',
  ),
  danger: clsx(
    'bg-semantic-error text-content-inverse',
    'hover:opacity-90 active:opacity-80',
    'shadow-xs',
    'border border-transparent',
  ),
};

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'h-7 px-2.5 text-xs gap-1.5 rounded-lg',
  md: 'h-8 px-3 text-sm gap-1.5 rounded-lg',
  lg: 'h-10 px-4 text-sm gap-2 rounded-lg',
};

/** Square icon-only geometry per size (used when a Button has no children). */
const iconOnlyStyles: Record<ButtonSize, string> = {
  sm: 'w-7 px-0',
  md: 'w-8 px-0',
  lg: 'w-10 px-0',
};

/**
 * Set by `PageHeader` around its action row: every Button inside renders at
 * the header size, whatever size the page asked for, so one row never mixes
 * 28px and 32px controls.
 */
export const ButtonSizeOverrideContext = createContext<ButtonSize | null>(null);

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
    const forcedSize = useContext(ButtonSizeOverrideContext);
    const effSize = forcedSize ?? size;
    const isDisabled = disabled || loading;
    const iconOnly = !children && !!icon && !loading;

    return (
      <button
        ref={ref}
        data-oe-button={variant}
        disabled={isDisabled}
        aria-busy={loading || undefined}
        className={clsx(
          'inline-flex items-center justify-center',
          'font-medium whitespace-nowrap select-none',
          'transition-colors duration-normal ease-oe active:scale-[0.98]',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/60',
          'focus-visible:ring-offset-2 focus-visible:ring-offset-surface-primary',
          variantStyles[variant],
          sizeStyles[effSize],
          iconOnly && iconOnlyStyles[effSize],
          isDisabled && 'pointer-events-none',
          isDisabled && !loading && 'opacity-40',
          className,
        )}
        {...props}
      >
        {loading ? (
          // Keep the label beside the spinner: a bare spinner tells nobody what is running.
          <>
            <Spinner size={effSize} />
            {children && <span className="ms-2 inline-flex items-center">{children}</span>}
          </>
        ) : (
          <>
            {icon && iconPosition === 'left' && <span className="shrink-0">{icon}</span>}
            {children && <span className="inline-flex items-center">{children}</span>}
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
      aria-hidden="true"
      className={clsx('shrink-0 animate-spin', sizeMap[size])}
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
