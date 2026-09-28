// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// ContractPunchItemsPanel - the open punch items attributed to this contract.
//
// A punch item may name the contract it belongs to. The ones that do are the
// snags this contract has to close before its retention comes back, so they sit
// here next to the release panel instead of only on the project's punch list.
// Items attributed to no contract stay the project's and are not listed: the
// panel shows what the contract owns, not everything the release may withhold
// for (the release panel says that itself).
//
// The punch list is its own module. When it is not installed, or the read
// fails, the panel renders nothing rather than an empty "no open items", which
// would claim something nobody checked.

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ListChecks } from 'lucide-react';

import { Badge } from '@/shared/ui';
import { fetchPunchItems } from '@/features/punchlist/api';

const SHOWN = 10;

export function ContractPunchItemsPanel({
  contractId,
  projectId,
}: {
  contractId: string;
  projectId: string;
}) {
  const { t } = useTranslation();
  const itemsQ = useQuery({
    queryKey: ['punchlist', 'contract-open', projectId, contractId],
    queryFn: () =>
      fetchPunchItems(projectId, { contract_id: contractId, open_only: true, limit: SHOWN }),
    enabled: !!projectId && !!contractId,
    retry: false,
    staleTime: 30_000,
  });

  if (!itemsQ.data) return null;
  const { items, total } = itemsQ.data;

  return (
    <div className="rounded-lg border border-border-light">
      <header className="flex items-center justify-between gap-2 border-b border-border-light px-4 py-2.5">
        <div className="flex items-center gap-2">
          <ListChecks size={15} className="text-content-tertiary" />
          <span className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
            {t('contracts.punch_items.title', { defaultValue: 'Open punch items' })}
          </span>
          {total > 0 && <Badge variant="warning">{total}</Badge>}
        </div>
        <Link to="/punchlist" className="text-xs text-oe-blue hover:underline">
          {t('contracts.punch_items.go_to_list', { defaultValue: 'Go to the punch list' })}
        </Link>
      </header>
      {items.length === 0 ? (
        <p className="px-4 py-3 text-xs text-content-tertiary">
          {t('contracts.punch_items.none', {
            defaultValue: 'No open punch items are attributed to this contract.',
          })}
        </p>
      ) : (
        <ul className="divide-y divide-border-light">
          {items.map((item) => (
            <li key={item.id} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
              <span className="min-w-0 truncate text-content-primary">{item.title}</span>
              <span className="shrink-0 text-xs text-content-tertiary">
                {t(`punch.status_${item.status}`, { defaultValue: item.status })}
              </span>
            </li>
          ))}
        </ul>
      )}
      {total > items.length && (
        <p className="border-t border-border-light px-4 py-2 text-xs text-content-tertiary">
          {t('contracts.punch_items.more', {
            defaultValue: '{{count}} more on the punch list.',
            count: total - items.length,
          })}
        </p>
      )}
    </div>
  );
}
