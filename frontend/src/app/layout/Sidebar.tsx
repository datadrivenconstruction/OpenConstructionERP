import { NavLink, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  LayoutDashboard,
  FolderOpen,
  Table2,
  Ruler,
  Database,
  ShieldCheck,
  FileText,
  Package,
  Settings,
  type LucideIcon,
} from 'lucide-react';

interface NavItem {
  labelKey: string;
  to: string;
  icon: LucideIcon;
  badge?: string;
}

const mainNav: NavItem[] = [
  { labelKey: 'nav.dashboard', to: '/', icon: LayoutDashboard },
  { labelKey: 'projects.title', to: '/projects', icon: FolderOpen },
  { labelKey: 'boq.title', to: '/boq', icon: Table2 },
  { labelKey: 'takeoff.title', to: '/takeoff', icon: Ruler },
  { labelKey: 'costs.title', to: '/costs', icon: Database },
  { labelKey: 'validation.title', to: '/validation', icon: ShieldCheck },
  { labelKey: 'tendering.title', to: '/tendering', icon: FileText },
];

const bottomNav: NavItem[] = [
  { labelKey: 'modules.title', to: '/modules', icon: Package },
  { labelKey: 'nav.settings', to: '/settings', icon: Settings },
];

export function Sidebar() {
  const { t } = useTranslation();

  return (
    <aside
      className={clsx(
        'fixed inset-y-0 left-0 z-30',
        'flex w-sidebar flex-col',
        'border-r border-border-light bg-surface-primary',
      )}
    >
      {/* Logo */}
      <div className="flex h-header items-center gap-3 px-5 border-b border-border-light">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-oe-blue">
          <span className="text-sm font-bold text-white">OE</span>
        </div>
        <div className="min-w-0">
          <span className="text-sm font-semibold text-content-primary">OpenEstimate</span>
          <span className="ml-1.5 text-2xs text-content-tertiary">v0.1</span>
        </div>
      </div>

      {/* Main navigation */}
      <nav className="flex-1 overflow-y-auto px-3 py-3">
        <ul className="space-y-0.5">
          {mainNav.map((item) => (
            <SidebarItem key={item.to} item={item} label={t(item.labelKey)} />
          ))}
        </ul>
      </nav>

      {/* Bottom navigation */}
      <div className="border-t border-border-light px-3 py-3">
        <ul className="space-y-0.5">
          {bottomNav.map((item) => (
            <SidebarItem key={item.to} item={item} label={t(item.labelKey)} />
          ))}
        </ul>
      </div>
    </aside>
  );
}

function SidebarItem({ item, label }: { item: NavItem; label: string }) {
  const Icon = item.icon;

  return (
    <li>
      <NavLink
        to={item.to}
        end={item.to === '/'}
        className={({ isActive }) =>
          clsx(
            'flex items-center gap-3 rounded-lg px-3 py-2',
            'text-sm font-medium transition-all duration-fast ease-oe',
            isActive
              ? 'bg-oe-blue-subtle text-oe-blue'
              : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
          )
        }
      >
        <Icon size={18} strokeWidth={1.75} className="shrink-0" />
        <span className="truncate">{label}</span>
        {item.badge && (
          <span className="ml-auto text-2xs font-medium text-content-tertiary">
            {item.badge}
          </span>
        )}
      </NavLink>
    </li>
  );
}
