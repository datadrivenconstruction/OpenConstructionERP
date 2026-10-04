// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - picking the screen a step opens.
//
// This replaced a text field with a <datalist>. A datalist is a list of
// strings, and the thing being chosen here is not a string, it is one of the
// product's screens. The author knows those screens by their icon and their
// place in the menu, which is exactly what a datalist cannot show, so picking
// "/rfis" out of a hundred typed paths meant recognising a path rather than
// recognising a module.
//
// So the picker shows the whole catalogue the way the menu shows it: every
// group, every screen, each with the icon it carries in the sidebar. The
// catalogue is `navGroups` itself rather than a copy of it, so a screen added
// to the menu appears here with no second edit.
//
// Two things sit above the catalogue on purpose. The screens our own shipped cases
// walk are offered first, because a case being written is usually a variation
// on one of them. And a free path stays possible at the bottom, for a screen
// no shipped case visits - the editor's job is to say "not one of ours" as
// information, not to refuse.

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowRight, Check, Search, Sparkles, X } from 'lucide-react';
import clsx from 'clsx';
import { Button, Input } from '@/shared/ui';
import { navGroups, type NavItem } from '@/app/layout/navCatalog';
import { STEP_TARGETS, isValidTarget } from './stepTargets';

interface ScreenPickerProps {
  /** The step's current target path. Empty while nothing is chosen. */
  value: string;
  /** Called with the path and the catalogue's own label for it. The label is
   *  passed so the caller can fill the step's module label without looking the
   *  screen up a second time. */
  onPick: (to: string, label: string) => void;
  onClose: () => void;
}

/** How many of a screen's uses across the shipped cases make it "one we lean
 *  on". Two is the floor: a screen one case visits is not yet a pattern. */
const POPULAR_MIN_USES = 2;

/** Admin-only surfaces are internal tools. A case that walks a reader into the
 *  architecture map is a case most readers cannot follow, so they are not
 *  offered - a typed path still reaches them. */
function pickable(item: NavItem): boolean {
  return !item.adminOnly;
}

