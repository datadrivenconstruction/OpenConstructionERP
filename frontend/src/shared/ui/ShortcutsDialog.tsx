// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import clsx from 'clsx';

interface ShortcutsDialogProps {
  open: boolean;
  onClose: () => void;
}

interface ShortcutEntry {
  keys: string[];
  descriptionKey: string;
  /** English fallback for a key that is newer than some locale files. */
  defaultValue?: string;
}

interface ShortcutGroup {
  titleKey: string;
  items: ShortcutEntry[];
}

const SHORTCUT_GROUPS: ShortcutGroup[] = [
  {
    titleKey: 'shortcuts.group.general',
    items: [
      { keys: ['/'], descriptionKey: 'shortcuts.open_search' },
      { keys: ['Ctrl', 'K'], descriptionKey: 'shortcuts.command_palette' },
      { keys: ['?'], descriptionKey: 'shortcuts.show_help' },
      { keys: ['Esc'], descriptionKey: 'shortcuts.cancel' },
      // Handled by the AI dock itself (features/erp-chat/useFloatingChat.ts
      // `isDockShortcut`). From the page it opens the dock or moves focus
      // into it; from inside the dock it closes it.
      {
        keys: ['Alt', 'A'],
        descriptionKey: 'shortcuts.toggle_ai_assistant',
        defaultValue: 'Open the AI assistant, press again to close',
      },
    ],
  },
  {
    titleKey: 'shortcuts.group.navigation',
    // Each row's descriptionKey below is the SAME locale key the target
    // route uses for its own name (Sidebar.tsx `labelKey` / the page's own
    // title key), not a dedicated shortcuts.nav_* string. A standalone
    // shortcuts.nav_* copy previously drifted out of sync with the sidebar
    // in up to 21/29 locales, and shortcuts.nav_finance was never added to
    // any locale at all, so opening this dialog printed the raw key.
    // Reusing the sidebar's own key removes the second copy that could drift.
    items: [
      { keys: ['g', 'd'], descriptionKey: 'nav.dashboard' },
      { keys: ['g', 'p'], descriptionKey: 'projects.title' },
      { keys: ['g', 'b'], descriptionKey: 'boq.title' },
      { keys: ['g', 'c'], descriptionKey: 'costs.title' },
      { keys: ['g', 'a'], descriptionKey: 'nav.assemblies' },
      { keys: ['g', 'v'], descriptionKey: 'validation.title' },
      { keys: ['g', 's'], descriptionKey: 'schedule.title' },
      { keys: ['g', 'f'], descriptionKey: 'finance.title' },
      { keys: ['g', '5'], descriptionKey: 'nav.5d_cost_model' },
      { keys: ['g', 'r'], descriptionKey: 'nav.reports' },
      { keys: ['g', 't'], descriptionKey: 'tendering.title' },
      { keys: ['g', 'm'], descriptionKey: 'meetings.title' },
      { keys: ['g', 'i'], descriptionKey: 'rfi.title' },
      { keys: ['g', 'o'], descriptionKey: 'contacts.title' },
    ],
  },
  {
    titleKey: 'shortcuts.group.actions',
    items: [
      { keys: ['n', 'p'], descriptionKey: 'shortcuts.new_project' },
      { keys: ['n', 'b'], descriptionKey: 'shortcuts.new_boq' },
      { keys: ['n', 't'], descriptionKey: 'shortcuts.new_task' },
    ],
  },
  {
    titleKey: 'shortcuts.group.module_pages',
    items: [
      { keys: ['n'], descriptionKey: 'shortcuts.create_new_item' },
    ],
  },
  {
    titleKey: 'shortcuts.group.boq_editor',
    items: [
      { keys: ['s'], descriptionKey: 'shortcuts.save_recalculate' },
      { keys: ['Ctrl', 'Z'], descriptionKey: 'shortcuts.undo' },
      { keys: ['Ctrl', 'Y'], descriptionKey: 'shortcuts.redo' },
      { keys: ['Ctrl', 'Shift', 'V'], descriptionKey: 'shortcuts.paste_from_excel' },
      { keys: ['Tab'], descriptionKey: 'shortcuts.next_field' },
      { keys: ['Enter'], descriptionKey: 'shortcuts.confirm_next_row' },
      { keys: ['Esc'], descriptionKey: 'shortcuts.cancel_editing' },
    ],
  },
];

