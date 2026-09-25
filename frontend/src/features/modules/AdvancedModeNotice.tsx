// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Explains, on the Modules page, why switching a module on can change nothing.
 *
 * Two independent gates decide whether a sidebar row renders. The module gate
 * (`passesRowGates` in `Sidebar.tsx`) is what this page controls. The
 * interface-mode gate (`advancedOnly` and `hideInSimple`, applied in
 * `visibleGroupItems` there) is not: it lives behind the Simple / Advanced switch in
 * Settings, its default follows the company profile (Simple when there is none,
 * `useViewModeDefault.ts`), and in Simple mode it hides most of the catalogue
 * outright. A user who enables a module here and then cannot find it
 * has met the second gate without ever being told it exists.
 *
 * The notice appears only in Simple mode, names the number of entries being
 * held back, and switches modes in place so the fix does not require hunting
 * through Settings for a toggle whose connection to this page is invisible.
 */
import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { EyeOff } from 'lucide-react';
import { Button } from '@/shared/ui';
import { useViewModeStore } from '@/stores/useViewModeStore';
import { useToastStore } from '@/stores/useToastStore';
import { useCompanyWorkspace } from '@/app/layout/useCompanyWorkspace';
import { countAdvancedOnlyEntries } from './advancedModeGap';

export function AdvancedModeNotice() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const isAdvanced = useViewModeStore((s) => s.isAdvanced);
  const setMode = useViewModeStore((s) => s.setMode);
  const addToast = useToastStore((s) => s.addToast);

  // With a company workspace, Simple mode hides nothing: the rows outside the
  // workspace sit under "More modules", where a module switched on here shows
  // up. The warning below would be false, so it stays away.
  const workspace = useCompanyWorkspace();

  // The catalogue is a module-scope constant, so this only ever runs once.
  const { hidden, total } = useMemo(() => countAdvancedOnlyEntries(), []);

  if (isAdvanced || workspace) return null;

  function enableAdvanced() {
    setMode('advanced');
    addToast({
      type: 'success',
      title: t('modules.advanced_mode_on', { defaultValue: 'Advanced mode is on' }),
      message: t('modules.advanced_mode_on_detail', {
        defaultValue: 'Every menu entry your enabled modules provide is now visible in the sidebar.',
      }),
    });
  }

  return (
    <div
      className="animate-card-in rounded-xl border border-amber-500/30 bg-amber-500/5 p-4"
      style={{ animationDelay: '10ms' }}
    >
      <div className="flex flex-wrap items-start gap-3">
        <span className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400">
          <EyeOff size={18} />
        </span>
        <div className="min-w-56 flex-1">
          <p className="text-sm font-semibold text-content-primary">
            {t('modules.simple_mode_title', {
              defaultValue: 'Simple mode hides most of the menu',
            })}
          </p>
          <p className="mt-1 text-sm leading-relaxed text-content-secondary">
            {t('modules.simple_mode_body', {
              defaultValue:
                'The sidebar is showing {{visible}} of {{total}} entries. The other {{hidden}} stay hidden while you are in Simple mode, so a module you switch on here may not appear in the menu until you turn on Advanced mode.',
              visible: total - hidden,
              total,
              hidden,
            })}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Button size="sm" onClick={enableAdvanced}>
            {t('modules.simple_mode_switch', { defaultValue: 'Turn on Advanced mode' })}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => navigate('/settings')}>
            {t('modules.simple_mode_settings', { defaultValue: 'Open Settings' })}
          </Button>
        </div>
      </div>
    </div>
  );
}
