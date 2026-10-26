// Subcontractor insurance status​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Insurance register of one subcontractor: the overall verdict (compliant,
 * expiring, non-compliant) and each certificate with its alert bucket, the
 * mandatory flag, policy number and cover. Reads
 * GET /subcontractors/{id}/insurance-status.
 */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Badge, type BadgeVariant } from '@/shared/ui';
import {
  getSubcontractorInsuranceStatus,
  type InsuranceBucket,
  type InsuranceCertificateView,
  type InsuranceStatus,
} from './api';
import { certTypeLabel, describeComplianceReasons } from './complianceReasons';

const STATUS_VARIANT: Record<InsuranceStatus, BadgeVariant> = {
  compliant: 'success',
  expiring: 'warning',
  non_compliant: 'error',
};

const BUCKET_VARIANT: Record<InsuranceBucket, BadgeVariant> = {
  valid: 'success',
  due_30: 'warning',
  due_14: 'warning',
  due_0: 'error',
  expired: 'error',
  revoked: 'error',
};

export function InsuranceStatusBadge({ status }: { status: InsuranceStatus }) {
  const { t } = useTranslation();
  const label: Record<InsuranceStatus, string> = {
    compliant: t('subcontractors.insurance.status.compliant', { defaultValue: 'Insurance compliant' }),
    expiring: t('subcontractors.insurance.status.expiring', { defaultValue: 'Insurance expiring' }),
    non_compliant: t('subcontractors.insurance.status.non_compliant', { defaultValue: 'Insurance non-compliant' }),
  };
  return (
    <Badge variant={STATUS_VARIANT[status] ?? 'neutral'} size="sm" dot>
      <span data-testid="insurance-status-badge" data-status={status}>
        {label[status] ?? status}
      </span>
    </Badge>
  );
}

export function InsuranceBucketBadge({ bucket }: { bucket: InsuranceBucket }) {
  const { t } = useTranslation();
  const label: Record<InsuranceBucket, string> = {
    valid: t('subcontractors.insurance.bucket.valid', { defaultValue: 'Valid' }),
    due_30: t('subcontractors.insurance.bucket.due_30', { defaultValue: 'Due in 30 days' }),
    due_14: t('subcontractors.insurance.bucket.due_14', { defaultValue: 'Due in 14 days' }),
    due_0: t('subcontractors.insurance.bucket.due_0', { defaultValue: 'Expires today' }),
    expired: t('subcontractors.insurance.bucket.expired', { defaultValue: 'Expired' }),
    revoked: t('subcontractors.insurance.bucket.revoked', { defaultValue: 'Revoked' }),
  };
  return (
    <Badge variant={BUCKET_VARIANT[bucket] ?? 'neutral'} size="sm">
      {label[bucket] ?? bucket}
    </Badge>
  );
}

export function InsuranceCertificateRow({ cert }: { cert: InsuranceCertificateView }) {
  const { t } = useTranslation();
  return (
    <li
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-border-light px-2.5 py-1.5 text-xs"
      data-testid="insurance-cert-row"
      data-bucket={cert.bucket}
    >
      <span className="font-medium text-content-primary">{certTypeLabel(cert.cert_type, t)}</span>
      <InsuranceBucketBadge bucket={cert.bucket} />
      {cert.is_mandatory && (
        <Badge variant="blue" size="sm">
          {t('subcontractors.insurance.mandatory', { defaultValue: 'Mandatory' })}
        </Badge>
      )}
      {cert.valid_until && (
        <span className="text-content-secondary">
          {t('subcontractors.insurance.valid_until', { defaultValue: 'Valid until {{date}}', date: cert.valid_until })}
        </span>
      )}
      {cert.policy_number && (
        <span className="text-content-tertiary">
          {t('subcontractors.insurance.policy', { defaultValue: 'Policy {{number}}', number: cert.policy_number })}
        </span>
      )}
      {cert.coverage_amount && (
        <span className="text-content-tertiary">
          {t('subcontractors.insurance.coverage', {
            defaultValue: 'Cover {{amount}} {{currency}}',
            amount: cert.coverage_amount,
            currency: cert.coverage_currency ?? '',
          })}
        </span>
      )}
    </li>
  );
}

export function InsuranceStatusPanel({ subcontractorId }: { subcontractorId: string }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['subcontractors', 'insuranceStatus', subcontractorId],
    queryFn: () => getSubcontractorInsuranceStatus(subcontractorId),
    enabled: !!subcontractorId,
    retry: false,
  });
  const data = q.data;
  if (!data || !Array.isArray(data.certificates)) return null;
  return (
    <div className="space-y-2" data-testid="insurance-status-panel">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
          {t('subcontractors.insurance.title', { defaultValue: 'Insurance' })}
        </p>
        <InsuranceStatusBadge status={data.status} />
        {data.payment_blocked && (
          <Badge variant="error" size="sm">
            {t('subcontractors.insurance.payments_held', { defaultValue: 'Payments held' })}
          </Badge>
        )}
      </div>
      {data.reasons.length > 0 && (
        <p className="text-xs text-semantic-error">{describeComplianceReasons(data.reasons, t)}</p>
      )}
      {data.certificates.length === 0 ? (
        <p className="text-xs text-content-tertiary">
          {t('subcontractors.insurance.none', { defaultValue: 'No insurance certificates on file.' })}
        </p>
      ) : (
        <ul className="space-y-1">
          {data.certificates.map((c) => (
            <InsuranceCertificateRow key={c.id} cert={c} />
          ))}
        </ul>
      )}
    </div>
  );
}
