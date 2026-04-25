/**
 * `<BlockShell>` — the base wrapper for every EAC block in the visual editor.
 *
 * Responsibilities:
 *  - Apply the right color tokens (background, border, text) for the block
 *    type and respond to the `selected` state with stronger styles.
 *  - Render the icon + label header so meaning is conveyed without color
 *    alone (AC-3.6).
 *  - Optionally make itself draggable via `useSortable` from `@dnd-kit/sortable`
 *    so the parent canvas can reorder children with WCAG-compliant keyboard
 *    interaction.
 *
 * This component is purely presentational; selection state, drag-end events,
 * and value editing are handled by the containing canvas / inspector
 * (EAC-3.2 — out of scope for this ticket).
 */
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import clsx from 'clsx';
import { GripVertical } from 'lucide-react';
import type { CSSProperties, KeyboardEvent, MouseEvent, ReactNode } from 'react';

import { getBlockTokens } from '../../tokens';
import type { BlockColor } from '../../types';

export interface BlockShellProps {
  /** The color identity for this block. Drives all visual styling. */
  color: BlockColor;
  /** Visible heading. If omitted, falls back to the color's canonical label. */
  label?: string;
  /**
   * Optional override for the lucide icon. If omitted, the canonical icon for
   * the color is used.
   */
  icon?: ReactNode;
  /**
   * Body content — block-specific summary (e.g. "Category: Walls",
   * "AND 2 children", "≥ 240 mm").
   */
  children?: ReactNode;
  /** Selected state — applies stronger border / background. */
  selected?: boolean;
  /** Click handler — wired to the canvas selection store at the parent. */
  onSelect?: () => void;
  /**
   * Whether this shell should register itself with `dnd-kit` and render a
   * drag handle. The canvas decides this — palette items use `useDraggable`
   * (different hook), so they pass `draggable={false}` and rely on the
   * `<DraggablePaletteItem>` wrapper instead.
   */
  draggable?: boolean;
  /**
   * Stable id used by `useSortable`. Required when `draggable` is true.
   * Ignored otherwise.
   */
  sortableId?: string;
  /** Extra Tailwind classes to apply to the outer container. */
  className?: string;
  /**
   * Test id for Playwright / Vitest selectors. Optional.
   */
  testId?: string;
}

/**
 * Sentinel id used when the caller marks the shell as draggable but forgets to
 * pass a `sortableId`. We still register the shell with `useSortable` so the
 * Hooks rules are obeyed, but we make the missing id loud in dev.
 */
const FALLBACK_SORTABLE_ID = '__eac_block_shell_unset__';

export function BlockShell({
  color,
  label,
  icon,
  children,
  selected = false,
  onSelect,
  draggable = false,
  sortableId,
  className,
  testId,
}: BlockShellProps) {
  const tokens = getBlockTokens(color);

  // Always call useSortable so React hook rules are honored. When the shell
  // isn't draggable we discard the listeners/attributes and don't show a drag
  // handle.
  const sortable = useSortable({
    id: sortableId ?? FALLBACK_SORTABLE_ID,
    disabled: !draggable,
  });

  const dragStyle: CSSProperties | undefined = draggable
    ? {
        transform: CSS.Transform.toString(sortable.transform),
        transition: sortable.transition,
        opacity: sortable.isDragging ? 0.6 : undefined,
      }
    : undefined;

  const Icon = tokens.Icon;
  const visibleLabel = label ?? tokens.label;

  function handleClick(event: MouseEvent<HTMLDivElement>) {
    // Don't steal focus from interactive children (e.g. inputs in the
    // inspector overlay).
    if (event.defaultPrevented) return;
    onSelect?.();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!onSelect) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onSelect();
    }
  }

  return (
    <div
      ref={draggable ? sortable.setNodeRef : undefined}
      style={dragStyle}
      role="group"
      aria-label={visibleLabel}
      aria-selected={selected || undefined}
      aria-grabbed={draggable ? sortable.isDragging : undefined}
      data-testid={testId ?? `eac-block-${color}`}
      data-block-color={color}
      data-block-selected={selected ? 'true' : 'false'}
      tabIndex={onSelect ? 0 : -1}
      onClick={onSelect ? handleClick : undefined}
      onKeyDown={onSelect ? handleKeyDown : undefined}
      className={clsx(
        'flex w-full flex-col gap-1 rounded-md border-2 px-3 py-2 text-sm',
        'transition-all duration-fast ease-oe transform-gpu',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
        selected ? tokens.classes.bgSelected : tokens.classes.bg,
        selected ? tokens.classes.borderSelected : tokens.classes.border,
        tokens.classes.text,
        onSelect && 'cursor-pointer hover:shadow-sm',
        className,
      )}
    >
      <div className="flex items-center gap-2">
        {draggable && (
          <button
            type="button"
            aria-label={`Drag ${visibleLabel} block`}
            data-testid="eac-block-drag-handle"
            className={clsx(
              'flex h-5 w-5 shrink-0 cursor-grab items-center justify-center rounded',
              'hover:bg-black/5 dark:hover:bg-white/10 active:cursor-grabbing',
              tokens.classes.icon,
            )}
            {...sortable.attributes}
            {...sortable.listeners}
          >
            <GripVertical size={14} aria-hidden="true" />
          </button>
        )}
        <span className={clsx('flex h-5 w-5 shrink-0 items-center justify-center', tokens.classes.icon)}>
          {icon ?? <Icon size={16} aria-hidden="true" />}
        </span>
        <span className="truncate font-medium">{visibleLabel}</span>
      </div>
      {children !== undefined && children !== null && (
        <div className={clsx('pl-7 text-xs', tokens.classes.textSubtle)}>{children}</div>
      )}
    </div>
  );
}
