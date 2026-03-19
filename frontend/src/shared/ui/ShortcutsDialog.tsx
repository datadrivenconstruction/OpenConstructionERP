import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import clsx from 'clsx';

interface ShortcutsDialogProps {
  open: boolean;
  onClose: () => void;
}

interface ShortcutEntry {
  keys: string[];
  description: string;
}

interface ShortcutGroup {
  title: string;
  items: ShortcutEntry[];
}

const SHORTCUT_GROUPS: ShortcutGroup[] = [
  {
    title: 'Navigation',
    items: [
      { keys: ['g', 'd'], description: 'Dashboard' },
      { keys: ['g', 'p'], description: 'Projects' },
      { keys: ['g', 'b'], description: 'Bill of Quantities' },
      { keys: ['g', 'c'], description: 'Cost Database' },
      { keys: ['g', 'a'], description: 'Assemblies' },
      { keys: ['g', 'v'], description: 'Validation' },
      { keys: ['g', 's'], description: '4D Schedule' },
      { keys: ['g', '5'], description: '5D Cost Model' },
    ],
  },
  {
    title: 'Actions',
    items: [
      { keys: ['/'], description: 'Search' },
      { keys: ['n', 'p'], description: 'New Project' },
      { keys: ['?'], description: 'Show this help' },
      { keys: ['Esc'], description: 'Close dialog / Cancel' },
    ],
  },
  {
    title: 'BOQ Editor',
    items: [
      { keys: ['Tab'], description: 'Next cell' },
      { keys: ['Enter'], description: 'Save & close cell' },
      { keys: ['Esc'], description: 'Cancel edit' },
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
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm animate-fade-in" />

      {/* Dialog */}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Keyboard Shortcuts"
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
          <h2 className="text-base font-semibold text-content-primary">Keyboard Shortcuts</h2>
          <button
            onClick={onClose}
            className={clsx(
              'flex h-8 w-8 items-center justify-center rounded-lg',
              'text-content-tertiary transition-colors',
              'hover:bg-surface-secondary hover:text-content-secondary',
            )}
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        {/* Content */}
        <div className="px-6 pb-6 max-h-[70vh] overflow-y-auto">
          {SHORTCUT_GROUPS.map((group, groupIdx) => (
            <div key={group.title} className={clsx(groupIdx > 0 && 'mt-5')}>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2.5">
                {group.title}
              </h3>
              <div className="space-y-1">
                {group.items.map((item) => (
                  <div
                    key={item.keys.join('+')}
                    className="flex items-center justify-between py-1.5"
                  >
                    <span className="text-sm text-content-primary">{item.description}</span>
                    <div className="flex items-center gap-1 ml-4 shrink-0">
                      {item.keys.map((key, keyIdx) => (
                        <span key={keyIdx} className="flex items-center gap-1">
                          {keyIdx > 0 && (
                            <span className="text-xs text-content-tertiary mx-0.5">then</span>
                          )}
                          <Kbd>{key}</Kbd>
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="border-t border-border-light px-6 py-3">
          <p className="text-xs text-content-tertiary">
            Shortcuts are disabled when focused on input fields.
          </p>
        </div>
      </div>
    </div>
  );
}
