// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * StatutoryChecksSection - lien notice deadlines, the retainage cap and the
 * statutory findings for the active project's state or province.
 *
 * Renders nothing unless a loaded pack carries tables for the project's
 * subdivision, so markets whose packs do not contribute it never see it.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Scale } from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  DateDisplay,
  EmptyState,
  ErrorState,
  Input,
  MoneyDisplay,
  TabBar,
  type BadgeVariant,
} from '@/shared/ui';
import { projectsApi } from '@/features/projects/api';
import {
  evaluateStatutory,
  fetchJurisdiction,
  fetchJurisdictions,
  type ClaimantRole,
  type NoticeStatus,
  type OwnerSector,
} from './api';
import { buildStatutoryFacts } from './facts';

type TabId = 'notices' | 'retainage' | 'findings';

const ROLE_LABELS: Record<ClaimantRole, string> = {
  direct_contractor: 'Direct contractor',
  subcontractor: 'Subcontractor',
  supplier: 'Supplier',
};

const EVENT_LABELS: Record<string, string> = {
  first_furnishing: 'First furnishing',
  final_furnishing: 'Final furnishing',
  last_work: 'Last work',
  completion: 'Completion',
  notice_of_completion_recorded: 'Notice of completion recorded',
  claim_recorded: 'Claim of lien recorded',
  pay_request_received: 'Pay request received',
  payment_received: 'Payment received',
  planned_suit_filing: 'Planned suit filing',
};

const STATUS_VARIANT: Record<NoticeStatus, BadgeVariant> = {
  upcoming: 'blue',
  due_today: 'warning',
  overdue: 'error',
};

const STATUS_LABELS: Record<NoticeStatus, string> = {
  upcoming: 'Upcoming',
  due_today: 'Due today',
  overdue: 'Overdue',
};

const SEVERITY_VARIANT: Record<string, BadgeVariant> = { error: 'error', warning: 'warning', info: 'neutral' };

const SELECT_CLASS =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary';

