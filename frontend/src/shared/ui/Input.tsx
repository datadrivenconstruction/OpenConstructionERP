import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react';
import clsx from 'clsx';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: string;
  error?: string;
  icon?: ReactNode;
  suffix?: ReactNode;
  /** Use floating label style instead of static label above the input. */
  floatingLabel?: boolean;
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  (
    { label, hint, error, icon, suffix, floatingLabel = false, className, id, ...props },
    ref,
  ) => {
    const inputId = id || label?.toLowerCase().replace(/\s+/g, '-');
    const hasError = Boolean(error);

    /* Static label variant (original behavior, enhanced with transition) */
    if (!floatingLabel || !label) {
      return (
        <div className="flex flex-col gap-1.5">
          {label && (
            <label
              htmlFor={inputId}
              className="text-sm font-medium text-content-primary transition-colors duration-fast ease-oe"
            >
              {label}
            </label>
          )}
          <div className="relative group">
            {icon && (
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary transition-colors duration-fast ease-oe group-focus-within:text-oe-blue">
                {icon}
              </div>
            )}
            <input
              ref={ref}
              id={inputId}
              className={clsx(
                'h-9 w-full rounded-lg border bg-surface-primary px-3',
                'text-sm text-content-primary placeholder:text-content-tertiary',
                'transition-all duration-normal ease-oe',
                'focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue',
                'focus:shadow-[0_0_0_4px_rgba(0,113,227,0.08)]',
                icon && 'pl-10',
                suffix && 'pr-10',
                hasError
                  ? 'border-semantic-error focus:ring-semantic-error/30 focus:border-semantic-error focus:shadow-[0_0_0_4px_rgba(255,59,48,0.08)]'
                  : 'border-border hover:border-content-tertiary',
                props.disabled && 'opacity-40 cursor-not-allowed bg-surface-secondary',
                className,
              )}
              aria-invalid={hasError}
              aria-describedby={
                hasError ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined
              }
              {...props}
            />
            {suffix && (
              <div className="absolute inset-y-0 right-0 flex items-center pr-3 text-content-tertiary transition-colors duration-fast ease-oe group-focus-within:text-oe-blue">
                {suffix}
              </div>
            )}
          </div>
          {error && (
            <p
              id={`${inputId}-error`}
              className="text-xs text-semantic-error animate-slide-up"
              role="alert"
            >
              {error}
            </p>
          )}
          {hint && !error && (
            <p id={`${inputId}-hint`} className="text-xs text-content-tertiary">
              {hint}
            </p>
          )}
        </div>
      );
    }

    /* Floating label variant — label animates from inside the input to above */
    return (
      <div className="flex flex-col gap-1.5">
        <div className="relative group">
          {icon && (
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary transition-colors duration-fast ease-oe group-focus-within:text-oe-blue z-10">
              {icon}
            </div>
          )}
          <input
            ref={ref}
            id={inputId}
            placeholder=" "
            className={clsx(
              'peer h-12 w-full rounded-lg border bg-surface-primary px-3 pt-4 pb-1',
              'text-sm text-content-primary',
              'transition-all duration-normal ease-oe',
              'focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue',
              'focus:shadow-[0_0_0_4px_rgba(0,113,227,0.08)]',
              icon && 'pl-10',
              suffix && 'pr-10',
              hasError
                ? 'border-semantic-error focus:ring-semantic-error/30 focus:border-semantic-error focus:shadow-[0_0_0_4px_rgba(255,59,48,0.08)]'
                : 'border-border hover:border-content-tertiary',
              props.disabled && 'opacity-40 cursor-not-allowed bg-surface-secondary',
              className,
            )}
            aria-invalid={hasError}
            aria-describedby={
              hasError ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined
            }
            {...props}
          />
          <label
            htmlFor={inputId}
            className={clsx(
              'absolute top-1/2 -translate-y-1/2 origin-left pointer-events-none',
              'text-sm text-content-tertiary',
              'transition-all duration-normal ease-oe',
              /* Float up when focused or has value (placeholder-shown trick) */
              'peer-focus:top-2.5 peer-focus:translate-y-0 peer-focus:text-2xs peer-focus:text-oe-blue',
              'peer-[:not(:placeholder-shown)]:top-2.5 peer-[:not(:placeholder-shown)]:translate-y-0 peer-[:not(:placeholder-shown)]:text-2xs',
              hasError && 'peer-focus:text-semantic-error',
              icon ? 'left-10' : 'left-3',
            )}
          >
            {label}
          </label>
          {suffix && (
            <div className="absolute inset-y-0 right-0 flex items-center pr-3 text-content-tertiary transition-colors duration-fast ease-oe group-focus-within:text-oe-blue">
              {suffix}
            </div>
          )}
        </div>
        {error && (
          <p
            id={`${inputId}-error`}
            className="text-xs text-semantic-error animate-slide-up"
            role="alert"
          >
            {error}
          </p>
        )}
        {hint && !error && (
          <p id={`${inputId}-hint`} className="text-xs text-content-tertiary">
            {hint}
          </p>
        )}
      </div>
    );
  },
);

Input.displayName = 'Input';
export { Input };
export type { InputProps };
