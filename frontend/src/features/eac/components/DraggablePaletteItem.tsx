/**
 * `<DraggablePaletteItem>` — single entry inside the palette categorized list.
 *
 * Uses `useDraggable` from `@dnd-kit/core` so the item can be dragged onto the
 * canvas with WCAG-compliant keyboard interaction (space/enter to lift,
 * arrow keys to move, space/enter to drop). The actual drop handling lives in
 * the canvas (EAC-3.2).
 */
import { useDraggable } from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import clsx from 'clsx';
import type { CSSProperties } from 'react';

import { getBlockTokens } from '../tokens';
import type { BlockColor } from '../types';

export interface PaletteItem {
  /** Stable id used by `useDraggable` and the canvas drop handler. */
  id: string;
  /** Block color identity. */
  color: BlockColor;
  /** Visible label, e.g. "IFC class", "Property", "AND". */
  label: string;
  /** Optional secondary line shown below the label. */
  description?: string;
  /**
   * Free-form payload describing what to instantiate when dropped on the
   * canvas. The canvas knows how to interpret these.
   */
  payload?: Record<string, unknown>;
}

export interface DraggablePaletteItemProps {
  item: PaletteItem;
  /** Optional callback fired when the user clicks (not drags) the item. */
  onActivate?: (item: PaletteItem) => void;
}

export function DraggablePaletteItem({ item, onActivate }: DraggablePaletteItemProps) {
  const tokens = getBlockTokens(item.color);
  const Icon = tokens.Icon;

  const { setNodeRef, attributes, listeners, transform, isDragging } = useDraggable({
    id: item.id,
    data: { source: 'palette', item },
  });

  const style: CSSProperties = {
    transform: CSS.Translate.toString(transform),
    opacity: isDragging ? 0.5 : undefined,
  };

  return (
    <button
      ref={setNodeRef}
      type="button"
      style={style}
      data-testid={`eac-palette-item-${item.id}`}
      data-block-color={item.color}
      onClick={() => onActivate?.(item)}
      className={clsx(
        'group flex w-full items-start gap-2 rounded-md border px-2.5 py-2 text-left',
        'transition-all duration-fast ease-oe transform-gpu cursor-grab',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
        'hover:shadow-sm active:cursor-grabbing',
        tokens.classes.bg,
        tokens.classes.border,
        tokens.classes.text,
      )}
      {...attributes}
      {...listeners}
    >
      <span
        className={clsx(
          'mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center',
          tokens.classes.icon,
        )}
      >
        <Icon size={14} aria-hidden="true" />
      </span>
      <span className="flex min-w-0 flex-col">
        <span className="truncate text-sm font-medium">{item.label}</span>
        {item.description && (
          <span className={clsx('truncate text-xs', tokens.classes.textSubtle)}>
            {item.description}
          </span>
        )}
      </span>
    </button>
  );
}
