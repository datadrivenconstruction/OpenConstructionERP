// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * One line that answers "how much is waiting on this phone": count, size and the
 * age of the oldest item, plus a warning when the device is nearly full.
 * Photos are the bulk, so their bytes are read from the raised-issue store.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { HardDrive } from 'lucide-react';
import type { QueuedOp } from '@/shared/lib/offline';
import {
  formatBytes,
  quotaLevel,
  readStorageEstimate,
  requestPersistentStorage,
  summariseBacklog,
  type QuotaLevel,
} from '@/shared/lib/offline/storageQuota';
import { pendingPhotoRecords } from './raisedIssuesStore';

export interface StorageMeterProps {
  ops: readonly QueuedOp[];
  now: number;
}

export function StorageMeter({ ops, now }: StorageMeterProps) {
  const { t } = useTranslation();
  const [photoBytes, setPhotoBytes] = useState(0);
  const [level, setLevel] = useState<QuotaLevel>('ok');

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const photos = await pendingPhotoRecords();
        const total = photos.reduce((sum, r) => sum + (r.photo?.size ?? 0), 0);
        const level = quotaLevel(await readStorageEstimate());
        if (!alive) return;
        setPhotoBytes(total);
        setLevel(level);
      } catch {
        /* the meter is advice; a storage error must not break the panel */
      }
    })();
    // Ask the browser not to evict what is waiting; harmless when refused.
    void requestPersistentStorage();
    return () => {
      alive = false;
    };
  }, [ops.length]);

  const backlog = summariseBacklog(ops, now, photoBytes);
  if (backlog.count === 0 && level === 'ok') return null;

  return (
    <div data-testid="storage-meter" data-level={level} className="flex flex-col gap-1">
      {backlog.count > 0 && (
        <p className="flex items-center gap-1.5 text-xs text-slate-600">
          <HardDrive size={14} aria-hidden="true" />
          {t('field.quota.summary', {
            count: backlog.count,
            size: formatBytes(backlog.bytes),
            days: backlog.oldestDays,
            defaultValue: 'Waiting: {{count}} · {{size}} · oldest {{days}} d',
          })}
        </p>
      )}
      {level !== 'ok' && (
        <p role="alert" className={`text-xs font-medium ${level === 'full' ? 'text-rose-600' : 'text-amber-700'}`}>
          {t('field.quota.warning', {
            defaultValue: 'Phone storage is almost full. Sync soon so photos are not lost.',
          })}
        </p>
      )}
    </div>
  );
}

export default StorageMeter;
