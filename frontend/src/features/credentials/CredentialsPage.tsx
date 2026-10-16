// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * CredentialsPage - the professional-credentials register and, more to the
 * point, the compliance answer it exists to give.
 *
 * Three tabs over one backend module (``app/modules/credentials``):
 *
 *  1. Compliance - who may not work today. Straight from ``GET /compliance/``,
 *     which is the module's own join of holders against requirements; nothing
 *     here is recomputed on the client.
 *  2. Register - the credentials themselves, with create / edit / delete and
 *     the human verification record.
 *  3. Requirements - what the project demands of whom. This is the half that
 *     makes a *missing* credential detectable: without a requirement, a ticket
 *     nobody entered is simply absent, not a gap.
 *
 * Expiry is derived by the server on every read, so the status shown here can
 * never be contradicted by the date beside it. The stored column is a cache,
 * and ``status_is_stale`` on any row is what surfaces the refresh action.
 */
import { Fragment, useCallback, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  ArrowRight,
  Ban,
  BadgeCheck,
  CalendarClock,
  CheckCircle2,
  ClipboardList,
  Info,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  ScrollText,
  ShieldAlert,
  Trash2,
  Users,
  XCircle,
} from 'lucide-react';
import clsx from 'clsx';
import {
  Badge,
  Button,
  CollapsibleSection,
  ConfirmDialog,
  DateDisplay,
  EmptyState,
  Input,
  KpiBand,
  SkeletonTable,
  type KpiBandItem,
} from '@/shared/ui';
import { TabBar, type TabBarTab } from '@/shared/ui/TabBar';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  createCredential,
  createRequirement,
  deleteCredential,
  deleteRequirement,
  fetchCompliance,
  fetchCredentials,
  fetchExpiringSoon,
  fetchMeta,
  fetchRequirements,
  fetchSummary,
  fetchValidation,
  refreshStatuses,
  updateCredential,
  updateRequirement,
  verifyCredential,
  APPLIES_TO_ALL,
  type ComplianceGap,
  type ComplianceHolderRow,
  type Credential,
  type CredentialCreatePayload,
  type CredentialStatus,
  type Requirement,
  type RequirementCreatePayload,
} from './api';
import { holderKindLabel, humanise, statusLabel, typeLabel } from './labels';
import { buildCredentialsInsights } from './credentialsInsights';
import { CredentialFormModal } from './CredentialFormModal';
import { RequirementFormModal } from './RequirementFormModal';

type TabId = 'compliance' | 'register' | 'requirements';
type HolderFilter = 'all' | 'gaps' | 'blocked';

/**
 * How a credential reads at a glance.
 *
 * Suspended and revoked sit with expired rather than with valid, because all
 * three mean the same thing to a gate: you cannot rely on this today. The word
 * on the badge is what tells them apart.
 */
function badgeVariant(status: CredentialStatus): 'neutral' | 'success' | 'warning' | 'error' {
  if (status === 'expiring_soon') return 'warning';
  if (status === 'expired' || status === 'suspended' || status === 'revoked') return 'error';
  return 'success';
}

/** Days remaining before a lapse stops being tolerated, or null when it already has. */
function graceRemaining(gap: ComplianceGap): number | null {
  if (!gap.within_grace || gap.days_until_expiry === null) return null;
  return gap.grace_days + gap.days_until_expiry;
}

/* ── Explainer ──────────────────────────────────────────────────────────── */

function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/**
 * What the register is, and the one thing about it that surprises people: it
 * cannot report a credential as missing until something says it was required.
 * A register with no requirements is a filing cabinet, not a control.
 */
