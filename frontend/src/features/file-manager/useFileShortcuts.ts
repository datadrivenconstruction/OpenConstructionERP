// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** Keyboard shortcuts for the /files page — Phase-0 quick win.
 *
 * Mirrors construction management platform conventions: `/` focuses the search box, `g` /
 * `l` toggle grid/list view, `Delete` bulk-deletes the current
 * selection, `Escape` clears selection + closes the preview, `?` opens
 * the cheatsheet.
 *
 * Shortcuts are suppressed when a text input / textarea / contenteditable
 * has focus so typing into the search box doesn't toggle views.
 */

import { useEffect } from 'react';

interface FileShortcutsOptions {
  onFocusSearch?: () => void;
  onSetView?: (view: 'grid' | 'list') => void;
  onDeleteSelection?: () => void;
  onEscape?: () => void;
  onToggleCheatsheet?: () => void;
  /** Set to false on routes where shortcuts must not fire. */
  enabled?: boolean;
}

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (target.isContentEditable) return true;
  return false;
}

export function useFileShortcuts({
  onFocusSearch,
  onSetView,
  onDeleteSelection,
  onEscape,
  onToggleCheatsheet,
  enabled = true,
}: FileShortcutsOptions) {
  useEffect(() => {
    if (!enabled) return;
    const handler = (e: KeyboardEvent) => {
      // Modifier-bound shortcuts stay reserved for the browser / OS.
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      if (e.key === 'Escape') {
        onEscape?.();
        return;
      }

      if (isEditable(e.target)) return;

      if (e.key === '/') {
        e.preventDefault();
        onFocusSearch?.();
        return;
      }
      if (e.key === '?') {
        e.preventDefault();
        onToggleCheatsheet?.();
        return;
      }
      if (e.key === 'g') {
        e.preventDefault();
        onSetView?.('grid');
        return;
      }
      if (e.key === 'l') {
        e.preventDefault();
        onSetView?.('list');
        return;
      }
      if (e.key === 'Delete' || e.key === 'Backspace') {
        // Only trigger Backspace fallback when nothing is being edited.
        if (e.key === 'Backspace' && !e.shiftKey) return;
        onDeleteSelection?.();
        return;
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [enabled, onFocusSearch, onSetView, onDeleteSelection, onEscape, onToggleCheatsheet]);
}

export interface ShortcutEntry {
  keys: string[];
  label: string;
}

export const FILE_SHORTCUTS: ShortcutEntry[] = [
  { keys: ['/'], label: 'Focus search' },
  { keys: ['g'], label: 'Grid view' },
  { keys: ['l'], label: 'List view' },
  { keys: ['Delete'], label: 'Delete selection' },
  { keys: ['Esc'], label: 'Clear selection / close preview' },
  { keys: ['?'], label: 'Show this cheatsheet' },
];
