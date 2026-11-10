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
  wip: { label: 'WIP', cls: 'bg-surface-secondary text-content-secondary' },
  shared: { label: 'Shared', cls: 'bg-semantic-warning-bg text-semantic-warning' },
  published: { label: 'Published', cls: 'bg-semantic-success-bg text-semantic-success' },
  archived: { label: 'Archived', cls: 'bg-surface-secondary text-content-secondary' },
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
        size === 'xs' ? 'px-1 py-px text-2xs' : 'px-1.5 py-0.5 text-2xs',
        cfg.cls,
      )}
      title={t(`cde.state_${state}`, { defaultValue: cfg.label })}
    >
      {t(`cde.state_${state}`, { defaultValue: cfg.label })}
    </span>
  );
}
