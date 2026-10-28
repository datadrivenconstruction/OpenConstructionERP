// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import clsx from 'clsx';
import type { ReactNode } from 'react';

export interface SliderProps {
  value: number;
  onChange: (next: number) => void;
  min: number;
  max: number;
  step: number;
  label?: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  format?: (v: number) => string;
  /** Optional list of marker positions to render under the track. */
  marks?: Array<{ value: number; label: ReactNode }>;
  className?: string;
}

export function Slider({
  value,
  onChange,
  min,
  max,
  step,
  label,
  description,
  disabled,
  format,
  marks,
  className,
}: SliderProps) {
  const display = format ? format(value) : String(value);
  return (
    <div className={clsx('flex flex-col gap-1.5', className)}>
      {(label || description) && (
        <div className="flex items-end justify-between gap-2">
          <div className="min-w-0">
            {label && (
              <div className="text-xs uppercase tracking-wider text-content-tertiary">
                {label}
              </div>
            )}
            {description && (
              <div className="text-xs text-content-tertiary mt-0.5">{description}</div>
            )}
          </div>
          <div className="text-sm font-medium text-content-primary tabular-nums">
            {display}
          </div>
        </div>
      )}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-oe-blue cursor-pointer disabled:cursor-not-allowed"
      />
      {marks && marks.length > 0 && (
        <div className="flex justify-between text-[10px] text-content-tertiary px-0.5">
          {marks.map((m) => (
            <span key={m.value} className="text-center">
              {m.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
