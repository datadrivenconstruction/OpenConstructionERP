// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Menu look" card in Settings > General: ready menu styles with a live
 * miniature, one control per axis (layout, active item, section headers, icon
 * weight, shape and colour), and the icons of single menu items.
 *
 * Hovering or focusing a style or an option previews it on the real sidebar;
 * leaving puts the chosen look back. The choice is personal and kept on this
 * device; admins can make the current look the workspace default.
 */
import { Suspense, lazy, useEffect, useMemo, useState, type CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CalendarDays,
  Check,
  LayoutDashboard,
  Palette,
  RotateCcw,
  ShieldCheck,
  Table2,
  Truck,
  type LucideIcon,
} from 'lucide-react';
import { Card, CardHeader, CardContent, Button } from '@/shared/ui';
import { apiPut } from '@/shared/lib/api';
import {
  MENU_ACTIVES,
  MENU_COLORS,
  MENU_CONTAINERS,
  MENU_HEADERS,
  MENU_ICONS,
  MENU_PRESETS,
  MENU_STROKES,
  MENU_STROKE_WIDTH,
  MENU_VIEWS,
  applyMenu,
  matchMenuPreset,
  type MenuAxis,
  type MenuLook,
  type MenuPresetId,
} from '@/shared/lib/menuAppearance';
import { navGroups, type NavItem } from '@/app/layout/navCatalog';
import { useMenuIcon } from '@/app/layout/menuIcons';
import { useAppearanceStore } from '@/stores/useAppearanceStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { Choice, OptionRow } from './AppearanceStyleCard';

const MenuIconPicker = lazy(() => import('@/app/layout/MenuIconPicker'));

const PRESET_FALLBACK: Record<MenuPresetId, string> = {
  classic: 'Classic',
  studio: 'Studio',
  blueprint: 'Blueprint',
  site_office: 'Site office',
  executive: 'Executive',
  focus: 'Focus',
};

const PRESET_HINT_FALLBACK: Record<MenuPresetId, string> = {
  classic: 'The menu as you know it',
  studio: 'Airy rows, soft tiles, accent icons',
  blueprint: 'Dense and technical, fine lines',
  site_office: 'Big rows, bold icons, a colour per section',
  executive: 'Floating panel, calm and quiet',
  focus: 'Labels only, nothing else',
};

const AXIS_FALLBACK: Record<MenuAxis, { label: string; values: Record<string, string> }> = {
  view: {
    label: 'Layout',
    values: { classic: 'Classic', compact: 'Compact', comfortable: 'Comfortable', rail: 'Rail', floating: 'Floating' },
  },
  active: { label: 'Current item', values: { bar: 'Side bar', pill: 'Filled pill', tint: 'Soft tint' } },
  headers: { label: 'Section headers', values: { caps: 'Caps label', divider: 'Divider line', none: 'None' } },
  stroke: { label: 'Icon weight', values: { light: 'Light', regular: 'Regular', bold: 'Bold' } },
  container: { label: 'Icon shape', values: { none: 'Plain', tile: 'Soft tile', circle: 'Circle' } },
  color: { label: 'Icon colour', values: { mono: 'Monochrome', accent: 'Accent', sections: 'Per section' } },
  icons: { label: 'Icons', values: { shown: 'Shown', hidden: 'Labels only' } },
};

const AXIS_ORDER: readonly { axis: MenuAxis; values: readonly string[] }[] = [
  { axis: 'view', values: MENU_VIEWS },
  { axis: 'active', values: MENU_ACTIVES },
  { axis: 'headers', values: MENU_HEADERS },
  { axis: 'stroke', values: MENU_STROKES },
  { axis: 'container', values: MENU_CONTAINERS },
  { axis: 'color', values: MENU_COLORS },
  { axis: 'icons', values: MENU_ICONS },
];

const PREVIEW_ROWS: readonly { icon: LucideIcon; width: string; tone: number }[] = [
  { icon: LayoutDashboard, width: '62%', tone: 0 },
  { icon: Table2, width: '78%', tone: 2 },
  { icon: CalendarDays, width: '55%', tone: 4 },
  { icon: ShieldCheck, width: '70%', tone: 5 },
  { icon: Truck, width: '48%', tone: 3 },
];

