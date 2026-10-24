// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Work-mode switcher, adaptive suggestion card and rail flyout for the sidebar. */
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Lightbulb, SlidersHorizontal, X } from 'lucide-react';
import clsx from 'clsx';
import { MENU_MODE_IDS, type MenuModeId } from './menuLayout';
import { MODE_DEFAULT_LABELS, modeLabelKey } from './MenuOrganizer';
import type { MenuSuggestion } from './menuUsage';

export function MenuModeBar({
  mode,
  onMode,
  onArrange,
}: {
  mode: MenuModeId;
  onMode: (m: MenuModeId) => void;
  onArrange: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-1.5 px-3 pb-1" data-testid="menu-mode-bar">
      <label className="sr-only" htmlFor="oe-menu-mode">
        {t('menu_layout.mode_label', { defaultValue: 'Work mode' })}
      </label>
      <select
        id="oe-menu-mode"
        data-testid="menu-mode-select"
        value={mode}
        onChange={(e) => onMode(e.target.value as MenuModeId)}
        title={t('menu_layout.mode_hint', { defaultValue: 'Show only the screens for your job' })}
        className="min-w-0 flex-1 rounded-md border border-border-light bg-surface-secondary/60 px-2 py-1 text-[12px] text-content-secondary"
      >
        {MENU_MODE_IDS.map((m) => (
          <option key={m} value={m}>
            {t(modeLabelKey(m), { defaultValue: MODE_DEFAULT_LABELS[m] })}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={onArrange}
        data-testid="menu-arrange"
        aria-label={t('menu_layout.title', { defaultValue: 'Arrange menu' })}
        title={t('menu_layout.title', { defaultValue: 'Arrange menu' })}
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border-light text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
      >
        <SlidersHorizontal size={13} />
      </button>
    </div>
  );
}

export function MenuSuggestionCard({
  suggestion,
  label,
  onAccept,
  onDismiss,
}: {
  suggestion: MenuSuggestion;
  label: string;
  onAccept: () => void;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();
  const hide = suggestion.kind === 'hide';
  return (
    <div
      role="status"
      data-testid="menu-suggestion"
      className="mx-3 mb-2 rounded-lg border border-oe-blue/30 bg-oe-blue/5 p-2 text-[12px]"
    >
      <div className="flex items-start gap-1.5">
        <Lightbulb size={13} className="mt-0.5 shrink-0 text-oe-blue" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="font-medium text-content-primary">
            {hide
              ? t('menu_layout.suggest_hide', { defaultValue: 'Hide {{label}}?', label })
              : t('menu_layout.suggest_pin', { defaultValue: 'Pin {{label}}?', label })}
          </div>
          <div className="text-content-tertiary">
            {hide
              ? t('menu_layout.reason_unused', { defaultValue: 'Days without use: {{count}}', count: suggestion.value })
              : t('menu_layout.reason_frequent', { defaultValue: 'Times opened: {{count}}', count: suggestion.value })}
          </div>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label={t('menu_layout.not_now', { defaultValue: 'Not now' })}
          className="text-content-quaternary hover:text-content-primary"
        >
          <X size={12} />
        </button>
      </div>
      <div className="mt-1.5 flex gap-1.5">
        <button type="button" onClick={onAccept} className="rounded bg-oe-blue px-2 py-0.5 text-white">
          {t('menu_layout.accept', { defaultValue: 'Accept' })}
        </button>
        <button type="button" onClick={onDismiss} className="rounded px-2 py-0.5 text-content-secondary hover:bg-surface-secondary">
          {t('menu_layout.not_now', { defaultValue: 'Not now' })}
        </button>
      </div>
    </div>
  );
}

/** One icon per section; its rows open in a flyout on hover or keyboard focus. */
export function RailFlyoutGroup({
  label,
  icon,
  children,
}: {
  label: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div
      className="relative mb-1 flex justify-center"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOpen(false);
      }}
      onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
      data-testid="rail-group"
    >
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={label}
        title={label}
        onClick={() => setOpen((o) => !o)}
        className={clsx(
          'flex h-9 w-9 items-center justify-center rounded-lg text-content-secondary hover:bg-surface-secondary',
          open && 'bg-surface-secondary',
        )}
      >
        {icon}
      </button>
      {open && (
        <div className="absolute start-full top-0 z-50 ms-1 w-56 rounded-lg border border-border-light bg-surface-primary p-1.5 shadow-lg">
          <div className="px-2 pb-1 text-[11px] font-medium text-content-tertiary">{label}</div>
          {children}
        </div>
      )}
    </div>
  );
}
