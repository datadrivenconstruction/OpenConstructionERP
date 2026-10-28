// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Small "drawn on V01 · current is V03" pill rendered next to a
 *  markup or comment whose ``file_version_id`` does not match the
 *  chain's current row.
 *
 *  Epic C — Document Versioning Unification. The pill is purely
 *  informational; it does not block interaction but warns the user
 *  that the annotation may be talking about a superseded revision.
 */

import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import clsx from 'clsx';
import { useFileVersions } from './hooks';
import type { FileKind } from './types';

interface StaleVersionPillProps {
  /** ID of the file the comment/markup is attached to. */
  fileId: string;
  /** File kind (document / sheet / etc.). */
  kind: FileKind;
  /** The version_id the comment/markup was authored against. NULL =
   *  pre-Epic-C (treat as current; no pill rendered). */
  pinnedVersionId: string | null;
  className?: string;
}

function formatVersionLabel(n: number): string {
  return n < 100 ? `V${String(n).padStart(2, '0')}` : `V${n}`;
}

export function StaleVersionPill({
  fileId,
  kind,
  pinnedVersionId,
  className,
}: StaleVersionPillProps) {
  const { t } = useTranslation();
  const { data: versions } = useFileVersions(fileId, kind);

  // No pin (legacy row) OR chain didn't load yet — render nothing.
  if (!pinnedVersionId || !versions || versions.length === 0) {
    return null;
  }

  const pinned = versions.find((v) => v.id === pinnedVersionId);
  const current = versions.find((v) => v.is_current);

  // Pinned is the current version → not stale, render nothing.
  if (!pinned || !current || pinned.id === current.id) {
    return null;
  }

  const pinnedLabel = formatVersionLabel(pinned.version_number);
  const currentLabel = formatVersionLabel(current.version_number);

  return (
    <span
      data-testid="stale-version-pill"
      className={clsx(
        'inline-flex items-center gap-1 h-5 px-1.5 rounded-md',
        'text-[10px] font-medium tabular-nums',
        'bg-semantic-warning/10 text-semantic-warning border border-semantic-warning/20',
        className,
      )}
      title={t('files.versions.stale_tooltip', {
        defaultValue:
          'This annotation was authored against {{pinned}} but the current revision is {{current}}.',
        pinned: pinnedLabel,
        current: currentLabel,
      })}
    >
      <AlertTriangle size={10} aria-hidden="true" />
      <span>
        {t('files.versions.stale_pill', {
          defaultValue: 'Drawn on {{pinned}} · current is {{current}}',
          pinned: pinnedLabel,
          current: currentLabel,
        })}
      </span>
    </span>
  );
}
