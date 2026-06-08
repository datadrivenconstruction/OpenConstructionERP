// OpenConstructionERP — DataDrivenConstruction (DDC)
// AI Estimate Builder — conversational intake v2 (live parameter sheet).
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The right-hand live sheet that fills in as answers arrive, and the
// checkpoint-A review where the user confirms the full parameter set before
// any groups are composed (human-confirmed AI: explicit confirm step).

import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui';
import { ListChecks } from 'lucide-react';
import type { IntakeState } from './types';

interface ParameterSheetProps {
  state: IntakeState;
  /** When true, render the editable confirm view with a Confirm button. */
  editable: boolean;
  onChangeParam?: (key: string, value: unknown) => void;
  onConfirm?: () => void;
  confirming?: boolean;
}

function displayValue(value: unknown): string {
  if (value === true) return 'Yes';
  if (value === false) return 'No';
  if (value === null || value === undefined || value === '') return '—';
  return String(value);
}

// Turn a raw parameter key into a readable label when no `aiest.param.<key>`
// translation exists yet, so the sheet never shows bare snake_case like
// "gross_floor_area_m2". Unit suffixes become proper symbols (m2 -> m²) and
// the first letter is capitalised: "gross_floor_area_m2" -> "Gross floor
// area m²".
function humanizeParamKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\bm2\b/g, 'm²')
    .replace(/\bm3\b/g, 'm³')
    .replace(/\bpct\b/g, '%')
    .replace(/\bdeg\b/g, '°')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^./, (c) => c.toUpperCase());
}

export function ParameterSheet({
  state,
  editable,
  onChangeParam,
  onConfirm,
  confirming,
}: ParameterSheetProps) {
  const { t } = useTranslation();
  const entries = Object.entries(state.params ?? {});

  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-content-primary">
        <ListChecks size={15} className="text-oe-blue" />
        {t('aiest.sheet.title', { defaultValue: 'Parameter sheet' })}
      </div>

      {entries.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-3 py-4 text-xs text-content-tertiary">
          {t('aiest.sheet.empty', {
            defaultValue: 'Values you confirm will appear here as you answer.',
          })}
        </p>
      ) : (
        <dl className="space-y-1.5">
          {entries.map(([key, value]) => {
            const label = t(`aiest.param.${key}`, { defaultValue: humanizeParamKey(key) });
            return (
              <div
                key={key}
                className="flex items-center justify-between gap-3 rounded-lg bg-surface-secondary/60 px-3 py-1.5"
              >
                <dt className="text-xs text-content-secondary">{label}</dt>
                <dd className="text-sm font-medium text-content-primary">
                  {editable && typeof value !== 'boolean' ? (
                    <input
                      aria-label={label}
                      value={value === null || value === undefined ? '' : String(value)}
                      onChange={(e) => onChangeParam?.(key, e.target.value)}
                      className="h-7 w-24 rounded-md border border-border bg-surface-primary px-2 text-right text-sm focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue/30"
                    />
                  ) : (
                    displayValue(value)
                  )}
                </dd>
              </div>
            );
          })}
        </dl>
      )}

      {editable && (
        <div className="mt-4">
          <p className="mb-2 text-xs text-content-tertiary">
            {t('aiest.sheet.confirm_hint', {
              defaultValue:
                'Review the values, then confirm to compose the work packages. You can still edit everything afterwards.',
            })}
          </p>
          <Button
            variant="primary"
            size="md"
            loading={confirming}
            onClick={onConfirm}
            className="w-full"
          >
            {t('aiest.sheet.confirm', { defaultValue: 'Confirm parameters' })}
          </Button>
        </div>
      )}
    </div>
  );
}
