// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** "Work mode" card: one click sets style, density, tables, menu and motion together. */
import { useTranslation } from 'react-i18next';
import { Card, CardHeader, CardContent } from '@/shared/ui';
import { useAppearanceStore } from '@/stores/useAppearanceStore';
import { readTablePrefs } from '@/shared/lib/tablePrefs';
import { WORK_MODE_IDS, applyWorkMode, matchWorkMode, type WorkModeId } from '@/shared/lib/workModes';

const DEFAULTS: Record<WorkModeId, { name: string; hint: string }> = {
  standard: { name: 'Standard', hint: 'The platform as it ships.' },
  classic: { name: 'Classic', hint: 'Calm and professional: no effects, sharp corners, plain menu.' },
  spreadsheet: { name: 'Compact / Spreadsheet', hint: 'Dense rows, spreadsheet tables, keyboard navigation on.' },
  field: { name: 'Field / Touch', hint: 'Large text and touch targets for tablets on site.' },
};

export function WorkModesCard({ onApplied }: { onApplied?: () => void }) {
  const { t } = useTranslation();
  const effective = useAppearanceStore((s) => s.effective);
  const menu = useAppearanceStore((s) => s.menu);
  const setAppearance = useAppearanceStore((s) => s.setAppearance);
  const setMenu = useAppearanceStore((s) => s.setMenu);
  const current = matchWorkMode(effective, menu, readTablePrefs());

  return (
    <Card>
      <CardHeader
        title={t('settings.work_mode_title', { defaultValue: 'Work mode' })}
        subtitle={t('settings.work_mode_subtitle', {
          defaultValue: 'Sets style, density, tables, menu and motion in one click. You can still change each setting below.',
        })}
      />
      <CardContent>
        <div className="grid gap-2 sm:grid-cols-2">
          {WORK_MODE_IDS.map((id) => (
            <button
              key={id}
              type="button"
              aria-pressed={current === id}
              onClick={() => {
                applyWorkMode(id, { setAppearance, setMenu });
                onApplied?.();
              }}
              className={
                'rounded-md border px-3 py-2.5 text-start transition-colors ' +
                (current === id
                  ? 'border-oe-blue bg-oe-blue/5'
                  : 'border-border-light hover:border-content-quaternary')
              }
            >
              <span className="block text-sm font-semibold text-content-primary">
                {t(`settings.work_mode_${id}`, { defaultValue: DEFAULTS[id].name })}
              </span>
              <span className="mt-0.5 block text-xs text-content-secondary">
                {t(`settings.work_mode_${id}_hint`, { defaultValue: DEFAULTS[id].hint })}
              </span>
            </button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
