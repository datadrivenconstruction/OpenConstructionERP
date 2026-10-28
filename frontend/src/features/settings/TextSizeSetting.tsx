// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Text size" control, shown under the theme choice in Settings > General.
 *
 * In the desktop app it zooms the window natively and remembers the size on
 * this device. In a browser there is nothing for the page to set, because the
 * only zoom that keeps popovers, grids and canvases aligned is the browser's
 * own, so it says which keys do that instead of offering buttons that could not
 * work. `uiScale.ts` carries the measurements behind that split.
 */
import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { fmtPercent } from '@/shared/lib/formatters';
import {
  UI_SCALE_STEPS,
  applyUiScale,
  canSetUiScale,
  isApplePlatform,
  readUiScale,
  writeUiScale,
} from '@/shared/lib/uiScale';
import { useToastStore } from '@/stores/useToastStore';

export function TextSizeSetting() {
  const { t } = useTranslation();
  const labelId = useId();
  const [scale, setScale] = useState(readUiScale);
  const [pending, setPending] = useState(false);

  const mod = isApplePlatform() ? '⌘' : t('settings.text_size_key_ctrl', { defaultValue: 'Ctrl' });

  const choose = async (next: number) => {
    if (next === scale || pending) return;
    setPending(true);
    const ok = await applyUiScale(next);
    setPending(false);
    if (ok) {
      writeUiScale(next);
      setScale(next);
      return;
    }
    useToastStore.getState().addToast({
      type: 'warning',
      title: t('settings.text_size_failed', { defaultValue: 'Could not change the text size' }),
      message: t('settings.text_size_failed_hint', {
        defaultValue: 'Use the keyboard shortcuts instead: {{mod}} + and {{mod}} -.',
        mod,
      }),
    });
  };

  return (
    <div className="mt-5 border-t border-border-light pt-4">
      <p id={labelId} className="text-sm font-medium text-content-primary">
        {t('settings.window_zoom_title', { defaultValue: 'Window zoom' })}
      </p>
      {canSetUiScale ? (
        <>
          <p className="mt-0.5 text-xs text-content-tertiary">
            {t('settings.text_size_desc', {
              defaultValue: 'Makes text and controls larger or smaller across the whole app. Remembered on this device.',
            })}
          </p>
          <div role="group" aria-labelledby={labelId} className="mt-3 grid grid-cols-5 gap-2">
            {UI_SCALE_STEPS.map((step) => {
              const isActive = step === scale;
              return (
                <button
                  key={step}
                  type="button"
                  onClick={() => void choose(step)}
                  aria-pressed={isActive}
                  disabled={pending}
                  className={`rounded-lg px-2 py-2 text-sm font-medium tabular-nums transition-all duration-normal ease-oe disabled:cursor-wait ${
                    isActive
                      ? 'bg-oe-blue-subtle border-2 border-oe-blue text-oe-blue-text'
                      : 'border-2 border-transparent bg-surface-secondary/50 hover:bg-surface-secondary text-content-secondary hover:text-content-primary'
                  }`}
                >
                  {fmtPercent(step * 100, 0)}
                </button>
              );
            })}
          </div>
          <p className="mt-3 text-xs text-content-tertiary">
            {t('settings.text_size_hotkeys', {
              defaultValue:
                'Shortcuts: {{mod}} + to enlarge, {{mod}} - to shrink, {{mod}} 0 to reset. The size chosen here is applied every time the app starts.',
              mod,
            })}
          </p>
        </>
      ) : (
        <p className="mt-0.5 text-xs text-content-tertiary">
          {t('settings.text_size_browser_hint', {
            defaultValue:
              'Your browser sets the text size for this app: {{mod}} + to enlarge, {{mod}} - to shrink, {{mod}} 0 to reset. The browser remembers it for this site.',
            mod,
          })}
        </p>
      )}
    </div>
  );
}
