// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Dashboard widget — top N expiring / expired compliance docs for a project.

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ShieldCheck } from 'lucide-react';

import { Card, EmptyState } from '@/shared/ui';
import { listExpiringSoon } from '@/features/compliance-docs/api';
import { ComplianceStatusBadge } from '@/features/compliance-docs/ComplianceStatusBadge';

export interface ExpiringComplianceCardProps {
  projectId: string;
  limit?: number;
}

export function ExpiringComplianceCard({
  projectId,
  limit = 5,
}: ExpiringComplianceCardProps) {
  const { t } = useTranslation();
  const { data, isLoading } = useQuery({
    queryKey: ['compliance-docs-expiring', projectId, limit],
    queryFn: () => listExpiringSoon(projectId, limit),
    enabled: Boolean(projectId),
    staleTime: 30_000,
  });

  const rows = data ?? [];

  return (
    <Card padding="md" data-testid="expiring-compliance-card">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('compliance.widget.title', {
              defaultValue: 'Expiring compliance',
            })}
          </h3>
          <p className="text-xs text-content-tertiary">
            {t('compliance.widget.subtitle', {
              defaultValue: 'Insurance, permits, bonds nearing expiry.',
            })}
          </p>
        </div>
        <ShieldCheck size={18} className="text-content-tertiary" />
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-9 w-full animate-pulse rounded-md bg-surface-secondary"
            />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<ShieldCheck size={32} strokeWidth={1.5} />}
          title={t('compliance.widget.empty_title', {
            defaultValue: 'Nothing expiring soon',
          })}
          description={t('compliance.widget.empty_description', {
            defaultValue: 'All tracked documents are current.',
          })}
        />
      ) : (
        <ul className="divide-y divide-border-light">
          {rows.map((row) => (
            <li
              key={row.id}
              className="flex items-center justify-between gap-2 py-2 text-sm"
            >
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium text-content-primary">
                  {row.name}
                </div>
                <div className="text-xs text-content-tertiary tabular-nums">
                  {row.expires_at} ·{' '}
                  {t('compliance.widget.days_left', {
                    defaultValue: '{{n}}d left',
                    n: row.days_until_expiry,
                  })}
                </div>
              </div>
              <ComplianceStatusBadge status={row.status} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
