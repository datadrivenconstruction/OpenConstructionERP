// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Sealed estimates register: every seal of the active project, the openings
 * across them and the audit trail. Sealing starts here or from the estimate.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Copy, Lock } from 'lucide-react';
import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  CollapsibleSection,
  DateDisplay,
  DismissibleInfo,
  EmptyState,
  ErrorState,
  KpiBand,
  MoneyDisplay,
  PageHeader,
  SkeletonTable,
  TabBar,
} from '@/shared/ui';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import { archiveApi, shortHash, type Opening, type SealSummary } from './api';
import { SealModal } from './SealModal';
import { AuditTimeline } from './AuditTimeline';
import { OpeningsTable } from './OpeningsTable';
import { receiptVariant, statusVariant, useArchiveTerm } from './labels';

type Tab = 'seals' | 'openings' | 'audit';

export function EstimateArchivePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const projectId = useActiveProjectId() || undefined;
  const [tab, setTab] = useState<Tab>('seals');
  const [sealOpen, setSealOpen] = useState(false);

  const policy = useQuery({
    queryKey: ['estimate-archive', 'policy', projectId],
    queryFn: () => archiveApi.policy(projectId as string),
    enabled: !!projectId,
  });
  const seals = useQuery({
    queryKey: ['estimate-archive', 'seals', projectId ?? null],
    queryFn: () => archiveApi.seals(projectId),
  });
  const kpis = useQuery({
    queryKey: ['estimate-archive', 'kpis', projectId ?? null],
    queryFn: () => archiveApi.kpis(projectId),
  });
  const openings = useQuery({
    queryKey: ['estimate-archive', 'openings', projectId ?? null],
    queryFn: () => archiveApi.openings({ projectId }),
    enabled: tab === 'openings',
  });
  const events = useQuery({
    queryKey: ['estimate-archive', 'events', projectId ?? null],
    queryFn: () => archiveApi.events(undefined, projectId),
    enabled: tab === 'audit',
  });
  const term = useArchiveTerm(policy.data?.profile);
  const k = kpis.data;
  const marketOff = policy.data && !policy.data.enabled;
  const canSeal = !!projectId && !marketOff;

  const sealAction = canSeal ? (
    <Button variant="primary" onClick={() => setSealOpen(true)} icon={<Lock size={14} />}>
      {t('estimate_archive.seal_action', { defaultValue: 'Seal an estimate' })}
    </Button>
  ) : null;

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          { label: t('nav.estimate_archive', { defaultValue: 'Sealed estimates' }) },
        ]}
      />
      <PageHeader
        srTitle={t('nav.estimate_archive', { defaultValue: 'Sealed estimates' })}
        subtitle={t('estimate_archive.subtitle', {
          defaultValue: 'The estimate behind the contract rates, frozen and fingerprinted, opened only with a record.',
        })}
        actions={sealAction}
      />
      <DismissibleInfo
        storageKey="estimate_archive.intro"
        title={t('estimate_archive.intro_title', { defaultValue: 'Why seal the estimate' })}
      >
        {t('estimate_archive.intro_body', {
          defaultValue:
            'When a change is priced, both sides need the rates the contract was built on. A seal keeps that estimate exactly as it was, with a SHA-256 fingerprint the other side can check. It opens only in a recorded meeting, and every reading is logged.',
        })}
      </DismissibleInfo>
      <CollapsibleSection
        storageKey="estimate_archive.how"
        title={t('estimate_archive.how_title', { defaultValue: 'How it works' })}
        defaultCollapsed
      >
        <ol className="list-decimal space-y-1 ps-5 text-sm text-content-secondary">
          <li>{t('estimate_archive.how_1', { defaultValue: 'Seal the locked award estimate. Nothing in the seal can change afterwards.' })}</li>
          <li>{t('estimate_archive.how_2', { defaultValue: 'Ask the client to acknowledge the fingerprint, or hand the package over on paper.' })}</li>
          <li>{t('estimate_archive.how_3', { defaultValue: 'When a change needs the rates, open the seal with both parties; the server re-checks the fingerprint first.' })}</li>
          <li>{t('estimate_archive.how_4', { defaultValue: 'Price the change from the sealed resources and compare it with cost plus markups. You choose the method.' })}</li>
        </ol>
      </CollapsibleSection>
      {k && (
        <KpiBand
          columns={5}
          items={[
            { key: 'seals', label: t('estimate_archive.kpi.seals', { defaultValue: 'Seals' }), value: k.seals },
            {
              key: 'receipt',
              label: t('estimate_archive.kpi.awaiting_receipt', { defaultValue: 'Awaiting receipt' }),
              value: k.awaiting_receipt,
              tone: k.awaiting_receipt ? 'warning' : undefined,
            },
            {
              key: 'progress',
              label: t('estimate_archive.kpi.openings_in_progress', { defaultValue: 'Openings in progress' }),
              value: k.openings_in_progress,
            },
            {
              key: 'year',
              label: t('estimate_archive.kpi.openings_this_year', { defaultValue: 'Openings this year' }),
              value: k.openings_this_year,
            },
            {
              key: 'breakdown',
              label: t('estimate_archive.kpi.without_breakdown', { defaultValue: 'Positions without breakdown' }),
              value: k.positions_without_breakdown,
              tone: k.positions_without_breakdown ? 'warning' : undefined,
            },
          ]}
        />
      )}
      <TabBar<Tab>
        ariaLabel={t('nav.estimate_archive', { defaultValue: 'Sealed estimates' })}
        activeId={tab}
        onChange={setTab}
        tabs={[
          { id: 'seals', label: t('estimate_archive.tab.seals', { defaultValue: 'Seals' }), badge: seals.data?.length },
          { id: 'openings', label: t('estimate_archive.tab.openings', { defaultValue: 'Openings' }) },
          { id: 'audit', label: t('estimate_archive.tab.audit', { defaultValue: 'Audit' }) },
        ]}
      />
      {tab === 'seals' && (
        <Card>
          {seals.isLoading ? (
            <SkeletonTable rows={4} />
          ) : seals.isError ? (
            <ErrorState
              title={t('estimate_archive.load_error', { defaultValue: 'Sealed estimates could not be loaded' })}
              onRetry={() => void seals.refetch()}
            />
          ) : !seals.data?.length ? (
            <EmptyState
              icon={<Lock size={28} />}
              title={
                marketOff
                  ? t('estimate_archive.empty.market_off', {
                      defaultValue: "Sealed estimates are not part of this project's market profile.",
                    })
                  : t('estimate_archive.empty.seals', {
                      defaultValue: 'No sealed estimates yet. Seal the estimate your contract rates came from.',
                    })
              }
              action={
                canSeal
                  ? { label: t('estimate_archive.seal_action', { defaultValue: 'Seal an estimate' }), onClick: () => setSealOpen(true) }
                  : undefined
              }
            />
          ) : (
            <SealsTable rows={seals.data} term={term} onOpen={(id) => navigate(`/estimate-archive/${id}`)} />
          )}
        </Card>
      )}
      {tab === 'openings' && (
        <Card>
          {openings.isLoading ? (
            <SkeletonTable rows={3} />
          ) : (
            <OpeningsTable rows={openings.data ?? ([] as Opening[])} showSeal />
          )}
        </Card>
      )}
      {tab === 'audit' && (
        <Card>{events.isLoading ? <SkeletonTable rows={5} /> : <AuditTimeline events={events.data ?? []} />}</Card>
      )}
      {sealOpen && projectId && (
        <SealModal
          projectId={projectId}
          onClose={() => setSealOpen(false)}
          onSealed={(id) => {
            setSealOpen(false);
            navigate(`/estimate-archive/${id}`);
          }}
        />
      )}
    </div>
  );
}

