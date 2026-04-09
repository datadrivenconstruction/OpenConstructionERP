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
  Box,
  ShieldCheck,
  FileText,
  FileBarChart,
  Package,
  Settings,
  Info,
  TrendingUp,
  ChevronDown,
  Ruler,
  Sparkles,
  MessageSquare,
  X,
  FileEdit,
  ShieldAlert,
  ClipboardCheck,
  ClipboardList,
  PenTool,
  ListChecks,
  Camera,
  TableProperties,
  Wallet,
  HardHat,
  Users,
  HelpCircle,
  AlertOctagon,
  FileCheck,
  Mail,
  Send,
  History,
  BrainCircuit,
  type LucideIcon,
} from 'lucide-react';
import { useModuleStore } from '@/stores/useModuleStore';
import { UpdateNotification } from '@/shared/ui/UpdateChecker';
import { useViewModeStore } from '@/stores/useViewModeStore';
import { useRecentStore } from '@/stores/useRecentStore';
import { getModuleNavItems } from '@/modules/_registry';
import { APP_VERSION } from '@/shared/lib/version';
import { useSidebarBadges } from '@/shared/hooks/useSidebarBadges';


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
  // ── CORE (always visible) ──────────────────────────────────────────
  {
    id: 'overview',
    labelKey: 'nav.group_overview',
    defaultOpen: true,
    items: [
      { labelKey: 'nav.dashboard', to: '/', icon: LayoutDashboard },
      { labelKey: 'projects.title', to: '/projects', icon: FolderOpen, tourId: 'projects' },
      { labelKey: 'nav.project_intelligence', to: '/project-intelligence', icon: BrainCircuit },
    ],
  },
  {
    id: 'estimation',
    labelKey: 'nav.group_estimation',
    descriptionKey: 'nav.group_estimation_desc',
    defaultOpen: true,
    items: [
      { labelKey: 'boq.title', to: '/boq', icon: Table2, tourId: 'boq' },
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
      { labelKey: 'nav.pdf_measurements', to: '/takeoff?tab=measurements', icon: Ruler },
      { labelKey: 'nav.cad_bim_explorer', to: '/data-explorer', icon: TableProperties },
      { labelKey: 'nav.bim_viewer', to: '/bim', icon: Box },
    ],
  },
  {
    id: 'ai',
    labelKey: 'nav.group_ai_estimation',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.ai_estimate', to: '/ai-estimate', icon: Sparkles },
      { labelKey: 'nav.ai_advisor', to: '/advisor', icon: MessageSquare },
    ],
  },
  // ── PLANNING & CONTROL (advanced) ──────────────────────────────────
  {
    id: 'planning',
    labelKey: 'nav.group_planning',
    descriptionKey: 'nav.group_planning_desc',
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'schedule.title', to: '/schedule', icon: CalendarDays, moduleKey: 'schedule' },
      { labelKey: 'tasks.title', to: '/tasks', icon: ClipboardList },
      { labelKey: 'nav.5d_cost_model', to: '/5d', icon: TrendingUp, moduleKey: '5d', advancedOnly: true },
      { labelKey: 'nav.requirements', to: '/requirements', icon: ClipboardCheck, advancedOnly: true },
      { labelKey: 'nav.risk_register', to: '/risks', icon: ShieldAlert, advancedOnly: true },
    ],
  },
  {
    id: 'finance',
    labelKey: 'nav.group_finance',
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'finance.title', to: '/finance', icon: Wallet, advancedOnly: true },
      { labelKey: 'procurement.title', to: '/procurement', icon: Package, advancedOnly: true },
      { labelKey: 'tendering.title', to: '/tendering', icon: FileText, moduleKey: 'tendering', advancedOnly: true },
      { labelKey: 'nav.change_orders', to: '/changeorders', icon: FileEdit, advancedOnly: true },
    ],
  },
  // ── COMMUNICATION ──────────────────────────────────────────────────
  {
    id: 'communication',
    labelKey: 'nav.group_communication',
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'contacts.title', to: '/contacts', icon: Users },
      { labelKey: 'meetings.title', to: '/meetings', icon: CalendarDays },
      { labelKey: 'rfi.title', to: '/rfi', icon: HelpCircle, advancedOnly: true },
      { labelKey: 'submittals.title', to: '/submittals', icon: FileCheck, advancedOnly: true },
      { labelKey: 'transmittals.title', to: '/transmittals', icon: Send, advancedOnly: true },
      { labelKey: 'correspondence.title', to: '/correspondence', icon: Mail, advancedOnly: true },
    ],
  },
  // ── DOCUMENTS ──────────────────────────────────────────────────────
  {
    id: 'documentation',
    labelKey: 'nav.group_documentation',
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.documents', to: '/documents', icon: FolderOpen },
      { labelKey: 'cde.title', to: '/cde', icon: Database },
      { labelKey: 'nav.photos', to: '/photos', icon: Camera },
      { labelKey: 'nav.markups', to: '/markups', icon: PenTool },
      { labelKey: 'nav.field_reports', to: '/field-reports', icon: ClipboardList, advancedOnly: true },
      { labelKey: 'nav.reports', to: '/reports', icon: FileBarChart, advancedOnly: true },
    ],
  },
  // ── QUALITY & SAFETY ───────────────────────────────────────────────
  {
    id: 'quality',
    labelKey: 'nav.group_quality',
    defaultOpen: false,
    hideInSimple: true,
    items: [
      { labelKey: 'validation.title', to: '/validation', icon: ShieldCheck, moduleKey: 'validation' },
      { labelKey: 'inspections.title', to: '/inspections', icon: ClipboardCheck },
      { labelKey: 'ncr.title', to: '/ncr', icon: AlertOctagon },
      { labelKey: 'safety.title', to: '/safety', icon: HardHat },
      { labelKey: 'nav.punchlist', to: '/punchlist', icon: ListChecks },
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
  { labelKey: 'users.management', to: '/users', icon: Users },
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
  const badgeCounts = useSidebarBadges();

  // Map route paths → open-item counts for sidebar badges
  const badgeMap: Record<string, number> = {
    '/tasks': badgeCounts.tasks,
    '/rfi': badgeCounts.rfi,
    '/safety': badgeCounts.safety,
  };

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
        <a href="https://openconstructionerp.com/?utm_source=app" target="_blank" rel="noopener noreferrer" className="hover:opacity-80 transition-opacity">
          <LogoWithText size="xs" />
        </a>
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
                    <SidebarItem
                      item={item}
                      label={t(item.labelKey)}
                      onClick={onClose}
                      badge={badgeMap[item.to]}
                    />
                  </li>
                ))}
              </ul>
            </NavGroupSection>
          );
        })}
      </nav>

      {/* Recent items */}
      <div className="bg-black/[0.02] dark:bg-white/[0.02]">
        <RecentSection onItemClick={onClose} />
      </div>

      {/* Bottom navigation */}
      <div className="border-t border-border-light px-3 py-2 bg-black/[0.04] dark:bg-white/[0.03]">
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

        {/* Version + AGPL notice */}
        <div className="px-3 pb-2 text-center">
          <span className="text-2xs text-content-quaternary/50">v{APP_VERSION}</span>
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
    <div className="mb-0.5">
      <button
        onClick={onToggle}
        aria-expanded={!isCollapsed}
        aria-label={isCollapsed ? t('common.expand_section', { defaultValue: 'Expand {{label}}', label }) : t('common.collapse_section', { defaultValue: 'Collapse {{label}}', label })}
        className="mt-2 mb-0.5 flex w-full items-center justify-between px-2.5 group cursor-pointer"
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

  // Pre-compute active state for badge styling (avoids children-as-function)
  const routerIsActive =
    location.pathname === item.to ||
    (!hasQuery && item.to !== '/' && location.pathname.startsWith(item.to + '/'));
  const isActive = computeActive(routerIsActive);

  return (
      <NavLink
        to={item.to}
        end={item.to === '/' || hasQuery}
        onClick={onClick}
        title={label}
        {...(item.tourId ? { 'data-tour': item.tourId } : {})}
        className={({ isActive: ria }) => {
          const active = computeActive(ria);
          return clsx(
            'flex items-center gap-2 rounded-md px-2.5 py-[5px]',
            'text-[13px] font-medium transition-all duration-fast ease-oe',
            item.highlight && !active
              ? 'bg-gradient-to-r from-[#7c3aed]/10 to-[#0ea5e9]/10 text-[#6d28d9] hover:from-[#7c3aed]/15 hover:to-[#0ea5e9]/15'
              : active
                ? 'bg-oe-blue-subtle text-oe-blue'
                : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
          );
        }}
      >
        <Icon size={16} strokeWidth={1.75} className="shrink-0" />
        <span className="truncate">{label}</span>
        {numericBadge != null && numericBadge > 0 && (
          <span
            className={clsx(
              'ms-auto flex h-4 min-w-[1.25rem] items-center justify-center rounded-full text-2xs font-bold px-1 transition-colors',
              isActive
                ? 'bg-oe-blue text-white'
                : 'bg-surface-tertiary text-content-secondary',
            )}
          >
            {numericBadge > 99 ? '99+' : numericBadge}
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

const RECENT_TYPE_ICONS: Record<string, LucideIcon> = {
  project: FolderOpen,
  boq: Table2,
  schedule: CalendarDays,
  task: ClipboardList,
  rfi: HelpCircle,
  contact: Users,
};

function RecentSection({ onItemClick }: { onItemClick?: () => void }) {
  const { t } = useTranslation();
  const recentItems = useRecentStore((s) => s.items);

  if (recentItems.length === 0) return null;

  const displayed = recentItems.slice(0, 3);

  return (
    <div className="border-t border-border-light px-3 py-2">
      <span className="mt-1 mb-1 flex items-center gap-1.5 px-2.5 text-2xs font-medium uppercase tracking-wider text-content-tertiary">
        <History size={11} strokeWidth={2} />
        {t('nav.recent', { defaultValue: 'Recent' })}
      </span>
      <ul className="space-y-0.5">
        {displayed.map((item) => {
          const Icon = RECENT_TYPE_ICONS[item.type] || FolderOpen;
          return (
            <li key={item.id}>
              <NavLink
                to={item.url}
                onClick={onItemClick}
                title={item.title}
                className="flex items-center gap-2 rounded-md px-2.5 py-[5px] text-[13px] font-medium text-content-secondary hover:bg-surface-secondary hover:text-content-primary transition-all duration-fast ease-oe"
              >
                <Icon size={14} strokeWidth={1.75} className="shrink-0 text-content-tertiary" />
                <span className="truncate">{item.title}</span>
              </NavLink>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
