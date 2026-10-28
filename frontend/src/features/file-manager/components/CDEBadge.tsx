// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/* CDE (Common Data Environment) state badges per ISO 19650 / BS 1192.
   Maps lifecycle state to a colored chip:
     wip       — Work in Progress (gray)
     shared    — Shared but unapproved (amber)
     published — Approved for construction (emerald)
     archived  — Superseded (slate) */

import clsx from 'clsx';
import { useTranslation } from 'react-i18next';

export const CDE_BADGE: Record<string, { label: string; cls: string }> = {
  wip: { label: 'WIP', cls: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300' },
  shared: { label: 'Shared', cls: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300' },
  published: { label: 'Published', cls: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300' },
  archived: { label: 'Archived', cls: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400' },
};

export function CDEBadge({ state, size = 'sm' }: { state: string | undefined; size?: 'xs' | 'sm' }) {
  const { t } = useTranslation();
  if (!state) return null;
  const cfg = CDE_BADGE[state] ?? null;
  if (!cfg) return null;
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-md font-medium uppercase tracking-wider',
        size === 'xs' ? 'px-1 py-px text-[9px]' : 'px-1.5 py-0.5 text-[10px]',
        cfg.cls,
      )}
      title={t(`cde.state_${state}`, { defaultValue: cfg.label })}
    >
      {t(`cde.state_${state}`, { defaultValue: cfg.label })}
    </span>
  );
}
