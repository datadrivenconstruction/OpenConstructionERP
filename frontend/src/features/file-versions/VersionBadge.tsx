// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Tiny V## chip showing a version's status (current vs superseded). */

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';

interface VersionBadgeProps {
  versionNumber: number;
  isCurrent: boolean;
  className?: string;
}

function formatVersionLabel(n: number): string {
  // V01, V02, ... up to V99; falls back to plain Vn for n >= 100.
  return n < 100 ? `V${String(n).padStart(2, '0')}` : `V${n}`;
}

export function VersionBadge({ versionNumber, isCurrent, className }: VersionBadgeProps) {
  const { t } = useTranslation();
  const label = formatVersionLabel(versionNumber);
  const statusKey = isCurrent ? 'files.versions.current' : 'files.versions.superseded';
  const statusFallback = isCurrent ? 'Current' : 'Superseded';

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 px-1.5 h-5 rounded-md text-[10px] font-semibold tabular-nums',
        isCurrent
          ? 'bg-oe-blue/10 text-oe-blue border border-oe-blue/20'
          : 'bg-surface-secondary text-content-tertiary border border-border-light',
        className,
      )}
      title={t(statusKey, { defaultValue: statusFallback })}
    >
      <span>{label}</span>
      <span className="opacity-70">·</span>
      <span>{t(statusKey, { defaultValue: statusFallback })}</span>
    </span>
  );
}
