// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Reusable radio group with arrow-key navigation and ARIA roles.

import clsx from 'clsx';
import type { ReactNode } from 'react';

export interface RadioGroupOption<T extends string> {
  value: T;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  disabledReason?: string;
}

export interface RadioGroupProps<T extends string> {
  name: string;
  value: T;
  onChange: (next: T) => void;
  options: RadioGroupOption<T>[];
  legend?: string;
  className?: string;
  /** "stack" (default) | "row" — visual orientation */
  orientation?: 'stack' | 'row';
}

export function RadioGroup<T extends string>({
  name,
  value,
  onChange,
  options,
  legend,
  className,
  orientation = 'stack',
}: RadioGroupProps<T>) {
  return (
    <fieldset
      className={clsx('border-0 p-0 m-0', className)}
      aria-label={legend}
    >
      {legend && (
        <legend className="text-xs uppercase tracking-wider text-content-tertiary mb-1.5">
          {legend}
        </legend>
      )}
      <div
        role="radiogroup"
        className={clsx(
          orientation === 'stack' ? 'flex flex-col gap-1.5' : 'flex flex-row flex-wrap gap-2',
        )}
      >
        {options.map((opt) => {
          const isSelected = value === opt.value;
          const inputId = `${name}-${opt.value}`;
          return (
            <label
              key={opt.value}
              htmlFor={inputId}
              title={opt.disabled ? opt.disabledReason : undefined}
              className={clsx(
                'flex items-start gap-2.5 rounded-lg border px-3 py-2 cursor-pointer transition',
                isSelected
                  ? 'border-oe-blue bg-oe-blue/5'
                  : 'border-border bg-surface-primary hover:border-oe-blue/40',
                opt.disabled && 'opacity-50 cursor-not-allowed',
              )}
            >
              <input
                id={inputId}
                type="radio"
                name={name}
                value={opt.value}
                checked={isSelected}
                disabled={opt.disabled}
                onChange={() => !opt.disabled && onChange(opt.value)}
                className="mt-0.5 h-4 w-4 accent-oe-blue"
              />
              <div className="min-w-0 flex-1">
                <div className="text-sm text-content-primary">{opt.label}</div>
                {opt.description && (
                  <div className="text-xs text-content-tertiary mt-0.5">{opt.description}</div>
                )}
              </div>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
