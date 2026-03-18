import { NavLink } from 'react-router-dom';
import { LogoWithText } from '@/shared/ui';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  LayoutDashboard,
  FolderOpen,
  Table2,
  CalendarDays,
  Database,
  Layers,
  ShieldCheck,
  FileText,
  Package,
  Settings,
  TrendingUp,
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
  { labelKey: 'costs.title', to: '/costs', icon: Database },
  { labelKey: 'assemblies.title', to: '/assemblies', icon: Layers },
  { labelKey: 'validation.title', to: '/validation', icon: ShieldCheck },
  { labelKey: 'schedule.title', to: '/schedule', icon: CalendarDays },
  { labelKey: 'nav.5d_cost_model', to: '/5d', icon: TrendingUp },
  { labelKey: 'tendering.title', to: '/tendering', icon: FileText },
];

const bottomNav: NavItem[] = [
  { labelKey: 'modules.title', to: '/modules', icon: Package },
  { labelKey: 'nav.settings', to: '/settings', icon: Settings },
];

export function Sidebar({ onClose: _onClose }: { onClose?: () => void }) {
  const { t } = useTranslation();

  return (
    <aside
      className={clsx(
        'flex h-full w-sidebar flex-col',
        'border-r border-border-light bg-surface-primary',
      )}
    >
      {/* Logo */}
      <div className="flex h-header items-center px-5 border-b border-border-light">
        <LogoWithText size="sm" />
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
