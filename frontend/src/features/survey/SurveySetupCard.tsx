// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One-click switch for the Survey & Land family: the seven survey modules with
 * a checkbox each, on by default except mine survey, which only mining work
 * needs. Shown on /survey while the family is off and in Settings > Market.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Compass } from 'lucide-react';
import { Button, Card, CardContent, CardHeader } from '@/shared/ui';
import { useModuleStore } from '@/stores/useModuleStore';
import { useToastStore } from '@/stores/useToastStore';

export interface SurveyModuleOption {
  id: string;
  labelKey: string;
  fallback: string;
  descKey: string;
  descFallback: string;
  defaultOn: boolean;
}

export const SURVEY_MODULES: SurveyModuleOption[] = [
  { id: 'survey_core', labelKey: 'survey.page.register', fallback: 'Survey register', descKey: 'survey.setup.core_desc', descFallback: 'Points, control and the project coordinate system. Every other survey page uses it.', defaultOn: true },
  { id: 'surfaces_volumes', labelKey: 'volumes.page.title', fallback: 'Surfaces & volumes', descKey: 'survey.setup.volumes_desc', descFallback: 'Cut and fill between two surfaces, sent to the BOQ.', defaultOn: true },
  { id: 'stockpiles', labelKey: 'stockpiles.page.title', fallback: 'Stockpiles', descKey: 'survey.setup.stockpiles_desc', descFallback: 'Pile volumes and tonnes from each survey, against the book stock.', defaultOn: true },
  { id: 'setting-out', labelKey: 'survey.page.setting_out', fallback: 'Setting-out', descKey: 'survey.setup.setting_out_desc', descFallback: 'Stake the design and check the as-built against tolerance.', defaultOn: true },
  { id: 'monitoring', labelKey: 'survey.page.monitoring', fallback: 'Monitoring', descKey: 'survey.setup.monitoring_desc', descFallback: 'Settlement and movement per epoch, with alert and action levels.', defaultOn: true },
  { id: 'land-parcels', labelKey: 'survey.parcels.title', fallback: 'Land parcels', descKey: 'survey.setup.parcels_desc', descFallback: 'Parcels, legal against computed areas, and who owns the land you work on.', defaultOn: true },
  { id: 'mine_survey', labelKey: 'mine.page.title', fallback: 'Mine survey', descKey: 'survey.setup.mine_desc', descFallback: 'Monthly mined volumes, ore and waste tonnes, drives and blast patterns.', defaultOn: false },
];

/** True while no survey module is on: the family still needs switching on. */
export function useSurveyFamilyOff(): boolean {
  const isModuleEnabled = useModuleStore((s) => s.isModuleEnabled);
  return !SURVEY_MODULES.some((m) => isModuleEnabled(m.id));
}

export function SurveySetupCard({ onEnabled }: { onEnabled?: () => void }) {
  const { t } = useTranslation();
  const setModuleEnabled = useModuleStore((s) => s.setModuleEnabled);
  const isModuleEnabled = useModuleStore((s) => s.isModuleEnabled);
  const addToast = useToastStore((s) => s.addToast);
  const anyOn = SURVEY_MODULES.some((m) => isModuleEnabled(m.id));
  const [picked, setPicked] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(SURVEY_MODULES.map((m) => [m.id, anyOn ? isModuleEnabled(m.id) : m.defaultOn])),
  );

  const toggle = (id: string, on: boolean) =>
    setPicked((p) => {
      const next = { ...p, [id]: on };
      // Every survey page reads its points from the register.
      if (on && id !== 'survey_core') next.survey_core = true;
      if (on && id === 'mine_survey') next.surfaces_volumes = true;
      return next;
    });

  const apply = () => {
    for (const m of SURVEY_MODULES) setModuleEnabled(m.id, !!picked[m.id]);
    addToast({ type: 'success', title: t('survey.setup.done', { defaultValue: 'Survey modules updated' }) });
    onEnabled?.();
  };

  return (
    <Card data-testid="survey-setup-card">
      <CardHeader
        title={t('survey.setup.title', { defaultValue: 'Survey & Land' })}
        subtitle={t('survey.setup.subtitle', {
          defaultValue: 'Points, volumes, stockpiles, setting-out, monitoring, parcels and mine survey. Pick what your team needs.',
        })}
      />
      <CardContent>
        <ul className="grid gap-2 sm:grid-cols-2">
          {SURVEY_MODULES.map((m) => (
            <li key={m.id}>
              <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-border-light p-3 hover:bg-surface-secondary">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={!!picked[m.id]}
                  onChange={(e) => toggle(m.id, e.target.checked)}
                  data-testid={`survey-setup-${m.id}`}
                />
                <span>
                  <span className="block text-sm font-medium text-content-primary">{t(m.labelKey, { defaultValue: m.fallback })}</span>
                  <span className="block text-xs text-content-secondary">{t(m.descKey, { defaultValue: m.descFallback })}</span>
                </span>
              </label>
            </li>
          ))}
        </ul>
        <div className="mt-4 flex justify-end">
          <Button variant="primary" icon={<Compass size={16} />} onClick={apply} data-testid="survey-setup-apply">
            {anyOn
              ? t('common.save', { defaultValue: 'Save' })
              : t('survey.setup.enable', { defaultValue: 'Switch on survey' })}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
