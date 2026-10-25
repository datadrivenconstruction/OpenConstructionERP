// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The actions every installation has, plus the bridge that registers the
 * actions module manifests declare. Each sidebar row becomes a "go to" action
 * (`nav.<path>`) so every menu item can carry a shortcut.
 */
import {
  FolderPlus,
  FilePlus2,
  ShieldCheck,
  Download,
  Moon,
  Sun,
  MonitorCog,
  Sparkles,
  Ruler,
  Table2,
  CalendarDays,
  FolderOpen,
  Wallet,
  ClipboardList,
  HelpCircle,
  Boxes,
  LayoutDashboard,
} from 'lucide-react';
import { navGroups } from '@/app/layout/navCatalog';
import { MODULE_REGISTRY } from '@/modules/_registry';
import { registerActions, type PaletteAction } from '@/shared/lib/actions/registry';
import { useThemeStore } from '@/stores/useThemeStore';
import { openAiPanel } from '@/shared/lib/actions/askAi';

/** Default "go to" sequences for the most used menu rows. */
export const NAV_DEFAULT_SHORTCUTS: Record<string, string> = {
  '/': 'G D',
  '/projects': 'G P',
  '/boq': 'G B',
  '/costs': 'G C',
  '/schedule': 'G S',
  '/tasks': 'G T',
  '/finance': 'G F',
  '/issues': 'G I',
  '/validation': 'G V',
  '/files': 'G O',
};

/** Action id of a sidebar row; the Sidebar uses it to show that row's shortcut. */
export function navActionId(path: string): string {
  return `nav.${path}`;
}

export function buildNavActions(): PaletteAction[] {
  const seen = new Set<string>();
  const out: PaletteAction[] = [];
  for (const group of navGroups) {
    for (const item of group.items) {
      // Role-gated rows stay in the sidebar only; the palette has no role context.
      if (item.adminOnly || item.roleGate) continue;
      const id = navActionId(item.to);
      if (seen.has(id) || !/^[a-z0-9][a-z0-9._/:-]{0,63}$/.test(id)) continue;
      seen.add(id);
      out.push({
        id,
        titleKey: item.labelKey,
        defaultTitle: item.defaultLabel ?? '',
        group: 'navigate',
        icon: item.icon,
        moduleKey: item.moduleKey,
        path: item.to,
        defaultShortcut: NAV_DEFAULT_SHORTCUTS[item.to],
      });
    }
  }
  return out;
}