export function ScreenPicker({ value, onPick, onClose }: ScreenPickerProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [custom, setCustom] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    searchRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const label = (item: NavItem) =>
    t(item.labelKey, { defaultValue: item.defaultLabel ?? item.labelKey });

  // The whole catalogue, flat, so search does not have to walk the groups.
  const everyScreen = useMemo(() => {
    const rows: { item: NavItem; group: string }[] = [];
    for (const group of navGroups) {
      const groupLabel = t(group.labelKey, { defaultValue: group.defaultLabel ?? group.labelKey });
      for (const item of group.items) {
        if (pickable(item)) rows.push({ item, group: groupLabel });
      }
    }
    return rows;
  }, [t]);

  // How often the shipped cases send a reader to each screen. Used only to
  // order the shortcut row; a screen absent from it is not lesser, it is just
  // one no shipped case happens to walk.
  const usesByRoute = useMemo(() => {
    const map = new Map<string, number>();
    for (const entry of STEP_TARGETS) map.set(entry.to, entry.uses);
    return map;
  }, []);

  const popular = useMemo(() => {
    return everyScreen
      .filter(({ item }) => (usesByRoute.get(item.to) ?? 0) >= POPULAR_MIN_USES)
      .sort((a, b) => (usesByRoute.get(b.item.to) ?? 0) - (usesByRoute.get(a.item.to) ?? 0))
      .slice(0, 10);
  }, [everyScreen, usesByRoute]);

  const needle = query.trim().toLowerCase();
  const matches = useMemo(() => {
    if (!needle) return null;
    return everyScreen.filter(
      ({ item, group }) =>
        label(item).toLowerCase().includes(needle) ||
        item.to.toLowerCase().includes(needle) ||
        group.toLowerCase().includes(needle),
    );
    // `label` closes over `t`, which `everyScreen` already depends on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needle, everyScreen]);

  const customOk = custom.trim().length > 0 && isValidTarget(custom.trim());

  const Tile = ({ item, group }: { item: NavItem; group?: string }) => {
    const Icon = item.icon;
    const chosen = item.to === value;
    return (
      <button
        type="button"
        onClick={() => onPick(item.to, label(item))}
        className={clsx(
          'group flex items-start gap-2.5 rounded-lg border p-2.5 text-left transition',
          chosen
            ? 'border-oe-blue bg-oe-blue/5 ring-1 ring-oe-blue/40'
            : 'border-border-light hover:border-oe-blue hover:bg-surface-secondary',
        )}
      >
        <span
          className={clsx(
            'mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md ring-1',
            chosen
              ? 'bg-oe-blue/15 text-oe-blue ring-oe-blue/30'
              : 'bg-surface-secondary text-content-secondary ring-border-light group-hover:text-oe-blue',
          )}
        >
          <Icon className="h-4 w-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5">
            <span className="truncate text-sm font-medium text-content-primary">{label(item)}</span>
            {chosen && <Check className="h-3.5 w-3.5 shrink-0 text-oe-blue" />}
          </span>
          <span className="mt-0.5 block truncate font-mono text-[11px] text-content-tertiary">
            {item.to}
          </span>
          {group && (
            <span className="mt-0.5 block truncate text-[11px] text-content-tertiary">{group}</span>
          )}
        </span>
      </button>
    );
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 backdrop-blur-sm sm:p-8"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('cases.editor.pick_title', { defaultValue: 'Which screen does this step open?' })}
        className="flex max-h-full w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-border-light bg-surface-primary shadow-2xl"
      >
        <div className="flex items-start gap-3 border-b border-border-light p-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold text-content-primary">
              {t('cases.editor.pick_title', {
                defaultValue: 'Which screen does this step open?',
              })}
            </h2>
            <p className="mt-0.5 text-xs text-content-tertiary">
              {t('cases.editor.pick_hint', {
                defaultValue:
                  'Every screen the platform has, grouped the way the menu groups them.',
              })}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('cases.editor.pick_close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="border-b border-border-light p-4 pb-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-content-tertiary" />
            <Input
              ref={searchRef}
              className="pl-9"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('cases.editor.pick_search', {
                defaultValue: 'Search screens by name or path',
              })}
            />
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {matches ? (
            matches.length === 0 ? (
              <p className="py-10 text-center text-sm text-content-tertiary">
                {t('cases.editor.pick_empty', {
                  defaultValue: 'No screen matches. Try a shorter word, or type the path below.',
                })}
              </p>
            ) : (
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {matches.map(({ item, group }) => (
                  <Tile key={item.to} item={item} group={group} />
                ))}
              </div>
            )
          ) : (
            <div className="space-y-6">
              {popular.length > 0 && (
                <section>
                  <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                    <Sparkles className="h-3.5 w-3.5" />
                    {t('cases.editor.pick_popular', {
                      defaultValue: 'Screens our own cases walk most',
                    })}
                  </h3>
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {popular.map(({ item }) => (
                      <Tile key={`pop-${item.to}`} item={item} />
                    ))}
                  </div>
                </section>
              )}
              {navGroups.map((group) => {
                const items = group.items.filter(pickable);
                if (items.length === 0) return null;
                return (
                  <section key={group.id}>
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                      {t(group.labelKey, { defaultValue: group.defaultLabel ?? group.labelKey })}
                    </h3>
                    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                      {items.map((item) => (
                        <Tile key={item.to} item={item} />
                      ))}
                    </div>
                  </section>
                );
              })}
            </div>
          )}
        </div>

        {/* A screen no shipped case visits is still a screen. */}
        <div className="flex flex-wrap items-center gap-2 border-t border-border-light bg-surface-secondary/50 p-3">
          <span className="text-xs text-content-tertiary">
            {t('cases.editor.pick_custom', { defaultValue: 'Or type a path' })}
          </span>
          <Input
            className="w-44"
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            placeholder="/boq"
          />
          <Button
            size="sm"
            variant="secondary"
            disabled={!customOk}
            onClick={() => onPick(custom.trim(), '')}
          >
            {t('cases.editor.pick_use', { defaultValue: 'Use it' })}
            <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}

export default ScreenPicker;
