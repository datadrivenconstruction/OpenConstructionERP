// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * DeadlinesPage - the cross-module deadline register (item #18).
 *
 * Aggregates overdue + approaching work from the thirteen collectors registered
 * in app/modules/deadlines/service.py into one read-only register, grouped by
 * module and filterable by all / overdue / approaching. Server state lives
 * entirely in React Query - no new Zustand store.
 */
import { Fragment, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  AlarmClock,
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  Hourglass,
  Inbox,
  Loader2,
  XCircle,
} from 'lucide-react';
import clsx from 'clsx';
import { Button, CollapsibleSection } from '@/shared/ui';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { fetchDeadlines, type DeadlineItem, type DeadlineStatusFilter } from './api';
import { buildDeadlinesInsights } from './deadlinesInsights';

const FILTERS: DeadlineStatusFilter[] = ['all', 'overdue', 'approaching'];

// One entry per backend collector (app/modules/deadlines/service.py:_COLLECTORS).
// The group heading falls back to the raw module key when a source is missing
// here, so every new collector needs a row - the English `def` keeps the heading
// readable in locales that have not picked up the key yet.
const MODULE_LABELS: Record<string, { key: string; def: string }> = {
  correspondence: { key: 'deadlines.module.correspondence', def: 'Correspondence' },
  qms_ncr_action: { key: 'deadlines.module.qms_ncr_action', def: 'NCR actions' },
  punchlist: { key: 'deadlines.module.punchlist', def: 'Punch list' },
  rfi: { key: 'deadlines.module.rfi', def: 'RFIs' },
  submittals: { key: 'deadlines.module.submittals', def: 'Submittals' },
  variations: { key: 'deadlines.module.variations', def: 'Variation decisions' },
  temporary_works: { key: 'deadlines.module.temporary_works', def: 'Temporary works design' },
  temporary_works_permit: {
    key: 'deadlines.module.temporary_works_permit',
    def: 'Temporary works permits',
  },
  defects_liability: { key: 'deadlines.module.defects_liability', def: 'Defect rectification' },
  inspections: { key: 'deadlines.module.inspections', def: 'Inspections' },
  compliance_docs: { key: 'deadlines.module.compliance_docs', def: 'Compliance documents' },
  bid_management: { key: 'deadlines.module.bid_management', def: 'Bid submissions' },
  signing: { key: 'deadlines.module.signing', def: 'Signatures' },
  contracts_payment_plan_claim: {
    key: 'deadlines.module.contracts_payment_plan_claim',
    def: 'Claims to raise',
  },
  contracts_payment_plan: {
    key: 'deadlines.module.contracts_payment_plan',
    def: 'Payment instalments',
  },
};

// Explainer chips, one per collector, in _COLLECTORS order.
//
// Deliberately a separate family from MODULE_LABELS above, which is not
// interchangeable with it. MODULE_LABELS names the *kind of item* that carries
// the date, because it heads a group of rows ("Bid submissions", "Defect
// rectification"). These name the *place you land*, because they are links, so
// they follow the module's own sidebar label shortened to chip length ("Bid
// management", "Defects liability"). Merging the two would put item types in a
// row of navigation chips.
const PULLS_FROM: { key: string; def: string; to: string }[] = [
  { key: 'deadlines.mod_correspondence', def: 'Correspondence', to: '/correspondence' },
  { key: 'deadlines.mod_ncr', def: 'NCR register', to: '/ncr' },
  { key: 'deadlines.mod_punchlist', def: 'Punch list', to: '/punchlist' },
  { key: 'deadlines.mod_rfi', def: 'RFIs', to: '/rfi' },
  { key: 'deadlines.mod_submittals', def: 'Submittals', to: '/submittals' },
  { key: 'deadlines.mod_variations', def: 'Variations', to: '/variations' },
  { key: 'deadlines.mod_temporary_works', def: 'Temporary works', to: '/temporary-works' },
  // Designs and permits are two collectors with two due dates on one screen.
  { key: 'deadlines.mod_temporary_works_permit', def: 'Work permits', to: '/temporary-works' },
  { key: 'deadlines.mod_defects_liability', def: 'Defects liability', to: '/defects-liability' },
  { key: 'deadlines.mod_inspections', def: 'Inspections', to: '/inspections' },
  // The compliance register has no standalone route - it is a tab on the
  // project page, which is where the item's own action_url points. Resolved
  // against the active project below; /projects is the fallback when none is.
  { key: 'deadlines.mod_compliance_docs', def: 'Compliance documents', to: '/projects' },
  { key: 'deadlines.mod_bid_management', def: 'Bid management', to: '/bid-management' },
  { key: 'deadlines.mod_signing', def: 'E-signatures', to: '/signing' },
  // A reached instalment nobody has claimed yet, and an instalment the client
  // owes: two collectors, both answered on the contract's payment plan.
  { key: 'deadlines.mod_contracts_payment_plan_claim', def: 'Instalment claims', to: '/contracts' },
  { key: 'deadlines.mod_contracts_payment_plan', def: 'Payment plans', to: '/contracts' },
];