/** A miniature sidebar drawn with the look's own layout, indicator and icons. */
function MenuPreview({ look }: { look: MenuLook }) {
  const rail = look.view === 'rail';
  const rowH = look.view === 'compact' ? 13 : look.view === 'comfortable' ? 19 : 16;
  const iconSize = look.view === 'compact' ? 9 : look.view === 'comfortable' ? 12 : 10;
  const box = look.container === 'none' ? iconSize : iconSize + 6;
  const iconColor = (tone: number) =>
    look.color === 'accent'
      ? 'var(--oe-blue-text)'
      : look.color === 'sections'
        ? `var(--oe-tone-${tone})`
        : 'var(--oe-text-secondary)';
  const showIcons = rail || look.icons === 'shown';

  const header =
    rail || look.headers === 'none' ? (
      <span className="block h-1" />
    ) : look.headers === 'caps' ? (
      <span className="mb-0.5 block h-1 w-8 rounded-full bg-content-quaternary/60" />
    ) : (
      <span className="mb-0.5 flex items-center gap-1">
        <span className="h-1 w-6 rounded-full bg-content-quaternary/60" />
        <span className="h-px flex-1 bg-border" />
      </span>
    );

  const panel = (
    <div className={rail ? 'flex flex-col items-center' : 'flex flex-col'} style={{ gap: look.view === 'compact' ? 1 : 2 }}>
      {header}
      {PREVIEW_ROWS.map((row, i) => {
        const active = i === 1;
        const Icon = row.icon;
        const pill = active && look.active === 'pill';
        const rowStyle: CSSProperties = {
          height: rowH,
          borderRadius: pill ? 999 : 4,
          background: pill ? 'var(--oe-blue)' : active ? 'rgb(var(--oe-blue-ch) / 0.14)' : undefined,
          boxShadow: active && look.active === 'bar' ? 'inset 2px 0 0 var(--oe-blue)' : undefined,
          width: rail ? rowH + 4 : undefined,
        };
        return (
          <div
            key={i}
            className={rail ? 'flex items-center justify-center' : 'flex items-center gap-1.5 px-1.5'}
            style={rowStyle}
          >
            {showIcons && (
              <span
                className="flex shrink-0 items-center justify-center"
                style={{
                  width: box,
                  height: box,
                  borderRadius: look.container === 'circle' ? 999 : 3,
                  color: pill ? 'var(--oe-on-accent)' : iconColor(row.tone),
                  background:
                    look.container === 'none' || pill
                      ? undefined
                      : `color-mix(in srgb, ${iconColor(row.tone)} 14%, transparent)`,
                }}
              >
                <Icon size={iconSize} strokeWidth={MENU_STROKE_WIDTH[look.stroke]} aria-hidden />
              </span>
            )}
            {!rail && (
              <span
                className="h-1 rounded-full"
                style={{
                  width: row.width,
                  background: pill
                    ? 'var(--oe-on-accent)'
                    : active
                      ? 'var(--oe-blue-text)'
                      : 'var(--oe-text-tertiary)',
                  opacity: active ? 0.9 : 0.45,
                }}
              />
            )}
          </div>
        );
      })}
    </div>
  );

  return (
    <div aria-hidden className="flex h-[7.25rem] w-full overflow-hidden rounded-lg border border-border-light bg-surface-secondary">
      <div
        className={
          look.view === 'floating'
            ? 'm-1.5 w-[62%] rounded-lg border border-border-light bg-surface-primary p-1.5 shadow-md'
            : rail
              ? 'w-8 border-e border-border-light bg-surface-primary py-1.5'
              : 'w-[62%] border-e border-border-light bg-surface-primary p-1.5'
        }
      >
        {panel}
      </div>
    </div>
  );
}

