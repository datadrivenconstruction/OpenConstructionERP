// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** "Arrange menu" dialog: order, own groups, work modes and the collapsed sidebar style. */
import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Plus, RotateCcw, Trash2, X } from 'lucide-react';
import { ReorderList } from './ReorderList';
import { useMenuLayoutStore } from './useMenuLayoutStore';
import { MENU_MODE_IDS, modeItems, type MenuModeId, type RailState } from './menuLayout';
import { useSidebarCollapseStore } from '@/stores/useSidebarCollapseStore';

export interface OrganizerItem {
  to: string;
  label: string;
}
export interface OrganizerGroup {
  id: string;
  label: string;
  items: OrganizerItem[];
}

type Tab = 'order' | 'groups' | 'modes' | 'sidebar';

export function modeLabelKey(mode: MenuModeId): string {
  return `menu_layout.mode_${mode}`;
}
export const MODE_DEFAULT_LABELS: Record<MenuModeId, string> = {
  estimator: 'Estimator',
  site_manager: 'Site manager',
  finance: 'Finance',
  manager: 'Manager',
  all: 'All',
};

export function MenuOrganizer({
  groups,
  allItems,
  onClose,
}: {
  /** Catalogue groups in their current display order, rows in their current order. */
  groups: OrganizerGroup[];
  allItems: OrganizerItem[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const layout = useMenuLayoutStore((s) => s.layout);
  const dispatch = useMenuLayoutStore((s) => s.dispatch);
  const setIconified = useSidebarCollapseStore((s) => s.setIconified);
  const [tab, setTab] = useState<Tab>('order');
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [newGroup, setNewGroup] = useState('');
  const [editMode, setEditMode] = useState<Exclude<MenuModeId, 'all'>>(
    layout.activeMode === 'all' ? 'estimator' : layout.activeMode,
  );
  const labelOf = useMemo(() => new Map(allItems.map((i) => [i.to, i.label])), [allItems]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const groupIds = groups.map((g) => g.id);
  const tabs: { id: Tab; label: string }[] = [
    { id: 'order', label: t('menu_layout.tab_order', { defaultValue: 'Order' }) },
    { id: 'groups', label: t('menu_layout.tab_groups', { defaultValue: 'My groups' }) },
    { id: 'modes', label: t('menu_layout.tab_modes', { defaultValue: 'Work modes' }) },
    { id: 'sidebar', label: t('menu_layout.tab_sidebar', { defaultValue: 'Sidebar' }) },
  ];
  const currentModeItems = modeItems(layout, editMode) ?? [];

  const setRail = (rail: RailState) => {
    dispatch({ type: 'setRail', rail });
    setIconified(rail !== 'open');
  };

  return createPortal(
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/30 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('menu_layout.title', { defaultValue: 'Arrange menu' })}
        data-testid="menu-organizer"
        className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-xl bg-surface-primary shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border-light px-4 py-3">
          <h2 className="text-base font-semibold">{t('menu_layout.title', { defaultValue: 'Arrange menu' })}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-surface-secondary"
          >
            <X size={16} />
          </button>
        </div>
        <div role="tablist" className="flex gap-1 border-b border-border-light px-3 pt-2">
          {tabs.map((x) => (
            <button
              key={x.id}
              role="tab"
              type="button"
              aria-selected={tab === x.id}
              onClick={() => setTab(x.id)}
              className={clsx(
                'rounded-t-md px-3 py-1.5 text-sm',
                tab === x.id ? 'border-b-2 border-oe-blue font-medium text-content-primary' : 'text-content-tertiary',
              )}
            >
              {x.label}
            </button>
          ))}
        </div>
        <div className="flex-1 overflow-y-auto p-4 text-sm">
          {tab === 'order' && (
            <div className="space-y-3">
              <p className="text-content-tertiary">
                {t('menu_layout.order_help', {
                  defaultValue: 'Drag sections and rows into the order you work in. Keyboard: focus a row, then Alt+Up or Alt+Down.',
                })}
              </p>
              <ReorderList
                testId="organizer-groups"
                entries={groups.map((g) => ({
                  id: g.id,
                  label: g.label,
                  extra: (
                    <button
                      type="button"
                      onClick={() => setOpenGroup((o) => (o === g.id ? null : g.id))}
                      aria-expanded={openGroup === g.id}
                      className="rounded px-1.5 text-xs text-oe-blue hover:underline"
                    >
                      {t('menu_layout.rows', { defaultValue: 'Rows' })}
                    </button>
                  ),
                }))}
                onMove={(from, to) => dispatch({ type: 'moveGroup', current: groupIds, from, to })}
              />
              {openGroup &&
                (() => {
                  const g = groups.find((x) => x.id === openGroup);
                  if (!g) return null;
                  return (
                    <div className="rounded-lg bg-surface-secondary/50 p-2">
                      <div className="mb-1 font-medium">{g.label}</div>
                      <ReorderList
                        testId="organizer-rows"
                        entries={g.items.map((i) => ({ id: i.to, label: i.label }))}
                        onMove={(from, to) =>
                          dispatch({ type: 'moveItem', groupId: g.id, current: g.items.map((i) => i.to), from, to })
                        }
                      />
                    </div>
                  );
                })()}
            </div>
          )}
          {tab === 'groups' && (
            <div className="space-y-4">
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!newGroup.trim()) return;
                  dispatch({ type: 'addUserGroup', id: `g${Date.now().toString(36)}`, label: newGroup });
                  setNewGroup('');
                }}
              >
                <input
                  value={newGroup}
                  onChange={(e) => setNewGroup(e.target.value)}
                  placeholder={t('menu_layout.new_group_placeholder', { defaultValue: 'New group, e.g. My day' })}
                  aria-label={t('menu_layout.new_group', { defaultValue: 'New group' })}
                  className="min-w-0 flex-1 rounded-md border border-border-light bg-surface-primary px-2 py-1.5"
                />
                <button type="submit" className="flex items-center gap-1 rounded-md bg-oe-blue px-3 py-1.5 text-white">
                  <Plus size={14} />
                  {t('menu_layout.add_group', { defaultValue: 'Add group' })}
                </button>
              </form>
              {layout.userGroups.length === 0 && (
                <p className="text-content-tertiary">
                  {t('menu_layout.no_groups', {
                    defaultValue: 'No groups of your own yet. A group shows at the top of the menu with the rows you put in it.',
                  })}
                </p>
              )}
              {layout.userGroups.map((g) => (
                <div key={g.id} className="rounded-lg border border-border-light p-2">
                  <div className="mb-2 flex items-center gap-2">
                    <input
                      defaultValue={g.label}
                      aria-label={t('menu_layout.group_name', { defaultValue: 'Group name' })}
                      onBlur={(e) => dispatch({ type: 'renameUserGroup', id: g.id, label: e.target.value })}
                      className="min-w-0 flex-1 rounded-md border border-border-light bg-surface-primary px-2 py-1 font-medium"
                    />
                    <button
                      type="button"
                      onClick={() => dispatch({ type: 'removeUserGroup', id: g.id })}
                      aria-label={t('menu_layout.remove_group', { defaultValue: 'Remove group {{label}}', label: g.label })}
                      className="flex h-7 w-7 items-center justify-center rounded text-content-tertiary hover:bg-surface-secondary"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                  <ReorderList
                    testId={`organizer-user-${g.id}`}
                    entries={g.items.map((r) => ({
                      id: r,
                      label: labelOf.get(r) ?? r,
                      extra: (
                        <button
                          type="button"
                          onClick={() => dispatch({ type: 'toggleUserGroupItem', id: g.id, route: r })}
                          aria-label={t('menu_layout.remove_row', { defaultValue: 'Remove {{label}}', label: labelOf.get(r) ?? r })}
                          className="flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:bg-surface-secondary"
                        >
                          <X size={12} />
                        </button>
                      ),
                    }))}
                    onMove={(from, to) => dispatch({ type: 'moveItem', groupId: `user:${g.id}`, current: g.items, from, to })}
                  />
                  <select
                    value=""
                    aria-label={t('menu_layout.add_row', { defaultValue: 'Add a screen' })}
                    onChange={(e) => e.target.value && dispatch({ type: 'toggleUserGroupItem', id: g.id, route: e.target.value })}
                    className="mt-2 w-full rounded-md border border-border-light bg-surface-primary px-2 py-1.5"
                  >
                    <option value="">{t('menu_layout.add_row', { defaultValue: 'Add a screen' })}</option>
                    {allItems
                      .filter((i) => !g.items.includes(i.to))
                      .map((i) => (
                        <option key={i.to} value={i.to}>
                          {i.label}
                        </option>
                      ))}
                  </select>
                </div>
              ))}
            </div>
          )}
          {tab === 'modes' && (
            <div className="space-y-3">
              <p className="text-content-tertiary">
                {t('menu_layout.modes_help', {
                  defaultValue: 'A work mode shows only the screens for that job. Pinned rows stay in every mode.',
                })}
              </p>
              <div className="flex flex-wrap gap-1">
                {MENU_MODE_IDS.filter((m): m is Exclude<MenuModeId, 'all'> => m !== 'all').map((m) => (
                  <button
                    key={m}
                    type="button"
                    aria-pressed={editMode === m}
                    onClick={() => setEditMode(m)}
                    className={clsx(
                      'rounded-full border px-3 py-1',
                      editMode === m ? 'border-oe-blue bg-oe-blue/10 text-oe-blue' : 'border-border-light',
                    )}
                  >
                    {t(modeLabelKey(m), { defaultValue: MODE_DEFAULT_LABELS[m] })}
                  </button>
                ))}
              </div>
              <ReorderList
                testId="organizer-mode"
                entries={currentModeItems.map((r) => ({
                  id: r,
                  label: labelOf.get(r) ?? r,
                  extra: (
                    <button
                      type="button"
                      onClick={() => dispatch({ type: 'toggleModeItem', mode: editMode, route: r })}
                      aria-label={t('menu_layout.remove_row', { defaultValue: 'Remove {{label}}', label: labelOf.get(r) ?? r })}
                      className="flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:bg-surface-secondary"
                    >
                      <X size={12} />
                    </button>
                  ),
                }))}
                onMove={(from, to) =>
                  dispatch({ type: 'moveItem', groupId: `mode:${editMode}`, current: currentModeItems, from, to })
                }
              />
              <div className="flex gap-2">
                <select
                  value=""
                  aria-label={t('menu_layout.add_row', { defaultValue: 'Add a screen' })}
                  onChange={(e) => e.target.value && dispatch({ type: 'toggleModeItem', mode: editMode, route: e.target.value })}
                  className="min-w-0 flex-1 rounded-md border border-border-light bg-surface-primary px-2 py-1.5"
                >
                  <option value="">{t('menu_layout.add_row', { defaultValue: 'Add a screen' })}</option>
                  {allItems
                    .filter((i) => !currentModeItems.includes(i.to))
                    .map((i) => (
                      <option key={i.to} value={i.to}>
                        {i.label}
                      </option>
                    ))}
                </select>
                <button
                  type="button"
                  onClick={() => dispatch({ type: 'resetMode', mode: editMode })}
                  className="rounded-md border border-border-light px-3 py-1.5"
                >
                  {t('menu_layout.reset_mode', { defaultValue: 'Default rows' })}
                </button>
              </div>
            </div>
          )}
          {tab === 'sidebar' && (
            <fieldset className="space-y-2">
              <legend className="mb-2 text-content-tertiary">
                {t('menu_layout.sidebar_help', { defaultValue: 'How the sidebar looks on a wide screen' })}
              </legend>
              {(
                [
                  ['open', t('menu_layout.rail_open', { defaultValue: 'Full menu with labels' })],
                  ['icons', t('menu_layout.rail_icons', { defaultValue: 'Icons only, every row' })],
                  ['rail', t('menu_layout.rail_rail', { defaultValue: 'Icon rail: one icon per section, rows open on hover' })],
                ] as [RailState, string][]
              ).map(([value, label]) => (
                <label key={value} className="flex cursor-pointer items-center gap-2">
                  <input type="radio" name="oe-rail" checked={layout.rail === value} onChange={() => setRail(value)} />
                  {label}
                </label>
              ))}
            </fieldset>
          )}
        </div>
        <div className="flex items-center justify-between border-t border-border-light px-4 py-3">
          <button
            type="button"
            data-testid="menu-layout-reset"
            onClick={() => dispatch({ type: 'reset' })}
            className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-content-secondary hover:bg-surface-secondary"
          >
            <RotateCcw size={14} />
            {t('menu_layout.reset', { defaultValue: 'Reset to default' })}
          </button>
          <button type="button" onClick={onClose} className="rounded-md bg-oe-blue px-4 py-1.5 text-white">
            {t('common.done', { defaultValue: 'Done' })}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