function Kbd({ children }: { children: string }) {
  return (
    <kbd
      className={clsx(
        'inline-flex h-6 min-w-[1.5rem] items-center justify-center rounded-md px-1.5',
        'bg-surface-secondary border border-border-light',
        'font-mono text-xs font-medium text-content-secondary',
        'shadow-[0_1px_0_1px_rgba(0,0,0,0.04)]',
      )}
    >
      {children}
    </kbd>
  );
}

export function ShortcutsDialog({ open, onClose }: ShortcutsDialogProps) {
  const { t } = useTranslation();
  const dialogRef = useRef<HTMLDivElement>(null);

  // Close on Escape key
  useEffect(() => {
    if (!open) return;

    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };

    document.addEventListener('keydown', handler, { capture: true });
    return () => document.removeEventListener('keydown', handler, { capture: true });
  }, [open, onClose]);

  // Close on click outside
  useEffect(() => {
    if (!open) return;

    const handler = (e: MouseEvent) => {
      if (dialogRef.current && !dialogRef.current.contains(e.target as Node)) {
        onClose();
      }
    };

    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open, onClose]);

  // Trap focus inside the dialog
  useEffect(() => {
    if (open) {
      dialogRef.current?.focus();
    }
  }, [open]);

  if (!open) return null;

  return (
    // z-[60], like the command palette: this dialog mounts early in the DOM
    // (App.tsx GlobalShortcuts), so at z-50 it would open UNDER the AI dock
    // and its backdrop when "?" is pressed with the dock open as an overlay.
    <div className="fixed inset-0 z-[60] flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in" />

      {/* Dialog */}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={t('shortcuts.title')}
        tabIndex={-1}
        className={clsx(
          'relative z-10 w-full max-w-lg mx-4',
          'rounded-2xl border border-border-light',
          'bg-surface-elevated shadow-xl',
          'animate-scale-in',
          'focus:outline-none',
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-5 pb-3">
          <h2 className="text-base font-semibold text-content-primary">
            {t('shortcuts.title')}
          </h2>
          <button
            onClick={onClose}
            className={clsx(
              'flex h-8 w-8 items-center justify-center rounded-lg',
              'text-content-tertiary transition-colors',
              'hover:bg-surface-secondary hover:text-content-secondary',
            )}
            aria-label={t('common.cancel')}
          >
            <X size={16} />
          </button>
        </div>

        {/* Content */}
        <div className="px-6 pb-6 max-h-[70vh] overflow-y-auto">
          {SHORTCUT_GROUPS.map((group, groupIdx) => (
            <div key={group.titleKey} className={clsx(groupIdx > 0 && 'mt-5')}>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2.5">
                {t(group.titleKey)}
              </h3>
              <div className="space-y-1">
                {group.items.map((item) => {
                  // If the combo includes a modifier key, separate with "+";
                  // otherwise it's a sequence (e.g. "g d") — separate with "then".
                  const hasModifier = item.keys.some((k) =>
                    ['Ctrl', 'Shift', 'Alt', 'Cmd', 'Meta'].includes(k),
                  );
                  return (
                    <div
                      key={item.descriptionKey}
                      className="flex items-center justify-between py-1.5"
                    >
                      <span className="text-sm text-content-primary">
                        {item.defaultValue
                          ? t(item.descriptionKey, { defaultValue: item.defaultValue })
                          : t(item.descriptionKey)}
                      </span>
                      <div className="flex items-center gap-1 ml-4 shrink-0">
                        {item.keys.map((key, keyIdx) => (
                          <span key={keyIdx} className="flex items-center gap-1">
                            {keyIdx > 0 && (
                              <span className="text-xs text-content-tertiary mx-0.5">
                                {hasModifier ? '+' : t('shortcuts.separator_then')}
                              </span>
                            )}
                            <Kbd>{key}</Kbd>
                          </span>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="border-t border-border-light px-6 py-3">
          <p className="text-xs text-content-tertiary">
            {t('shortcuts.footer_hint')}
          </p>
        </div>
      </div>
    </div>
  );
}
