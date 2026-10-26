// Project insurance dashboard​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Insurance compliance of every subcontractor on the active project: a count
 * per status, the certificates by alert bucket, and the pay applications the
 * insurance gate holds or has released.
 */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Badge, Card } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import {
  getProjectInsurance,
  type InsuranceBucket,
  type InsuranceStatus,
  type ProjectInsuranceDashboard as DashboardData,
} from './api';
import { describeComplianceReasons } from './complianceReasons';
import { InsuranceBucketBadge, InsuranceStatusBadge } from './InsuranceStatusPanel';

const STATUSES: InsuranceStatus[] = ['compliant', 'expiring', 'non_compliant'];
const BUCKETS: InsuranceBucket[] = ['valid', 'due_30', 'due_14', 'due_0', 'expired', 'revoked'];

export function ProjectInsuranceView({ data }: { data: DashboardData }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-4">
        {STATUSES.map((s) => (
          <div key={s} className="flex items-center gap-2" data-testid={`insurance-count-${s}`}>
            <span className="text-xl font-semibold tabular-nums text-content-primary">{data.counts[s] ?? 0}</span>
            <InsuranceStatusBadge status={s} />
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-3 text-xs">
        {BUCKETS.map((b) => (
          <span key={b} className="flex items-center gap-1" data-testid={`insurance-bucket-${b}`}>
            <InsuranceBucketBadge bucket={b} />
            <span className="tabular-nums text-content-secondary">{data.certificate_buckets[b] ?? 0}</span>
          </span>
        ))}
      </div>

      {data.subcontractors.length > 0 && (
        <ul className="space-y-1">
          {data.subcontractors
            .filter((s) => s.status !== 'compliant')
            .map((s) => (
              <li key={s.subcontractor_id} className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-medium text-content-primary">{s.name}</span>
                <InsuranceStatusBadge status={s.status} />
                {s.reasons.length > 0 && (
                  <span className="text-content-tertiary">{describeComplianceReasons(s.reasons, t)}</span>
                )}
              </li>
            ))}
        </ul>
      )}

      <div>
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
          {t('subcontractors.insurance.gated_payments', { defaultValue: 'Pay applications held by insurance' })}
        </p>
        {data.gated_payments.length === 0 ? (
          <p className="text-xs text-content-tertiary">
            {t('subcontractors.insurance.no_gated', { defaultValue: 'No pay application is held by the insurance gate.' })}
          </p>
        ) : (
          <ul className="space-y-1">
            {data.gated_payments.map((p) => (
              <li
                key={p.payment_application_id}
                className="flex flex-wrap items-center gap-2 rounded-md border border-border-light px-2.5 py-1.5 text-xs"
                data-testid="insurance-gated-payment"
              >
                <span className="font-medium text-content-primary">{p.application_number}</span>
                <MoneyDisplay amount={p.net_amount} currency={p.currency} />
                <Badge variant={p.blocked ? 'error' : 'success'} size="sm">
                  {p.blocked
                    ? t('subcontractors.insurance.held', { defaultValue: 'Held' })
                    : t('subcontractors.insurance.overridden', { defaultValue: 'Overridden' })}
                </Badge>
                {p.reasons.length > 0 && (
                  <span className="text-content-tertiary">{describeComplianceReasons(p.reasons, t)}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export function ProjectInsuranceDashboard() {
  const { t } = useTranslation();
  const projectId = useActiveProjectId();
  const q = useQuery({
    queryKey: ['subcontractors', 'insuranceProject', projectId],
    queryFn: () => getProjectInsurance(projectId as string),
    enabled: !!projectId,
    retry: false,
  });
  const data = q.data;
  if (!projectId || !data || !data.counts) return null;
  return (
    <Card padding="md">
      <h3 className="mb-3 text-sm font-semibold text-content-primary">
        {t('subcontractors.insurance.project_title', { defaultValue: 'Insurance compliance on this project' })}
      </h3>
      <ProjectInsuranceView data={data} />
    </Card>
  );
}