function HowCredentialsWork() {
  const { t } = useTranslation();

  const steps: { icon: ReactNode; title: string; desc: string }[] = [
    {
      icon: <ScrollText size={14} className="text-oe-blue" />,
      title: t('credentials.flow_1_title', { defaultValue: 'Record what people hold' }),
      desc: t('credentials.flow_1_desc', {
        defaultValue:
          'Licences, certifications, statutory memberships, indemnity cover, registrations and training, each with the authority that issued it and the dates it runs between.',
      }),
    },
    {
      icon: <ClipboardList size={14} className="text-oe-blue" />,
      title: t('credentials.flow_2_title', { defaultValue: 'State what the project demands' }),
      desc: t('credentials.flow_2_desc', {
        defaultValue:
          'A requirement names a credential type, who it applies to, whether a gap stops work, and how long a lapse is tolerated.',
      }),
    },
    {
      icon: <ShieldAlert size={14} className="text-oe-blue" />,
      title: t('credentials.flow_3_title', { defaultValue: 'The register joins the two' }),
      desc: t('credentials.flow_3_desc', {
        defaultValue:
          'Every holder is measured against every requirement that binds them, and expiry is worked out from the dates each time it is read, not from a status somebody typed.',
      }),
    },
    {
      icon: <Ban size={14} className="text-oe-blue" />,
      title: t('credentials.flow_4_title', { defaultValue: 'Act before the gate does' }),
      desc: t('credentials.flow_4_desc', {
        defaultValue:
          'Renew what is about to lapse, chase what is missing, and know before the shift starts who should not be on site.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="credentials.how"
      icon={<BadgeCheck size={15} className="text-oe-blue" />}
      title={t('credentials.flow_title', {
        defaultValue: 'How the Credentials register fits together',
      })}
    >
      <p className="text-xs text-content-tertiary">
        {t('credentials.flow_intro', {
          defaultValue:
            'Who on this project is qualified to do what, and until when. The register holds the credentials; the requirements say which of them the project actually demands. Only together can they report a credential as missing, so a register with no requirements will always look clean.',
        })}
      </p>

      <ol className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-stretch">
        {steps.map((s, i) => (
          <Fragment key={s.title}>
            <li className="flex-1 rounded-lg border border-border-light bg-surface-secondary/40 p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle text-2xs font-bold text-oe-blue-text">
                  {i + 1}
                </span>
                <span className="flex items-center gap-1 text-xs font-semibold text-content-primary">
                  {s.icon}
                  {s.title}
                </span>
              </div>
              <p className="mt-1.5 text-2xs leading-relaxed text-content-tertiary">{s.desc}</p>
            </li>
            {i < steps.length - 1 && (
              <li
                aria-hidden="true"
                className="hidden shrink-0 items-center self-center text-content-quaternary lg:flex"
              >
                <ArrowRight size={16} />
              </li>
            )}
          </Fragment>
        ))}
      </ol>

      <div className="mt-3 flex flex-col gap-1.5 border-t border-border-light pt-3 text-2xs text-content-tertiary sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5 sm:gap-y-1">
        <span>
          <span className="font-medium text-content-secondary">
            {t('credentials.flow_sits_beside', { defaultValue: 'Sits beside:' })}
          </span>{' '}
          <ModLink to="/safety">
            {t('credentials.mod_safety', { defaultValue: 'Safety' })}
          </ModLink>
          {' · '}
          <ModLink to="/subcontractors">
            {t('credentials.mod_subcontractors', { defaultValue: 'Subcontractors' })}
          </ModLink>
          {' · '}
          <ModLink to="/teams">{t('credentials.mod_teams', { defaultValue: 'Teams' })}</ModLink>
          {' · '}
          <ModLink to="/deadlines">
            {t('credentials.mod_deadlines', { defaultValue: 'Deadline register' })}
          </ModLink>
        </span>
      </div>
    </CollapsibleSection>
  );
}

/* ── Small presentational pieces ────────────────────────────────────────── */

/** The signed day count as a chip, coloured by what it means. */
function ExpiryChip({ days, status }: { days: number | null; status: CredentialStatus }) {
  const { t } = useTranslation();
  if (days === null) return null;

  let text: string;
  if (days < 0) {
    text = t('credentials.lapsed_ago', {
      count: -days,
      defaultValue: 'lapsed {{count}} d ago',
    });
  } else if (days === 0) {
    text = t('credentials.expires_today', { defaultValue: 'expires today' });
  } else {
    text = t('credentials.expires_in', { count: days, defaultValue: 'in {{count}} d' });
  }

  const tone =
    days < 0
      ? 'bg-semantic-error/10 text-semantic-error'
      : status === 'expiring_soon'
        ? 'bg-semantic-warning/10 text-semantic-warning'
        : 'bg-surface-secondary text-content-tertiary';

  return (
    <span className={clsx('inline-flex items-center rounded-full px-2 py-0.5 text-2xs font-medium', tone)}>
      {text}
    </span>
  );
}

/**
 * One unmet requirement.
 *
 * The consequence chip is the point of the row. A blocking gap outside its
 * grace window is somebody being sent home; a non-blocking one is a note for
 * the next meeting. Those must not look alike, so they get different words,
 * different colours and different icons rather than the same pill in two
 * shades.
 */
function GapLine({ gap, typeName }: { gap: ComplianceGap; typeName: string }) {
  const { t } = useTranslation();

  const reasonText = t(`credentials.gap_reason.${gap.reason}`, {
    defaultValue: humanise(gap.reason),
  });

  const graceLeft = graceRemaining(gap);
  const stopsWork = gap.is_blocking && !gap.within_grace && gap.reason !== 'expiring_soon';

  let consequence: { text: string; icon: ReactNode; className: string };
  if (stopsWork) {
    consequence = {
      text: t('credentials.gap_stops_work', { defaultValue: 'Stops work today' }),
      icon: <Ban size={11} />,
      className: 'bg-semantic-error/10 text-semantic-error',
    };
  } else if (gap.is_blocking && gap.within_grace) {
    consequence = {
      text:
        graceLeft === null
          ? t('credentials.gap_in_grace', { defaultValue: 'Inside the grace period' })
          : t('credentials.gap_grace_left', {
              count: graceLeft,
              defaultValue: 'grace ends in {{count}} d',
            }),
      icon: <AlertTriangle size={11} />,
      className: 'bg-semantic-warning/10 text-semantic-warning',
    };
  } else if (gap.is_blocking) {
    consequence = {
      text: t('credentials.gap_will_stop_work', { defaultValue: 'Will stop work when it lapses' }),
      icon: <AlertTriangle size={11} />,
      className: 'bg-semantic-warning/10 text-semantic-warning',
    };
  } else {
    consequence = {
      text: t('credentials.gap_advisory', { defaultValue: 'Worth knowing, does not stop work' }),
      icon: <Info size={11} />,
      className: 'bg-oe-blue-subtle text-oe-blue-text',
    };
  }

  return (
    <li className="flex flex-wrap items-center gap-x-2 gap-y-1 py-1 text-xs">
      <span className="font-medium text-content-primary">{typeName}</span>
      <span className="text-content-tertiary">
        {gap.applies_to === APPLIES_TO_ALL
          ? t('credentials.applies_all_short', { defaultValue: 'everyone' })
          : gap.applies_to}
      </span>
      <Badge variant={gap.reason === 'missing' ? 'error' : 'neutral'} size="sm">
        {reasonText}
      </Badge>
      <span
        className={clsx(
          'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-medium',
          consequence.className,
        )}
      >
        {consequence.icon}
        {consequence.text}
      </span>
      {gap.valid_until && (
        <span className="text-content-tertiary">
          <DateDisplay value={gap.valid_until} />
        </span>
      )}
    </li>
  );
}

function HolderCard({
  row,
  typeName,
}: {
  row: ComplianceHolderRow;
  typeName: (code: string) => string;
}) {
  const { t } = useTranslation();
  const hasGaps = row.gaps.length > 0;

  return (
    <div
      className={clsx(
        'rounded-xl border bg-surface-elevated p-4',
        row.is_blocked ? 'border-semantic-error' : hasGaps ? 'border-border' : 'border-border-light',
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-content-primary">{row.holder_name}</span>
          <Badge variant="neutral" size="sm">
            {holderKindLabel(row.holder_kind, t)}
          </Badge>
          {row.discipline && (
            <span className="text-xs text-content-tertiary">{row.discipline}</span>
          )}
        </div>
        {row.is_blocked ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-semantic-error px-2.5 py-1 text-2xs font-bold uppercase tracking-wide text-white">
            <Ban size={12} />
            {t('credentials.holder_blocked', { defaultValue: 'May not work today' })}
          </span>
        ) : hasGaps ? (
          <Badge variant="warning" size="sm">
            {t('credentials.holder_attention', { defaultValue: 'Needs attention' })}
          </Badge>
        ) : (
          <Badge variant="success" size="sm" dot>
            {t('credentials.holder_clear', { defaultValue: 'Clear' })}
          </Badge>
        )}
      </div>

      {hasGaps && (
        <ul className="mt-2 divide-y divide-border-light/60 border-t border-border-light/60 pt-1">
          {row.gaps.map((g) => (
            <GapLine
              key={`${g.requirement_id}-${g.credential_id ?? 'missing'}`}
              gap={g}
              typeName={typeName(g.credential_type)}
            />
          ))}
        </ul>
      )}

      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-2xs text-content-tertiary">
        <span>
          {t('credentials.satisfied_count', {
            count: row.satisfied_count,
            defaultValue: '{{count}} requirements met',
          })}
        </span>
        {row.unverified_count > 0 && (
          <span className="text-semantic-warning">
            {t('credentials.unverified_count', {
              count: row.unverified_count,
              defaultValue: '{{count}} met by a credential nobody has checked',
            })}
          </span>
        )}
      </div>
    </div>
  );
}

/* ── Page ───────────────────────────────────────────────────────────────── */

export function CredentialsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { projectId: routeProjectId } = useParams<{ projectId?: string }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectId = routeProjectId || activeProjectId || '';

  const [tab, setTab] = useState<TabId>('compliance');
  const [statusFilter, setStatusFilter] = useState<CredentialStatus | ''>('');
  const [typeFilter, setTypeFilter] = useState('');
  const [search, setSearch] = useState('');
  const [holderFilter, setHolderFilter] = useState<HolderFilter>('all');
  const [includeInactive, setIncludeInactive] = useState(false);
  const [credModal, setCredModal] = useState<{ open: boolean; item: Credential | null }>({
    open: false,
    item: null,
  });
  const [reqModal, setReqModal] = useState<{ open: boolean; item: Requirement | null }>({
    open: false,
    item: null,
  });

  const enabled = !!projectId;

  const metaQuery = useQuery({
    queryKey: ['credentials-meta'],
    queryFn: fetchMeta,
    enabled,
    staleTime: 30 * 60_000,
  });
  const meta = metaQuery.data;

  const credentialsQuery = useQuery({
    queryKey: ['credentials', projectId, statusFilter, typeFilter],
    queryFn: () =>
      fetchCredentials({
        project_id: projectId,
        status: statusFilter,
        credential_type: typeFilter || undefined,
      }),
    enabled,
  });

  const requirementsQuery = useQuery({
    queryKey: ['credentials-requirements', projectId, includeInactive],
    queryFn: () => fetchRequirements({ project_id: projectId, include_inactive: includeInactive }),
    enabled,
  });

  const complianceQuery = useQuery({
    queryKey: ['credentials-compliance', projectId],
    queryFn: () => fetchCompliance(projectId),
    enabled,
  });

  const summaryQuery = useQuery({
    queryKey: ['credentials-summary', projectId],
    queryFn: () => fetchSummary(projectId),
    enabled,
  });

  const validationQuery = useQuery({
    queryKey: ['credentials-validation', projectId],
    queryFn: () => fetchValidation(projectId),
    enabled: enabled && tab === 'register',
  });

  const expiringQuery = useQuery({
    queryKey: ['credentials-expiring', projectId],
    queryFn: () => fetchExpiringSoon({ project_id: projectId, limit: 10 }),
    enabled: enabled && tab === 'compliance',
  });

  // ── Derived values. Every hook below sits above the first early return, so
  //    no branch of this component can render a different number of them.
  const typeName = useCallback((code: string) => typeLabel(code, meta, t), [meta, t]);
  const statusName = useCallback((code: string) => statusLabel(code, meta, t), [meta, t]);

  const credentials = useMemo(() => credentialsQuery.data ?? [], [credentialsQuery.data]);
  const requirements = useMemo(() => requirementsQuery.data ?? [], [requirementsQuery.data]);
  const compliance = complianceQuery.data;
  const summary = summaryQuery.data;

  // Free-text narrowing happens on the client because the API filters on
  // status, type and holder id only - there is no search parameter to pass.
  const visibleCredentials = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (needle === '') return credentials;
    return credentials.filter((c) =>
      [c.holder_name, c.authority, c.identifier, c.jurisdiction, c.discipline]
        .filter((v): v is string => typeof v === 'string' && v !== '')
        .some((v) => v.toLowerCase().includes(needle)),
    );
  }, [credentials, search]);

  const visibleHolders = useMemo(() => {
    const holders = compliance?.holders ?? [];
    if (holderFilter === 'blocked') return holders.filter((h) => h.is_blocked);
    if (holderFilter === 'gaps') return holders.filter((h) => h.gaps.length > 0);
    return holders;
  }, [compliance, holderFilter]);

  const unmatchedRequirements = useMemo(() => {
    const ids = new Set(compliance?.unmatched_requirement_ids ?? []);
    if (ids.size === 0) return [];
    return requirements.filter((r) => ids.has(r.id));
  }, [compliance, requirements]);

  const staleCount = summary?.stale_status_count ?? 0;

  const insights = useModuleInsights('credentials', { defaultOpen: false });
  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildCredentialsInsights(credentials, t, typeName, statusName),
    [credentials, t, typeName, statusName],
  );

  const kpis = useMemo<KpiBandItem[]>(() => {
    const items: KpiBandItem[] = [
      {
        key: 'blocked',
        label: t('credentials.kpi_blocked', { defaultValue: 'May not work today' }),
        value: compliance?.blocked_holder_count ?? 0,
        icon: Ban,
        tone: (compliance?.blocked_holder_count ?? 0) > 0 ? 'danger' : 'success',
        tintValue: true,
        sub: t('credentials.kpi_blocked_sub', {
          count: compliance?.holder_count ?? 0,
          defaultValue: 'of {{count}} holders on the register',
        }),
      },
      {
        key: 'expiring',
        label: t('credentials.kpi_expiring', { defaultValue: 'Expiring in 30 days' }),
        value: summary?.expiring_within_30_days ?? 0,
        icon: CalendarClock,
        tone: (summary?.expiring_within_30_days ?? 0) > 0 ? 'warning' : 'default',
      },
      {
        key: 'expired',
        label: t('credentials.kpi_expired', { defaultValue: 'Already expired' }),
        value: summary?.expired ?? 0,
        icon: AlertTriangle,
        tone: (summary?.expired ?? 0) > 0 ? 'danger' : 'default',
      },
      {
        key: 'unverified',
        label: t('credentials.kpi_unverified', { defaultValue: 'Never verified' }),
        value: summary?.unverified ?? 0,
        icon: ShieldAlert,
        tone: 'default',
      },
      {
        key: 'requirements',
        label: t('credentials.kpi_requirements', { defaultValue: 'Requirements in force' }),
        value: compliance?.requirement_count ?? 0,
        icon: ClipboardList,
        tone: 'blue',
      },
      {
        key: 'total',
        label: t('credentials.kpi_total', { defaultValue: 'Credentials held' }),
        value: summary?.total ?? 0,
        icon: BadgeCheck,
        tone: 'default',
        sub:
          (summary?.perpetual ?? 0) > 0
            ? t('credentials.kpi_perpetual_sub', {
                count: summary?.perpetual ?? 0,
                defaultValue: '{{count}} with no expiry date',
              })
            : undefined,
      },
    ];
    return items;
  }, [compliance, summary, t]);

  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['credentials'] });
    qc.invalidateQueries({ queryKey: ['credentials-requirements'] });
    qc.invalidateQueries({ queryKey: ['credentials-compliance'] });
    qc.invalidateQueries({ queryKey: ['credentials-summary'] });
    qc.invalidateQueries({ queryKey: ['credentials-validation'] });
    qc.invalidateQueries({ queryKey: ['credentials-expiring'] });
  }, [qc]);

  const failed = useCallback(
    (fallback: string) => (e: Error) =>
      addToast({ type: 'error', title: fallback, message: e.message }),
    [addToast],
  );

  const saveCredentialMut = useMutation({
    mutationFn: (vars: { id: string | null; data: Omit<CredentialCreatePayload, 'project_id'> }) =>
      vars.id === null
        ? createCredential({ ...vars.data, project_id: projectId })
        : updateCredential(vars.id, vars.data),
    onSuccess: (_res, vars) => {
      setCredModal({ open: false, item: null });
      invalidateAll();
      addToast({
        type: 'success',
        title:
          vars.id === null
            ? t('credentials.toast_created', { defaultValue: 'Credential added' })
            : t('credentials.toast_updated', { defaultValue: 'Credential saved' }),
      });
    },
    onError: failed(t('credentials.toast_save_failed', { defaultValue: 'Could not save the credential' })),
  });

  const deleteCredentialMut = useMutation({
    mutationFn: (id: string) => deleteCredential(id),
    onSuccess: () => {
      invalidateAll();
      addToast({ type: 'success', title: t('credentials.toast_deleted', { defaultValue: 'Credential removed' }) });
    },
    onError: failed(t('credentials.toast_delete_failed', { defaultValue: 'Could not remove the credential' })),
  });

  const verifyMut = useMutation({
    mutationFn: (vars: { id: string; verified: boolean }) =>
      verifyCredential(vars.id, { verified: vars.verified }),
    onSuccess: (_res, vars) => {
      invalidateAll();
      addToast({
        type: 'success',
        title: vars.verified
          ? t('credentials.toast_verified', { defaultValue: 'Marked as checked' })
          : t('credentials.toast_unverified', { defaultValue: 'Verification withdrawn' }),
      });
    },
    onError: failed(t('credentials.toast_verify_failed', { defaultValue: 'Could not record the check' })),
  });

  const saveRequirementMut = useMutation({
    mutationFn: (vars: { id: string | null; data: Omit<RequirementCreatePayload, 'project_id'> }) =>
      vars.id === null
        ? createRequirement({ ...vars.data, project_id: projectId })
        : updateRequirement(vars.id, vars.data),
    onSuccess: (_res, vars) => {
      setReqModal({ open: false, item: null });
      invalidateAll();
      addToast({
        type: 'success',
        title:
          vars.id === null
            ? t('credentials.toast_req_created', { defaultValue: 'Requirement added' })
            : t('credentials.toast_req_updated', { defaultValue: 'Requirement saved' }),
      });
    },
    onError: failed(t('credentials.toast_req_save_failed', { defaultValue: 'Could not save the requirement' })),
  });

  const deleteRequirementMut = useMutation({
    mutationFn: (id: string) => deleteRequirement(id),
    onSuccess: () => {
      invalidateAll();
      addToast({ type: 'success', title: t('credentials.toast_req_deleted', { defaultValue: 'Requirement removed' }) });
    },
    onError: failed(t('credentials.toast_req_delete_failed', { defaultValue: 'Could not remove the requirement' })),
  });

  const refreshMut = useMutation({
    mutationFn: () => refreshStatuses(projectId),
    onSuccess: (res) => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('credentials.toast_refreshed', {
          count: res.updated,
          defaultValue: '{{count}} stored statuses brought up to date',
        }),
      });
    },
    onError: failed(t('credentials.toast_refresh_failed', { defaultValue: 'Could not refresh the statuses' })),
  });

  const { confirm, ...confirmProps } = useConfirm();

  const askDeleteCredential = useCallback(
    async (c: Credential) => {
      const ok = await confirm({
        title: t('credentials.confirm_delete_title', { defaultValue: 'Remove this credential?' }),
        message: t('credentials.confirm_delete_msg', {
          defaultValue:
            'This deletes the record of "{{holder}}" holding this credential. Any requirement it was meeting will start reporting as missing.',
          holder: c.holder_name,
        }),
      });
      if (ok) deleteCredentialMut.mutate(c.id);
    },
    [confirm, deleteCredentialMut, t],
  );

  const askDeleteRequirement = useCallback(
    async (r: Requirement) => {
      const ok = await confirm({
        title: t('credentials.confirm_req_delete_title', { defaultValue: 'Remove this requirement?' }),
        message: t('credentials.confirm_req_delete_msg', {
          defaultValue:
            'Gaps against this rule stop being reported straight away. To pause it instead, turn off "in force" and the history stays.',
        }),
      });
      if (ok) deleteRequirementMut.mutate(r.id);
    },
    [confirm, deleteRequirementMut, t],
  );

  const tabs: TabBarTab<TabId>[] = [
    {
      id: 'compliance',
      label: t('credentials.tab_compliance', { defaultValue: 'Who may not work today' }),
      icon: <ShieldAlert size={14} />,
      badge:
        (compliance?.blocked_holder_count ?? 0) > 0 ? (
          <Badge variant="error" size="sm">
            {compliance?.blocked_holder_count ?? 0}
          </Badge>
        ) : undefined,
    },
    {
      id: 'register',
      label: t('credentials.tab_register', { defaultValue: 'Register' }),
      icon: <BadgeCheck size={14} />,
    },
    {
      id: 'requirements',
      label: t('credentials.tab_requirements', { defaultValue: 'Requirements' }),
      icon: <ClipboardList size={14} />,
    },
  ];

  const holderFilters: HolderFilter[] = ['all', 'gaps', 'blocked'];
  function holderFilterLabel(f: HolderFilter): string {
    if (f === 'blocked') return t('credentials.holders_blocked', { defaultValue: 'Blocked only' });
    if (f === 'gaps') return t('credentials.holders_gaps', { defaultValue: 'With gaps' });
    return t('credentials.holders_all', { defaultValue: 'Everyone' });
  }

  return (
    <div className="w-full">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <BadgeCheck size={22} className="mt-0.5 shrink-0 text-oe-blue" />
          <div>
            <h1 className="text-xl font-semibold text-content-primary">
              {t('credentials.page_title', { defaultValue: 'Credentials register' })}
            </h1>
            <p className="mt-0.5 text-sm text-content-secondary">
              {t('credentials.page_subtitle', {
                defaultValue:
                  'Licences, certifications and training on this project, what the project requires of whom, and who that leaves unable to work today.',
              })}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {staleCount > 0 && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => refreshMut.mutate()}
              disabled={refreshMut.isPending}
            >
              <RefreshCw size={14} className={clsx('me-1.5', refreshMut.isPending && 'animate-spin')} />
              {t('credentials.refresh_statuses', {
                count: staleCount,
                defaultValue: 'Refresh {{count}} stored statuses',
              })}
            </Button>
          )}
        </div>
      </div>

      <div className="mb-4">
        <HowCredentialsWork />
      </div>

      <RequiresProject
        emptyHint={t('credentials.no_project', {
          defaultValue:
            'Pick a project from the header to see which credentials it holds and what it requires.',
        })}
      >
        <KpiBand items={kpis} columns={6} size="sm" className="mb-4" />

        <TabBar
          tabs={tabs}
          activeId={tab}
          onChange={setTab}
          ariaLabel={t('credentials.tabs_aria', { defaultValue: 'Credentials sections' })}
          className="mb-4"
          idPrefix="credentials"
        />

        {/* ── Compliance ───────────────────────────────────────────── */}
        {tab === 'compliance' && (
          <div>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="inline-flex rounded-lg border border-border-light bg-surface-secondary p-0.5">
                {holderFilters.map((f) => (
                  <button
                    key={f}
                    type="button"
                    onClick={() => setHolderFilter(f)}
                    className={clsx(
                      'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                      holderFilter === f
                        ? 'bg-surface-elevated text-content-primary shadow-sm'
                        : 'text-content-secondary hover:text-content-primary',
                    )}
                  >
                    {holderFilterLabel(f)}
                  </button>
                ))}
              </div>
              {compliance && (
                <span className="text-xs text-content-tertiary">
                  {t('credentials.as_of', { defaultValue: 'As of' })}{' '}
                  <DateDisplay value={compliance.as_of} />
                </span>
              )}
            </div>

            {complianceQuery.isLoading ? (
              <div className="flex items-center justify-center p-8 text-content-tertiary">
                <Loader2 className="me-2 animate-spin" size={16} />
                {t('common.loading', { defaultValue: 'Loading...' })}
              </div>
            ) : complianceQuery.isError ? (
              <div className="p-8 text-center">
                <XCircle size={24} className="mx-auto mb-2 text-semantic-error" />
                <p className="mb-3 text-sm text-content-secondary">
                  {t('credentials.compliance_error', {
                    defaultValue: "Couldn't work out who is compliant",
                  })}
                </p>
                <Button variant="secondary" size="sm" onClick={() => complianceQuery.refetch()}>
                  {t('common.retry', { defaultValue: 'Try again' })}
                </Button>
              </div>
            ) : (compliance?.requirement_count ?? 0) === 0 ? (
              <EmptyState
                icon={<ClipboardList size={28} strokeWidth={1.5} />}
                title={t('credentials.no_requirements_title', {
                  defaultValue: 'Nothing is required yet, so nobody can be short of it',
                })}
                description={t('credentials.no_requirements_desc', {
                  defaultValue:
                    'This report measures holders against what the project demands. Until a requirement exists it has nothing to measure, and an empty result here means the rules are missing rather than that everyone is qualified.',
                })}
                action={
                  <Button onClick={() => setTab('requirements')}>
                    {t('credentials.go_to_requirements', { defaultValue: 'Set the requirements' })}
                  </Button>
                }
              />
            ) : visibleHolders.length === 0 ? (
              <EmptyState
                icon={<CheckCircle2 size={28} strokeWidth={1.5} />}
                title={
                  holderFilter === 'all'
                    ? t('credentials.no_holders_title', { defaultValue: 'No holders to measure' })
                    : t('credentials.nobody_blocked_title', { defaultValue: 'Nobody is held up' })
                }
                description={
                  holderFilter === 'all'
                    ? t('credentials.no_holders_desc', {
                        defaultValue:
                          'The requirements are in place but the register holds no matching person or firm, so there is nobody to assess. Add credentials and the holders appear here.',
                      })
                    : t('credentials.nobody_blocked_desc', {
                        defaultValue: 'Everyone measured against the current rules comes back clear.',
                      })
                }
              />
            ) : (
              <div className="flex flex-col gap-2">
                {visibleHolders.map((h) => (
                  <HolderCard
                    key={`${h.holder_name}-${h.holder_user_id ?? 'anon'}`}
                    row={h}
                    typeName={typeName}
                  />
                ))}
              </div>
            )}

            {unmatchedRequirements.length > 0 && (
              <div className="mt-4 rounded-xl border border-semantic-warning/40 bg-semantic-warning/5 p-4">
                <div className="flex items-center gap-2">
                  <Users size={15} className="text-semantic-warning" />
                  <h3 className="text-sm font-semibold text-content-primary">
                    {t('credentials.unmatched_title', {
                      count: unmatchedRequirements.length,
                      defaultValue: '{{count}} requirements bind nobody',
                    })}
                  </h3>
                </div>
                <p className="mt-1 text-xs text-content-tertiary">
                  {t('credentials.unmatched_desc', {
                    defaultValue:
                      'No holder on the register matches these rules, so they are neither met nor broken. Usually that means the rule is aimed at a discipline nobody has been entered under.',
                  })}
                </p>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {unmatchedRequirements.map((r) => (
                    <li key={r.id}>
                      <Badge variant="warning" size="sm">
                        {typeName(r.credential_type)}
                        {r.applies_to !== APPLIES_TO_ALL && ` · ${r.applies_to}`}
                      </Badge>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {(expiringQuery.data?.length ?? 0) > 0 && (
              <div className="mt-4 rounded-xl border border-border-light bg-surface-elevated p-4">
                <div className="flex items-center gap-2">
                  <CalendarClock size={15} className="text-oe-blue" />
                  <h3 className="text-sm font-semibold text-content-primary">
                    {t('credentials.renewals_title', { defaultValue: 'Renewals ahead' })}
                  </h3>
                </div>
                <p className="mt-1 text-xs text-content-tertiary">
                  {t('credentials.renewals_desc', {
                    defaultValue:
                      'Soonest first, whether or not a requirement covers them. A credential nobody demands can still be the one that stops a delivery.',
                  })}
                </p>
                <ul className="mt-2 divide-y divide-border-light/60">
                  {(expiringQuery.data ?? []).map((c) => (
                    <li key={c.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5 text-xs">
                      <span className="font-medium text-content-primary">{c.holder_name}</span>
                      <span className="text-content-secondary">{typeName(c.credential_type)}</span>
                      <DateDisplay value={c.valid_until} className="text-content-tertiary" />
                      <ExpiryChip days={c.days_until_expiry} status={c.status} />
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* ── Register ─────────────────────────────────────────────── */}
        {tab === 'register' && (
          <div>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <div className="w-full sm:w-72">
                <Input
                  id="credentials-search"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t('credentials.search_placeholder', {
                    defaultValue: 'Search holder, authority or reference',
                  })}
                  autoComplete="off"
                />
              </div>
              <select
                className="h-9 rounded-md border border-border bg-surface-primary px-2.5 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as CredentialStatus | '')}
                aria-label={t('credentials.field.status', { defaultValue: 'Standing' })}
              >
                <option value="">
                  {t('credentials.all_statuses', { defaultValue: 'Any standing' })}
                </option>
                {(meta?.statuses ?? []).map((s) => (
                  <option key={s.code} value={s.code}>
                    {statusName(s.code)}
                  </option>
                ))}
              </select>
              <select
                className="h-9 rounded-md border border-border bg-surface-primary px-2.5 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                aria-label={t('credentials.field.credential_type', { defaultValue: 'Credential type' })}
              >
                <option value="">{t('credentials.all_types', { defaultValue: 'Any type' })}</option>
                {(meta?.credential_types ?? []).map((o) => (
                  <option key={o.code} value={o.code}>
                    {typeName(o.code)}
                  </option>
                ))}
              </select>
              <div className="ms-auto flex items-center gap-2">
                <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
                <Button size="sm" onClick={() => setCredModal({ open: true, item: null })}>
                  <Plus size={14} className="me-1.5" />
                  {t('credentials.add_credential', { defaultValue: 'Add credential' })}
                </Button>
              </div>
            </div>

            <InsightsPanel
              open={insights.open}
              title={t('credentials.insights.title', { defaultValue: 'Register insights' })}
              datasets={insightDatasets}
              builtins={insightBuiltins}
              custom={insights.custom}
              onAdd={insights.addCustom}
              onUpdate={insights.updateCustom}
              onRemove={insights.removeCustom}
              onCollapse={() => insights.setOpen(false)}
            />

            {(validationQuery.data?.findings.length ?? 0) > 0 && (
              <div className="mb-3 rounded-xl border border-border-light bg-surface-elevated p-4">
                <div className="flex items-center gap-2">
                  <AlertTriangle size={15} className="text-semantic-warning" />
                  <h3 className="text-sm font-semibold text-content-primary">
                    {t('credentials.validation_title', { defaultValue: 'What the rules flag' })}
                  </h3>
                </div>
                <ul className="mt-2 flex flex-col gap-1">
                  {(validationQuery.data?.findings ?? []).map((f, i) => (
                    <li key={`${f.rule_id}-${i}`} className="flex items-start gap-2 text-xs">
                      <Badge variant={f.severity === 'error' ? 'error' : 'warning'} size="sm">
                        {t(`credentials.severity.${f.severity}`, { defaultValue: humanise(f.severity) })}
                      </Badge>
                      <span className="text-content-secondary">
                        {t(f.key, { defaultValue: f.message })}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {credentialsQuery.isLoading ? (
              <SkeletonTable rows={5} />
            ) : credentialsQuery.isError ? (
              <div className="p-8 text-center">
                <XCircle size={24} className="mx-auto mb-2 text-semantic-error" />
                <p className="mb-3 text-sm text-content-secondary">
                  {t('credentials.load_error', { defaultValue: "Couldn't load the register" })}
                </p>
                <Button variant="secondary" size="sm" onClick={() => credentialsQuery.refetch()}>
                  {t('common.retry', { defaultValue: 'Try again' })}
                </Button>
              </div>
            ) : visibleCredentials.length === 0 ? (
              <EmptyState
                icon={<BadgeCheck size={28} strokeWidth={1.5} />}
                title={t('credentials.empty_title', { defaultValue: 'No credentials recorded yet' })}
                description={t('credentials.empty_desc', {
                  defaultValue:
                    'Add the licences, certifications and training the people and firms on this project hold, and the register starts warning you before any of them lapse.',
                })}
                action={
                  <Button onClick={() => setCredModal({ open: true, item: null })}>
                    {t('credentials.add_credential', { defaultValue: 'Add credential' })}
                  </Button>
                }
              />
            ) : (
              <div className="overflow-x-auto rounded-xl border border-border-light bg-surface-elevated">
                <table className="w-full min-w-[900px] text-sm">
                  <thead>
                    <tr className="border-b border-border-light text-start text-xs uppercase tracking-wide text-content-tertiary">
                      <th className="px-4 py-2.5 text-start font-medium">
                        {t('credentials.col_holder', { defaultValue: 'Holder' })}
                      </th>
                      <th className="px-4 py-2.5 text-start font-medium">
                        {t('credentials.col_type', { defaultValue: 'Type' })}
                      </th>
                      <th className="px-4 py-2.5 text-start font-medium">
                        {t('credentials.col_authority', { defaultValue: 'Authority' })}
                      </th>
                      <th className="px-4 py-2.5 text-start font-medium">
                        {t('credentials.col_jurisdiction', { defaultValue: 'Jurisdiction' })}
                      </th>
                      <th className="px-4 py-2.5 text-start font-medium">
                        {t('credentials.col_valid_until', { defaultValue: 'Valid until' })}
                      </th>
                      <th className="px-4 py-2.5 text-start font-medium">
                        {t('credentials.col_status', { defaultValue: 'Standing' })}
                      </th>
                      <th className="px-4 py-2.5 text-end font-medium">
                        {t('credentials.col_actions', { defaultValue: 'Actions' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleCredentials.map((c) => (
                      <tr key={c.id} className="border-b border-border-light/60 last:border-0">
                        <td className="px-4 py-2.5">
                          <div className="font-medium text-content-primary">{c.holder_name}</div>
                          <div className="text-2xs text-content-tertiary">
                            {holderKindLabel(c.holder_kind, t)}
                            {c.discipline ? ` · ${c.discipline}` : ''}
                          </div>
                        </td>
                        <td className="px-4 py-2.5 text-content-secondary">
                          <div>{typeName(c.credential_type)}</div>
                          {c.identifier && (
                            <div className="text-2xs text-content-tertiary">{c.identifier}</div>
                          )}
                        </td>
                        <td className="px-4 py-2.5 text-content-secondary">{c.authority ?? '-'}</td>
                        <td className="px-4 py-2.5 text-content-secondary">{c.jurisdiction ?? '-'}</td>
                        <td className="whitespace-nowrap px-4 py-2.5">
                          {c.valid_until === null ? (
                            <span className="text-2xs text-content-tertiary">
                              {t('credentials.no_expiry', { defaultValue: 'Does not expire' })}
                            </span>
                          ) : (
                            <div className="flex flex-col gap-1">
                              <DateDisplay value={c.valid_until} className="text-content-secondary" />
                              <ExpiryChip days={c.days_until_expiry} status={c.status} />
                            </div>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-4 py-2.5">
                          <Badge variant={badgeVariant(c.status)} size="sm" dot>
                            {statusName(c.status)}
                          </Badge>
                          <div className="mt-1 text-2xs text-content-tertiary">
                            {c.verified_at ? (
                              <span className="inline-flex items-center gap-1 text-semantic-success">
                                <CheckCircle2 size={11} />
                                <DateDisplay value={c.verified_at} />
                              </span>
                            ) : (
                              t('credentials.never_verified', { defaultValue: 'Never checked' })
                            )}
                          </div>
                        </td>
                        <td className="whitespace-nowrap px-4 py-2.5 text-end">
                          <div className="inline-flex items-center gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={verifyMut.isPending}
                              onClick={() => verifyMut.mutate({ id: c.id, verified: !c.verified_at })}
                              title={
                                c.verified_at
                                  ? t('credentials.action_unverify', { defaultValue: 'Withdraw the check' })
                                  : t('credentials.action_verify', {
                                      defaultValue: 'Record that you checked this with the authority',
                                    })
                              }
                            >
                              <ShieldAlert size={14} />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setCredModal({ open: true, item: c })}
                              title={t('common.edit', { defaultValue: 'Edit' })}
                            >
                              <Pencil size={14} />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => void askDeleteCredential(c)}
                              title={t('common.delete', { defaultValue: 'Delete' })}
                            >
                              <Trash2 size={14} className="text-semantic-error" />
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* ── Requirements ─────────────────────────────────────────── */}
        {tab === 'requirements' && (
          <div>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-content-secondary">
                <input
                  type="checkbox"
                  checked={includeInactive}
                  onChange={(e) => setIncludeInactive(e.target.checked)}
                  className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
                />
                {t('credentials.show_inactive', { defaultValue: 'Include rules not in force' })}
              </label>
              <div className="ms-auto">
                <Button size="sm" onClick={() => setReqModal({ open: true, item: null })}>
                  <Plus size={14} className="me-1.5" />
                  {t('credentials.add_requirement', { defaultValue: 'Add requirement' })}
                </Button>
              </div>
            </div>

            {requirementsQuery.isLoading ? (
              <SkeletonTable rows={4} />
            ) : requirementsQuery.isError ? (
              <div className="p-8 text-center">
                <XCircle size={24} className="mx-auto mb-2 text-semantic-error" />
                <p className="mb-3 text-sm text-content-secondary">
                  {t('credentials.req_load_error', {
                    defaultValue: "Couldn't load what the project requires",
                  })}
                </p>
                <Button variant="secondary" size="sm" onClick={() => requirementsQuery.refetch()}>
                  {t('common.retry', { defaultValue: 'Try again' })}
                </Button>
              </div>
            ) : requirements.length === 0 ? (
              <EmptyState
                icon={<ClipboardList size={28} strokeWidth={1.5} />}
                title={t('credentials.req_empty_title', {
                  defaultValue: 'The project demands nothing yet',
                })}
                description={t('credentials.req_empty_desc', {
                  defaultValue:
                    'A requirement is what turns an absent credential into a reported gap. Until one exists the compliance report has nothing to measure and will always come back clear.',
                })}
                action={
                  <Button onClick={() => setReqModal({ open: true, item: null })}>
                    {t('credentials.add_requirement', { defaultValue: 'Add requirement' })}
                  </Button>
                }
              />
            ) : (
              <div className="flex flex-col gap-2">
                {requirements.map((r) => (
                  <div
                    key={r.id}
                    className={clsx(
                      'rounded-xl border bg-surface-elevated p-4',
                      r.is_active ? 'border-border-light' : 'border-dashed border-border-light opacity-70',
                    )}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-semibold text-content-primary">
                            {typeName(r.credential_type)}
                          </span>
                          {r.is_blocking ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-semantic-error/10 px-2 py-0.5 text-2xs font-semibold text-semantic-error">
                              <Ban size={11} />
                              {t('credentials.req_blocking', { defaultValue: 'Stops work' })}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 rounded-full bg-oe-blue-subtle px-2 py-0.5 text-2xs font-semibold text-oe-blue-text">
                              <Info size={11} />
                              {t('credentials.req_advisory', { defaultValue: 'Worth knowing' })}
                            </span>
                          )}
                          {!r.is_active && (
                            <Badge variant="neutral" size="sm">
                              {t('credentials.req_paused', { defaultValue: 'Not in force' })}
                            </Badge>
                          )}
                        </div>
                        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-2xs text-content-tertiary">
                          <span>
                            {t('credentials.req_applies_to', { defaultValue: 'Applies to' })}:{' '}
                            {r.applies_to === APPLIES_TO_ALL
                              ? t('credentials.req_form.applies_all', {
                                  defaultValue: 'Everyone on the register',
                                })
                              : r.applies_to}
                          </span>
                          <span>{holderKindLabel(r.holder_kind, t)}</span>
                          <span>
                            {r.grace_days > 0
                              ? t('credentials.req_grace', {
                                  count: r.grace_days,
                                  defaultValue: '{{count}} days of grace after expiry',
                                })
                              : t('credentials.req_no_grace', { defaultValue: 'No grace after expiry' })}
                          </span>
                        </div>
                        {r.description && (
                          <p className="mt-1.5 text-xs text-content-secondary">{r.description}</p>
                        )}
                      </div>
                      <div className="inline-flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setReqModal({ open: true, item: r })}
                          title={t('common.edit', { defaultValue: 'Edit' })}
                        >
                          <Pencil size={14} />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => void askDeleteRequirement(r)}
                          title={t('common.delete', { defaultValue: 'Delete' })}
                        >
                          <Trash2 size={14} className="text-semantic-error" />
                        </Button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </RequiresProject>

      <CredentialFormModal
        open={credModal.open}
        onClose={() => setCredModal({ open: false, item: null })}
        credential={credModal.item}
        meta={meta}
        busy={saveCredentialMut.isPending}
        onSubmit={(data) => saveCredentialMut.mutate({ id: credModal.item?.id ?? null, data })}
      />

      <RequirementFormModal
        open={reqModal.open}
        onClose={() => setReqModal({ open: false, item: null })}
        requirement={reqModal.item}
        meta={meta}
        busy={saveRequirementMut.isPending}
        onSubmit={(data) => saveRequirementMut.mutate({ id: reqModal.item?.id ?? null, data })}
      />

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
