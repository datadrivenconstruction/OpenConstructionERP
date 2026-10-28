// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** Keyboard-shortcuts cheatsheet modal — Phase-0 quick win.
 *
 * Reachable via `?` on the /files page. Lists the active shortcuts in a
 * tidy two-column grid with kbd-styled key caps.
 */

import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Keyboard, X } from 'lucide-react';
import { FILE_SHORTCUTS } from '../useFileShortcuts';

interface ShortcutsCheatsheetProps {
  open: boolean;
  onClose: () => void;
}

export function ShortcutsCheatsheet({ open, onClose }: ShortcutsCheatsheetProps) {
  const { t } = useTranslation();

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="file-shortcuts-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-content-primary/30 dark:bg-content-primary/50 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-xl border border-border-light bg-surface-elevated shadow-2xl p-5"
      >
        <div className="flex items-center gap-2 mb-3">
          <Keyboard size={18} className="text-content-tertiary" />
          <h2
            id="file-shortcuts-title"
            className="text-base font-semibold text-content-primary"
          >
            {t('files.shortcuts.title', { defaultValue: 'Keyboard shortcuts' })}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="ml-auto inline-flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
          >
            <X size={14} />
          </button>
        </div>
        <ul className="divide-y divide-border-light">
          {FILE_SHORTCUTS.map((entry) => (
            <li
              key={entry.label}
              className="flex items-center justify-between gap-3 py-2"
            >
              <span className="text-sm text-content-secondary">
                {t(`files.shortcuts.${slug(entry.label)}`, {
                  defaultValue: entry.label,
                })}
              </span>
              <span className="flex items-center gap-1 shrink-0">
                {entry.keys.map((k) => (
                  <kbd
                    key={k}
                    className="inline-flex h-6 min-w-[26px] items-center justify-center px-1.5 rounded border border-border-light bg-surface-secondary text-2xs font-semibold text-content-secondary tabular-nums"
                  >
                    {k}
                  </kbd>
                ))}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-2xs text-content-tertiary">
          {t('files.shortcuts.hint', {
            defaultValue: 'Shortcuts are inactive while typing in an input.',
          })}
        </p>
      </div>
    </div>
  );
}

function slug(label: string): string {
  return label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/_$/g, '');
}
