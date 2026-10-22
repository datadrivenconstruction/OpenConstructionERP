// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** "Start and calendar" card in Settings > General: personal, kept on this device. */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardHeader, CardContent } from '@/shared/ui';
import {
  LANDING_PAGES,
  WEEK_STARTS,
  readWorkPrefs,
  writeWorkPrefs,
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
