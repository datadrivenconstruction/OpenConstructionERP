import { useState, useCallback, useEffect } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
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
  Boxes,
  ShieldCheck,
  FileText,
  FileSearch,
  FileBarChart,
  Package,
  Settings,
  Info,
  TrendingUp,
  ChevronDown,
  Ruler,
  Sparkles,
  MessageSquare,
  Box,
  X,
  FileEdit,
  BarChart3,
  ShieldAlert,
  ClipboardCheck,
  ClipboardList,
  PenTool,
  ListChecks,
  Camera,
  type LucideIcon,
} from 'lucide-react';
import { useModuleStore } from '@/stores/useModuleStore';
import { UpdateNotification } from '@/shared/ui/UpdateChecker';
import { useViewModeStore } from '@/stores/useViewModeStore';
import { getModuleNavItems } from '@/modules/_registry';


interface NavItem {
  labelKey: string;
  to: string;
  icon: LucideIcon;
  badge?: string;
  highlight?: boolean;
  moduleKey?: string;
  advancedOnly?: boolean; // Hidden in simple mode
  tourId?: string; // data-tour attribute for onboarding
}

interface NavGroup {
  id: string;
  labelKey: string;
  descriptionKey?: string;
  items: NavItem[];
  defaultOpen: boolean;
  hideInSimple?: boolean; // Entire group hidden in simple mode
}

// Navigation groups — collapsible sections
const navGroups: NavGroup[] = [
  {
    id: 'estimation',
    labelKey: 'nav.group_estimation',
    descriptionKey: 'nav.group_estimation_desc',
    defaultOpen: true,
    items: [
      { labelKey: 'nav.dashboard', to: '/', icon: LayoutDashboard },
      { labelKey: 'projects.title', to: '/projects', icon: FolderOpen, tourId: 'projects' },
      { labelKey: 'boq.title', to: '/boq', icon: Table2, tourId: 'boq' },
    ],
  },
  {
    id: 'databases',
    labelKey: 'nav.group_databases',
    defaultOpen: true,
    items: [
      { labelKey: 'costs.title', to: '/costs', icon: Database, tourId: 'costs' },
      { labelKey: 'nav.assemblies', to: '/assemblies', icon: Layers },
      { labelKey: 'catalog.title', to: '/catalog', icon: Boxes },
    ],
  },
  {
    id: 'takeoff',
    labelKey: 'nav.group_takeoff',
    defaultOpen: true,
    items: [
      { labelKey: 'nav.takeoff_overview', to: '/quantities', icon: Ruler },
      { labelKey: 'nav.pdf_measurements', to: '/takeoff?tab=measurements', icon: Ruler },
      { labelKey: 'nav.pdf_documents', to: '/takeoff?tab=documents', icon: FileSearch },
      { labelKey: 'nav.ai_estimate', to: '/ai-estimate', icon: Sparkles },
      { labelKey: 'nav.ai_advisor', to: '/advisor', icon: MessageSquare },
      { labelKey: 'nav.cad_takeoff', to: '/cad-takeoff', icon: Box },
    ],
  },
  {
    id: 'planning',
    labelKey: 'nav.group_planning',
    descriptionKey: 'nav.group_planning_desc',
    defaultOpen: true,
    items: [
      { labelKey: 'schedule.title', to: '/schedule', icon: CalendarDays, moduleKey: 'schedule' },
      { labelKey: 'nav.5d_cost_model', to: '/5d', icon: TrendingUp, moduleKey: '5d', advancedOnly: true },
    ],
  },
  {
    id: 'procurement',
    labelKey: 'nav.group_procurement',
    descriptionKey: 'nav.group_procurement_desc',
    defaultOpen: false,
    items: [
      { labelKey: 'tendering.title', to: '/tendering', icon: FileText, moduleKey: 'tendering', advancedOnly: true },
      { labelKey: 'nav.change_orders', to: '/changeorders', icon: FileEdit, advancedOnly: true },
      { labelKey: 'nav.reports', to: '/reports', icon: FileBarChart, advancedOnly: true },
    ],
  },
  {
    id: 'tools',
    labelKey: 'nav.group_tools',
    descriptionKey: 'nav.group_tools_desc',
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'validation.title', to: '/validation', icon: ShieldCheck, moduleKey: 'validation' },
      { labelKey: 'nav.analytics', to: '/analytics', icon: BarChart3 },
      { labelKey: 'nav.risk_register', to: '/risks', icon: ShieldAlert },
      { labelKey: 'nav.documents', to: '/documents', icon: FolderOpen },
      { labelKey: 'nav.photos', to: '/photos', icon: Camera },
      { labelKey: 'nav.requirements', to: '/requirements', icon: ClipboardCheck },
      { labelKey: 'nav.markups', to: '/markups', icon: PenTool },
      { labelKey: 'nav.punchlist', to: '/punchlist', icon: ListChecks },
      { labelKey: 'nav.field_reports', to: '/field-reports', icon: ClipboardList },
      // sustainability + cost-benchmark injected dynamically from module registry
    ],
  },
  {
    id: 'regional',
    labelKey: 'modules.cat_regional',
    descriptionKey: 'modules.cat_regional_desc',
    defaultOpen: false,
    hideInSimple: true,
    items: [
      // All regional exchange modules injected dynamically from module registry
    ],
  },
];

