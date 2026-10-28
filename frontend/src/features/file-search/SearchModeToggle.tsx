// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** Pill toggle between `Filename` and `Content` search modes.
 *
 * Designed to sit immediately next to the file-manager search input —
 * the user types once, the toggle decides which surface gets hit.
 *
 * Markup stays inline (we keep the custom rounded-full pill styling
 * that the file-manager toolbar relies on) but we use
 * {@link useTabKeyboardNav} to wire ArrowLeft/Right + Home/End and
 * roving tabIndex on the buttons so screen-reader / keyboard users get
 * the full WAI-ARIA "tabs" interaction.
 */

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { FileSearch, Type } from 'lucide-react';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import type { SearchMode } from './types';

const TAB_IDS = ['filename', 'content'] as const satisfies readonly SearchMode[];

interface SearchModeToggleProps {
  mode: SearchMode;
  onChange: (mode: SearchMode) => void;
  className?: string | undefined;
}

export function SearchModeToggle({ mode, onChange, className }: SearchModeToggleProps) {
  const { t } = useTranslation();

  const onTabKeyDown = useTabKeyboardNav<SearchMode>({
    ids: TAB_IDS,
    activeId: mode,
    onChange,
    orientation: 'horizontal',
  });

  return (
    <div
      role="tablist"
      aria-label={t('files.search.mode_label', { defaultValue: 'Search mode' })}
      onKeyDown={onTabKeyDown}
      className={clsx(
        'inline-flex h-7 items-center rounded-full border border-border-light bg-surface-elevated p-0.5',
        className,
      )}
    >
      <ModeButton
        id="filename"
        active={mode === 'filename'}
        onClick={() => onChange('filename')}
        icon={<Type size={11} />}
        label={t('files.search.mode_filename', { defaultValue: 'Filename' })}
      />
      <ModeButton
        id="content"
        active={mode === 'content'}
        onClick={() => onChange('content')}
        icon={<FileSearch size={11} />}
        label={t('files.search.mode_content', { defaultValue: 'Content' })}
      />
    </div>
  );
}

interface ModeButtonProps {
  id: SearchMode;
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}

function ModeButton({ id, active, onClick, icon, label }: ModeButtonProps) {
  return (
    <button
      type="button"
      role="tab"
      id={`files-search-mode-tab-${id}`}
      aria-selected={active}
      aria-controls={`files-search-mode-panel-${id}`}
      tabIndex={active ? 0 : -1}
      onClick={onClick}
      className={clsx(
        'inline-flex items-center gap-1 h-6 px-2 rounded-full text-[11px] font-medium transition-colors',
        active
          ? 'bg-oe-blue text-white'
          : 'text-content-secondary hover:bg-surface-secondary',
      )}
    >
      {icon}
      {label}
    </button>
  );
}
