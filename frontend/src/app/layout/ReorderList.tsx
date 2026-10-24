// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** A list reordered by drag and drop, by the up/down buttons, or by Alt+Arrow keys. */
import { useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { ArrowDown, ArrowUp, GripVertical } from 'lucide-react';

export interface ReorderEntry {
  id: string;
  label: string;
  extra?: ReactNode;
}

export function ReorderList({
  entries,
  onMove,
  testId,
}: {
  entries: ReorderEntry[];
  onMove: (from: number, to: number) => void;
  testId?: string;
}) {
  const { t } = useTranslation();
  const [dragFrom, setDragFrom] = useState<number | null>(null);
  const [over, setOver] = useState<number | null>(null);
  const rows = useRef<(HTMLLIElement | null)[]>([]);

  const move = (from: number, to: number) => {
    if (to < 0 || to >= entries.length || from === to) return;
    onMove(from, to);
    // Keep focus on the moved row so repeated key presses keep moving it.
    requestAnimationFrame(() => rows.current[to]?.focus());
  };

  return (
    <ul className="space-y-1" data-testid={testId} aria-label={t('menu_layout.reorder_hint', { defaultValue: 'Drag, or press Alt and an arrow key to move' })}>
      {entries.map((entry, i) => (
        <li
          key={entry.id}
          ref={(el) => {
            rows.current[i] = el;
          }}
          tabIndex={0}
          draggable
          data-testid={testId ? `${testId}-row-${entry.id}` : undefined}
          onDragStart={(e) => {
            setDragFrom(i);
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', entry.id);
          }}
          onDragOver={(e) => {
            e.preventDefault();
            setOver(i);
          }}
          onDragLeave={() => setOver((o) => (o === i ? null : o))}
          onDrop={(e) => {
            e.preventDefault();
            if (dragFrom != null) move(dragFrom, i);
            setDragFrom(null);
            setOver(null);
          }}
          onDragEnd={() => {
            setDragFrom(null);
            setOver(null);
          }}
          onKeyDown={(e) => {
            if (!e.altKey || e.target !== e.currentTarget) return;
            if (e.key === 'ArrowUp') {
              e.preventDefault();
              move(i, i - 1);
            } else if (e.key === 'ArrowDown') {
              e.preventDefault();
              move(i, i + 1);
            }
          }}
          className={clsx(
            'flex items-center gap-2 rounded-md border bg-surface-primary px-2 py-1.5 text-sm',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
            over === i && dragFrom !== i ? 'border-oe-blue' : 'border-border-light',
            dragFrom === i && 'opacity-50',
          )}
        >
          <GripVertical size={14} className="shrink-0 cursor-grab text-content-quaternary" aria-hidden />
          <span className="min-w-0 flex-1 truncate">{entry.label}</span>
          {entry.extra}
          <button
            type="button"
            onClick={() => move(i, i - 1)}
            disabled={i === 0}
            aria-label={t('menu_layout.move_up', { defaultValue: 'Move {{label}} up', label: entry.label })}
            className="flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:bg-surface-secondary disabled:opacity-30"
          >
            <ArrowUp size={12} />
          </button>
          <button
            type="button"
            onClick={() => move(i, i + 1)}
            disabled={i === entries.length - 1}
            aria-label={t('menu_layout.move_down', { defaultValue: 'Move {{label}} down', label: entry.label })}
            className="flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:bg-surface-secondary disabled:opacity-30"
          >
            <ArrowDown size={12} />
          </button>
        </li>
      ))}
    </ul>
  );
}