const bottomNav: NavItem[] = [
  { labelKey: 'modules.title', to: '/modules', icon: Package },
  { labelKey: 'nav.settings', to: '/settings', icon: Settings },
  { labelKey: 'nav.about', to: '/about', icon: Info },
];

// localStorage key for collapsed state
const COLLAPSED_KEY = 'oe_sidebar_collapsed';

function readCollapsedState(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(COLLAPSED_KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    /* ignore */
  }
  return {};
}

function writeCollapsedState(state: Record<string, boolean>) {
  try {
    localStorage.setItem(COLLAPSED_KEY, JSON.stringify(state));
  } catch {
    /* ignore */
  }
}

export function Sidebar({ onClose }: { onClose?: () => void }) {
  const { t } = useTranslation();
  const { isModuleEnabled } = useModuleStore();
  const isAdvanced = useViewModeStore((s) => s.isAdvanced);

  // Initialize collapsed state from localStorage, falling back to group defaults
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => {
    const stored = readCollapsedState();
    const initial: Record<string, boolean> = {};
    for (const group of navGroups) {
      initial[group.id] = stored[group.id] ?? !group.defaultOpen;
    }
    return initial;
  });

  // Persist collapsed state to localStorage
  useEffect(() => {
    writeCollapsedState(collapsed);
  }, [collapsed]);

  const toggleGroup = useCallback((groupId: string) => {
    setCollapsed((prev) => ({ ...prev, [groupId]: !prev[groupId] }));
  }, []);

  return (
    <aside
      data-tour="sidebar"
      className={clsx(
        'flex h-full w-sidebar flex-col',
        'border-r border-border-light bg-surface-primary',
      )}
    >
      {/* Logo + mobile close button */}
      <div className="flex h-header items-center justify-between px-5 border-b border-border-light">
        <LogoWithText size="xs" />
        {onClose && (
          <button
            onClick={onClose}
            className="lg:hidden flex h-7 w-7 min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        )}
      </div>

      {/* Main navigation — grouped with collapsible headers */}
      <nav className="flex-1 overflow-y-auto px-3 py-3" data-engine="cwicr">
        {navGroups.map((group) => {
          // Hide entire group in simple mode if flagged
          if (group.hideInSimple && !isAdvanced) return null;

          // Merge static items + dynamic module items for this group
          const dynamicItems: NavItem[] = getModuleNavItems(group.id)
            .filter((mi) => {
              const moduleId = mi.labelKey.split('.')[1] ?? mi.to.slice(1);
              return isModuleEnabled(moduleId);
            })
            .map((mi) => ({
              labelKey: mi.labelKey,
              to: mi.to,
              icon: mi.icon,
              moduleKey: mi.to.slice(1), // e.g. '/sustainability' → 'sustainability'
              advancedOnly: mi.advancedOnly,
            }));

          // Filter items by module enabled and advanced mode
          const allItems = [...group.items, ...dynamicItems];
          const visibleItems = allItems.filter(
            (item) =>
              (!item.moduleKey || isModuleEnabled(item.moduleKey)) &&
              (!item.advancedOnly || isAdvanced),
          );

          // Skip group if no visible items
          if (visibleItems.length === 0) return null;

          const isCollapsed = collapsed[group.id] ?? false;

          return (
            <NavGroupSection
              key={group.id}
              label={t(group.labelKey, { defaultValue: group.id })}
              isCollapsed={isCollapsed}
              onToggle={() => toggleGroup(group.id)}
            >
              <ul className="space-y-0.5">
                {visibleItems.map((item) => (
                  <li key={item.to}>
                    <SidebarItem item={item} label={t(item.labelKey)} onClick={onClose} />
                  </li>
                ))}
              </ul>
            </NavGroupSection>
          );
        })}
      </nav>

      {/* Bottom navigation */}
      <div className="border-t border-border-light px-3 py-3">
        <ul className="space-y-0.5">
          {bottomNav.map((item) => (
            <li key={item.to}>
              <SidebarItem
                item={item}
                label={t(item.labelKey)}
                onClick={onClose}
              />
            </li>
          ))}
        </ul>

        {/* Update notification */}
        <UpdateNotification />

        {/* DDC branding */}
        <div className="mt-3 pt-3 border-t border-border-light px-1">
          <a
            href="https://OpenConstructionERP.com"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-content-quaternary hover:text-content-secondary hover:bg-surface-secondary/50 transition-all"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
            <span className="text-2xs">OpenConstructionERP.com</span>
          </a>
          <a
            href="https://github.com/datadrivenconstruction/OpenConstructionERP"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-content-quaternary hover:text-content-secondary hover:bg-surface-secondary/50 transition-all"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>
            <span className="text-2xs">GitHub</span>
          </a>
        </div>

        {/* Version + AGPL notice */}
        <div className="px-3 pb-2 text-center">
          <span className="text-2xs text-content-quaternary/50">v0.2.1</span>
          <span className="text-2xs text-content-quaternary/30 mx-1">·</span>
          <a href="/api/source" target="_blank" className="text-2xs text-content-quaternary/40 hover:text-content-quaternary transition-colors">
            AGPL-3.0
          </a>
        </div>
      </div>
    </aside>
  );
}

function NavGroupSection({
  label,
  isCollapsed,
  onToggle,
  children,
}: {
  label: string;
  isCollapsed: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className="mb-1">
      <button
        onClick={onToggle}
        aria-expanded={!isCollapsed}
        aria-label={isCollapsed ? t('common.expand_section', { defaultValue: 'Expand {{label}}', label }) : t('common.collapse_section', { defaultValue: 'Collapse {{label}}', label })}
        className="mt-4 mb-1 flex w-full items-center justify-between px-3 group cursor-pointer"
      >
        <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary group-hover:text-content-secondary transition-colors">
          {label}
        </span>
        <ChevronDown
          size={12}
          className={clsx(
            'text-content-tertiary group-hover:text-content-secondary transition-all duration-150',
            isCollapsed && '-rotate-90',
          )}
        />
      </button>
      {!isCollapsed && children}
    </div>
  );
}

function SidebarItem({ item, label, onClick, badge: numericBadge }: { item: NavItem; label: string; onClick?: () => void; badge?: number }) {
  const Icon = item.icon;
  const location = useLocation();

  // For links with query params (e.g. /takeoff?tab=measurements), check both
  // pathname and query string to determine active state. Without this, all
  // links sharing the same pathname would appear active simultaneously.
  const hasQuery = item.to.includes('?');
  const computeActive = (routerIsActive: boolean): boolean => {
    if (!hasQuery) return routerIsActive;
    const [pathname, queryString] = item.to.split('?');
    if (location.pathname !== pathname) return false;
    const itemParams = new URLSearchParams(queryString);
    const currentParams = new URLSearchParams(location.search);
    for (const [key, value] of itemParams.entries()) {
      if (currentParams.get(key) !== value) return false;
    }
    return true;
  };

  return (
      <NavLink
        to={item.to}
        end={item.to === '/' || hasQuery}
        onClick={onClick}
        title={label}
        {...(item.tourId ? { 'data-tour': item.tourId } : {})}
        className={({ isActive: routerIsActive }) => {
          const isActive = computeActive(routerIsActive);
          return clsx(
            'flex items-center gap-3 rounded-lg px-3 py-2',
            'text-sm font-medium transition-all duration-fast ease-oe',
            item.highlight && !isActive
              ? 'bg-gradient-to-r from-[#7c3aed]/10 to-[#0ea5e9]/10 text-[#6d28d9] hover:from-[#7c3aed]/15 hover:to-[#0ea5e9]/15'
              : isActive
                ? 'bg-oe-blue-subtle text-oe-blue'
                : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
          );
        }}
      >
        <Icon size={18} strokeWidth={1.75} className="shrink-0" />
        <span className="truncate">{label}</span>
        {numericBadge != null && numericBadge > 0 && (
          <span className="ms-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-amber-500 text-white text-2xs font-bold px-1">
            {numericBadge}
          </span>
        )}
        {item.badge && (
          <span
            className={clsx(
              'ms-auto text-2xs font-semibold px-1.5 py-0.5 rounded-full',
              item.highlight
                ? 'bg-gradient-to-r from-[#7c3aed] to-[#0ea5e9] text-white'
                : 'text-content-tertiary',
            )}
          >
            {item.badge}
          </span>
        )}
      </NavLink>
  );
}
