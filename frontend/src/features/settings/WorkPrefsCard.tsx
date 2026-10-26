// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** "Start and calendar" card in Settings > General: personal, kept on this device. */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardHeader, CardContent } from '@/shared/ui';
import {
  LANDING_PAGES,
  PROJECT_ROLES,
  PROJECT_START_PAGES,
  WEEK_STARTS,
  readWorkPrefs,
  writeWorkPrefs,
  type ProjectRole,
  type ProjectStartPage,
  type WorkPrefs,
} from '@/shared/lib/workPrefs';
import { Choice, OptionRow } from './AppearanceStyleCard';

const LANDING_FALLBACK: Record<WorkPrefs['landing'], string> = {
  dashboard: 'Dashboard',
  projects: 'Projects',
  boq: 'Bills of quantities',
  tasks: 'Tasks',
  schedule: 'Schedule',
  inbox: 'Inbox',
};

const ROLE_FALLBACK: Record<ProjectRole, string> = {
  client_owner: 'Client / owner',
  general_contractor: 'General contractor',
  subcontractor: 'Subcontractor',
  cost_engineer: 'Cost engineer',
  designer_architect: 'Designer / architect',
  bim_manager: 'BIM manager',
  bim_consultant: 'BIM consultant',
  developer: 'Developer',
};

const START_FALLBACK: Record<ProjectStartPage, string> = {
  overview: 'Project page',
  boq: 'Bills of quantities',
  tasks: 'Tasks',
  schedule: 'Schedule',
  inbox: 'Inbox',
};

const WEEK_FALLBACK: Record<WorkPrefs['weekStart'], string> = {
  auto: 'From language',
  monday: 'Monday',
  sunday: 'Sunday',
  saturday: 'Saturday',
};

export function WorkPrefsCard() {
  const { t } = useTranslation();
  const [prefs, setPrefs] = useState<WorkPrefs>(readWorkPrefs);
  const update = (next: WorkPrefs) => {
    writeWorkPrefs(next);
    setPrefs(next);
  };

  const setProjectStart = (role: ProjectRole, page: ProjectStartPage) => {
    const projectStart = { ...prefs.projectStart };
    if (page === 'overview') delete projectStart[role];
    else projectStart[role] = page;
    update({ ...prefs, projectStart });
  };

  return (
    <Card>
      <CardHeader
        title={t('settings.work_title', { defaultValue: 'Start and calendar' })}
        subtitle={t('settings.work_subtitle', {
          defaultValue: 'Where you land after signing in and how weeks are laid out. Saved on this device.',
        })}
      />
      <CardContent>
        <div className="flex flex-col gap-3">
          <OptionRow label={t('settings.work_landing', { defaultValue: 'Start page' })}>
            {LANDING_PAGES.map((page) => (
              <Choice
                key={page}
                active={prefs.landing === page}
                onSelect={() => update({ ...prefs, landing: page })}
                label={t(`settings.work_landing_${page}`, { defaultValue: LANDING_FALLBACK[page] })}
              />
            ))}
          </OptionRow>
          <div>
            <p className="text-sm font-medium text-content-primary">
              {t('settings.work_project_start', { defaultValue: 'When opening a project, go to' })}
            </p>
            <p className="mb-2 text-xs text-content-tertiary">
              {t('settings.work_project_start_hint', {
                defaultValue: 'By the role set in the project profile. Unset roles open the project page.',
              })}
            </p>
            <ul className="grid grid-cols-1 gap-x-4 gap-y-1.5 sm:grid-cols-2">
              {PROJECT_ROLES.map((role) => {
                const roleLabel = t(`settings.work_role_${role}`, { defaultValue: ROLE_FALLBACK[role] });
                return (
                  <li key={role} className="flex items-center justify-between gap-2">
                    <span className="text-sm text-content-secondary">{roleLabel}</span>
                    <select
                      aria-label={t('settings.work_project_start_for', {
                        defaultValue: 'Start page for {{role}}',
                        role: roleLabel,
                      })}
                      value={prefs.projectStart[role] ?? 'overview'}
                      onChange={(e) => setProjectStart(role, e.target.value as ProjectStartPage)}
                      className="h-8 rounded-lg border border-border bg-surface-primary px-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
                    >
                      {PROJECT_START_PAGES.map((page) => (
                        <option key={page} value={page}>
                          {t(`settings.work_start_${page}`, { defaultValue: START_FALLBACK[page] })}
                        </option>
                      ))}
                    </select>
                  </li>
                );
              })}
            </ul>
          </div>
          <OptionRow label={t('settings.work_week_start', { defaultValue: 'Week starts on' })}>
            {WEEK_STARTS.map((day) => (
              <Choice
                key={day}
                active={prefs.weekStart === day}
                onSelect={() => update({ ...prefs, weekStart: day })}
                label={t(`settings.work_week_${day}`, { defaultValue: WEEK_FALLBACK[day] })}
              />
            ))}
          </OptionRow>
        </div>
      </CardContent>
    </Card>
  );
}
