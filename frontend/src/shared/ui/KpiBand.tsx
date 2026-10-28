// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// KpiBand - the canonical KPI / role-home summary strip for module pages.
//
// This is the reference arrangement the founder picked off the Punch List
// screen (issue #70): a single, calm row of StatCard tiles that sits at the
// top of a page and answers "where do things stand" at a glance. Other
// role-home surfaces copy this pattern, so it lives in shared/ui as one
// component rather than being hand-rolled per page.
//
// Design contract:
//   * Tiles are the canonical StatCard (90% surface, no blur, tabular-nums)
//     so a band reads identically on every page.
//   * The grid is responsive and dense: it fits as many tiles per row as the
//     viewport allows, wrapping cleanly on narrow screens. Pass `columns` to
//     pin a fixed count when a page wants an exact layout.
//   * Each item maps straight onto StatCard props, so callers compose the
//     same vocabulary (tone, icon, sub, delta) without learning a new API.

import type { KeyboardEvent, ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import clsx from 'clsx';
import { StatCard, type StatCardTone } from './StatCard';

export interface KpiBandItem {
  /** Stable key for the tile (defaults to the label when omitted). */
  key?: string;
  /** Short, quiet caption above the value ("Open", "Overdue"). */
  label: ReactNode;
  /** The headline figure. */
  value: ReactNode;
  /** Optional secondary line under the value. */
  sub?: ReactNode;
  /** Optional Lucide icon shown in a tinted chip. */
  icon?: LucideIcon;
  /** Accent for the icon chip and (when `tintValue`) the value. */
  tone?: StatCardTone;
  /** Also tint the value itself, not just the icon chip. */
  tintValue?: boolean;
  /** Optional delta line, e.g. "+3 this week". */
  delta?: ReactNode;
  /** Direction colours the delta: up=green, down=red, flat=neutral. */
  deltaDirection?: 'up' | 'down' | 'flat';
  /** Optional click handler - turns the tile into a button for drill-down. */
  onClick?: () => void;
  /** Accessible label when the tile is interactive. */
  ariaLabel?: string;
}

export interface KpiBandProps {
  /** The tiles to render, left to right. */
  items: KpiBandItem[];
  /**
   * Fixed column count at the largest breakpoint. When omitted the band
   * auto-fits as many tiles per row as the viewport allows (min 150px each).
   */
  columns?: 2 | 3 | 4 | 5 | 6;
  /** Compact paddings for dense dashboards. Forwarded to each StatCard. */
  size?: 'sm' | 'md';
  className?: string;
}

const FIXED_GRID: Record<NonNullable<KpiBandProps['columns']>, string> = {
  2: 'grid-cols-2',
  3: 'grid-cols-2 sm:grid-cols-3',
  4: 'grid-cols-2 sm:grid-cols-2 lg:grid-cols-4',
  5: 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-5',
  6: 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-6',
};

export function KpiBand({ items, columns, size = 'md', className }: KpiBandProps) {
  if (items.length === 0) return null;

  return (
    <div
      className={clsx(
        'grid gap-3',
        columns
          ? FIXED_GRID[columns]
          : 'grid-cols-2 sm:[grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]',
        className,
      )}
    >
      {items.map((item) => {
        const interactive = typeof item.onClick === 'function';
        return (
          <StatCard
            key={item.key ?? (typeof item.label === 'string' ? item.label : undefined)}
            label={item.label}
            value={item.value}
            sub={item.sub}
            icon={item.icon}
            tone={item.tone}
            tintValue={item.tintValue}
            delta={item.delta}
            deltaDirection={item.deltaDirection}
            size={size}
            {...(interactive
              ? {
                  onClick: item.onClick,
                  role: 'button',
                  tabIndex: 0,
                  'aria-label':
                    item.ariaLabel ?? (typeof item.label === 'string' ? item.label : undefined),
                  onKeyDown: (e: KeyboardEvent<HTMLDivElement>) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      item.onClick?.();
                    }
                  },
                  className: 'cursor-pointer hover:shadow-sm focus-visible:shadow-sm',
                }
              : {})}
          />
        );
      })}
    </div>
  );
}
