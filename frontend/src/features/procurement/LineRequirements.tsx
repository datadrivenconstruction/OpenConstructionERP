// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// LineRequirements - what a delivery of one order line must arrive with.
//
// EN 10204 has the type of inspection document agreed when the material is
// ordered, so the requirement sits on the order line: a certificate type from
// the catalogue (GET /v1/procurement/certificate-types/) and whether the
// delivery gets an incoming inspection. The receipt is then checked against it.

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/shared/lib/api';
import type { CertificateType } from './ConfirmReceiptDialog';

/** The part of an order-form line the requirements live in. */
export interface RequirementLine {
  id?: string;
  required_certificate_type?: string;
  requires_inspection?: boolean;
}

/**
 * Lines whose delivery requirements changed against the prefill. A requirement
 * moves no money, so on an approved or issued order it is saved line by line
 * through its own endpoint instead of with the locked figures.
 */
export function changedRequirements(
  items: RequirementLine[],
  base: RequirementLine[],
): { id: string; required_certificate_type: string; requires_inspection: boolean }[] {
  const before = new Map(base.filter((li) => li.id).map((li) => [li.id!, li]));
  const out: { id: string; required_certificate_type: string; requires_inspection: boolean }[] = [];
  for (const li of items) {
    const old = li.id ? before.get(li.id) : undefined;
    if (!old) continue;
    const cert = li.required_certificate_type ?? '';
    const insp = Boolean(li.requires_inspection);
    if (cert !== (old.required_certificate_type ?? '') || insp !== Boolean(old.requires_inspection)) {
      out.push({ id: li.id!, required_certificate_type: cert, requires_inspection: insp });
    }
  }
  return out;
}

interface Props {
  line: number;
  certificateType: string;
  requiresInspection: boolean;
  disabled?: boolean;
  onChange: (certificateType: string, requiresInspection: boolean) => void;
}

export function LineRequirements({ line, certificateType, requiresInspection, disabled, onChange }: Props) {
  const { t } = useTranslation();
  const types = useQuery({
    queryKey: ['procurement-certificate-types'],
    queryFn: () => apiGet<CertificateType[]>('/v1/procurement/certificate-types/'),
    staleTime: 60 * 60 * 1000,
  });
  const list = Array.isArray(types.data) ? types.data : [];

  return (
    <div className="flex flex-wrap items-center gap-2 text-2xs text-content-tertiary">
      <select
        value={certificateType}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value, requiresInspection)}
        aria-label={t('procurement.item_certificate_for', {
          defaultValue: 'Required certificate for line {{line}}',
          line,
        })}
        className="h-7 rounded-md border border-border bg-surface-primary px-1.5 text-2xs text-content-secondary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
      >
        <option value="">{t('procurement.item_no_certificate', { defaultValue: 'No certificate required' })}</option>
        {list.map((tp) => (
          <option key={tp.code} value={tp.code}>
            {tp.label}
          </option>
        ))}
        {certificateType && !list.some((tp) => tp.code === certificateType) && (
          <option value={certificateType}>{certificateType}</option>
        )}
      </select>
      <label className="inline-flex items-center gap-1">
        <input
          type="checkbox"
          checked={requiresInspection}
          disabled={disabled}
          onChange={(e) => onChange(certificateType, e.target.checked)}
        />
        {t('procurement.item_requires_inspection', { defaultValue: 'Incoming inspection' })}
      </label>
    </div>
  );
}
