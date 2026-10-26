// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Words for the codes the compliance gates answer with.
 *
 * The award and payment gates explain a refusal with flat codes such as
 * `missing_required_certificate:insurance` or
 * `expired_required_certificate:license:2026-08-31`. They are stable for
 * programs and were printed to people as they came, colon and all. Every code
 * the backend writes has a sentence here; a code it starts writing later reads
 * as a general "requirement not met" rather than as raw text.
 */
import type { TFunction } from 'i18next';
import { ApiError, getErrorMessage } from '@/shared/lib/api';

const CERT_TYPES = new Set([
  'insurance',
  'license',
  'iso',
  'safety',
  'bond',
  'public_liability',
  'employers_liability',
  'professional_indemnity',
  'contractors_all_risk',
  'workers_compensation',
  'motor_vehicle',
  'product_liability',
  'plant_equipment',
  'environmental_liability',
  'cyber_liability',
]);

const CERT_TYPE_EN: Record<string, string> = {
  public_liability: 'Public liability',
  employers_liability: 'Employers liability',
  professional_indemnity: 'Professional indemnity',
  contractors_all_risk: 'Contractors all risk',
  workers_compensation: 'Workers compensation',
  motor_vehicle: 'Motor vehicle',
  product_liability: 'Product liability',
  plant_equipment: 'Plant and equipment',
  environmental_liability: 'Environmental liability',
  cyber_liability: 'Cyber liability',
};

/** A certificate type in the reader's language, or the stored type as written. */
export function certTypeLabel(certType: string, t: TFunction): string {
  if (!CERT_TYPES.has(certType)) return certType;
  const fallback = CERT_TYPE_EN[certType];
  const key = `subcontractors.cert_type.${certType}`;
  return fallback ? t(key, { defaultValue: fallback }) : t(key);
}

/** One gate reason code as a sentence. */
export function describeComplianceReason(code: string, t: TFunction): string {
  const [kind, subject = '', date = ''] = code.split(':');
  const document = certTypeLabel(subject, t);
  switch (kind) {
    case 'subcontractor_blocked':
      return t('subcontractors.reason_code.subcontractor_blocked');
    case 'prequalification_rejected':
      return t('subcontractors.reason_code.prequalification_rejected');
    case 'prequalification_suspended':
      return t('subcontractors.reason_code.prequalification_suspended');
    case 'missing_required_certificate':
      return t('subcontractors.reason_code.missing_certificate', { document });
    case 'expired_or_revoked_certificate':
      return t('subcontractors.reason_code.expired_or_revoked_certificate', { document });
    case 'revoked_required_certificate':
      return t('subcontractors.reason_code.revoked_certificate', { document });
    case 'expired_required_certificate':
      return t('subcontractors.reason_code.expired_certificate', { document, date });
    case 'expired_insurance_on_record':
      // The date sits where the document would: the record names no type.
      return t('subcontractors.reason_code.expired_insurance_on_record', { date: subject });
    case 'expired_mandatory_certificate':
      return t('subcontractors.reason_code.expired_mandatory_certificate', {
        defaultValue: 'Mandatory insurance certificate {{document}} expired on {{date}}',
        document,
        date,
      });
    case 'revoked_mandatory_certificate':
      return t('subcontractors.reason_code.revoked_mandatory_certificate', {
        defaultValue: 'Mandatory insurance certificate {{document}} was revoked',
        document,
      });
    case 'missing_waiver':
      return t('subcontractors.reason_code.missing_waiver');
    case 'waiver_amount_mismatch':
      return t('subcontractors.reason_code.waiver_amount_mismatch');
    default:
      return t('subcontractors.reason_code.unknown');
  }
}

/** Every reason as one line, in the order the gate gave them. */
export function describeComplianceReasons(codes: readonly string[], t: TFunction): string {
  return codes.map((code) => describeComplianceReason(code, t)).join('; ');
}

/**
 * A refused request in the reader's words.
 *
 * The award and payment gates answer 409 with `{code, reasons}`; the reasons
 * are what the person has to fix, so they are spelled out. Anything else is
 * the ordinary error message.
 */
/** The 409 code the payment steps answer with while mandatory insurance has lapsed. */
export function isInsuranceBlock(err: unknown): boolean {
  if (!(err instanceof ApiError)) return false;
  const detail = (err.body as { detail?: { code?: string } } | null)?.detail;
  return detail?.code === 'insurance_compliance_blocked';
}

export function gateErrorMessage(err: unknown, t: TFunction): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: { reasons?: unknown } } | null;
    const reasons = body?.detail?.reasons;
    if (Array.isArray(reasons) && reasons.length > 0 && reasons.every((r) => typeof r === 'string')) {
      return describeComplianceReasons(reasons as string[], t);
    }
  }
  return getErrorMessage(err);
}
