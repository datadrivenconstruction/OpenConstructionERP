// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Two small pieces shared by the offline-capable registers​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠:
 *  - `SavedOnDeviceBadge`  the per-row "saved on this device" marker
 *  - `MergeHistoryList`    who merged what, from GET .../merge-audit/
 */

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { GitMerge, HardDrive } from 'lucide-react';
import { fetchMergeAudit } from '@/shared/lib/offline/recordSync';
import { isLocalId, type OfflineEntityKind } from '@/shared/lib/offline/offlineStore';

export function SavedOnDeviceBadge({ flag }: { flag?: 'new' | 'edited' | null }) {
  const { t } = useTranslation();
  if (!flag) return null;
  return (
    <span
      data-testid="saved-on-device"
      data-flag={flag}
      title={t('offline_sync.saved_on_device_hint', {
        defaultValue: 'Not on the server yet. It uploads when you are back online.',
      })}
      className="inline-flex shrink-0 items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800"
    >
      <HardDrive size={11} aria-hidden="true" />
      {t('offline_sync.saved_on_device', { defaultValue: 'Saved on this device' })}
    </span>
  );
}

export function MergeHistoryList({ kind, id }: { kind: OfflineEntityKind; id: string }) {
  const { t } = useTranslation();
  const { data = [] } = useQuery({
    queryKey: ['merge-audit', kind, id],
    queryFn: () => fetchMergeAudit(kind, id),
    enabled: !!id && !isLocalId(id),
    retry: false,
    staleTime: 30_000,
  });
  if (data.length === 0) return null;
  return (
    <section data-testid="merge-history" className="space-y-1">
      <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase text-content-tertiary">
        <GitMerge size={12} aria-hidden="true" />
        {t('offline_sync.merge_history', { defaultValue: 'Merge history' })}
      </h4>
      <ul className="space-y-1">
        {data.slice(0, 10).map((row, i) => {
          const fields = Object.keys(row.resolutions ?? row.fields ?? {});
          return (
            <li
              key={row.id ?? i}
              className="rounded bg-surface-secondary px-2 py-1.5 text-xs text-content-secondary"
            >
              <span className="font-medium text-content-primary">
                {row.created_at ? new Date(row.created_at).toLocaleString() : ''}
              </span>
              {row.base_version != null && row.against_version != null && (
                <span className="ml-2">
                  {t('offline_sync.merge_versions', {
                    from: row.base_version,
                    to: row.against_version,
                    defaultValue: 'v{{from}} onto v{{to}}',
                  })}
                </span>
              )}
              {fields.length > 0 && <span className="ml-2">{fields.join(', ')}</span>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