export function StatutoryChecksSection({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<TabId>('notices');
  const [role, setRole] = useState<ClaimantRole>('direct_contractor');
  const [sector, setSector] = useState<OwnerSector>('private');
  const [events, setEvents] = useState<Record<string, string>>({});
  const [contractValue, setContractValue] = useState('');
  const [paymentAmount, setPaymentAmount] = useState('');
  const [retentionAmount, setRetentionAmount] = useState('');

  const project = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => projectsApi.get(projectId),
    enabled: !!projectId,
  });
  const subdivision = project.data?.subdivision_code ?? null;
  const codes = useQuery({
    queryKey: ['statutory', 'jurisdictions'],
    queryFn: fetchJurisdictions,
    enabled: !!subdivision,
    retry: false,
    staleTime: 5 * 60_000,
  });
  const carried = !!subdivision && (codes.data ?? []).includes(subdivision);
  const summary = useQuery({
    queryKey: ['statutory', 'jurisdiction', subdivision],
    queryFn: () => fetchJurisdiction(subdivision as string),
    enabled: carried,
    retry: false,
  });
  const run = useMutation({
    mutationFn: () =>
      evaluateStatutory(
        buildStatutoryFacts(subdivision as string, {
          role,
          sector,
          events,
          contractValue,
          paymentAmount,
          retentionAmount,
        }),
      ),
  });

  if (!carried || !summary.data) return null;
  const table = summary.data;
  const currency = project.data?.currency || 'USD';
  const outcome = run.data;

  const tabs = [
    { id: 'notices' as const, label: t('statutory.tab_notices', { defaultValue: 'Lien notices' }) },
    { id: 'retainage' as const, label: t('statutory.tab_retainage', { defaultValue: 'Retainage' }) },
    {
      id: 'findings' as const,
      label: t('statutory.tab_findings', { defaultValue: 'Findings' }),
      badge: outcome?.findings.length ? outcome.findings.length : undefined,
    },
  ];

  return (
    <Card padding="md" className="space-y-4" data-testid="statutory-checks">
      <div className="flex items-start gap-3">
        <Scale size={18} className="mt-0.5 shrink-0 text-oe-blue" />
        <div>
          <h2 className="text-sm font-semibold text-content-primary">
            {t('statutory.section_title', { defaultValue: 'Statutory checks' })}
          </h2>
          <p className="text-xs text-content-secondary">
            {t('statutory.section_hint', {
              defaultValue:
                'Lien notice deadlines and the retainage cap under {{name}} law, computed from the statute cited beside each line. Verify every date with counsel before relying on it.',
              name: table.name,
            })}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="space-y-1 text-xs text-content-secondary">
          <span>{t('statutory.role', { defaultValue: 'Your place in the chain' })}</span>
          <select
            className={SELECT_CLASS}
            value={role}
            onChange={(e) => setRole(e.target.value as ClaimantRole)}
          >
            {(Object.keys(ROLE_LABELS) as ClaimantRole[]).map((r) => (
              <option key={r} value={r}>
                {t(`statutory.role_${r}`, { defaultValue: ROLE_LABELS[r] })}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1 text-xs text-content-secondary">
          <span>{t('statutory.sector', { defaultValue: 'Owner' })}</span>
          <select
            className={SELECT_CLASS}
            value={sector}
            onChange={(e) => setSector(e.target.value as OwnerSector)}
          >
            <option value="private">{t('statutory.sector_private', { defaultValue: 'Private' })}</option>
            <option value="public">{t('statutory.sector_public', { defaultValue: 'Public' })}</option>
          </select>
        </label>
        <Input
          label={t('statutory.contract_value', { defaultValue: 'Contract value' })}
          inputMode="decimal"
          value={contractValue}
          onChange={(e) => setContractValue(e.target.value)}
        />
      </div>

      <TabBar
        tabs={tabs}
        activeId={tab}
        onChange={setTab}
        ariaLabel={t('statutory.section_title', { defaultValue: 'Statutory checks' })}
      />

      {tab === 'notices' && (
        <div className="space-y-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {table.events.map((ev) => (
              <Input
                key={ev}
                type="date"
                label={t(`statutory.event_${ev}`, { defaultValue: EVENT_LABELS[ev] ?? ev })}
                value={events[ev] ?? ''}
                onChange={(e) => setEvents((prev) => ({ ...prev, [ev]: e.target.value }))}
              />
            ))}
          </div>
          {outcome && outcome.notices.length > 0 ? (
            <ul className="divide-y divide-border-light" data-testid="statutory-notices">
              {outcome.notices.map((n) => (
                <li
                  key={`${n.code}-${n.period ?? n.event_date}`}
                  className="flex flex-wrap items-center gap-3 py-2 text-sm"
                >
                  <span className="min-w-0 flex-1 text-content-primary">{n.name}</span>
                  <DateDisplay value={n.due_date} className="tabular-nums text-content-primary" />
                  <Badge variant={STATUS_VARIANT[n.status]}>
                    {t(`statutory.status_${n.status}`, { defaultValue: STATUS_LABELS[n.status] })}
                  </Badge>
                  <span className="w-full text-xs text-content-tertiary">{n.source}</span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              icon={<Scale size={40} />}
              title={t('statutory.notices_empty', {
                defaultValue: 'Enter the event dates to see the notice deadlines.',
              })}
            />
          )}
        </div>
      )}

      {tab === 'retainage' && (
        <div className="space-y-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Input
              label={t('statutory.payment_amount', { defaultValue: 'Payment amount' })}
              inputMode="decimal"
              value={paymentAmount}
              onChange={(e) => setPaymentAmount(e.target.value)}
            />
            <Input
              label={t('statutory.retention_amount', { defaultValue: 'Amount held' })}
              inputMode="decimal"
              value={retentionAmount}
              onChange={(e) => setRetentionAmount(e.target.value)}
            />
          </div>
          {outcome?.retention && (
            <div className="flex flex-wrap items-center gap-3 text-sm" data-testid="statutory-retention">
              <Badge variant={outcome.retention.over_cap ? 'error' : 'success'}>
                {outcome.retention.over_cap
                  ? t('statutory.retention_over_cap', {
                      defaultValue: 'Above the {{pct}} percent cap',
                      pct: outcome.retention.cap_pct,
                    })
                  : t('statutory.retention_within_cap', { defaultValue: 'Within the cap' })}
              </Badge>
              {outcome.retention.cap_amount && (
                <MoneyDisplay amount={outcome.retention.cap_amount} currency={currency} />
              )}
              {outcome.retention.cap_source && (
                <span className="text-xs text-content-tertiary">{outcome.retention.cap_source}</span>
              )}
            </div>
          )}
        </div>
      )}

      {tab === 'findings' &&
        (outcome && outcome.findings.length > 0 ? (
          <ul className="divide-y divide-border-light">
            {outcome.findings.map((f) => (
              <li key={f.rule_id} className="flex items-start gap-3 py-2 text-sm">
                <Badge variant={SEVERITY_VARIANT[f.severity] ?? 'neutral'}>{f.check}</Badge>
                <span className="min-w-0 flex-1 text-content-primary">{f.message}</span>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            icon={<Scale size={40} />}
            title={t('statutory.findings_empty', { defaultValue: 'No findings for the facts entered.' })}
          />
        ))}

      {run.isError && (
        <ErrorState
          title={t('statutory.error', { defaultValue: 'The checks could not run.' })}
          onRetry={() => run.mutate()}
        />
      )}

      <div className="flex justify-end">
        <Button variant="primary" size="sm" loading={run.isPending} onClick={() => run.mutate()}>
          {t('statutory.run', { defaultValue: 'Check' })}
        </Button>
      </div>
    </Card>
  );
}
