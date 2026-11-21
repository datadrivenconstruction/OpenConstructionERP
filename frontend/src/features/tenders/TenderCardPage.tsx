// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import { Pencil } from 'lucide-react';
import { Badge, Breadcrumb, Button, Card, EmptyState, ErrorState, KpiBand, SkeletonTable, TabBar } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { fmtQuantity } from '@/shared/lib/formatters';
import { fetchTender, tenderEditPath, type TenderDetail } from './api';

type Tab = 'scope' | 'bidders' | 'qa' | 'bids' | 'levelling' | 'award';

export function TenderCardPage() {
  const { t } = useTranslation();
  const { tenderId = '' } = useParams<{ tenderId: string }>();
  const [tab, setTab] = useState<Tab>('scope');
  const navigate = useNavigate();
  const query = useQuery({ queryKey: ['tender', tenderId], queryFn: () => fetchTender(tenderId), enabled: !!tenderId });
  const tender = query.data;

  const bidderName = useMemo(() => {
    const names = new Map<string, string>();
    for (const b of tender?.bidders ?? []) names.set(b.id, b.company_name);
    return (id: string | null | undefined) => (id ? names.get(id) ?? '' : '');
  }, [tender]);

  const title = tender ? `${tender.package.code} ${tender.package.title}`.trim() : t('tenders.title', { defaultValue: 'Tenders' });
  const lowest = useMemo(() => {
    const totals = (tender?.submissions ?? []).map((s) => Number(s.total_amount)).filter((n) => Number.isFinite(n) && n > 0);
    return totals.length ? Math.min(...totals) : null;
  }, [tender]);

  return (
    <div className="min-w-0 space-y-5 animate-fade-in">
      <Breadcrumb
        items={[{ label: t('tenders.title', { defaultValue: 'Tenders' }), to: '/tenders' }, { label: title }]}
      />
      <PageHeader
        srTitle={t('tenders.title', { defaultValue: 'Tenders' })}
        subtitle={
          tender ? (
            <span className="text-lg font-semibold text-content-primary">
              <span className="text-content-tertiary tabular-nums">{tender.package.code}</span> {tender.package.title}
            </span>
          ) : (
            t('tenders.card_loading', { defaultValue: 'Loading the tender.' })
          )
        }
        actions={
          tender ? (
            <Button
              variant="secondary"
              icon={<Pencil size={16} />}
              onClick={() =>
                navigate(tenderEditPath({ ...tender, id: tender.package.id, project_id: tender.package.project_id }))
              }
            >
              {t('tenders.edit', { defaultValue: 'Edit' })}
            </Button>
          ) : null
        }
      />
      {query.isLoading ? (
        <Card>
          <SkeletonTable rows={5} columns={5} />
        </Card>
      ) : query.isError || !tender ? (
        <Card>
          <ErrorState
            title={t('tenders.card_failed', { defaultValue: 'This tender could not be loaded.' })}
            onRetry={() => query.refetch()}
          />
        </Card>
      ) : (
        <>
          {tender.read_only && (
            <div className="rounded-xl border border-semantic-info/30 bg-semantic-info-bg px-4 py-3 text-sm text-content-secondary">
              {t('tenders.copy_notice', {
                defaultValue: 'Created in an older module. It is shown here in full; changes are still made with Edit.',
              })}
            </div>
          )}
          <KpiBand
            columns={4}
            items={[
              { key: 'status', label: t('tenders.col_status', { defaultValue: 'Status' }), value: t(`bid_management.status_${tender.package.status}`, { defaultValue: tender.package.status }) },
              { key: 'deadline', label: t('tenders.col_deadline', { defaultValue: 'Bids due' }), value: tender.package.submission_deadline ? <DateDisplay value={tender.package.submission_deadline} /> : '-' },
              { key: 'bids', label: t('tenders.kpi_bids', { defaultValue: 'Bids received' }), value: tender.submissions.length },
              { key: 'lowest', label: t('tenders.col_lowest', { defaultValue: 'Lowest bid' }), value: lowest != null ? <MoneyDisplay amount={lowest} currency={tender.package.currency} /> : '-' },
            ]}
          />
          <TabBar<Tab>
            ariaLabel={t('tenders.card_tabs', { defaultValue: 'Tender sections' })}
            activeId={tab}
            onChange={setTab}
            tabs={[
              { id: 'scope', label: t('tenders.tab_scope', { defaultValue: 'Scope' }), badge: tender.line_items.length },
              { id: 'bidders', label: t('tenders.tab_bidders', { defaultValue: 'Bidders' }), badge: tender.bidders.length },
              { id: 'qa', label: t('tenders.tab_qa', { defaultValue: 'Q&A' }), badge: tender.questions.length },
              { id: 'bids', label: t('tenders.col_bids', { defaultValue: 'Bids' }), badge: tender.submissions.length },
              { id: 'levelling', label: t('tenders.tab_levelling', { defaultValue: 'Levelling' }) },
              { id: 'award', label: t('tenders.tab_award', { defaultValue: 'Award' }) },
            ]}
          />
          <Card>
            <div className="overflow-x-auto">
              <TabBody tab={tab} tender={tender} bidderName={bidderName} />
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

function TabBody({
  tab,
  tender,
  bidderName,
}: {
  tab: Tab;
  tender: TenderDetail;
  bidderName: (id: string | null | undefined) => string;
}) {
  const { t } = useTranslation();
  const empty = <EmptyState title={t('tenders.tab_empty', { defaultValue: 'Nothing recorded here yet.' })} />;
  const cur = tender.package.currency;

  if (tab === 'scope') {
    if (!tender.line_items.length) return empty;
    return (
      <table className="oe-table w-full">
        <thead>
          <tr>
            <th>{t('tenders.col_code', { defaultValue: 'Code' })}</th>
            <th>{t('tenders.col_description', { defaultValue: 'Description' })}</th>
            <th>{t('tenders.col_unit', { defaultValue: 'Unit' })}</th>
            <th className="num">{t('tenders.col_quantity', { defaultValue: 'Quantity' })}</th>
          </tr>
        </thead>
        <tbody>
          {tender.line_items.map((l) => (
            <tr key={l.id}>
              <td>{l.code}</td>
              <td className="text-content-primary">{l.description}</td>
              <td>{l.unit}</td>
              <td className="num tabular-nums">{fmtQuantity(l.quantity)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (tab === 'bidders') {
    if (!tender.bidders.length) return empty;
    return (
      <table className="oe-table w-full">
        <thead>
          <tr>
            <th>{t('tenders.col_company', { defaultValue: 'Company' })}</th>
            <th>{t('tenders.col_email', { defaultValue: 'Email' })}</th>
            <th>{t('tenders.col_status', { defaultValue: 'Status' })}</th>
          </tr>
        </thead>
        <tbody>
          {tender.bidders.map((b) => (
            <tr key={b.id}>
              <td className="text-content-primary">{b.company_name}</td>
              <td>{b.contact_email}</td>
              <td>
                <Badge variant={b.status === 'active' ? 'neutral' : 'warning'}>
                  {t(`tenders.bidder_${b.status}`, { defaultValue: b.status })}
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (tab === 'qa') {
    if (!tender.questions.length) return empty;
    return (
      <ul className="divide-y divide-border-light">
        {tender.questions.map((q) => (
          <li key={q.id} className="py-3 first:pt-0 last:pb-0">
            <p className="text-sm font-medium text-content-primary">{q.question}</p>
            <p className="mt-1 text-sm text-content-secondary">
              {q.answer || t('tenders.unanswered', { defaultValue: 'Not answered yet.' })}
            </p>
          </li>
        ))}
      </ul>
    );
  }
  if (tab === 'bids') {
    if (!tender.submissions.length) return empty;
    const sorted = [...tender.submissions].sort((a, b) => Number(a.total_amount) - Number(b.total_amount));
    return (
      <table className="oe-table w-full">
        <thead>
          <tr>
            <th>{t('tenders.col_company', { defaultValue: 'Company' })}</th>
            <th>{t('tenders.col_submitted', { defaultValue: 'Submitted' })}</th>
            <th className="num">{t('tenders.col_total', { defaultValue: 'Total' })}</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((s) => (
            <tr key={s.id}>
              <td className="text-content-primary">{bidderName(s.bidder_id)}</td>
              <td>{s.submitted_at ? <DateDisplay value={s.submitted_at} /> : '-'}</td>
              <td className="num tabular-nums">
                <MoneyDisplay amount={s.total_amount} currency={s.currency || cur} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (tab === 'levelling') {
    const c = tender.comparison;
    if (!c) return empty;
    return (
      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <Fact label={t('tenders.levelled_low', { defaultValue: 'Levelled low' })}>
          <MoneyDisplay amount={c.normalized_low} currency={cur} />
        </Fact>
        <Fact label={t('tenders.levelled_high', { defaultValue: 'Levelled high' })}>
          <MoneyDisplay amount={c.normalized_high} currency={cur} />
        </Fact>
        <Fact label={t('tenders.weights', { defaultValue: 'Price / quality weight' })}>
          {`${c.commercial_weight_pct} / ${c.technical_weight_pct}`}
        </Fact>
        <Fact label={t('tenders.recommended', { defaultValue: 'Recommended' })}>
          {bidderName(c.recommended_bidder_id) || '-'}
        </Fact>
      </dl>
    );
  }
  const a = tender.award;
  if (!a) return empty;
  return (
    <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
      <Fact label={t('tenders.col_awarded', { defaultValue: 'Awarded to' })}>{bidderName(a.awarded_bidder_id)}</Fact>
      <Fact label={t('tenders.awarded_amount', { defaultValue: 'Amount' })}>
        <MoneyDisplay amount={a.awarded_amount} currency={a.currency || cur} />
      </Fact>
      <Fact label={t('tenders.decided_on', { defaultValue: 'Decided on' })}>
        {a.decision_signed_at ? <DateDisplay value={a.decision_signed_at} /> : '-'}
      </Fact>
      <Fact label={t('tenders.decision', { defaultValue: 'Reason' })}>{a.decision_summary || '-'}</Fact>
    </dl>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="oe-overline">{label}</dt>
      <dd className="mt-1 text-content-primary">{children}</dd>
    </div>
  );
}
