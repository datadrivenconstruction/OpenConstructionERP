// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// OpenConstructionERP — DataDrivenConstruction (DDC)
// AI Estimate Builder — conversational intake v2 (dependency warnings note).
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Renders IntakeState.dependency_warnings as NON-BLOCKING yellow advisory
// notes. These never gate submission (founder decision 4: AI proposes, human
// confirms). The wording comes from `aiest.dep.missing_prereq` with a
// `{{prereq}}` interpolation so locales can reorder the sentence.

import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import { mapDependencyWarnings } from './helpers';
import type { DependencyWarning } from './types';

interface DependencyWarningsProps {
  warnings: DependencyWarning[] | undefined | null;
}

export function DependencyWarnings({ warnings }: DependencyWarningsProps) {
  const { t } = useTranslation();
  const mapped = mapDependencyWarnings(warnings);
  if (mapped.length === 0) return null;

  return (
    <div
      role="note"
      className="rounded-xl border border-amber-300/60 bg-amber-50 px-4 py-3 dark:border-amber-500/30 dark:bg-amber-500/10"
    >
      <div className="flex items-center gap-2 text-sm font-medium text-[#b45309] dark:text-amber-300">
        <AlertTriangle size={15} />
        {t('aiest.dep.heading', { defaultValue: 'Sequence notes (non-blocking)' })}
      </div>
      <ul className="mt-1.5 space-y-1 pl-6 text-xs text-[#92400e] dark:text-amber-200/90">
        {mapped.map((w) => (
          <li key={w.id} className="list-disc">
            {t(w.i18nKey, { defaultValue: w.defaultValue, ...w.params })}
          </li>
        ))}
      </ul>
    </div>
  );
}
