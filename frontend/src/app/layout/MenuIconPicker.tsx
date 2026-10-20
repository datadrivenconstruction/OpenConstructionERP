// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Searchable icon picker for one menu item. Lazily loaded together with the
 * curated catalogue, so neither weighs on the main bundle. Picking an icon
 * applies it at once everywhere the route's icon shows; Reset brings back
 * the default.
 */
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { RotateCcw, Search, X } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import clsx from 'clsx';
import { useFocusTrap } from '@/shared/hooks/useFocusTrap';
import { useAppearanceStore } from '@/stores/useAppearanceStore';
import { MENU_ICON_GROUPS, MENU_ICON_BY_NAME, type CatalogGroup } from './menuIconCatalog';

export interface MenuIconPickerProps {
  /** Menu route whose icon is being chosen. */
  route: string;
  /** The item's label, for the title. */
  label: string;
  /** The item's default icon, shown while nothing else is chosen. */
  defaultIcon: LucideIcon;
  onClose: () => void;
}

const GROUP_FALLBACK: Record<CatalogGroup['id'], string> = {
  construction: 'Site and buildings',
  documents: 'Documents',
  money: 'Money and contracts',
  charts: 'Charts and structure',
  time: 'Time',
  people: 'People and messages',
  quality: 'Quality and safety',
  tech: 'Data and tools',
};

/** "FileSpreadsheet" -> "file spreadsheet", so names are searchable as words. */
function words(name: string): string {
  return name.replace(/([a-z])([A-Z0-9])/g, '$1 $2').toLowerCase();
}

export default function MenuIconPicker({ route, label, defaultIcon, onClose }: MenuIconPickerProps) {
  const { t } = useTranslation();
  const current = useAppearanceStore((s) => s.iconOverrides[route] ?? null);
  const setIconOverride = useAppearanceStore((s) => s.setIconOverride);
  const [query, setQuery] = useState('');
  const [hovered, setHovered] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  useFocusTrap(dialogRef, true);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return MENU_ICON_GROUPS;
    const terms = q.split(/\s+/);
    return MENU_ICON_GROUPS.map((g) => ({
      ...g,
      icons: g.icons.filter((c) => {
        const hay = `${words(c.name)} ${c.keywords}`;
        return terms.every((term) => hay.includes(term));
      }),
    })).filter((g) => g.icons.length > 0);
  }, [query]);

  const PreviewIcon = (hovered && MENU_ICON_BY_NAME[hovered]) || (current && MENU_ICON_BY_NAME[current]) || defaultIcon;
  const groupLabel = (id: CatalogGroup['id']) =>
    t(`settings.menu_icons_group_${id}`, { defaultValue: GROUP_FALLBACK[id] });

  const choose = (name: string | null) => {
    setIconOverride(route, name);
    onClose();
  };

  // Arrow keys move through the grid in reading order (mirrored in RTL).
  const onGridKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const keys = ['ArrowRight', 'ArrowLeft', 'ArrowDown', 'ArrowUp', 'Home', 'End'];
    if (!keys.includes(e.key) || !gridRef.current) return;
    const buttons = Array.from(gridRef.current.querySelectorAll<HTMLButtonElement>('button[data-icon]'));
    const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (at < 0) return;
    e.preventDefault();
    const rtl = document.documentElement.dir === 'rtl';
    const first = buttons[0]!;
    const cols = Math.max(1, Math.round(gridRef.current.clientWidth / (first.offsetWidth + 4)));
    let next = at;
    if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = buttons.length - 1;
    else if (e.key === 'ArrowDown') next = at + cols;
    else if (e.key === 'ArrowUp') next = at - cols;
    else if ((e.key === 'ArrowRight') !== rtl) next = at + 1;
    else next = at - 1;
    buttons[Math.min(buttons.length - 1, Math.max(0, next))]?.focus();
  };

  const title = t('settings.menu_icons_pick_title', { defaultValue: 'Icon for {{label}}', label });

  return createPortal(
    <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm animate-fade-in" onClick={onClose} aria-hidden />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="relative z-10 flex max-h-[min(36rem,90vh)] w-full max-w-lg flex-col rounded-2xl border border-border-light bg-surface-elevated shadow-xl animate-scale-in"
      >
        <div className="flex items-center gap-3 border-b border-border-light p-4">
          <span
            aria-hidden
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue-text"
          >
            <PreviewIcon size={20} strokeWidth={1.75} />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-sm font-semibold text-content-primary">{title}</h2>
            <p className="text-xs text-content-tertiary">
              {t('settings.menu_icons_pick_hint', {
                defaultValue: 'Shown in the menu, the top bar and the command palette.',
              })}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
          >
            <X size={16} />
          </button>
        </div>

        <div className="px-4 pt-3">
          <label className="relative block">
            <span className="sr-only">{t('settings.menu_icons_search', { defaultValue: 'Search icons' })}</span>
            <Search
              size={14}
              aria-hidden
              className="pointer-events-none absolute start-2.5 top-1/2 -translate-y-1/2 text-content-tertiary"
            />
            <input
              type="search"
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('settings.menu_icons_search_placeholder', {
                defaultValue: 'Search in English: truck, invoice, safety…',
              })}
              className="h-9 w-full rounded-lg border border-border bg-surface-primary ps-8 pe-3 text-sm text-content-primary placeholder:text-content-quaternary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/20"
            />
          </label>
        </div>

        <div ref={gridRef} onKeyDown={onGridKey} className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          {groups.length === 0 && (
            <p className="py-8 text-center text-sm text-content-tertiary">
              {t('settings.menu_icons_none', { defaultValue: 'No icon matches this search.' })}
            </p>
          )}
          {groups.map((g) => (
            <section key={g.id} className="mb-3 last:mb-0" aria-label={groupLabel(g.id)}>
              <h3 className="mb-1.5 text-[11px] font-semibold text-content-tertiary">{groupLabel(g.id)}</h3>
              <div className="grid grid-cols-[repeat(auto-fill,minmax(2.5rem,1fr))] gap-1">
                {g.icons.map(({ name, icon: Icon }) => {
                  const active = current === name;
                  return (
                    <button
                      key={name}
                      type="button"
                      data-icon={name}
                      aria-pressed={active}
                      aria-label={words(name)}
                      title={words(name)}
                      onClick={() => choose(name)}
                      onMouseEnter={() => setHovered(name)}
                      onMouseLeave={() => setHovered(null)}
                      onFocus={() => setHovered(name)}
                      onBlur={() => setHovered(null)}
                      className={clsx(
                        'flex h-10 items-center justify-center rounded-lg border transition-colors',
                        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/50',
                        active
                          ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
                          : 'border-transparent text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
                      )}
                    >
                      <Icon size={18} strokeWidth={1.75} aria-hidden />
                    </button>
                  );
                })}
              </div>
            </section>
          ))}
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-border-light px-4 py-3">
          <button
            type="button"
            onClick={() => choose(null)}
            disabled={!current}
            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary hover:text-content-primary disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RotateCcw size={14} aria-hidden />
            {t('settings.menu_icons_reset_one', { defaultValue: 'Reset to default' })}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-3 py-1.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary hover:text-content-primary"
          >
            {t('common.done', { defaultValue: 'Done' })}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
