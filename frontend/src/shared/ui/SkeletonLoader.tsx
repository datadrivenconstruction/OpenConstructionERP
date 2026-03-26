import clsx from 'clsx';

/* ── Base skeleton pulse bar ──────────────────────────────────────────── */

const pulseBase =
  'animate-pulse rounded bg-surface-secondary';

/* ── SkeletonText ─────────────────────────────────────────────────────── */

export interface SkeletonTextProps {
  /** Width of the line as a Tailwind class (e.g. "w-3/4", "w-full"). Defaults to "w-full". */
  width?: string;
  className?: string;
}

/**
 * A single line of placeholder text.
 * Use `width` to control how wide the bar is (Tailwind class).
 */
export function SkeletonText({ width = 'w-full', className }: SkeletonTextProps) {
  return (
    <div
      className={clsx(pulseBase, 'h-4', width, className)}
      aria-hidden="true"
      data-testid="skeleton-text"
    />
  );
}

/* ── SkeletonCard ─────────────────────────────────────────────────────── */

export interface SkeletonCardProps {
  className?: string;
}

/**
 * A card-shaped placeholder that mimics a typical project/assembly card.
 */
export function SkeletonCard({ className }: SkeletonCardProps) {
  return (
    <div
      className={clsx(
        'rounded-xl border border-border-light bg-surface-elevated p-5 space-y-3',
        className,
      )}
      aria-hidden="true"
      data-testid="skeleton-card"
    >
      {/* Icon placeholder */}
      <div className={clsx(pulseBase, 'h-10 w-10 rounded-xl')} />
      {/* Title */}
      <div className={clsx(pulseBase, 'h-4 w-3/4')} />
      {/* Subtitle */}
      <div className={clsx(pulseBase, 'h-3 w-1/2')} />
      {/* Tags row */}
      <div className="flex items-center gap-2 pt-1">
        <div className={clsx(pulseBase, 'h-5 w-16 rounded-full')} />
        <div className={clsx(pulseBase, 'h-5 w-12 rounded-full')} />
      </div>
    </div>
  );
}

/* ── SkeletonTable ────────────────────────────────────────────────────── */

export interface SkeletonTableProps {
  /** Number of body rows to render. Defaults to 5. */
  rows?: number;
  /** Number of columns. Defaults to 5. */
  columns?: number;
  className?: string;
}

/**
 * A table-shaped placeholder with a header row and N body rows.
 */
export function SkeletonTable({ rows = 5, columns = 5, className }: SkeletonTableProps) {
  return (
    <div
      className={clsx(
        'rounded-xl border border-border-light bg-surface-elevated overflow-hidden',
        className,
      )}
      aria-hidden="true"
      data-testid="skeleton-table"
    >
      {/* Header */}
      <div className="flex items-center gap-4 px-4 py-3 border-b border-border-light bg-surface-secondary/40">
        {Array.from({ length: columns }).map((_, i) => (
          <div
            key={`header-${i}`}
            className={clsx(pulseBase, 'h-3', i === 0 ? 'w-24' : 'flex-1')}
          />
        ))}
      </div>
      {/* Rows */}
      {Array.from({ length: rows }).map((_, rowIdx) => (
        <div
          key={`row-${rowIdx}`}
          className={clsx(
            'flex items-center gap-4 px-4 py-3.5',
            rowIdx < rows - 1 && 'border-b border-border-light/50',
          )}
          data-testid="skeleton-table-row"
        >
          {Array.from({ length: columns }).map((_, colIdx) => (
            <div
              key={`cell-${rowIdx}-${colIdx}`}
              className={clsx(
                pulseBase,
                'h-3.5',
                colIdx === 0 ? 'w-20' : colIdx === 1 ? 'flex-1' : 'w-16',
              )}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

/* ── SkeletonGrid ─────────────────────────────────────────────────────── */

export interface SkeletonGridProps {
  /** Number of skeleton cards to render. Defaults to 6. */
  items?: number;
  /** Grid columns class. Defaults to "sm:grid-cols-2 lg:grid-cols-3". */
  gridCols?: string;
  className?: string;
}

/**
 * A grid of card-shaped placeholders.
 */
export function SkeletonGrid({
  items = 6,
  gridCols = 'sm:grid-cols-2 lg:grid-cols-3',
  className,
}: SkeletonGridProps) {
  return (
    <div
      className={clsx('grid gap-4', gridCols, className)}
      aria-hidden="true"
      data-testid="skeleton-grid"
    >
      {Array.from({ length: items }).map((_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  );
}