export const CORE_ACTIONS: PaletteAction[] = [
  {
    id: 'project.new',
    titleKey: 'palette.action.new_project',
    defaultTitle: 'New project',
    keywordsKey: 'palette.keywords.new_project',
    defaultKeywords: 'create, add, start, job',
    group: 'create',
    icon: FolderPlus,
    path: '/projects/new',
    defaultShortcut: 'N P',
    priority: 2,
  },
  {
    id: 'boq.new',
    titleKey: 'palette.action.new_estimate',
    defaultTitle: 'New estimate',
    keywordsKey: 'palette.keywords.new_estimate',
    defaultKeywords: 'boq, bill of quantities, cost estimate, create, lv',
    group: 'create',
    icon: FilePlus2,
    scope: 'project',
    path: '/projects/:projectId/boq/new',
    defaultShortcut: 'N E',
    priority: 2,
  },
  {
    id: 'validation.run',
    moduleKey: 'validation',
    path: '/validation',
    group: 'create',
    icon: ShieldCheck,
    titleKey: 'palette.action.run_validation',
    defaultTitle: 'Run validation',
    keywordsKey: 'palette.keywords.run_validation',
    defaultKeywords: 'check, rules, errors, quality',
    defaultShortcut: 'R V',
  },
  {
    id: 'costs.import',
    titleKey: 'palette.action.import_cost_database',
    defaultTitle: 'Import cost database',
    keywordsKey: 'palette.keywords.import_cost_database',
    defaultKeywords: 'prices, rates, catalogue, upload',
    group: 'import',
    icon: Download,
    path: '/costs/import',
  },
  {
    id: 'theme.dark',
    titleKey: 'palette.action.theme_dark',
    defaultTitle: 'Dark theme',
    keywordsKey: 'palette.keywords.theme',
    defaultKeywords: 'appearance, colour, color, mode',
    group: 'view',
    icon: Moon,
    run: () => useThemeStore.getState().setTheme('dark'),
  },
  {
    id: 'theme.light',
    titleKey: 'palette.action.theme_light',
    defaultTitle: 'Light theme',
    keywordsKey: 'palette.keywords.theme',
    defaultKeywords: 'appearance, colour, color, mode',
    group: 'view',
    icon: Sun,
    run: () => useThemeStore.getState().setTheme('light'),
  },
  {
    id: 'theme.system',
    titleKey: 'palette.action.theme_system',
    defaultTitle: 'Theme follows the system',
    keywordsKey: 'palette.keywords.theme',
    defaultKeywords: 'appearance, colour, color, mode',
    group: 'view',
    icon: MonitorCog,
    run: () => useThemeStore.getState().setTheme('system'),
  },
  {
    id: 'theme.toggle',
    titleKey: 'palette.action.theme_toggle',
    defaultTitle: 'Switch light / dark theme',
    keywordsKey: 'palette.keywords.theme',
    defaultKeywords: 'appearance, colour, color, mode',
    group: 'view',
    icon: Moon,
    run: () => useThemeStore.getState().toggleTheme(),
    defaultShortcut: 'T T',
  },
  {
    id: 'ai.open',
    titleKey: 'palette.action.open_ai',
    defaultTitle: 'Open AI assistant',
    keywordsKey: 'palette.keywords.open_ai',
    defaultKeywords: 'chat, assistant, ask, help',
    group: 'ai',
    icon: Sparkles,
    run: () => openAiPanel(),
    defaultShortcut: 'A I',
  },
  // Project-scoped: "Berlin > quantities", or the active project.
  { id: 'project.open', titleKey: 'palette.action.project_overview', defaultTitle: 'Project overview', group: 'project', scope: 'project', icon: LayoutDashboard, path: '/projects/:projectId', priority: 1 },
  { id: 'project.quantities', titleKey: 'palette.action.project_quantities', defaultTitle: 'Quantities', keywordsKey: 'palette.keywords.project_quantities', defaultKeywords: 'takeoff, measure, qto', group: 'project', scope: 'project', icon: Ruler, path: '/quantities' },
  { id: 'project.boq', titleKey: 'palette.action.project_boq', defaultTitle: 'Estimates (BOQ)', keywordsKey: 'palette.keywords.project_boq', defaultKeywords: 'bill of quantities, estimate, lv', group: 'project', scope: 'project', icon: Table2, path: '/projects/:projectId/boq' },
  { id: 'project.schedule', titleKey: 'palette.action.project_schedule', defaultTitle: 'Schedule', group: 'project', scope: 'project', icon: CalendarDays, moduleKey: 'schedule', path: '/schedule' },
  { id: 'project.files', titleKey: 'palette.action.project_files', defaultTitle: 'Files and drawings', keywordsKey: 'palette.keywords.project_files', defaultKeywords: 'documents, drawings, plans, revision', group: 'project', scope: 'project', icon: FolderOpen, path: '/projects/:projectId/files' },
  { id: 'project.finance', titleKey: 'palette.action.project_finance', defaultTitle: 'Finance', keywordsKey: 'palette.keywords.project_finance', defaultKeywords: 'invoices, payments, budget', group: 'project', scope: 'project', icon: Wallet, path: '/projects/:projectId/finance' },
  { id: 'project.tasks', titleKey: 'palette.action.project_tasks', defaultTitle: 'Tasks', group: 'project', scope: 'project', icon: ClipboardList, path: '/projects/:projectId/tasks' },
  { id: 'project.rfi', titleKey: 'palette.action.project_rfi', defaultTitle: 'RFIs', group: 'project', scope: 'project', icon: HelpCircle, path: '/projects/:projectId/rfi' },
  { id: 'project.bim', titleKey: 'palette.action.project_bim', defaultTitle: '3D model', keywordsKey: 'palette.keywords.project_bim', defaultKeywords: 'bim, model, viewer', group: 'project', scope: 'project', icon: Boxes, path: '/projects/:projectId/bim' },
];

let registered = false;

/** Register core, menu and module-manifest actions once per page load. */
export function registerAppActions(): void {
  if (registered) return;
  registered = true;
  registerActions('core', CORE_ACTIONS);
  registerActions('nav', buildNavActions());
  for (const manifest of MODULE_REGISTRY) {
    if (!manifest.actions?.length) continue;
    registerActions(
      `module:${manifest.id}`,
      manifest.actions.map((a) => ({ ...a, moduleKey: a.moduleKey ?? manifest.id })),
    );
  }
}
