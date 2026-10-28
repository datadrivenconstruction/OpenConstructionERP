// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import clsx from 'clsx';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';

export interface Chip<T> {
  value: T;
  label: ReactNode;
  count?: number;
  disabled?: boolean;
}

export interface ChipBarProps<T> {
  chips: Array<Chip<T>>;
  selected: T[];
  onToggle: (value: T) => void;
  onClear?: () => void;
  className?: string;
  size?: 'sm' | 'md';
  /** Render mode: "filter" highlights selected chips with primary color,
   * "tag" adds an X to remove and renders selected as muted. */
  mode?: 'filter' | 'tag';
  emptyText?: ReactNode;
}

export function ChipBar<T extends string>({
  chips,
  selected,
  onToggle,
  onClear,
  className,
  size = 'md',
  mode = 'filter',
  emptyText,
}: ChipBarProps<T>) {
  const padCls = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs';
  if (chips.length === 0 && emptyText) {
    return <div className="text-xs text-content-tertiary">{emptyText}</div>;
  }
  const selectedSet = new Set(selected);
  return (
    <div className={clsx('flex flex-wrap items-center gap-1.5', className)}>
      {chips.map((chip) => {
        const isOn = selectedSet.has(chip.value);
        return (
          <button
            key={String(chip.value)}
            type="button"
            disabled={chip.disabled}
            onClick={() => !chip.disabled && onToggle(chip.value)}
            className={clsx(
              'inline-flex items-center gap-1.5 rounded-full border transition',
              padCls,
              chip.disabled && 'opacity-50 cursor-not-allowed',
              mode === 'filter'
                ? isOn
                  ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                  : 'border-border bg-surface-primary text-content-secondary hover:border-oe-blue/40'
                : isOn
                  ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                  : 'border-border bg-surface-secondary text-content-secondary hover:bg-surface-tertiary',
            )}
          >
            <span className="truncate max-w-[16ch]">{chip.label}</span>
            {chip.count !== undefined && (
              <span className="text-[10px] tabular-nums opacity-70">{chip.count}</span>
            )}
            {mode === 'tag' && isOn && <X className="w-3 h-3" />}
          </button>
        );
      })}
      {onClear && selected.length > 0 && (
        <button
          type="button"
          onClick={onClear}
          className="ml-1 text-xs text-content-tertiary hover:text-content-primary underline"
        >
          clear
        </button>
      )}
    </div>
  );
}
