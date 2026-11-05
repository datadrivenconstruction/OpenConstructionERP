// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Learning tips" card in Settings > General: one switch for the small
 * "Learn this step" button that videos, courses and guides hang from, the
 * number of screens it was hidden on, and a reset. It is the same store the
 * button's own "Hide" actions write to; the choice stays on this device.
 */
import { useTranslation } from 'react-i18next';
import { Card, CardHeader, CardContent } from '@/shared/ui/Card';
import { useVideoHintsStore } from '@/features/videos/videoRoutes';

export function LearningTipsCard() {
  const { t } = useTranslation();
  const off = useVideoHintsStore((s) => s.off);
  const hidden = useVideoHintsStore((s) => s.hidden);
  const setOff = useVideoHintsStore((s) => s.setOff);
  const showAgain = useVideoHintsStore((s) => s.showAgain);
  const shown = !off;
  const label = t('settings.learning_tips_toggle', { defaultValue: 'Show learning tips on screens' });

  return (
    <Card>
      <CardHeader
        title={t('settings.learning_tips_title', { defaultValue: 'Learning tips' })}
        subtitle={t('settings.learning_tips_subtitle', {
          defaultValue: 'A small "Learn this step" button on screens that have videos or courses.',
        })}
      />
      <CardContent>
        <div className="flex items-center justify-between gap-3 py-1">
          <span className="text-sm text-content-primary">{label}</span>
          <button
            type="button"
            role="switch"
            aria-checked={shown}
            aria-label={label}
            data-testid="learning-tips-switch"
            onClick={() => setOff(shown)}
            className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors duration-normal ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue/40 motion-reduce:transition-none ${
              shown ? 'bg-oe-blue' : 'bg-surface-tertiary'
            }`}
          >
            <span
              className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform duration-normal ease-oe motion-reduce:transition-none ${
                shown ? 'translate-x-5 rtl:-translate-x-5' : 'translate-x-0.5 rtl:-translate-x-0.5'
              }`}
            />
          </button>
        </div>
        {(hidden.length > 0 || off) && (
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-content-tertiary">
            <span data-testid="learning-tips-hidden-count">
              {hidden.length > 0 &&
                t('settings.learning_tips_hidden_count', {
                  defaultValue: 'Hidden on screens: {{number}}',
                  number: hidden.length,
                })}
            </span>
            <button
              type="button"
              onClick={showAgain}
              data-testid="learning-tips-show-all"
              className="font-medium text-oe-blue hover:underline"
            >
              {t('settings.learning_tips_show_all', { defaultValue: 'Show on all screens again' })}
            </button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
