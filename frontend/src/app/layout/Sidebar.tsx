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
  PencilRuler,
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
  SlidersHorizontal,
  Plus,
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
      { labelKey: 'nav.quantity_rules', to: '/bim/rules', icon: ClipboardCheck, badge: 'BETA' },
    ],
  },
  {
    id: 'takeoff',
    labelKey: 'nav.group_takeoff',
    defaultOpen: true,
    items: [
      { labelKey: 'nav.pdf_measurements', to: '/takeoff?tab=measurements', icon: Ruler },
      { labelKey: 'nav.dwg_takeoff', to: '/dwg-takeoff', icon: PencilRuler },
      { labelKey: 'nav.cad_bim_explorer', to: '/data-explorer', icon: TableProperties },
      { labelKey: 'nav.bim_viewer', to: '/bim', icon: Box },
      { labelKey: 'nav.bim_rules', to: '/bim/rules?mode=requirements', icon: SlidersHorizontal, badge: 'BETA' },
    ],
  },
  {
    id: 'ai',
    labelKey: 'nav.group_ai_estimation',
    defaultOpen: true,
    hideInSimple: true,
    items: [
      { labelKey: 'nav.ai_estimate', to: '/ai-estimate', icon: Sparkles, badge: 'BETA' },
      { labelKey: 'nav.ai_advisor', to: '/advisor', icon: MessageSquare },
      { labelKey: 'nav.estimation_dashboard', to: '/project-intelligence', icon: BrainCircuit, badge: 'BETA' },
      { labelKey: 'nav.erp_chat', to: '/chat', icon: MessageSquare, badge: 'BETA' },
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
      // Requirements merged into /bim/rules — sidebar entry removed
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
        {/* Add-a-module CTA — dashed-border tile with a plus icon. Sits at
             the very end of the main nav groups so it reads as "keep going,
             there's more — build your own". Navigates into the in-app
             developer guide rather than to the marketplace, which gives
             contributors a clearer first step. */}
        <li className="px-3 pt-2 pb-3">
          <NavLink
            to="/modules/developer-guide"
            onClick={onClose}
            className="group flex items-center gap-2.5 rounded-lg border border-dashed border-oe-blue/40 bg-gradient-to-br from-oe-blue/5 via-transparent to-blue-50/40 dark:from-oe-blue/10 dark:via-transparent dark:to-slate-900/30 px-2.5 py-2 hover:border-oe-blue hover:from-oe-blue/10 hover:shadow-sm transition-all"
          >
            <span className="shrink-0 flex h-7 w-7 items-center justify-center rounded-md bg-oe-blue/10 text-oe-blue group-hover:bg-oe-blue group-hover:text-white transition-colors">
              <Plus size={14} strokeWidth={2.5} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-xs font-semibold text-content-primary leading-tight">
                {t('nav.add_module', { defaultValue: 'Add module' })}
              </span>
              <span className="block text-[10px] text-content-tertiary leading-tight mt-0.5 truncate">
                {t('nav.add_module_hint', { defaultValue: 'Build your own · developer guide' })}
              </span>
            </span>
          </NavLink>
        </li>
      </nav>

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

        {/* Update notification — compact clickable card in the sidebar; the
            whole card opens a full-screen modal with highlights + install
            commands when the user clicks it. */}
        <UpdateNotification />

        {/* Version + AGPL notice */}
        <div className="px-3 pb-2 text-center">
          <span className="text-2xs text-content-quaternary/50">v{APP_VERSION}</span>
          <span className="text-2xs text-content-quaternary/30 mx-1">·</span>
          <a href="/api/source" target="_blank" rel="noopener noreferrer" className="text-2xs text-content-quaternary/40 hover:text-content-quaternary transition-colors">
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
              // BETA badge: tiny, subtle, lowercase, neutral grey.
              // Reads as "this module is still in development" without
              // visually competing for the user's attention.
              item.badge === 'BETA'
                ? 'ms-auto text-[9px] font-medium uppercase tracking-wide px-1.5 py-px rounded text-content-quaternary bg-surface-tertiary/60 dark:bg-surface-tertiary/40'
                : item.highlight
                  ? 'ms-auto text-2xs font-semibold px-1.5 py-0.5 rounded-full bg-gradient-to-r from-[#7c3aed] to-[#0ea5e9] text-white'
                  : 'ms-auto text-2xs font-semibold px-1.5 py-0.5 rounded-full text-content-tertiary',
            )}
          >
            {item.badge === 'BETA' ? 'beta' : item.badge}
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

