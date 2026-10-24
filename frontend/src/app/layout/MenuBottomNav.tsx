// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Bottom bar on tablet and phone widths: the work mode's first rows plus "More". */
import { NavLink } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Menu } from 'lucide-react';
import { navGroups, type NavItem } from './navCatalog';
import { DEFAULT_MODE_ITEMS, modeItems } from './menuLayout';
import { useMenuLayoutStore } from './useMenuLayoutStore';

const BY_ROUTE: Record<string, NavItem> = Object.fromEntries(
  navGroups.flatMap((g) => g.items.map((i) => [i.to, i] as const)),
);
const BOTTOM_COUNT = 4;

export function bottomNavRoutes(modeRoutes: string[] | null, pinned: readonly string[] = []): string[] {
  const source = [...pinned, ...(modeRoutes ?? DEFAULT_MODE_ITEMS.manager)];
  return [...new Set(source)].filter((r) => BY_ROUTE[r]).slice(0, BOTTOM_COUNT);
}

export function MenuBottomNav({ onMore }: { onMore: () => void }) {
  const { t } = useTranslation();
  const layout = useMenuLayoutStore((s) => s.layout);
  const routes = bottomNavRoutes(modeItems(layout, layout.activeMode));
  return (
    <>
      <div className="h-16 lg:hidden" aria-hidden />
      <nav
        data-testid="menu-bottom-nav"
        aria-label={t('menu_layout.bottom_nav', { defaultValue: 'Quick navigation' })}
        className="fixed inset-x-0 bottom-0 z-30 flex border-t border-border-light bg-surface-primary pb-[env(safe-area-inset-bottom)] lg:hidden"
      >
        {routes.map((route) => {
          const item = BY_ROUTE[route]!;
          const Icon = item.icon;
          const label = t(item.labelKey, { defaultValue: item.defaultLabel });
          return (
            <NavLink
              key={route}
              to={route}
              end={route === '/'}
              className={({ isActive }) =>
                clsx(
                  'flex min-h-[56px] min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-1 text-[10px]',
                  isActive ? 'text-oe-blue' : 'text-content-tertiary',
                )
              }
            >
              <Icon size={18} strokeWidth={1.75} aria-hidden />
              <span className="w-full truncate text-center">{label}</span>
            </NavLink>
          );
        })}
        <button
          type="button"
          onClick={onMore}
          className="flex min-h-[56px] min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-1 text-[10px] text-content-tertiary"
        >
          <Menu size={18} strokeWidth={1.75} aria-hidden />
          <span>{t('menu_layout.more', { defaultValue: 'More' })}</span>
        </button>
      </nav>
    </>
  );
}
