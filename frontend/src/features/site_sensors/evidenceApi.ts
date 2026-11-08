// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Sensor evidence API: POST /api/v1/site_sensors/devices/{id}/evidence. */
import { apiPost } from '@/shared/lib/api';

export interface EvidenceFiled {
  device_id: string;
  csv_document_id: string;
  pdf_document_id: string;
  csv_sha256: string;
  readings: number;
}

export const fileSensorEvidence = (
  deviceId: string,
  opts: { from: string; to: string; claimRef?: string; alertId?: string },
) => {
  const q = new URLSearchParams({ from: opts.from, to: opts.to });
  if (opts.claimRef) q.set('claim_ref', opts.claimRef);
  if (opts.alertId) q.set('alert_id', opts.alertId);
  return apiPost<EvidenceFiled, Record<string, never>>(
    `/v1/site_sensors/devices/${encodeURIComponent(deviceId)}/evidence?${q.toString()}`,
    {},
  );
};