/** Floating Recent button — rendered by AppLayout in the bottom-right corner. */
export function FloatingRecentButton() {
  const { t } = useTranslation();
  const recentItems = useRecentStore((s) => s.items);
  const [open, setOpen] = useState(false);

  if (recentItems.length === 0) return null;
  const displayed = recentItems.slice(0, 5);

  return (
    // Smaller, slightly higher than the Chat FAB so they stack visually
    <div className="fixed bottom-24 end-4 z-40">
      {/* Popover */}
      {open && (
        <div className="absolute bottom-12 end-0 w-72 rounded-xl border border-border-light bg-surface-primary shadow-xl overflow-hidden animate-in fade-in slide-in-from-bottom-2 duration-150">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-light">
            <span className="text-xs font-semibold text-content-primary">{t('nav.recent', { defaultValue: 'Recent' })}</span>
            <button onClick={() => setOpen(false)} className="p-0.5 rounded text-content-tertiary hover:text-content-primary">
              <X size={14} />
            </button>
          </div>
          <ul className="py-1.5 max-h-60 overflow-y-auto">
            {displayed.map((item) => {
              const Icon = RECENT_TYPE_ICONS[item.type] || FolderOpen;
              return (
                <li key={item.id}>
                  <NavLink
                    to={item.url}
                    onClick={() => setOpen(false)}
                    title={item.title}
                    className="flex items-center gap-2.5 px-4 py-2 text-[13px] font-medium text-content-secondary hover:bg-surface-secondary hover:text-content-primary transition-all"
                  >
                    <Icon size={14} strokeWidth={1.75} className="shrink-0 text-content-tertiary" />
                    <span className="truncate flex-1">{item.title}</span>
                    <span className="text-[10px] text-content-quaternary shrink-0 tabular-nums">
                      {new Date(item.visitedAt).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </NavLink>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* FAB button */}
      <button
        onClick={() => setOpen((p) => !p)}
        className={clsx(
          'w-10 h-10 rounded-full flex items-center justify-center shadow-lg border transition-all duration-200 hover:scale-105 active:scale-95',
          open
            ? 'bg-oe-blue text-white border-oe-blue shadow-oe-blue/20'
            : 'bg-surface-primary text-content-secondary border-border-light hover:border-oe-blue/30 hover:text-oe-blue',
        )}
        title={t('nav.recent', { defaultValue: 'Recent' })}
      >
        <History size={18} strokeWidth={2} />
      </button>
    </div>
  );
}

/** Floating AI Chat button — large pill-shaped FAB in bottom-right that
 *  navigates to /chat. Hidden when already on the chat page. */
export function FloatingChatButton() {
  const { t } = useTranslation();
  const location = useLocation();

  // Hide when already on the chat page so it doesn't overlap the chat itself
  if (location.pathname.startsWith('/chat')) return null;

  return (
    <NavLink
      to="/chat"
      className="fixed bottom-6 end-6 z-40 group flex items-center gap-2.5 px-5 py-3.5 rounded-full bg-gradient-to-r from-oe-blue to-blue-600 text-white shadow-xl shadow-oe-blue/30 hover:shadow-2xl hover:shadow-oe-blue/40 hover:scale-105 active:scale-95 transition-all duration-200 border border-oe-blue/50"
      title={t('nav.erp_chat', { defaultValue: 'AI Chat' })}
    >
      <MessageSquare size={20} strokeWidth={2.25} className="shrink-0" />
      <span className="text-sm font-semibold whitespace-nowrap">
        {t('nav.erp_chat', { defaultValue: 'AI Chat' })}
      </span>
      {/* Subtle pulse indicator */}
      <span className="relative flex h-2 w-2">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-white" />
      </span>
    </NavLink>
  );
}
