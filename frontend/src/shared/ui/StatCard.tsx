// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// StatCard - the canonical KPI tile for module pages (founder 2026-06-06:
// "фон сделать немного полупрозрачным 90% и попробовать стиль этих карточек
// на всех страницах сделать немного современней и красивей и понятней").
//
// Design contract:
//   * Surface is bg-surface-elevated/90 - 90% alpha, NO backdrop-blur. The
//     app backdrop behind every page is a 0.9px dot grid + tinted spotlight;
//     any blur wipes that texture out and the card reads as a solid plate.
//     Plain alpha lets the grid show through faintly = visibly translucent
//     without costing GPU time on pages with many tiles.
//   * Label is a quiet, uppercase 2xs line; the value is the hero (semibold,
//     tabular-nums so columns of tiles align digit-for-digit).
//   * Optional icon sits in a tinted chip on the trailing edge, optional
//     delta renders green/red/neutral with an arrow glyph.
//
// Use this instead of hand-rolling `rounded-xl bg-surface-elevated border
// p-3` tiles - one component, one look on every page.

import type { HTMLAttributes, ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import clsx from 'clsx';

export type StatCardTone = 'default' | 'blue' | 'success' | 'warning' | 'danger';

const ICON_CHIP_TONES: Record<StatCardTone, string> = {
  default: 'bg-surface-tertiary text-content-tertiary',
  blue: 'bg-oe-blue/10 text-oe-blue-text',
  success: 'bg-semantic-success/10 text-semantic-success',
  warning: 'bg-amber-500/10 text-amber-600 dark:text-amber-400',
  danger: 'bg-semantic-error/10 text-semantic-error',
};

const VALUE_TONES: Record<StatCardTone, string> = {
  default: 'text-content-primary',
  blue: 'text-oe-blue-text',
  success: 'text-semantic-success',
  warning: 'text-amber-600 dark:text-amber-400',
  danger: 'text-semantic-error',
};

export interface StatCardProps extends HTMLAttributes<HTMLDivElement> {
  /** Short, quiet caption above the value ("Open RFIs", "Total budget"). */
  label: ReactNode;
  /** The headline figure. Strings/numbers render tabular-nums. */
  value: ReactNode;
  /** Optional secondary line under the value ("of 24 planned"). */
  sub?: ReactNode;
  /** Optional Lucide icon shown in a tinted chip. */
  icon?: LucideIcon;
  /** Accent for the icon chip and (when `tintValue`) the value. */
  tone?: StatCardTone;
  /** Also tint the value itself, not just the icon chip. */
  tintValue?: boolean;
  /** Optional delta line, e.g. "+12% vs last month". */
  delta?: ReactNode;
  /** Direction colours the delta: up=green, down=red, flat=neutral. */
  deltaDirection?: 'up' | 'down' | 'flat';
  /** Compact paddings for dense dashboards. */
  size?: 'sm' | 'md';
}

export function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  tone = 'default',
  tintValue = false,
  delta,
  deltaDirection = 'flat',
  size = 'md',
  className,
  ...props
}: StatCardProps) {
  return (
    <div
      className={clsx(
        // 90% surface, no blur - see the design contract in the header.
        'rounded-xl border border-border-light bg-surface-elevated/90 shadow-xs',
        'transition-shadow duration-normal ease-oe hover:shadow-sm',
        size === 'sm' ? 'p-3' : 'p-4',
        className,
      )}
      {...props}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-2xs font-medium uppercase tracking-wide text-content-tertiary">
            {label}
          </div>
          <div
            className={clsx(
              'mt-1 truncate font-semibold tabular-nums leading-tight',
              size === 'sm' ? 'text-lg' : 'text-2xl',
              tintValue ? VALUE_TONES[tone] : 'text-content-primary',
            )}
          >
            {value}
          </div>
          {sub != null && (
            <div className="mt-0.5 truncate text-xs text-content-tertiary">{sub}</div>
          )}
          {delta != null && (
            <div
              className={clsx(
                'mt-1 inline-flex items-center gap-1 text-xs font-medium tabular-nums',
                deltaDirection === 'up' && 'text-semantic-success',
                deltaDirection === 'down' && 'text-semantic-error',
                deltaDirection === 'flat' && 'text-content-tertiary',
              )}
            >
              {deltaDirection === 'up' && <span aria-hidden>↑</span>}
              {deltaDirection === 'down' && <span aria-hidden>↓</span>}
              {delta}
            </div>
          )}
        </div>
        {Icon && (
          <span
            className={clsx(
              'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
              ICON_CHIP_TONES[tone],
            )}
            aria-hidden
          >
            <Icon size={16} />
          </span>
        )}
      </div>
    </div>
  );
}
