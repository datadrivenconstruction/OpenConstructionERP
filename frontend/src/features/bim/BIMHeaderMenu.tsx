// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, MoreHorizontal } from 'lucide-react';
import clsx from 'clsx';

import { Button } from '@/shared/ui/Button';

/** Row look shared by every entry of the BIM header "More" menu. */
export function moreItemClass(active = false): string {
  return clsx(
    'flex h-8 w-full items-center gap-2 rounded-lg px-2.5 text-start text-sm transition-colors',
    'disabled:cursor-not-allowed disabled:opacity-40',
    active
      ? 'bg-oe-blue/10 text-oe-blue'
      : 'text-content-primary hover:bg-surface-secondary',
  );
}

interface MoreItemProps {
  icon: ReactNode;
  label: string;
  active?: boolean;
  onClick: () => void;
  disabled?: boolean;
  title?: string;
  testId?: string;
}

/** One toggle or jump inside the BIM header "More" menu. */
export function MoreItem({ icon, label, active, onClick, disabled, title, testId }: MoreItemProps) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      disabled={disabled}
      title={title ?? label}
      aria-pressed={active === undefined ? undefined : active}
      data-testid={testId}
      className={moreItemClass(!!active)}
    >
      <span className="shrink-0">{icon}</span>
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {active && <Check size={14} className="shrink-0" />}
    </button>
  );
}

/** Overflow dropdown of the BIM header: secondary panels and cross-module jumps. */
export function HeaderMoreMenu({ children, activeCount = 0 }: { children: ReactNode; activeCount?: number }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const label = t('common.more_actions', { defaultValue: 'More actions' });
  return (
    <div ref={boxRef} className="relative shrink-0" data-testid="bim-header-more">
      <Button
        variant="secondary"
        size="md"
        icon={<MoreHorizontal size={16} />}
        aria-label={label}
        title={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={clsx(activeCount > 0 && 'text-oe-blue')}
      />
      {open && (
        <div
          role="menu"
          className="absolute end-0 top-full z-dropdown mt-1 flex min-w-56 flex-col gap-0.5 rounded-xl border border-border-light bg-surface-primary p-1.5 shadow-md"
          onClick={(e) => {
            // Toggles that open their own panel close the menu after the click.
            if ((e.target as HTMLElement).closest('[role="menuitem"]')) setOpen(false);
          }}
        >
          {children}
        </div>
      )}
    </div>
  );
}
