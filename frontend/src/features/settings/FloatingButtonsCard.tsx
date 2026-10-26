// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Floating buttons" card in Settings > General: a show/hide switch for the
 * Recent and AI assistant buttons in the bottom-right corner. Both are shown
 * by default; the choice is kept on this device.
 */
import { useTranslation } from 'react-i18next';
import { Card, CardHeader, CardContent } from '@/shared/ui';
import { FLOATING_ITEMS, floatingPref, type FloatingItem } from '@/shared/lib/floatingPrefs';

const LABEL: Record<FloatingItem, { key: string; fallback: string }> = {
  recent: { key: 'settings.floating_recent', fallback: 'Recent pages' },
  assistant: { key: 'settings.floating_assistant', fallback: 'AI assistant' },
};

export function FloatingButtonsCard() {
  const { t } = useTranslation();
  const prefs = floatingPref.use();

  return (
    <Card>
      <CardHeader
        title={t('settings.floating_title', { defaultValue: 'Floating buttons' })}
        subtitle={t('settings.floating_subtitle', {
          defaultValue: 'Choose which round buttons appear in the bottom-right corner.',
        })}
      />
      <CardContent>
        <ul className="flex flex-col divide-y divide-border-light">
          {FLOATING_ITEMS.map((item) => {
            const shown = !prefs[item];
            const label = t(LABEL[item].key, { defaultValue: LABEL[item].fallback });
            return (
              <li key={item} className="flex items-center justify-between gap-3 py-2">
                <span className="text-sm text-content-primary">{label}</span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={shown}
                  aria-label={t('settings.floating_show', {
                    defaultValue: 'Show the {{label}} button',
                    label,
                  })}
                  onClick={() => floatingPref.write({ ...prefs, [item]: shown })}
                  className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors duration-normal ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue/40 ${
                    shown ? 'bg-oe-blue' : 'bg-surface-tertiary'
                  }`}
                >
                  <span
                    className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform duration-normal ease-oe ${
                      shown ? 'translate-x-5' : 'translate-x-0.5'
                    }`}
                  />
                </button>
              </li>
            );
          })}
        </ul>
        <p className="mt-3 text-xs text-content-tertiary">
          {t('settings.floating_note', {
            defaultValue: 'The assistant still opens with Alt+A and from the command palette.',
          })}
        </p>
      </CardContent>
    </Card>
  );
}
