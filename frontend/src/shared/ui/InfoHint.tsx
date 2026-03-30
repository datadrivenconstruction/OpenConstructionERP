import { useState, useRef, useEffect } from 'react';
import { Info, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';

interface InfoHintProps {
  text: string;
  className?: string;
  style?: React.CSSProperties;
  /** Render as inline icon next to a title instead of standalone block */
  inline?: boolean;
  /** Custom label for the block-mode button */
  label?: string;
}

/**
 * Collapsible info hint — shows an (i) icon that reveals help text on click.
 * Use `inline` for placement next to titles; omit for standalone usage.
 */
export function InfoHint({ text, className, style, inline, label }: InfoHintProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Close inline popover on outside click
  useEffect(() => {
    if (!open || !inline) return;
    const handler = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open, inline]);

  if (inline) {
    return (
      <span ref={popoverRef} className={clsx('relative inline-flex items-center', className)}>
        <button
          onClick={() => setOpen(!open)}
          className={clsx(
            'inline-flex items-center justify-center rounded-full p-0.5 transition-colors',
            open
              ? 'text-oe-blue bg-oe-blue/10'
              : 'text-content-tertiary hover:text-content-secondary hover:bg-surface-secondary',
          )}
          aria-label={t('common.info', { defaultValue: 'Info' })}
          aria-expanded={open}
        >
          <Info size={14} strokeWidth={2} />
        </button>
        {open && (
          <div className="absolute left-0 top-full z-20 mt-1.5 w-80">
            <div className="rounded-lg border border-border-light bg-surface-primary px-3 py-2.5 text-xs text-content-secondary leading-relaxed shadow-lg">
              {text}
              <button
                onClick={() => setOpen(false)}
                className="ml-2 inline-flex align-middle text-content-tertiary hover:text-content-secondary transition-colors"
                aria-label={t('common.close', { defaultValue: 'Close' })}
              >
                <X size={12} />
              </button>
            </div>
          </div>
        )}
      </span>
    );
  }

  return (
    <div className={className} style={style}>
      <button
        onClick={() => setOpen(!open)}
        className={clsx(
          'flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-all',
          open
            ? 'text-oe-blue bg-oe-blue/10'
            : 'text-content-tertiary hover:text-content-secondary hover:bg-surface-secondary/60',
        )}
        aria-expanded={open}
      >
        <Info size={14} strokeWidth={2} className="shrink-0" />
        <span>
          {label ?? (open
            ? t('common.hide_info', { defaultValue: 'Hide info' })
            : t('common.how_it_works', { defaultValue: 'How it works' }))}
        </span>
      </button>
      <div
        className={clsx(
          'overflow-hidden transition-all duration-200 ease-out',
          open ? 'mt-1.5 max-h-40 opacity-100' : 'max-h-0 opacity-0',
        )}
      >
        <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-4 py-2.5 text-xs text-content-secondary leading-relaxed">
          {text}
        </div>
      </div>
    </div>
  );
}
