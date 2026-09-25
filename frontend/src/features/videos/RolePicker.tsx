// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The fifteen roles as avatar tiles, for "Recommended for you" when the page
// does not know the reader's role yet. The pick is remembered in this browser.

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { ROLE_META } from '@/features/cases/roles';
import { RoleAvatar } from '@/features/cases/RoleAvatar';
import type { ProfessionalRole } from '@/features/cases/types';

export interface RolePickerProps {
  value: ProfessionalRole | null;
  onPick: (role: ProfessionalRole) => void;
  className?: string;
}

export function RolePicker({ value, onPick, className }: RolePickerProps) {
  const { t } = useTranslation();
  return (
    <ul
      data-testid="video-role-picker"
      className={clsx('grid grid-cols-2 gap-2 min-[480px]:grid-cols-3 md:grid-cols-5', className)}
    >
      {ROLE_META.map((meta) => {
        const label = t(meta.labelKey, { defaultValue: meta.labelDefault });
        const active = value === meta.id;
        return (
          <li key={meta.id}>
            <button
              type="button"
              aria-pressed={active}
              onClick={() => onPick(meta.id)}
              className={clsx(
                'flex h-full w-full items-center gap-2 rounded-xl border px-2.5 py-2 text-left text-xs font-medium transition-all',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
                active
                  ? 'border-oe-blue bg-oe-blue/10 text-oe-blue shadow-sm'
                  : 'border-border-light bg-surface-primary text-content-primary hover:-translate-y-px hover:border-oe-blue/40 hover:shadow-sm',
              )}
            >
              <RoleAvatar role={meta.id} className="h-9 w-9" />
              <span className="min-w-0 leading-snug">{label}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
