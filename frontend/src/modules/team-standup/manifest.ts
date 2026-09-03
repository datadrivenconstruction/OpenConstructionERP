// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
import { lazy, type ComponentType, type LazyExoticComponent } from 'react';
import { BarChart3, Users } from 'lucide-react';

import { ROLE_RANK, normalizeRole } from '@/shared/lib/roles';
import { useAuthStore } from '@/stores/useAuthStore';

import type { ModuleManifest, ModuleNavItem } from '../_types';

const TeamStandupModule = lazy(
  () => import('./TeamStandupModule'),
) as unknown as LazyExoticComponent<ComponentType<unknown>>;

const TeamMetricsPage = lazy(
  () => import('./TeamMetricsPage'),
) as unknown as LazyExoticComponent<ComponentType<unknown>>;

const STANDUP_NAV: ModuleNavItem = {
  // Overview group like Comms Intelligence: a daily-driver screen the
  // whole PM team opens every morning, so it sits with Dashboard and
  // stays visible in Simple mode.
  labelKey: 'nav.team_standup',
  to: '/team-standup',
  icon: Users,
  group: 'grp_overview',
  advancedOnly: false,
};

const METRICS_NAV: ModuleNavItem = {
  // Directly under Team Standup: the metrics dashboard fed by the board's
  // tasks/standups and the presence beacon. Manager-and-above only - it
  // reports on people, not on work. Its labelKey's second segment
  // ('team_standup_metrics') is what the sidebar checks with
  // isModuleEnabled, which is fail-open for unknown keys.
  labelKey: 'nav.team_standup_metrics',
  to: '/team-standup/metrics',
  icon: BarChart3,
  group: 'grp_overview',
  advancedOnly: false,
};

/**
 * Whether the signed-in user is a manager or above.
 *
 * Read through `getState()` rather than a hook because this is called
 * from a plain object getter, not from a component. The role tables come
 * from `shared/lib/roles` - never copied, because
 * `scripts/check_role_mirrors_match_the_backend.py` fails on a second
 * copy of either table under `frontend/src`.
 */
const MAY_READ_METRICS = (): boolean => {
  const rank = ROLE_RANK[normalizeRole(useAuthStore.getState().userRole) as keyof typeof ROLE_RANK];
  return typeof rank === 'number' && rank >= ROLE_RANK.manager;
};

export const manifest: ModuleManifest = {
  id: 'team-standup',
  name: 'modules.team_standup.name',
  description: 'modules.team_standup.description',
  version: '0.1.0',
  icon: Users,
  category: 'tools',
  defaultEnabled: true,
  routes: [
    {
      path: '/team-standup',
      title: 'nav.team_standup',
      component: TeamStandupModule,
    },
    {
      path: '/team-standup/metrics',
      title: 'nav.team_standup_metrics',
      component: TeamMetricsPage,
    },
  ],
  get navItems(): ModuleNavItem[] {
    // A getter, not a literal, and the reason matters. `ModuleNavItem`
    // has no permission field and the sidebar's own gates (`adminOnly`,
    // `roleGate`) live on the STATIC catalogue - a module's dynamic items
    // are rebuilt from these four fields and cannot carry either. The
    // sidebar reads this property inside its render body, on every render,
    // and it re-renders whenever `userRole` changes, so computing the list
    // here is what lets the metrics row follow the role without changing
    // the shared nav layer. This is a UX affordance only: the real rail is
    // `team_standup.metrics` (MANAGER) on GET /metrics in the backend, and
    // the page itself shows a managers-only panel to anyone who arrives by
    // URL.
    return MAY_READ_METRICS() ? [STANDUP_NAV, METRICS_NAV] : [STANDUP_NAV];
  },
  translations: {
    en: {
      'modules.team_standup.name': 'Team Standup',
      'modules.team_standup.description':
        'Daily standup board for the PM team - who is where, what everyone is on today, blockers, and comments on each other’s updates',
      'nav.team_standup': 'Team Standup',
      'nav.team_standup_metrics': 'Team metrics',
      'teamstandup.title': 'Team Standup',
    },
    de: {
      'modules.team_standup.name': 'Team-Standup',
      'modules.team_standup.description':
        'Tägliches Standup-Board für das PM-Team - wer wo ist, was heute ansteht, Blocker und Kommentare zu den Updates',
      'nav.team_standup': 'Team-Standup',
      'nav.team_standup_metrics': 'Team-Kennzahlen',
      'teamstandup.title': 'Team-Standup',
    },
    fr: {
      'modules.team_standup.name': 'Standup d’équipe',
      'modules.team_standup.description':
        'Tableau de standup quotidien pour l’équipe PM - qui est où, le programme du jour, les blocages et les commentaires',
      'nav.team_standup': 'Standup d’équipe',
      'nav.team_standup_metrics': 'Indicateurs d’équipe',
      'teamstandup.title': 'Standup d’équipe',
    },
    ru: {
      'modules.team_standup.name': 'Планёрка команды',
      'modules.team_standup.description':
        'Ежедневная доска планёрки для команды ПМ - кто где, чем занят сегодня, блокеры и комментарии к обновлениям',
      'nav.team_standup': 'Планёрка команды',
      'nav.team_standup_metrics': 'Метрики команды',
      'teamstandup.title': 'Планёрка команды',
    },
  },
};
