// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Add to claim" on a sensor alert: pick the window (an hour either side by default),
 * file the readings as a hashed CSV and PDF in the project documents.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { FilePlus2 } from 'lucide-react';
import { Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { fileSensorEvidence } from '../evidenceApi';
import { shortHash, windowAround, windowIsValid } from '../evidenceData';
import { isoFromLocal, localDateTimeValue } from '../sensorData';

const FIELD = 'h-8 rounded-lg border border-border-light bg-surface-primary px-2 text-xs text-content-primary';

export function AddToClaimButton({ alertId, deviceId, raisedAt }: { alertId: string; deviceId: string; raisedAt: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [open, setOpen] = useState(false);
  const initial = windowAround(raisedAt);
  const [from, setFrom] = useState(() => (initial ? localDateTimeValue(new Date(initial.from)) : ''));
  const [to, setTo] = useState(() => (initial ? localDateTimeValue(new Date(initial.to)) : ''));
  const [claimRef, setClaimRef] = useState('');
  const fromIso = isoFromLocal(from);
  const toIso = isoFromLocal(to);
  const valid = windowIsValid(fromIso, toIso);

  const mut = useMutation({
    mutationFn: () =>
      fileSensorEvidence(deviceId, { from: fromIso ?? '', to: toIso ?? '', claimRef: claimRef.trim(), alertId }),
    onSuccess: (r) => {
      setOpen(false);
      qc.invalidateQueries({ queryKey: ['site-sensors'] });
      addToast({
        type: 'success',
        title: t('site_sensors.evidence.filed', { defaultValue: 'Evidence filed in the project documents' }),
        message: t('site_sensors.evidence.filed_hint', {
          defaultValue: 'SHA-256 {{hash}}. CSV and PDF are in the folder Monitoring evidence.',
          hash: shortHash(r.csv_sha256),
        }),
      });
    },
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  if (!open) {
    return (
      <Button variant="secondary" size="sm" icon={<FilePlus2 size={14} />} onClick={() => setOpen(true)}>
        {t('site_sensors.evidence.add_to_claim', { defaultValue: 'Add to claim' })}
      </Button>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="text-xs text-content-secondary">
        {t('site_sensors.evidence.from', { defaultValue: 'From' })}
        <input type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} className={`${FIELD} ml-1`} />
      </label>
      <label className="text-xs text-content-secondary">
        {t('site_sensors.evidence.to', { defaultValue: 'To' })}
        <input type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} className={`${FIELD} ml-1`} />
      </label>
      <input
        type="text"
        value={claimRef}
        maxLength={200}
        onChange={(e) => setClaimRef(e.target.value)}
        placeholder={t('site_sensors.evidence.claim_ref', { defaultValue: 'Claim reference (optional)' })}
        aria-label={t('site_sensors.evidence.claim_ref', { defaultValue: 'Claim reference (optional)' })}
        className={`${FIELD} w-48`}
      />
      <Button variant="primary" size="sm" disabled={!valid} loading={mut.isPending} onClick={() => mut.mutate()}>
        {t('site_sensors.evidence.file', { defaultValue: 'File evidence' })}
      </Button>
      {!valid && (
        <span className="text-xs text-semantic-error">
          {t('site_sensors.evidence.bad_window', { defaultValue: 'Choose a start before the end, within one year.' })}
        </span>
      )}
    </div>
  );
}
