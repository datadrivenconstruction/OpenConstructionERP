// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import clsx from 'clsx';
import type { ReactNode } from 'react';

export interface ToggleProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  label?: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  size?: 'sm' | 'md';
  className?: string;
}

export function Toggle({
  checked,
  onChange,
  label,
  description,
  disabled,
  size = 'md',
  className,
}: ToggleProps) {
  const trackCls =
    size === 'sm' ? 'w-7 h-4' : 'w-9 h-5';
  const knobCls =
    size === 'sm' ? 'w-3 h-3 translate-y-0.5' : 'w-4 h-4 translate-y-0.5';
  const translateCls =
    size === 'sm'
      ? checked
        ? 'translate-x-3.5'
        : 'translate-x-0.5'
      : checked
        ? 'translate-x-4'
        : 'translate-x-0.5';
  return (
    <label
      className={clsx(
        'inline-flex items-start gap-2.5 cursor-pointer',
        disabled && 'opacity-50 cursor-not-allowed',
        className,
      )}
    >
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-disabled={disabled}
        disabled={disabled}
        onClick={() => !disabled && onChange(!checked)}
        className={clsx(
          'relative shrink-0 rounded-full transition-colors',
          trackCls,
          checked ? 'bg-oe-blue' : 'bg-slate-300 dark:bg-slate-600',
        )}
      >
        <span
          className={clsx(
            'absolute left-0 top-0 rounded-full bg-white shadow transition-transform',
            knobCls,
            translateCls,
          )}
        />
      </button>
      {(label || description) && (
        <span className="min-w-0">
          {label && <span className="text-sm text-content-primary">{label}</span>}
          {description && (
            <span className="block text-xs text-content-tertiary mt-0.5">
              {description}
            </span>
          )}
        </span>
      )}
    </label>
  );
}
