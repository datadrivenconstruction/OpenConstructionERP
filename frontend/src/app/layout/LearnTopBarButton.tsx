// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Where the Learn section (Videos and Cases) goes when it is hidden from the
// top of the menu: one graduation cap in the top bar. Clicking it puts the
// section back and the cap leaves. It shows at every width, a phone included,
// because it is the only way back.

import { useTranslation } from 'react-i18next';
import { GraduationCap } from 'lucide-react';
import { useModuleStore } from '@/stores/useModuleStore';
import { LEARN_GROUP_ID } from './navCatalog';
import { LEARN_ANCHOR_ATTR, anchorRect, flyLearn } from './learnFlight';

export function LearnTopBarButton() {
  const { t } = useTranslation();
  const hidden = useModuleStore((s) => s.hiddenGroups.includes(LEARN_GROUP_ID));
  const setGroupHidden = useModuleStore((s) => s.setGroupHidden);
  if (!hidden) return null;

  const label = t('sidebar.learn.show', { defaultValue: 'Show video guides & use cases' });
  const hint = t('sidebar.learn.show_hint', { defaultValue: 'Put Video guides and Use cases back at the top of the menu' });

  return (
    <button
      type="button"
      data-testid="header-learn-restore"
      {...{ [LEARN_ANCHOR_ATTR]: 'topbar' }}
      onClick={() => {
        const from = anchorRect('topbar');
        setGroupHidden(LEARN_GROUP_ID, false);
        flyLearn(from, 'sidebar');
      }}
      aria-label={`${label}. ${hint}`}
      title={hint}
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue ring-1 ring-inset ring-oe-blue/20 transition-colors hover:bg-oe-blue/15 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue dark:bg-oe-blue/20 dark:text-sky-300"
    >
      <GraduationCap size={16} strokeWidth={2} aria-hidden />
    </button>
  );
}
