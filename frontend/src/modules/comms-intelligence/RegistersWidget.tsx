// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Project hub widget: what the registers hold on this job.
 *
 * One row per kind (open / overdue / with them) and the five most recent
 * open items, each wearing its reference chip. Sits beside the RFI inbox
 * on /projects/:id so the registers are visible from the job itself, not
 * only from their own screen.
 */
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, ListChecks } from 'lucide-react';
import clsx from 'clsx';
import { Card, Skeleton } from '@/shared/ui';
import { fmtDate } from '@/shared/lib/formatters';
import { fetchItems, fetchSummary, type Kind, type RegisterItemRow, type Summary } from './registers-api';
import { RegisterChip } from './RegisterChip';

const KIND_ORDER: Kind[] = ['rfi', 'rfq', 'order', 'variation', 'delay', 'toolbox'];

export function RegistersWidget({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const KIND_LABEL: Record<Kind, string> = {
    rfi: t('registers.kind_rfi', { defaultValue: 'RFIs' }),
    rfq: t('registers.kind_rfq', { defaultValue: 'RFQs' }),
    order: t('registers.kind_order', { defaultValue: 'Orders' }),
    variation: t('registers.kind_variation', { defaultValue: 'Variations' }),
    delay: t('registers.kind_delay', { defaultValue: 'Delays' }),
    toolbox: t('registers.kind_toolbox', { defaultValue: 'Toolbox talks' }),
  };

  const summaryQ = useQuery<Summary>({
    queryKey: ['registers', projectId, 'summary'],
    queryFn: () => fetchSummary(projectId),
    retry: false,
    staleTime: 30_000,
  });
  const openQ = useQuery<RegisterItemRow[]>({
    queryKey: ['registers', projectId, 'hub-open'],
    queryFn: () => fetchItems(projectId, undefined, 'open'),
    retry: false,
    staleTime: 30_000,
  });

  const rows = useMemo(() => {
    const sum = summaryQ.data;
    if (!sum) return [];
    return KIND_ORDER.filter((k) => (sum[k]?.total ?? 0) > 0).map((k) => ({ kind: k, ...sum[k] }));
  }, [summaryQ.data]);
  // The list arrives newest first; five is a sample, and the CTA says so.
  const recent = useMemo(() => (openQ.data ?? []).slice(0, 5), [openQ.data]);

  const isLoading = summaryQ.isLoading || openQ.isLoading;
  const isError = summaryQ.isError && openQ.isError;
  const isEmpty = !isLoading && !isError && rows.length === 0 && recent.length === 0;

  return (
    <Card padding="sm" className="flex h-full flex-col">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-start gap-2">
          <span className="mt-0.5 shrink-0 text-content-tertiary">
            <ListChecks size={16} />
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-sm font-semibold text-content-primary">
              {t('project.widget.registers.title', { defaultValue: 'Registers' })}
            </h3>
            <p className="truncate text-2xs text-content-tertiary">
              {t('project.widget.registers.card_subtitle', {
                defaultValue: 'RFIs, RFQs, orders and variations raised on this job',
              })}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => navigate(`/comms-intelligence?project=${encodeURIComponent(projectId)}`)}
          className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-2xs font-medium text-oe-blue transition-colors hover:bg-oe-blue/10"
        >
          {t('project.widget.registers.open', { defaultValue: 'Open the registers' })}
          <ArrowRight size={12} />
        </button>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} height={24} className="w-full" rounded="md" />
          ))}
        </div>
      ) : isError ? (
        <p className="py-2 text-center text-2xs text-content-quaternary">
          {t('project.widget.registers.unavailable', {
            defaultValue: 'The registers could not be read for this job.',
          })}
        </p>
      ) : isEmpty ? (
        <p className="py-2 text-center text-2xs text-content-quaternary">
          {t('project.widget.registers.empty', { defaultValue: 'Nothing raised on this job yet.' })}
        </p>
      ) : (
        <div className="space-y-3">
          {rows.length > 0 && (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-2xs uppercase tracking-wide text-content-tertiary">
                  <th className="pb-1 text-left font-medium">
                    {t('project.widget.registers.col_kind', { defaultValue: 'Register' })}
                  </th>
                  <th className="pb-1 text-right font-medium">
                    {t('project.widget.registers.col_open', { defaultValue: 'Open' })}
                  </th>
                  <th className="pb-1 text-right font-medium">
                    {t('project.widget.registers.col_overdue', { defaultValue: 'Overdue' })}
                  </th>
                  <th className="pb-1 text-right font-medium">
                    {t('project.widget.registers.col_with_them', { defaultValue: 'With them' })}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {rows.map((r) => (
                  <tr key={r.kind}>
                    <td className="py-1 text-content-primary">{KIND_LABEL[r.kind]}</td>
                    <td className="py-1 text-right font-mono text-content-secondary">{r.open}</td>
                    <td
                      className={clsx(
                        'py-1 text-right font-mono',
                        r.overdue > 0 ? 'font-semibold text-semantic-error' : 'text-content-tertiary',
                      )}
                    >
                      {r.overdue}
                    </td>
                    <td className="py-1 text-right font-mono text-content-secondary">{r.with_them}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {recent.length > 0 && (
            <div>
              <p className="mb-1 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                {t('project.widget.registers.recent', { defaultValue: 'Latest open' })}
              </p>
              <ul className="-mx-2 divide-y divide-border-light">
                {recent.map((item) => (
                  <li key={item.id} className="flex items-center gap-2 px-2 py-1.5">
                    <RegisterChip
                      item={{
                        item_id: item.id,
                        reference: item.reference,
                        kind: item.kind,
                        status: item.status,
                        is_overdue: item.is_overdue,
                      }}
                      className="shrink-0"
                    />
                    <span className="min-w-0 flex-1 truncate text-sm text-content-primary">
                      {/* An untitled item carries its reference as its title;
                          the chip already shows that. */}
                      {item.title && item.title !== item.reference
                        ? item.title
                        : <span className="text-content-tertiary">{t('registers.untitled', { defaultValue: '(no title)' })}</span>}
                    </span>
                    {item.due_date && (
                      <span
                        className={clsx(
                          'shrink-0 text-2xs',
                          item.is_overdue ? 'font-semibold text-semantic-error' : 'text-content-tertiary',
                        )}
                        title={t('project.widget.registers.due', { defaultValue: 'Due' })}
                      >
                        {fmtDate(item.due_date)}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
