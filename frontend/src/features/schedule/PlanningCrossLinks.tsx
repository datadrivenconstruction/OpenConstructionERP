import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import {
  CalendarDays,
  GitBranch,
  DollarSign,
  ShieldAlert,
  ClipboardList,
  Users,
} from 'lucide-react';

/**
 * Shared "Planning & Control" cross-module navigation strip.
 *
 * Every page in the planning section (Schedule, Advanced Schedule, Tasks,
 * 5D Cost Model, Risk Register) shares the same value chain:
 *
 *   BOQ → Schedule → 5D Cost (EVM) → Risk
 *
 * Surfacing the sibling modules inline turns five siloed screens into one
 * connected workflow and makes the relationship discoverable. The current
 * route is rendered as a non-interactive active chip so the user always
 * knows where they are within the chain.
 */

export type PlanningRouteKey =
  | 'schedule'
  | 'schedule-advanced'
  | 'tasks'
  | '5d'
  | 'risks';

interface LinkDef {
  key: PlanningRouteKey | 'meetings';
  to: string;
  icon: typeof CalendarDays;
  label: string;
}

export function PlanningCrossLinks({ active }: { active: PlanningRouteKey }) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const links: LinkDef[] = [
    {
      key: 'schedule',
      to: '/schedule',
      icon: CalendarDays,
      label: t('planning.link_schedule', { defaultValue: '4D Schedule' }),
    },
    {
      key: 'schedule-advanced',
      to: '/schedule-advanced',
      icon: GitBranch,
      label: t('planning.link_schedule_advanced', { defaultValue: 'Last Planner' }),
    },
    {
      key: 'tasks',
      to: '/tasks',
      icon: ClipboardList,
      label: t('planning.link_tasks', { defaultValue: 'Tasks' }),
    },
    {
      key: '5d',
      to: '/5d',
      icon: DollarSign,
      label: t('planning.link_5d', { defaultValue: '5D Cost Model' }),
    },
    {
      key: 'risks',
      to: '/risks',
      icon: ShieldAlert,
      label: t('planning.link_risks', { defaultValue: 'Risk Register' }),
    },
    {
      key: 'meetings',
      to: '/meetings',
      icon: Users,
      label: t('planning.link_meetings', { defaultValue: 'Meetings' }),
    },
  ];

  return (
    <nav
      aria-label={t('planning.section_nav', { defaultValue: 'Planning & Control modules' })}
      className="mb-4 flex flex-wrap items-center gap-1.5"
    >
      <span className="mr-1 text-2xs font-semibold uppercase tracking-wider text-content-quaternary">
        {t('planning.section_label', { defaultValue: 'Planning & Control' })}
      </span>
      {links.map((l) => {
        const Icon = l.icon;
        const isActive = l.key === active;
        return (
          <button
            key={l.key}
            type="button"
            disabled={isActive}
            aria-current={isActive ? 'page' : undefined}
            onClick={() => navigate(l.to)}
            className={
              isActive
                ? 'inline-flex items-center gap-1.5 rounded-full bg-oe-blue px-3 py-1 text-xs font-semibold text-white shadow-sm'
                : 'inline-flex items-center gap-1.5 rounded-full border border-border-light bg-surface-primary px-3 py-1 text-xs font-medium text-content-secondary transition-colors hover:border-oe-blue/40 hover:bg-oe-blue-subtle/40 hover:text-oe-blue-text'
            }
          >
            <Icon size={13} />
            {l.label}
          </button>
        );
      })}
    </nav>
  );
}

export default PlanningCrossLinks;
