/**
 * The records behind one commitment grid row: the issued order items and live
 * subcontract lines on the position's cost line. Their figures add up to the
 * row, so every committed and received number can be traced to a document.
 */
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Badge, RecoveryCard, Skeleton } from '@/shared/ui';
import { fmtNumber } from '@/shared/lib/formatters';
import { formatCurrency, toNum } from '@/shared/lib/money';
import { fetchCommitmentSources, type CommitmentSource } from './api';

function qty(value: string): string {
  const n = toNum(value);
  return Number.isFinite(n) ? fmtNumber(n, 3) : value;
}

function sourceHref(src: CommitmentSource): string {
  return src.kind === 'purchase_order'
    ? `/procurement?po=${encodeURIComponent(src.document_id)}`
    : `/contracts/${encodeURIComponent(src.document_id)}`;
}

export function CommitmentSources({
  projectId,
  positionId,
  onCostSpine,
}: {
  projectId: string;
  positionId: string;
  onCostSpine: boolean;
}) {
  const { t } = useTranslation();
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['commitment-sources', projectId, positionId],
    queryFn: () => fetchCommitmentSources(projectId, positionId),
    enabled: onCostSpine,
  });

  if (!onCostSpine) {
    return (
      <p className="text-xs text-content-secondary">
        {t('commercial_control.sources_off_spine', {
          defaultValue: 'This line has no cost line, so no order or subcontract can count against it. Generate the cost lines from the bill on the Cost model page.',
        })}
      </p>
    );
  }
  if (isLoading) return <Skeleton className="h-10 w-full" />;
  if (isError) return <RecoveryCard error={error} onRetry={() => refetch()} />;
  const currency = data?.currency ?? '';
  const sources = data?.sources ?? [];
  if (sources.length === 0) {
    return (
      <p className="text-xs text-content-secondary">
        {t('commercial_control.sources_empty', {
          defaultValue: 'No issued purchase order or live subcontract on this line yet. Raise one from Procurement or Contracts.',
        })}{' '}
        <Link className="underline" to="/procurement">
          {t('commercial_control.sources_open_procurement', { defaultValue: 'Open Procurement' })}
        </Link>
      </p>
    );
  }
  return (
    <table className="w-full text-xs" data-testid="commitment-sources">
      <thead>
        <tr className="text-left text-content-tertiary">
          <th className="pr-3">{t('commercial_control.src_document', { defaultValue: 'Document' })}</th>
          <th className="pr-3">{t('commercial_control.src_line', { defaultValue: 'Line' })}</th>
          <th className="pr-3">{t('commercial_control.src_status', { defaultValue: 'Status' })}</th>
          <th className="pr-3 text-right">{t('commercial_control.col_committed_qty', { defaultValue: 'Committed qty' })}</th>
          <th className="pr-3 text-right">{t('commercial_control.col_committed', { defaultValue: 'Committed' })}</th>
          <th className="pr-3 text-right">{t('commercial_control.col_received_qty', { defaultValue: 'Received qty' })}</th>
          <th className="pr-3 text-right">{t('commercial_control.col_received', { defaultValue: 'Received' })}</th>
        </tr>
      </thead>
      <tbody>
        {sources.map((src) => (
          <tr key={src.line_id}>
            <td className="pr-3">
              <div className="flex items-center gap-1.5">
                <Badge variant="neutral">
                  {src.kind === 'purchase_order'
                    ? t('commercial_control.src_kind_po', { defaultValue: 'Order' })
                    : t('commercial_control.src_kind_subcontract', { defaultValue: 'Subcontract' })}
                </Badge>
                <Link className="font-medium underline" to={sourceHref(src)}>
                  {src.document_number || src.document_title || '-'}
                </Link>
              </div>
            </td>
            <td className="max-w-[16rem] truncate pr-3 text-content-secondary" title={src.description}>
              {src.description}
            </td>
            <td className="pr-3 text-content-secondary">{src.status}</td>
            <td className="pr-3 text-right tabular-nums">{qty(src.committed_qty)}</td>
            <td className="pr-3 text-right tabular-nums">{formatCurrency(src.committed_value, currency)}</td>
            <td className="pr-3 text-right tabular-nums text-content-tertiary">{qty(src.received_qty)}</td>
            <td className="pr-3 text-right tabular-nums text-content-tertiary">
              {formatCurrency(src.received_value, currency)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
