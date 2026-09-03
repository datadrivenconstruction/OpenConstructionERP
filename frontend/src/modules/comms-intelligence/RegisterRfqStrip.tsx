// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The registers' RFQ packages, shown on the Bid Management page.
 *
 * A register RFQ is compared and awarded inside the registers (its quote
 * gate, its columns, its PO); the bid packages on this page are the
 * module's own records and do not share ids with them. So rather than a
 * lookup that can never match, the page shows the job's open register
 * RFQs as a strip, each chip landing on that package's compare columns.
 */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { fmtDate } from '@/shared/lib/formatters';
import { fetchItems, type RegisterItemRow } from './registers-api';
import { RegisterChip } from './RegisterChip';

export function RegisterRfqStrip({ projectId }: { projectId: string | null | undefined }) {
  const { t } = useTranslation();
  const query = useQuery<RegisterItemRow[]>({
    queryKey: ['register-rfqs', projectId ?? ''],
    queryFn: () => fetchItems(projectId as string, 'rfq', 'open'),
    enabled: !!projectId,
    // A project without the registers, or a viewer without the permission,
    // simply gets no strip - the page is unchanged.
    retry: false,
    staleTime: 30_000,
  });
  const rows = query.data ?? [];
  if (!projectId || query.isError || rows.length === 0) return null;

  return (
    <div className="mb-3 rounded-lg border border-border-light bg-surface-primary px-4 py-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-semibold">
          {t('registers.rfq_strip_title', { defaultValue: 'RFQ packages in the registers' })}{' '}
          <span className="font-normal text-content-tertiary">({rows.length})</span>
        </span>
        <Link
          to={`/comms-intelligence?project=${encodeURIComponent(projectId)}`}
          className="text-xs text-oe-blue hover:underline"
        >
          {t('registers.rfq_strip_open', { defaultValue: 'Open the registers' })}
        </Link>
      </div>
      <ul className="flex flex-col gap-1.5">
        {rows.slice(0, 8).map((r) => (
          <li key={r.id} className="flex flex-wrap items-center gap-2 text-sm">
            <RegisterChip
              item={{
                item_id: r.id,
                reference: r.reference,
                kind: r.kind,
                status: r.status,
                is_overdue: r.is_overdue,
                title: r.title,
              }}
            />
            {/* An item raised without a title carries its reference as one;
                the chip already says that, so the row shows it as untitled. */}
            <span className="min-w-0 truncate">
              {r.title && r.title !== r.reference
                ? r.title
                : <span className="text-content-tertiary">{t('registers.untitled', { defaultValue: '(no title)' })}</span>}
            </span>
            <span className="ml-auto whitespace-nowrap text-xs text-content-tertiary">
              {r.ball_in_court === 'them'
                ? t('registers.with_them', { defaultValue: 'with the suppliers' })
                : t('registers.with_us', { defaultValue: 'with us' })}
              {r.due_date
                ? ` · ${t('registers.due_on', { defaultValue: 'due {{d}}', d: fmtDate(r.due_date) })}`
                : ''}
            </span>
          </li>
        ))}
      </ul>
      {rows.length > 8 && (
        <p className="mt-2 text-xs text-content-tertiary">
          {t('registers.rfq_strip_more', {
            defaultValue: '{{n}} more in the registers',
            n: rows.length - 8,
          })}
        </p>
      )}
    </div>
  );
}
