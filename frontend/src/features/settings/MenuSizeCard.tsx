// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Menu size" card in Settings > General: how long item names show in the left
 * menu (wrapped or on one line) and how wide the menu is. The width can also be
 * dragged on the menu's own edge. Both are personal and kept on this device.
 */
import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { LayoutDashboard, RotateCcw, Table2 } from 'lucide-react';
import { Card, CardHeader, CardContent, Button } from '@/shared/ui';
import {
  SIDEBAR_DEFAULT_WIDTH,
  SIDEBAR_MAX_WIDTH,
  SIDEBAR_MIN_WIDTH,
  SIDEBAR_WIDTH_STEP,
  useSidebarPrefsStore,
  type SidebarLabelMode,
} from '@/stores/useSidebarPrefsStore';
import { Choice, OptionRow } from './AppearanceStyleCard';

const MODES: readonly SidebarLabelMode[] = ['wrap', 'single'];

export function MenuSizeCard() {
  const { t } = useTranslation();
  const width = useSidebarPrefsStore((s) => s.width);
  const labelMode = useSidebarPrefsStore((s) => s.labelMode);
  const setWidth = useSidebarPrefsStore((s) => s.setWidth);
  const resetWidth = useSidebarPrefsStore((s) => s.resetWidth);
  const setLabelMode = useSidebarPrefsStore((s) => s.setLabelMode);
  const sliderId = useId();

  const modeLabel = (mode: SidebarLabelMode) =>
    mode === 'wrap'
      ? t('settings.menu_size_labels_wrap', { defaultValue: 'Full names on several lines' })
      : t('settings.menu_size_labels_single', { defaultValue: 'One line, cut off at the panel edge' });
  const sample = t('settings.menu_size_sample', { defaultValue: 'Bill of quantities and cost estimates' });
  const sampleShort = t('settings.menu_size_sample_short', { defaultValue: 'Schedule' });

  return (
    <Card className="lg:col-span-2">
      <CardHeader
        title={t('settings.menu_size_title', { defaultValue: 'Menu size' })}
        subtitle={t('settings.menu_size_subtitle', {
          defaultValue: 'How item names show in the left menu and how wide the menu is. You can also drag the menu edge.',
        })}
      />
      <CardContent>
        <div className="flex flex-col gap-4">
          <OptionRow label={t('settings.menu_size_labels', { defaultValue: 'Item names' })}>
            {MODES.map((mode) => (
              <Choice key={mode} active={labelMode === mode} onSelect={() => setLabelMode(mode)} label={modeLabel(mode)} />
            ))}
          </OptionRow>

          <div className="grid gap-2 sm:grid-cols-[9rem_1fr] sm:items-center">
            <label htmlFor={sliderId} className="text-sm font-medium text-content-primary">
              {t('settings.menu_size_width', { defaultValue: 'Menu width' })}
            </label>
            <div className="flex flex-wrap items-center gap-3">
              <input
                id={sliderId}
                type="range"
                min={SIDEBAR_MIN_WIDTH}
                max={SIDEBAR_MAX_WIDTH}
                step={SIDEBAR_WIDTH_STEP}
                value={width}
                onChange={(e) => setWidth(Number(e.target.value))}
                aria-valuetext={`${width} px`}
                className="h-2 min-w-0 flex-1 cursor-pointer accent-oe-blue sm:max-w-xs"
              />
              <output htmlFor={sliderId} className="w-16 text-sm tabular-nums text-content-secondary">
                {width} px
              </output>
              <Button
                variant="secondary"
                size="sm"
                icon={<RotateCcw size={14} />}
                disabled={width === SIDEBAR_DEFAULT_WIDTH}
                onClick={resetWidth}
              >
                {t('settings.menu_size_reset', { defaultValue: 'Reset' })}
              </Button>
            </div>
          </div>
        </div>

        <div
          aria-hidden
          data-testid="menu-size-preview"
          className="mt-5 overflow-hidden rounded-lg border border-border-light bg-surface-secondary p-3"
        >
          <div
            className="max-w-full rounded-lg border border-border-light bg-surface-primary p-1.5"
            style={{ width }}
          >
            {[
              { icon: LayoutDashboard, text: sampleShort, active: false },
              { icon: Table2, text: sample, active: true },
              { icon: LayoutDashboard, text: sample, active: false },
            ].map((row, i) => {
              const Icon = row.icon;
              return (
                <div
                  key={i}
                  className={`flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] ${
                    row.active ? 'bg-oe-blue-subtle text-oe-blue-text' : 'text-content-secondary'
                  }`}
                >
                  <Icon size={16} strokeWidth={1.75} className="shrink-0" />
                  <span
                    className={`min-w-0 leading-snug ${labelMode === 'single' ? 'truncate' : 'break-words'}`}
                    title={row.text}
                  >
                    {row.text}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