// Where an overdue date ends up: the sweeper writes deadline_overdue and
// deadline_escalated notifications, and the inbox rolls unread notifications in.
const FEEDS: { key: string; def: string; to: string }[] = [
  { key: 'deadlines.mod_notifications', def: 'Notifications', to: '/notifications' },
  { key: 'deadlines.mod_inbox', def: 'Inbox', to: '/inbox' },
];

/** Humanise a source-native status string ("awaiting_response" -> "Awaiting response"). */
function humaniseStatus(status: string): string {
  const s = status.replace(/_/g, ' ').trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/**
 * One-glance explainer: what the deadline register is and, just as importantly,
 * what it is not.
 *
 * This page owns nothing. It creates no deadlines of its own, it aggregates
 * only the sources that carry a date, and an item leaves the list by being
 * answered in its own module, not here. A site manager who reads it as
 * "everything that is late on the project" is trusting it wrongly, so the
 * intro says the boundary out loud, and the chip rows name every source it
 * does read rather than leaving the reader to guess the coverage.
 */
function HowDeadlinesWork() {
  const { t } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';

  // The compliance register lives on the project page, so its chip can only be
  // aimed once a project is active.
  const pulls = useMemo(
    () =>
      PULLS_FROM.map((m) =>
        m.key === 'deadlines.mod_compliance_docs' && projectId
          ? { ...m, to: `/projects/${projectId}?tab=compliance` }
          : m,
      ),
    [projectId],
  );

  const steps: { icon: ReactNode; title: string; desc: string }[] = [
    {
      icon: <CalendarClock size={14} className="text-oe-blue" />,
      title: t('deadlines.flow_1_title', { defaultValue: 'Dates are set upstream' }),
      desc: t('deadlines.flow_1_desc', {
        defaultValue:
          'A response date on a letter, a due date on an NCR corrective action, a due date on a punch item. Each is set in its own module.',
      }),
    },
    {
      icon: <Inbox size={14} className="text-oe-blue" />,
      title: t('deadlines.flow_2_title', { defaultValue: 'The register gathers them' }),
      desc: t('deadlines.flow_2_desc', {
        defaultValue:
          'Everything still outstanding with a date is pulled together here, grouped by the module it came from.',
      }),
    },
    {
      icon: <AlertTriangle size={14} className="text-oe-blue" />,
      title: t('deadlines.flow_3_title', { defaultValue: 'Standing and severity' }),
      desc: t('deadlines.flow_3_desc', {
        defaultValue:
          'Each item is marked overdue, approaching or on time, and carries a severity so the critical ones stand out.',
      }),
    },
    {
      icon: <ArrowRight size={14} className="text-oe-blue" />,
      title: t('deadlines.flow_4_title', { defaultValue: 'Act in the source' }),
      desc: t('deadlines.flow_4_desc', {
        defaultValue:
          'Open the item to answer it where it lives. Once it is answered or the date is met it drops off this list.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="deadlines.how"
      icon={<Hourglass size={15} className="text-oe-blue" />}
      title={t('deadlines.flow_title', {
        defaultValue: 'How the Deadline register fits together',
      })}
    >
      <p className="text-xs text-content-tertiary">
        {t('deadlines.flow_intro', {
          defaultValue:
            'One list of everything on the project that has a date attached and has not been answered yet. It does not create deadlines of its own; it gathers the dates other modules already hold so nothing quietly runs out of time.',
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
            {t('deadlines.flow_pulls', { defaultValue: 'Pulls from:' })}
          </span>{' '}
          {pulls.map((m, i) => (
            <Fragment key={m.key}>
              {i > 0 && ' · '}
              <ModLink to={m.to}>{t(m.key, { defaultValue: m.def })}</ModLink>
            </Fragment>
          ))}
        </span>
        <span>
          <span className="font-medium text-content-secondary">
            {t('deadlines.flow_feeds', { defaultValue: 'Feeds:' })}
          </span>{' '}
          {FEEDS.map((m, i) => (
            <Fragment key={m.key}>
              {i > 0 && ' · '}
              <ModLink to={m.to}>{t(m.key, { defaultValue: m.def })}</ModLink>
            </Fragment>
          ))}
        </span>
      </div>
    </CollapsibleSection>
  );
}

export function DeadlinesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';
  const [statusFilter, setStatusFilter] = useState<DeadlineStatusFilter>('all');

  const query = useQuery({
    queryKey: ['deadlines', projectId, statusFilter],
    queryFn: () => fetchDeadlines({ project_id: projectId, status: statusFilter }),
    enabled: !!projectId,
  });

  // Group items by module, preserving the backend's overdue-first ordering.
  const groups = useMemo(() => {
    const items = query.data?.items ?? [];
    const byModule = new Map<string, DeadlineItem[]>();
    for (const it of items) {
      const arr = byModule.get(it.module) ?? [];
      arr.push(it);
      byModule.set(it.module, arr);
    }
    return Array.from(byModule.entries());
  }, [query.data]);

  const overdueCount = query.data?.overdue_count ?? 0;
  const approachingCount = query.data?.approaching_count ?? 0;

  const insights = useModuleInsights('deadlines', { defaultOpen: true });
  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildDeadlinesInsights(query.data?.items ?? [], t),
    [query.data, t],
  );

  function daysChip(it: DeadlineItem): { text: string; overdue: boolean } {
    if (it.days_overdue > 0) {
      return {
        text: t('deadlines.overdue_by', { count: it.days_overdue, defaultValue: '{{count}}d overdue' }),
        overdue: true,
      };
    }
    if (it.days_overdue === 0) {
      return { text: t('deadlines.due_today', { defaultValue: 'Due today' }), overdue: false };
    }
    return {
      text: t('deadlines.due_in', { count: -it.days_overdue, defaultValue: 'in {{count}}d' }),
      overdue: false,
    };
  }

  function filterLabel(f: DeadlineStatusFilter): string {
    if (f === 'overdue') {
      return t('deadlines.filter.overdue', { defaultValue: 'Overdue' });
    }
    if (f === 'approaching') {
      return t('deadlines.filter.approaching', { defaultValue: 'Approaching' });
    }
    return t('deadlines.filter.all', { defaultValue: 'All' });
  }

  function filterCount(f: DeadlineStatusFilter): number | null {
    if (f === 'overdue') return overdueCount;
    if (f === 'approaching') return approachingCount;
    return null;
  }

  return (
    <div className="mx-auto w-full max-w-6xl p-4 sm:p-6">
      {/* Header */}
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <CalendarClock size={22} className="mt-0.5 shrink-0 text-oe-blue" />
          <div>
            <h1 className="text-xl font-semibold text-content-primary">
              {t('deadlines.register_title', { defaultValue: 'Deadline register' })}
            </h1>
            <p className="mt-0.5 text-sm text-content-secondary">
              {t('deadlines.subtitle', {
                defaultValue: 'Overdue and upcoming items across every module, in one place.',
              })}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
          <Link
            to="/notifications"
            className="inline-flex items-center gap-1 text-sm font-medium text-oe-blue hover:underline"
          >
            {t('deadlines.settings_link', { defaultValue: 'Notification settings' })}
            <ArrowRight size={14} />
          </Link>
        </div>
      </div>

      <div className="mb-4">
        <HowDeadlinesWork />
      </div>

      <InsightsPanel
        open={insights.open}
        title={t('deadlines.insights.title', { defaultValue: 'Deadline insights' })}
        datasets={insightDatasets}
        builtins={insightBuiltins}
        custom={insights.custom}
        onAdd={insights.addCustom}
        onUpdate={insights.updateCustom}
        onRemove={insights.removeCustom}
        onCollapse={() => insights.setOpen(false)}
      />

      {/* Filter segmented control */}
      <div className="mb-4 inline-flex rounded-lg border border-border-light bg-surface-secondary p-0.5">
        {FILTERS.map((f) => {
          const count = filterCount(f);
          const active = statusFilter === f;
          return (
            <button
              key={f}
              type="button"
              onClick={() => setStatusFilter(f)}
              className={clsx(
                'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                active
                  ? 'bg-surface-elevated text-content-primary shadow-sm'
                  : 'text-content-secondary hover:text-content-primary',
              )}
            >
              {filterLabel(f)}
              {count !== null && count > 0 && (
                <span
                  className={clsx(
                    'ms-1.5 rounded-full px-1.5 py-0.5 text-xs font-semibold',
                    f === 'overdue'
                      ? 'bg-semantic-error/10 text-semantic-error'
                      : 'bg-semantic-warning/10 text-semantic-warning',
                  )}
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Body states */}
      {!projectId ? (
        <div className="p-12 text-center">
          <CalendarClock size={28} strokeWidth={1.5} className="mx-auto mb-2 text-content-tertiary" />
          <p className="text-sm text-content-secondary">
            {t('deadlines.no_project', { defaultValue: 'Select a project to see its deadlines.' })}
          </p>
        </div>
      ) : query.isLoading ? (
        <div className="flex items-center justify-center p-8 text-content-tertiary">
          <Loader2 className="me-2 animate-spin" size={16} />
          {t('common.loading', { defaultValue: 'Loading...' })}
        </div>
      ) : query.isError ? (
        <div className="p-8 text-center">
          <XCircle size={24} className="mx-auto mb-2 text-semantic-error" />
          <p className="mb-3 text-sm text-content-secondary">
            {t('deadlines.load_error', { defaultValue: "Couldn't load the deadline register" })}
          </p>
          <Button variant="secondary" size="sm" onClick={() => query.refetch()}>
            {t('common.retry', { defaultValue: 'Try again' })}
          </Button>
        </div>
      ) : groups.length === 0 ? (
        <div className="p-12 text-center">
          <CheckCircle2 size={28} strokeWidth={1.5} className="mx-auto mb-2 text-semantic-success" />
          <p className="text-sm text-content-secondary">
            {t('deadlines.empty', {
              defaultValue: "Nothing overdue or approaching. You're on top of it.",
            })}
          </p>
          {/* An empty register usually means dates are missing upstream, not
              that nothing is outstanding. Name the three surfaces that feed it. */}
          <p className="mx-auto mt-2 max-w-md text-xs text-content-tertiary">
            {t('deadlines.empty_hint', {
              defaultValue:
                'Nothing is waiting on a date. Items appear here once a letter has a response date, an NCR has a corrective action due date, or a punch item has a due date.',
            })}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border-light bg-surface-elevated">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-border-light text-start text-xs uppercase tracking-wide text-content-tertiary">
                <th className="px-4 py-2.5 text-start font-medium">
                  {t('deadlines.col.title', { defaultValue: 'Item' })}
                </th>
                <th className="px-4 py-2.5 text-start font-medium">
                  {t('deadlines.col.due', { defaultValue: 'Due' })}
                </th>
                <th className="px-4 py-2.5 text-start font-medium">
                  {t('deadlines.col.days', { defaultValue: 'Days' })}
                </th>
                <th className="px-4 py-2.5 text-start font-medium">
                  {t('deadlines.col.owner', { defaultValue: 'Owner' })}
                </th>
                <th className="px-4 py-2.5 text-start font-medium">
                  {t('deadlines.col.status', { defaultValue: 'Status' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {groups.map(([moduleKey, items]) => {
                const label = MODULE_LABELS[moduleKey] ?? { key: `deadlines.module.${moduleKey}`, def: moduleKey };
                return (
                  <Fragment key={`grp-${moduleKey}`}>
                    <tr className="bg-surface-secondary/60">
                      <td
                        colSpan={5}
                        className="px-4 py-1.5 text-xs font-semibold uppercase tracking-wide text-content-secondary"
                      >
                        {t(label.key, { defaultValue: label.def })}
                        <span className="ms-2 font-normal text-content-tertiary">({items.length})</span>
                      </td>
                    </tr>
                    {items.map((it) => {
                      const chip = daysChip(it);
                      return (
                        <tr
                          key={it.id}
                          onClick={() => navigate(it.action_url)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') navigate(it.action_url);
                          }}
                          tabIndex={0}
                          className="cursor-pointer border-b border-border-light/60 last:border-0 hover:bg-surface-secondary/40 focus:bg-surface-secondary/40 focus:outline-none"
                        >
                          <td className="px-4 py-2.5 text-content-primary">{it.title}</td>
                          <td className="whitespace-nowrap px-4 py-2.5 text-content-secondary">
                            {it.due_date ? it.due_date.slice(0, 10) : '-'}
                          </td>
                          <td className="whitespace-nowrap px-4 py-2.5">
                            <span
                              className={clsx(
                                'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium',
                                chip.overdue
                                  ? 'bg-semantic-error/10 text-semantic-error'
                                  : 'bg-semantic-warning/10 text-semantic-warning',
                              )}
                            >
                              <AlarmClock size={11} />
                              {chip.text}
                            </span>
                          </td>
                          <td className="whitespace-nowrap px-4 py-2.5 text-content-secondary">
                            {it.owner_name ?? (
                              <span className="italic text-content-tertiary">
                                {t('deadlines.no_owner', { defaultValue: 'Unassigned' })}
                              </span>
                            )}
                          </td>
                          <td className="whitespace-nowrap px-4 py-2.5 text-content-secondary">
                            {humaniseStatus(it.status)}
                          </td>
                        </tr>
                      );
                    })}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