function SealsTable({
  rows,
  term,
  onOpen,
}: {
  rows: SealSummary[];
  term: string;
  onOpen: (id: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">{term}</caption>
        <thead>
          <tr className="border-b border-border-light text-start text-xs text-content-tertiary">
            <th className="px-3 py-2 text-start font-medium">{t('estimate_archive.col.label', { defaultValue: 'Label' })}</th>
            <th className="px-3 py-2 text-start font-medium">{t('estimate_archive.col.contract', { defaultValue: 'Contract' })}</th>
            <th className="px-3 py-2 text-start font-medium">{t('estimate_archive.col.basis', { defaultValue: 'Basis' })}</th>
            <th className="px-3 py-2 text-start font-medium">{t('estimate_archive.col.sealed_at', { defaultValue: 'Sealed at' })}</th>
            <th className="px-3 py-2 text-end font-medium">{t('estimate_archive.col.total', { defaultValue: 'Total' })}</th>
            <th className="px-3 py-2 text-start font-medium">{t('estimate_archive.fingerprint', { defaultValue: 'Fingerprint (SHA-256)' })}</th>
            <th className="px-3 py-2 text-start font-medium">{t('estimate_archive.col.receipt', { defaultValue: 'Receipt' })}</th>
            <th className="px-3 py-2 text-end font-medium">{t('estimate_archive.tab.openings', { defaultValue: 'Openings' })}</th>
            <th className="px-3 py-2 text-start font-medium">{t('estimate_archive.col.status', { defaultValue: 'Status' })}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr
              key={s.id}
              className="cursor-pointer border-b border-border-light hover:bg-surface-secondary"
              onClick={() => onOpen(s.id)}
            >
              <td className="px-3 py-2 font-medium text-content-primary">{s.label}</td>
              <td className="px-3 py-2 text-content-secondary">{s.contract_label || '-'}</td>
              <td className="px-3 py-2">{t(`estimate_archive.basis.${s.basis_kind}`, { defaultValue: s.basis_kind })}</td>
              <td className="px-3 py-2"><DateDisplay value={s.sealed_at} format="datetime" /></td>
              <td className="px-3 py-2 text-end"><MoneyDisplay amount={s.award_total} currency={s.currency} /></td>
              <td className="px-3 py-2">
                <span className="inline-flex items-center gap-1">
                  <bdi dir="ltr" className="font-mono text-xs">{shortHash(s.content_hash)}</bdi>
                  <button
                    type="button"
                    className="text-content-tertiary hover:text-content-primary"
                    aria-label={t('estimate_archive.copy_fingerprint', { defaultValue: 'Copy fingerprint' })}
                    onClick={(e) => {
                      e.stopPropagation();
                      void navigator.clipboard?.writeText(s.content_hash);
                    }}
                  >
                    <Copy size={12} />
                  </button>
                </span>
              </td>
              <td className="px-3 py-2">
                <Badge variant={receiptVariant(s.receipt_status)} size="sm">
                  {t(`estimate_archive.receipt.${s.receipt_status}`, { defaultValue: s.receipt_status })}
                </Badge>
              </td>
              <td className="px-3 py-2 text-end">{s.openings}</td>
              <td className="px-3 py-2">
                <Badge variant={statusVariant(s.status)} size="sm">
                  {t(`estimate_archive.status.${s.status}`, { defaultValue: s.status })}
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
