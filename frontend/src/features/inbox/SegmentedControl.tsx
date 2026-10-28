// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Accessible single-select segmented control.
 *
 * Real ``<button>`` elements (never divs): each carries ``aria-pressed`` to
 * announce the active segment, and the group uses roving ``tabIndex`` so it is
 * one tab stop with Arrow / Home / End moving both focus and selection (the
 * ergonomics users expect from a segmented filter). Kept generic over the
 * value type so the inbox page can drive it with its typed kind filter.
 */
import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import clsx from 'clsx';

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  /** Optional count shown after the label (e.g. how many items match). */
  count?: number;
  icon?: ReactNode;
}

export interface SegmentedControlProps<T extends string> {
  options: SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  /** Describes the control for assistive tech (the group has no visible label). */
  ariaLabel: string;
  'data-testid'?: string;
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  'data-testid': testId,
}: SegmentedControlProps<T>) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const selectedIndex = Math.max(
    0,
    options.findIndex((o) => o.value === value),
  );

  const selectAt = (index: number) => {
    const count = options.length;
    if (count === 0) return;
    const wrapped = ((index % count) + count) % count;
    const opt = options[wrapped];
    if (!opt) return;
    onChange(opt.value);
    const btn = refs.current[wrapped];
    if (btn) btn.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    switch (event.key) {
      case 'ArrowRight':
      case 'ArrowDown':
        event.preventDefault();
        selectAt(index + 1);
        break;
      case 'ArrowLeft':
      case 'ArrowUp':
        event.preventDefault();
        selectAt(index - 1);
        break;
      case 'Home':
        event.preventDefault();
        selectAt(0);
        break;
      case 'End':
        event.preventDefault();
        selectAt(options.length - 1);
        break;
      default:
        break;
    }
  };

  return (
    <div
      role="group"
      aria-label={ariaLabel}
      data-testid={testId}
      className="inline-flex items-center gap-0.5 rounded-lg border border-border-light bg-surface-secondary/60 p-0.5"
    >
      {options.map((opt, index) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            ref={(el) => {
              refs.current[index] = el;
            }}
            type="button"
            aria-pressed={active}
            tabIndex={index === selectedIndex ? 0 : -1}
            onClick={() => onChange(opt.value)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={clsx(
              'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
              active
                ? 'bg-surface-primary text-content-primary shadow-sm'
                : 'text-content-secondary hover:text-content-primary',
            )}
          >
            {opt.icon}
            <span>{opt.label}</span>
            {typeof opt.count === 'number' && (
              <span
                className={clsx(
                  'tabular-nums',
                  active ? 'text-oe-blue-text' : 'text-content-tertiary',
                )}
              >
                {opt.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export default SegmentedControl;
