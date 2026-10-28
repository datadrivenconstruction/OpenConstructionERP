// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Compact dropdown listing every version in a file's chain with a
 * "Make current" action on historical rows. */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, History, Loader2, RotateCcw } from 'lucide-react';
import clsx from 'clsx';
import { useToastStore } from '@/stores/useToastStore';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useFileVersions, useRestoreVersion } from './hooks';
import { VersionBadge } from './VersionBadge';
import type { FileKind, FileVersionResponse } from './types';

interface VersionDropdownProps {
  fileId: string;
  kind: FileKind;
  /** Fires after a successful restore; carries the now-current version id. */
  onChange?: (versionId: string) => void;
  className?: string;
}

export function VersionDropdown({
  fileId,
  kind,
  onChange,
  className,
}: VersionDropdownProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const addToast = useToastStore((s) => s.addToast);
  const { data: versions, isLoading, isError } = useFileVersions(fileId, kind);
  const restore = useRestoreVersion(fileId, kind);

  const current = versions?.find((v) => v.is_current);
  const total = versions?.length ?? 0;

  const handleRestore = (row: FileVersionResponse) => {
    if (restore.isPending) return;
    restore.mutate(row.id, {
      onSuccess: (restored) => {
        addToast({
          type: 'success',
          title: t('files.versions.restored_title', {
            defaultValue: 'Restored to V{{n}}',
            n: String(restored.version_number).padStart(2, '0'),
          }),
        });
        onChange?.(restored.id);
        setOpen(false);
      },
      onError: (err: Error) => {
        addToast({
          type: 'error',
          title: t('files.versions.restore_failed', {
            defaultValue: 'Could not restore version',
          }),
          message: err.message,
        });
      },
    });
  };

  if (isError) {
    return (
      <div
        className={clsx(
          'inline-flex items-center gap-1.5 px-2 h-7 rounded-md text-[11px] text-semantic-error border border-semantic-error/20 bg-semantic-error/5',
          className,
        )}
      >
        <History size={12} />
        {t('files.versions.load_failed', { defaultValue: 'Versions unavailable' })}
      </div>
    );
  }

  return (
    <div className={clsx('relative inline-block', className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={isLoading || total === 0}
        data-testid="version-dropdown-button"
        className={clsx(
          'inline-flex items-center gap-1.5 h-7 px-2 rounded-md',
          'text-[11px] font-medium border border-border-light',
          'text-content-secondary hover:bg-surface-secondary',
          'disabled:opacity-50 disabled:cursor-not-allowed',
        )}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        {isLoading ? (
          <Loader2 size={12} className="animate-spin" />
        ) : (
          <History size={12} />
        )}
        {current ? (
          <VersionBadge
            versionNumber={current.version_number}
            isCurrent
            className="!h-4 !px-1"
          />
        ) : (
          <span>{t('files.versions.no_history', { defaultValue: 'No history' })}</span>
        )}
        {total > 1 && (
          <span className="text-content-tertiary tabular-nums">
            ({total})
          </span>
        )}
        <ChevronDown size={11} className={clsx('transition-transform', open && 'rotate-180')} />
      </button>

      {open && versions && versions.length > 0 && (
        <div
          role="listbox"
          aria-label={t('files.versions.dropdown_aria', { defaultValue: 'File version history' })}
          className={clsx(
            'absolute right-0 mt-1 w-72 max-h-80 overflow-y-auto',
            'rounded-lg border border-border-light bg-surface-elevated shadow-lg z-20',
          )}
        >
          <ul className="divide-y divide-border-light">
            {versions.map((v) => (
              <li
                key={v.id}
                className="flex items-start gap-2 px-3 py-2 text-xs"
                data-testid={`version-row-${v.version_number}`}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <VersionBadge
                      versionNumber={v.version_number}
                      isCurrent={v.is_current}
                    />
                    <DateDisplay
                      value={v.uploaded_at}
                      format="datetime"
                      className="text-[10px] text-content-tertiary"
                    />
                  </div>
                  {v.notes && (
                    <p className="mt-1 text-[11px] text-content-secondary line-clamp-2">
                      {v.notes}
                    </p>
                  )}
                </div>
                {!v.is_current && (
                  <button
                    type="button"
                    onClick={() => handleRestore(v)}
                    disabled={restore.isPending}
                    data-testid={`version-restore-${v.version_number}`}
                    className={clsx(
                      'inline-flex items-center gap-1 h-6 px-1.5 rounded text-[10px] font-medium',
                      'text-oe-blue hover:bg-oe-blue/10',
                      'disabled:opacity-50 disabled:cursor-not-allowed',
                    )}
                    title={t('files.versions.make_current_title', {
                      defaultValue: 'Promote this version to current',
                    })}
                  >
                    {restore.isPending ? (
                      <Loader2 size={10} className="animate-spin" />
                    ) : (
                      <RotateCcw size={10} />
                    )}
                    {t('files.versions.make_current', { defaultValue: 'Make current' })}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
