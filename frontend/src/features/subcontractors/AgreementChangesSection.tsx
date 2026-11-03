/** "Changes" section of a subcontract agreement: its changes, each linking back to the owner VO/CO. */
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Badge } from '@/shared/ui';
import type { BadgeVariant } from '@/shared/ui/Badge';
import { fmtCurrency } from '@/shared/lib/formatters';
import { ownerChangeHref, useAgreementChanges, type SubChangeStatus } from './changesApi';

const STATUS_VARIANT: Record<SubChangeStatus, BadgeVariant> = {
  draft: 'neutral',
  submitted: 'blue',
  approved: 'success',
  rejected: 'error',
  withdrawn: 'warning',
};

export function AgreementChangesSection({ agreementId }: { agreementId: string }) {
  const { t } = useTranslation();
  const q = useAgreementChanges(agreementId);
  const changes = q.data ?? [];
  if (changes.length === 0) return null;
  return (
    <div className="mt-3 border-t border-border-light pt-3 space-y-1.5" data-testid="agreement-changes">
      <div className="text-xs font-medium text-content-secondary">
        {t('subcontractors.changes_section', { defaultValue: 'Changes' })}
      </div>
      {changes.map((c) => {
        const href = ownerChangeHref(c.owner_change_type, c.owner_change_id);
        return (
          <div key={c.id} className="flex items-center justify-between gap-2 text-xs">
            <span className="min-w-0 truncate text-content-secondary">
              <span className="font-mono">{c.code}</span> {c.title}
            </span>
            <span className="flex shrink-0 items-center gap-2">
              <span className="tabular-nums">{fmtCurrency(c.amount, c.currency)}</span>
              <Badge variant={STATUS_VARIANT[c.status]} size="sm" dot>
                {t(`subcontractors.change_status_${c.status}`, { defaultValue: c.status })}
              </Badge>
              {href && (
                <Link to={href} className="text-oe-blue hover:underline">
                  {c.owner_change_type === 'variation_order'
                    ? t('subcontractors.changes_open_vo', { defaultValue: 'Variation order' })
                    : t('subcontractors.changes_open_co', { defaultValue: 'Change order' })}
                </Link>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}
