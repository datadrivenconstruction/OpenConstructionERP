// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Settings > AI > Site assistants: what each assistant does and the morning briefing schedule. */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Sparkles } from 'lucide-react';
import { Button, Card } from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { fetchSitePrefs, saveSitePrefs, type BriefingSection, type SitePrefs } from './api';

const SECTION_DEFAULTS: Record<BriefingSection, string> = {
  weather: 'Weather',
  rfis: 'RFIs',
  inspections: 'Inspections due',
  deliveries: 'Deliveries',
  diary: "Yesterday's diary",
};

export function SiteAssistantsSettings() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const prefs = useQuery<SitePrefs>({
    queryKey: ['site-prefs', projectId],
    queryFn: () => fetchSitePrefs(projectId as string),
    enabled: !!projectId,
    retry: false,
  });
  const [enabled, setEnabled] = useState(false);
  const [time, setTime] = useState('06:30');
  const [sections, setSections] = useState<BriefingSection[]>([]);

  useEffect(() => {
    if (!prefs.data) return;
    setEnabled(prefs.data.enabled);
    setTime(prefs.data.briefing_time);
    setSections(prefs.data.enabled_sections.length ? prefs.data.enabled_sections : prefs.data.available_sections);
  }, [prefs.data]);

  const save = useMutation({
    mutationFn: () =>
      saveSitePrefs({ project_id: projectId as string, enabled, briefing_time: time, enabled_sections: sections }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['site-prefs', projectId] });
      addToast({ type: 'success', title: t('site_ai.settings.saved', { defaultValue: 'Briefing settings saved' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('site_ai.save_failed', { defaultValue: 'Could not save' }), message: e.message }),
  });

  const toggle = (s: BriefingSection) =>
    setSections((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]));

  const assistants: [string, string, string][] = [
    ['briefing', 'Morning briefing', 'Weather, open and overdue RFIs, inspections due, deliveries and yesterday\'s diary in one place.'],
    ['diary', 'Diary draft', 'Proposes diary entries from the day\'s photos and voice notes.'],
    ['rfi', 'RFI check', 'Checks an RFI for completeness before it is sent.'],
    ['actions', 'Meeting actions', 'Proposes action items from meeting minutes.'],
  ];

  return (
    <Card className="lg:col-span-2" data-testid="site-assistants-settings">
      <div className="flex flex-col gap-4 p-5">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
            <Sparkles size={15} />
            {t('site_ai.settings.title', { defaultValue: 'Site assistants' })}
          </h3>
          <p className="mt-1 text-xs text-content-tertiary">
            {t('site_ai.settings.intro', {
              defaultValue: 'They suggest; you decide. Without an AI provider they still show the facts and rule-based checks.',
            })}
          </p>
        </div>
        <ul className="grid gap-2 sm:grid-cols-2">
          {assistants.map(([id, title, body]) => (
            <li key={id} className="rounded-lg border border-border-light p-3">
              <p className="text-sm font-medium text-content-primary">
                {t(`site_ai.settings.assistant.${id}.title`, { defaultValue: title })}
              </p>
              <p className="mt-0.5 text-xs text-content-secondary">
                {t(`site_ai.settings.assistant.${id}.body`, { defaultValue: body })}
              </p>
            </li>
          ))}
        </ul>

        <div className="flex flex-col gap-3 rounded-lg border border-border-light p-3">
          <p className="text-sm font-medium text-content-primary">
            {t('site_ai.settings.schedule', { defaultValue: 'Daily briefing for the active project' })}
          </p>
          {!projectId && (
            <p className="text-xs text-content-tertiary">
              {t('site_ai.settings.pick_project', { defaultValue: 'Open a project to set its briefing.' })}
            </p>
          )}
          {projectId && prefs.isError && (
            <p className="text-xs text-content-tertiary">
              {t('site_ai.settings.unavailable', { defaultValue: 'Briefing settings are not available for this project.' })}
            </p>
          )}
          {projectId && prefs.data && (
            <>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                  data-testid="site-pref-enabled"
                />
                {t('site_ai.settings.enable', { defaultValue: 'Prepare the briefing every morning' })}
              </label>
              <label className="flex items-center gap-2 text-sm">
                <span>{t('site_ai.settings.time', { defaultValue: 'Time (server time)' })}</span>
                <input
                  type="time"
                  value={time}
                  onChange={(e) => setTime(e.target.value)}
                  className="rounded-md border border-border-light bg-surface-primary px-2 py-1"
                  data-testid="site-pref-time"
                />
              </label>
              <div className="flex flex-wrap gap-3">
                {prefs.data.available_sections.map((s) => (
                  <label key={s} className="flex items-center gap-1.5 text-sm">
                    <input type="checkbox" checked={sections.includes(s)} onChange={() => toggle(s)} />
                    {t(`site_ai.settings.section.${s}`, { defaultValue: SECTION_DEFAULTS[s] })}
                  </label>
                ))}
              </div>
              <div>
                <Button size="sm" variant="primary" onClick={() => save.mutate()} disabled={save.isPending}>
                  {t('site_ai.settings.save', { defaultValue: 'Save' })}
                </Button>
              </div>
            </>
          )}
        </div>
      </div>
    </Card>
  );
}