/** One overridden menu item in the settings list. */
function OverrideRow({
  item,
  label,
  onChange,
  onReset,
}: {
  item: NavItem;
  label: string;
  onChange: () => void;
  onReset: () => void;
}) {
  const { t } = useTranslation();
  const Icon = useMenuIcon(item.to, item.icon);
  const Default = item.icon;
  return (
    <li className="flex items-center gap-2 rounded-lg border border-border-light px-2.5 py-1.5">
      <Default size={15} strokeWidth={1.75} aria-hidden className="shrink-0 text-content-quaternary" />
      <span aria-hidden className="text-content-quaternary">
        →
      </span>
      <Icon size={16} strokeWidth={1.75} aria-hidden className="shrink-0 text-oe-blue-text" />
      <span className="min-w-0 flex-1 truncate text-sm text-content-primary">{label}</span>
      <Button variant="ghost" size="sm" onClick={onChange}>
        {t('settings.menu_icons_change', { defaultValue: 'Change' })}
      </Button>
      <button
        type="button"
        onClick={onReset}
        aria-label={t('settings.menu_icons_reset_item', { defaultValue: 'Reset the icon of {{label}}', label })}
        title={t('settings.menu_icons_reset_one', { defaultValue: 'Reset to default' })}
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
      >
        <RotateCcw size={13} aria-hidden />
      </button>
    </li>
  );
}

export function MenuAppearanceCard() {
  const { t } = useTranslation();
  const menu = useAppearanceStore((s) => s.menu);
  const menuUser = useAppearanceStore((s) => s.menuUser);
  const menuWorkspace = useAppearanceStore((s) => s.menuWorkspace);
  const setMenu = useAppearanceStore((s) => s.setMenu);
  const setMenuAxis = useAppearanceStore((s) => s.setMenuAxis);
  const followWorkspaceMenu = useAppearanceStore((s) => s.followWorkspaceMenu);
  const setWorkspaceMenu = useAppearanceStore((s) => s.setWorkspaceMenu);
  const iconOverrides = useAppearanceStore((s) => s.iconOverrides);
  const setIconOverride = useAppearanceStore((s) => s.setIconOverride);
  const resetIconOverrides = useAppearanceStore((s) => s.resetIconOverrides);
  const isAdmin = useAuthStore((s) => s.userRole) === 'admin';
  const [saving, setSaving] = useState(false);
  const [picking, setPicking] = useState<NavItem | null>(null);

  // Leaving the page mid-preview must not strand a previewed look on <html>.
  useEffect(() => () => applyMenu(useAppearanceStore.getState().menu), []);

  const preview = (look: MenuLook | null) => applyMenu(look ?? useAppearanceStore.getState().menu);
  const current = matchMenuPreset(menu);
  const presetName = (id: MenuPresetId) => t(`settings.menu_preset_${id}`, { defaultValue: PRESET_FALLBACK[id] });
  const itemLabel = (item: NavItem) => t(item.labelKey, { defaultValue: item.defaultLabel ?? item.to });

  const allItems = useMemo(() => {
    const seen = new Set<string>();
    return navGroups.map((g) => ({
      group: g,
      items: g.items.filter((item) => (seen.has(item.to) ? false : (seen.add(item.to), true))),
    }));
  }, []);
  const itemByRoute = useMemo(() => {
    const map = new Map<string, NavItem>();
    for (const { items } of allItems) for (const item of items) map.set(item.to, item);
    return map;
  }, [allItems]);
  const overridden = Object.keys(iconOverrides)
    .map((route) => itemByRoute.get(route))
    .filter((item): item is NavItem => Boolean(item));

  const source = menuUser
    ? t('settings.menu_source_personal', { defaultValue: 'Your own menu look, saved on this device.' })
    : menuWorkspace
      ? t('settings.menu_source_workspace', { defaultValue: 'Following the workspace default.' })
      : t('settings.menu_source_platform', { defaultValue: 'Platform default.' });

  const saveWorkspace = async (value: MenuLook | null) => {
    setSaving(true);
    try {
      await apiPut('/v1/branding/', { appearance: { menu: value } });
      setWorkspaceMenu(value);
      useToastStore.getState().addToast({
        type: 'success',
        title: value
          ? t('settings.style_workspace_saved', { defaultValue: 'Workspace default saved' })
          : t('settings.style_workspace_cleared', { defaultValue: 'Workspace default cleared' }),
      });
    } catch {
      useToastStore.getState().addToast({
        type: 'error',
        title: t('settings.style_workspace_failed', { defaultValue: 'Could not save the workspace default' }),
      });
    } finally {
      setSaving(false);
    }
  };

  const axisLabel = (axis: MenuAxis) =>
    t(`settings.menu_axis_${axis}`, { defaultValue: AXIS_FALLBACK[axis].label });
  const valueLabel = (axis: MenuAxis, value: string) =>
    t(`settings.menu_${axis}_${value}`, { defaultValue: AXIS_FALLBACK[axis].values[value] ?? value });

  return (
    <Card className="lg:col-span-2">
      <CardHeader
        title={t('settings.menu_title', { defaultValue: 'Menu look' })}
        subtitle={t('settings.menu_subtitle', {
          defaultValue:
            'How the side menu is laid out and how its icons look. Point at a style to try it on the menu, click to keep it.',
        })}
      />
      <CardContent>
        <div
          role="radiogroup"
          aria-label={t('settings.menu_title', { defaultValue: 'Menu look' })}
          className="grid grid-cols-[repeat(auto-fill,minmax(9.5rem,1fr))] gap-3"
          onMouseLeave={() => preview(null)}
        >
          {MENU_PRESETS.map((preset) => {
            const active = current === preset.id;
            return (
              <button
                key={preset.id}
                type="button"
                role="radio"
                aria-checked={active}
                aria-describedby={`menu-preset-hint-${preset.id}`}
                onClick={() => setMenu(preset.value)}
                onMouseEnter={() => preview(preset.value)}
                onFocus={() => preview(preset.value)}
                onBlur={() => preview(null)}
                className={`flex h-full w-full flex-col gap-1.5 rounded-xl border-2 p-1.5 text-start transition-colors duration-normal ease-oe ${
                  active ? 'border-oe-blue bg-oe-blue-subtle' : 'border-transparent hover:border-border'
                }`}
              >
                <MenuPreview look={preset.value} />
                <span className="flex items-center justify-between gap-1 px-0.5">
                  <span className="truncate text-sm font-semibold text-content-primary">{presetName(preset.id)}</span>
                  {active && <Check size={14} aria-hidden className="shrink-0 text-oe-blue-text" />}
                </span>
                <span id={`menu-preset-hint-${preset.id}`} className="px-0.5 text-xs leading-snug text-content-tertiary">
                  {t(`settings.menu_preset_${preset.id}_hint`, { defaultValue: PRESET_HINT_FALLBACK[preset.id] })}
                </span>
              </button>
            );
          })}
          <div
            role="radio"
            aria-checked={current === null}
            aria-disabled={current !== null}
            className={`flex flex-col gap-1.5 rounded-xl border-2 border-dashed p-1.5 ${
              current === null ? 'border-oe-blue bg-oe-blue-subtle' : 'border-border-light opacity-60'
            }`}
          >
            <MenuPreview look={menu} />
            <span className="px-0.5 text-sm font-semibold text-content-primary">
              {t('settings.style_custom', { defaultValue: 'Custom' })}
            </span>
            <span className="px-0.5 text-xs leading-snug text-content-tertiary">
              {t('settings.menu_custom_hint', { defaultValue: 'Your own mix of the options below' })}
            </span>
          </div>
        </div>

        <div className="mt-5 flex flex-col gap-4 border-t border-border-light pt-4">
          {AXIS_ORDER.map(({ axis, values }) => (
            <OptionRow key={axis} label={axisLabel(axis)}>
              {values.map((value) => (
                <Choice
                  key={value}
                  active={menu[axis] === value}
                  onSelect={() => setMenuAxis(axis, value as MenuLook[typeof axis])}
                  onPreview={(on) => preview(on ? { ...useAppearanceStore.getState().menu, [axis]: value } : null)}
                  label={valueLabel(axis, value)}
                />
              ))}
            </OptionRow>
          ))}
          {menu.view === 'rail' && (
            <p className="text-xs text-content-tertiary">
              {t('settings.menu_rail_hint', {
                defaultValue: 'Rail shows icons only. Point at an icon for its name; the tab on the menu edge opens it in full.',
              })}
            </p>
          )}
        </div>

        <div className="mt-5 border-t border-border-light pt-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-sm font-medium text-content-primary">
                {t('settings.menu_icons_title', { defaultValue: 'Icons of single items' })}
              </p>
              <p className="mt-0.5 text-xs text-content-tertiary">
                {t('settings.menu_icons_desc', {
                  defaultValue: 'Right-click an item in the menu, or pick it here. The icon changes everywhere the item shows.',
                })}
              </p>
            </div>
            {overridden.length > 0 && (
              <Button variant="ghost" size="sm" onClick={resetIconOverrides}>
                {t('settings.menu_icons_reset_all', { defaultValue: 'Reset all icons' })}
              </Button>
            )}
          </div>
          <label className="mt-3 flex flex-wrap items-center gap-2">
            <Palette size={15} aria-hidden className="text-content-tertiary" />
            <span className="text-sm text-content-secondary">
              {t('settings.menu_icons_pick_item', { defaultValue: 'Change the icon of' })}
            </span>
            <select
              value=""
              onChange={(e) => {
                const item = itemByRoute.get(e.target.value);
                if (item) setPicking(item);
              }}
              className="h-9 min-w-0 max-w-full flex-1 rounded-lg border border-border bg-surface-primary px-2 text-sm text-content-primary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/20 sm:max-w-xs"
            >
              <option value="">{t('settings.menu_icons_choose_item', { defaultValue: 'Choose a menu item…' })}</option>
              {allItems.map(({ group, items }) => (
                <optgroup key={group.id} label={t(group.labelKey, { defaultValue: group.defaultLabel ?? group.id })}>
                  {items.map((item) => (
                    <option key={item.to} value={item.to}>
                      {itemLabel(item)}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
          {overridden.length > 0 && (
            <ul className="mt-3 grid gap-1.5 sm:grid-cols-2">
              {overridden.map((item) => (
                <OverrideRow
                  key={item.to}
                  item={item}
                  label={itemLabel(item)}
                  onChange={() => setPicking(item)}
                  onReset={() => setIconOverride(item.to, null)}
                />
              ))}
            </ul>
          )}
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border-light pt-4">
          <p className="text-xs text-content-secondary">{source}</p>
          {menuUser && (
            <Button variant="secondary" size="sm" icon={<RotateCcw size={14} />} onClick={followWorkspaceMenu}>
              {menuWorkspace
                ? t('settings.style_use_workspace', { defaultValue: 'Use workspace default' })
                : t('settings.menu_reset', { defaultValue: 'Reset to default' })}
            </Button>
          )}
        </div>

        {isAdmin && (
          <div className="mt-4 rounded-lg border border-border-light bg-surface-secondary/50 p-3">
            <p className="text-sm font-medium text-content-primary">
              {t('settings.style_workspace_title', { defaultValue: 'Workspace default' })}
            </p>
            <p className="mt-0.5 text-xs text-content-tertiary">
              {t('settings.menu_workspace_desc', {
                defaultValue:
                  'Make the menu look above the default for everyone in this workspace. Item icons stay personal, and people who picked their own look keep it.',
              })}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="sm" disabled={saving} onClick={() => void saveWorkspace(menu)}>
                {t('settings.style_workspace_save', { defaultValue: 'Set as workspace default' })}
              </Button>
              {menuWorkspace && (
                <Button variant="ghost" size="sm" disabled={saving} onClick={() => void saveWorkspace(null)}>
                  {t('settings.style_workspace_clear', { defaultValue: 'Clear workspace default' })}
                </Button>
              )}
            </div>
          </div>
        )}
      </CardContent>

      {picking && (
        <Suspense fallback={null}>
          <MenuIconPicker
            route={picking.to}
            label={itemLabel(picking)}
            defaultIcon={picking.icon}
            onClose={() => setPicking(null)}
          />
        </Suspense>
      )}
    </Card>
  );
}
