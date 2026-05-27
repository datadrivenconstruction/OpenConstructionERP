import { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  HardHat,
  Plus,
  Search,
  X,
  Loader2,
  Star,
  FileText,
  Award,
  DollarSign,
  ClipboardList,
  Pencil,
  Trash2,
  ShieldAlert,
  Save,
  Shield,
  Ban,
  CheckCircle2,
  ClipboardCheck,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  SkeletonTable,
  ConfirmDialog,
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { PipelineBanner } from './PipelineBanner';
import { PrequalModal } from './PrequalModal';
import { ScorecardTile } from './ScorecardTile';
import { LienWaiverPanel } from './LienWaiverPanel';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  listSubcontractors,
  getSubcontractor,
  createSubcontractor,
  updateSubcontractor,
  deleteSubcontractor,
  getSubcontractorDashboard,
  listAgreements,
  listWorkPackages,
  listPaymentApplications,
  listRetentionLedger,
  listRatings,
  listCertificates,
  blockSubcontractor,
  unblockSubcontractor,
  type Subcontractor,
  type PrequalStatus,
  type Agreement,
  type AgreementStatus,
  type PaymentApplication,
  type PaymentApplicationStatus,
  type CreateSubcontractorPayload,
  type Rating,
} from './api';

type DrawerTab = 'scope' | 'payments' | 'ratings' | 'retention';

const PREQUAL_VARIANT: Record<PrequalStatus, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  pending: 'warning',
  approved: 'success',
  suspended: 'warning',
  rejected: 'error',
};

const AGREEMENT_VARIANT: Record<
  AgreementStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  draft: 'neutral',
  active: 'success',
  completed: 'blue',
  terminated: 'error',
};

const PAYMENT_VARIANT: Record<
  PaymentApplicationStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  submitted: 'blue',
  foreman_approved: 'warning',
  finance_approved: 'warning',
  paid: 'success',
  rejected: 'error',
};

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

function toNum(n: number | string | null | undefined): number {
  if (n === null || n === undefined) return 0;
  return typeof n === 'number' ? n : Number(n) || 0;
}

/**
 * Derive a 3-state insurance traffic-light from the expiry date.
 *
 * - ``red``    : expired (past), or missing entirely
 * - ``amber``  : within 1-30 days of expiry
 * - ``green``  : more than 30 days away
 *
 * Mirrors the server-side ``flag_expiring_insurance`` behaviour so the
 * UI stays consistent with the nightly sweep report.
 */
function insuranceStatus(
  expiry: string | null | undefined,
): 'red' | 'amber' | 'green' {
  if (!expiry) return 'red';
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const exp = new Date(expiry);
  if (Number.isNaN(exp.getTime())) return 'red';
  const diffDays = Math.floor((exp.getTime() - today.getTime()) / 86_400_000);
  if (diffDays < 0) return 'red';
  if (diffDays <= 30) return 'amber';
  return 'green';
}

function InsuranceChip({
  expiry,
}: {
  expiry: string | null | undefined;
}) {
  const { t } = useTranslation();
  const state = insuranceStatus(expiry);
  const cfg: Record<
    'red' | 'amber' | 'green',
    { variant: 'success' | 'warning' | 'error'; label: string }
  > = {
    green: {
      variant: 'success',
      label: t('subcontractors.insurance_ok', {
        defaultValue: 'Insurance OK',
      }),
    },
    amber: {
      variant: 'warning',
      label: t('subcontractors.insurance_soon', {
        defaultValue: 'Insurance soon',
      }),
    },
    red: {
      variant: 'error',
      label: expiry
        ? t('subcontractors.insurance_expired', {
            defaultValue: 'Insurance expired',
          })
        : t('subcontractors.insurance_missing', {
            defaultValue: 'No insurance',
          }),
    },
  };
  const c = cfg[state];
  return (
    <Badge variant={c.variant} dot>
      {c.label}
      {expiry && state !== 'green' ? ` · ${expiry}` : ''}
    </Badge>
  );
}

function RatingStars({ score }: { score: number | string }) {
  const num = toNum(score);
  // rating_score is 0..100; convert to 0..5
  const stars = Math.round((num / 100) * 5);
  return (
    <span className="inline-flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((i) => (
        <Star
          key={i}
          size={12}
          className={clsx(
            i <= stars ? 'fill-oe-blue text-oe-blue' : 'text-content-tertiary',
          )}
        />
      ))}
      <span className="ml-1.5 text-xs text-content-secondary tabular-nums">
        {num.toFixed(0)}
      </span>
    </span>
  );
}

export function SubcontractorsPage() {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const subsQ = useQuery({
    queryKey: ['subcontractors', 'list'],
    queryFn: () => listSubcontractors({ limit: 200 }),
  });

  const filtered = useMemo(() => {
    const items = subsQ.data ?? [];
    const s = search.toLowerCase();
    return items.filter((it) => {
      if (statusFilter && it.prequalification_status !== statusFilter) return false;
      if (!s) return true;
      return (
        it.legal_name.toLowerCase().includes(s) ||
        (it.trade_name || '').toLowerCase().includes(s) ||
        (it.tax_id || '').toLowerCase().includes(s) ||
        it.trade_categories.some((c) => c.toLowerCase().includes(s))
      );
    });
  }, [subsQ.data, search, statusFilter]);

  // For the "latest payment app" column we need a hint, but it would
  // require N+1 queries. We skip it in the row and surface it inside
  // the drawer instead.

  return (
    <div className="space-y-5">
      <Breadcrumb
        items={[
          { label: t('subcontractors.title', { defaultValue: 'Subcontractors' }) },
        ]}
      />

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-content-primary">
            {t('subcontractors.title', { defaultValue: 'Subcontractors' })}
          </h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('subcontractors.subtitle', {
              defaultValue:
                'Manage subcontractor prequalifications, scopes, payments and ratings.',
            })}
          </p>
        </div>
        <Button
          variant="primary"
          icon={<Plus size={14} />}
          onClick={() => setCreateOpen(true)}
        >
          {t('subcontractors.new', { defaultValue: 'New Subcontractor' })}
        </Button>
      </div>

      <PipelineBanner
        intro={t('subcontractors.pipeline_intro', {
          defaultValue:
            'Subcontractors are your prequalified supply chain. Approved firms can be invited to bid packages, bound by subcontract agreements, and paid via payment applications — with certificates and ratings gating eligibility.',
        })}
        steps={[
          {
            label: t('subcontractors.step_subs', {
              defaultValue: 'Subcontractors',
            }),
            current: true,
          },
          {
            label: t('subcontractors.step_bid', {
              defaultValue: 'Bid Management',
            }),
            to: '/bid-management',
          },
          {
            label: t('subcontractors.step_contract', {
              defaultValue: 'Contracts',
            }),
            to: '/contracts',
          },
          {
            label: t('subcontractors.step_procurement', {
              defaultValue: 'Procurement',
            }),
            to: '/procurement',
          },
        ]}
      />

      {/* Tabs (single tab — left for layout parity with ServicePage) */}
      <div className="border-b border-border-light">
        <nav className="flex gap-1 -mb-px">
          <button
            type="button"
            className="flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 border-oe-blue text-oe-blue"
          >
            <HardHat size={14} />
            {t('subcontractors.tab_list', { defaultValue: 'Subcontractors' })}
          </button>
        </nav>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            type="text"
            placeholder={t('common.search', { defaultValue: 'Search…' })}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={clsx(inputCls, 'pl-8')}
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className={clsx(inputCls, 'max-w-[200px]')}
          aria-label={t('subcontractors.filter_by_status', {
            defaultValue: 'Filter by prequalification status',
          })}
        >
          <option value="">
            {t('common.all_statuses', { defaultValue: 'All statuses' })}
          </option>
          {(['pending', 'approved', 'suspended', 'rejected'] as PrequalStatus[]).map(
            (s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ),
          )}
        </select>
      </div>

      {/* Body */}
      <Card padding="none">
        {subsQ.isLoading ? (
          <div className="p-4">
            <SkeletonTable rows={8} columns={5} />
          </div>
        ) : subsQ.isError ? (
          <EmptyState
            icon={<ShieldAlert size={22} />}
            title={t('subcontractors.load_error', {
              defaultValue: 'Could not load subcontractors',
            })}
            description={getErrorMessage(subsQ.error)}
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => {
                void subsQ.refetch();
              },
            }}
          />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<HardHat size={22} />}
            title={t('subcontractors.empty', {
              defaultValue: 'No subcontractors yet',
            })}
            description={t('subcontractors.empty_desc', {
              defaultValue:
                'Add subcontractors to track prequalification, scope, payments and performance.',
            })}
            action={{
              label: t('subcontractors.new', { defaultValue: 'New Subcontractor' }),
              onClick: () => setCreateOpen(true),
            }}
          />
        ) : (
          <SubcontractorTable rows={filtered} onSelect={setSelectedId} />
        )}
      </Card>

      {selectedId && (
        <DetailDrawer id={selectedId} onClose={() => setSelectedId(null)} />
      )}

      {createOpen && (
        <SubcontractorFormModal
          mode="create"
          onClose={() => setCreateOpen(false)}
        />
      )}
    </div>
  );
}

/* ─── Table ─── */

function SubcontractorTable({
  rows,
  onSelect,
}: {
  rows: Subcontractor[];
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">
              {t('subcontractors.col_name', { defaultValue: 'Name' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('subcontractors.col_trades', { defaultValue: 'Trades' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('subcontractors.col_status', { defaultValue: 'Status' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('subcontractors.col_insurance', { defaultValue: 'Insurance' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('subcontractors.col_rating', { defaultValue: 'Rating' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('subcontractors.col_country', { defaultValue: 'Country' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.id}
              onClick={() => onSelect(r.id)}
              className="border-t border-border-light hover:bg-surface-secondary cursor-pointer"
            >
              <td className="px-4 py-2">
                <div className="flex items-center gap-2 min-w-0">
                  <div className="font-medium text-content-primary truncate max-w-[260px]">
                    {r.legal_name}
                  </div>
                  {r.is_blocked && (
                    <Badge variant="error" size="sm">
                      <Ban size={10} className="mr-0.5 inline" />
                      {t('subcontractors.blocked_badge', {
                        defaultValue: 'Blocked',
                      })}
                    </Badge>
                  )}
                </div>
                {r.trade_name && (
                  <div className="text-xs text-content-tertiary truncate max-w-[280px]">
                    {r.trade_name}
                  </div>
                )}
              </td>
              <td className="px-4 py-2 text-xs text-content-secondary">
                <div className="flex flex-wrap gap-1">
                  {r.trade_categories.slice(0, 3).map((c) => (
                    <span
                      key={c}
                      className="rounded bg-surface-secondary px-1.5 py-0.5"
                    >
                      {c}
                    </span>
                  ))}
                  {r.trade_categories.length > 3 && (
                    <span className="text-content-tertiary">
                      +{r.trade_categories.length - 3}
                    </span>
                  )}
                </div>
              </td>
              <td className="px-4 py-2">
                <Badge variant={PREQUAL_VARIANT[r.prequalification_status]} dot>
                  {r.prequalification_status}
                </Badge>
              </td>
              <td className="px-4 py-2">
                <InsuranceChip expiry={r.insurance_expiry_date} />
              </td>
              <td className="px-4 py-2">
                <RatingStars score={r.rating_score} />
              </td>
              <td className="px-4 py-2 text-content-secondary text-xs">
                {r.country || '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ─── Detail Drawer ─── */

function DetailDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [tab, setTab] = useState<DrawerTab>('scope');
  // Edit + delete UI state — both gated to the loaded subcontractor so
  // the header buttons can't fire stale operations against a different id.
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  // Prequal modal + block-action state (Wave 4 / T12). The block toggle
  // optimistically refetches `getSubcontractor` rather than mutating local
  // state so the rest of the drawer (dashboard banner, insurance chip)
  // picks up the new is_blocked value automatically.
  const [prequalOpen, setPrequalOpen] = useState(false);
  const [blockBusy, setBlockBusy] = useState(false);

  const subQ = useQuery({
    queryKey: ['subcontractors', 'detail', id],
    queryFn: () => getSubcontractor(id),
    enabled: !!id,
  });
  const sub = subQ.data;

  // Dashboard rollup — expired/expiring certs, pending retention, KPI roll-up.
  // Surfaces compliance state in the header without forcing the user to
  // click into a tab. Errors are silent (server-side scoring may not yet
  // exist for very fresh tenants).
  const dashboardQ = useQuery({
    queryKey: ['subcontractors', 'dashboard', id],
    queryFn: () => getSubcontractorDashboard(id),
    enabled: !!id,
    retry: false,
  });

  const agreementsQ = useQuery({
    queryKey: ['subcontractors', 'agreements', id],
    queryFn: () => listAgreements({ subcontractor_id: id }),
    enabled: !!id,
  });

  // Eager fetch so the ScorecardTile inside the Ratings tab has data
  // by the time the user clicks the tab. ~1-3 KB payload (one row per
  // YYYY-MM period); negligible compared to the dashboard rollup.
  const ratingsQ = useQuery({
    queryKey: ['subcontractors', 'ratings', id],
    queryFn: () => listRatings(id),
    enabled: !!id,
  });

  const certsQ = useQuery({
    queryKey: ['subcontractors', 'certificates', id],
    queryFn: () => listCertificates(id),
    enabled: !!id,
  });

  const agreements = agreementsQ.data ?? [];
  const firstAgreement = agreements[0];
  const dashboard = dashboardQ.data;

  const handleDelete = async () => {
    if (!sub) return;
    setDeleting(true);
    try {
      await deleteSubcontractor(sub.id);
      addToast({
        type: 'success',
        title: t('subcontractors.deleted', {
          defaultValue: '{{name}} deleted',
          name: sub.legal_name,
        }),
      });
      qc.invalidateQueries({ queryKey: ['subcontractors'] });
      setDeleteOpen(false);
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setDeleting(false);
    }
  };

  /**
   * Block / unblock handler — single function, dispatches by current
   * is_blocked state. Prompts for a reason on block; clears the flag on
   * unblock. Invalidates the subcontractors cache so the row in the
   * background table refreshes its blocked badge.
   */
  const handleBlockToggle = async () => {
    if (!sub) return;
    setBlockBusy(true);
    try {
      if (sub.is_blocked) {
        await unblockSubcontractor(sub.id);
        addToast({
          type: 'success',
          title: t('subcontractors.unblocked_toast', {
            defaultValue: '{{name}} unblocked',
            name: sub.legal_name,
          }),
        });
      } else {
        // Plain prompt() keeps the change scoped — a richer modal can come
        // later if the audit log shows recurring patterns of reasons.
        const reason = window.prompt(
          t('subcontractors.block_prompt', {
            defaultValue: 'Reason for blocking this subcontractor?',
          }) as string,
        );
        if (!reason || !reason.trim()) {
          setBlockBusy(false);
          return;
        }
        await blockSubcontractor(sub.id, reason.trim());
        addToast({
          type: 'success',
          title: t('subcontractors.blocked_toast', {
            defaultValue: '{{name}} blocked',
            name: sub.legal_name,
          }),
        });
      }
      qc.invalidateQueries({ queryKey: ['subcontractors'] });
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBlockBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        className="relative h-full w-full max-w-2xl overflow-y-auto bg-surface-elevated shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-light bg-surface-elevated px-5 py-3 gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold truncate">
              {sub?.legal_name || t('common.loading', { defaultValue: 'Loading…' })}
            </h2>
            {sub?.trade_name && (
              <p className="text-xs text-content-tertiary truncate">{sub.trade_name}</p>
            )}
          </div>
          {/* Action toolbar — Edit + Delete + Close. Disabled while the
              subcontractor record is still loading so the buttons cannot
              fire against an undefined id. Edit reopens the form modal in
              edit mode; Delete is danger-confirmed. */}
          <div className="flex items-center gap-1 shrink-0">
            {/* Prequalify — opens the questionnaire modal. Available regardless
                of the current prequalification_status so the user can re-run
                the assessment and update the score over time. */}
            <button
              type="button"
              onClick={() => setPrequalOpen(true)}
              disabled={!sub}
              className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-xs font-medium text-content-secondary hover:text-oe-blue-text hover:border-oe-blue hover:bg-oe-blue-subtle transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label={t('subcontractors.prequalify', {
                defaultValue: 'Prequalify',
              })}
            >
              <ClipboardCheck size={12} />
              {t('subcontractors.prequalify', { defaultValue: 'Prequalify' })}
              {typeof sub?.prequal_score === 'number' && (
                <span className="ml-0.5 tabular-nums text-content-tertiary">
                  ({sub.prequal_score})
                </span>
              )}
            </button>
            {/* Block / Unblock — single button, label flips by current state.
                Block prompts for a reason; unblock clears. Both invalidate
                the subcontractors query so the row badge refreshes. */}
            <button
              type="button"
              onClick={handleBlockToggle}
              disabled={!sub || blockBusy}
              className={clsx(
                'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed',
                sub?.is_blocked
                  ? 'border-emerald-300 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 dark:bg-emerald-950/30 dark:border-emerald-900/40 dark:text-emerald-200'
                  : 'border-border-light bg-surface-primary text-content-secondary hover:text-rose-600 hover:border-rose-300 hover:bg-rose-50 dark:hover:bg-rose-950/30',
              )}
            >
              {sub?.is_blocked ? <CheckCircle2 size={12} /> : <Ban size={12} />}
              {sub?.is_blocked
                ? t('subcontractors.unblock_button', { defaultValue: 'Unblock' })
                : t('subcontractors.block_button', { defaultValue: 'Block' })}
            </button>
            <button
              type="button"
              onClick={() => setEditOpen(true)}
              disabled={!sub}
              className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-xs font-medium text-content-secondary hover:text-oe-blue-text hover:border-oe-blue hover:bg-oe-blue-subtle transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label={t('common.edit', { defaultValue: 'Edit' })}
            >
              <Pencil size={12} />
              {t('common.edit', { defaultValue: 'Edit' })}
            </button>
            <button
              type="button"
              onClick={() => setDeleteOpen(true)}
              disabled={!sub}
              className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-xs font-medium text-content-secondary hover:text-rose-600 hover:border-rose-300 hover:bg-rose-50 dark:hover:bg-rose-950/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label={t('common.delete', { defaultValue: 'Delete' })}
            >
              <Trash2 size={12} />
              {t('common.delete', { defaultValue: 'Delete' })}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="ml-1 rounded p-1 hover:bg-surface-secondary"
              aria-label={t('common.close', { defaultValue: 'Close' })}
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Compliance banner — only when expiry or block conditions hit.
            Shows at the very top of the drawer below the action toolbar
            so dispatcher cannot miss "this sub is currently blocked
            because Insurance X expired on Y". */}
        {dashboard && (dashboard.blocked || dashboard.expired_certificates > 0 || dashboard.expiring_soon_certificates > 0) && (
          <div
            className={clsx(
              'border-b px-5 py-2.5 flex items-start gap-2 text-xs',
              dashboard.blocked || dashboard.expired_certificates > 0
                ? 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-200'
                : 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200',
            )}
          >
            <ShieldAlert size={14} className="mt-0.5 shrink-0" />
            <div className="min-w-0 flex-1 space-y-0.5">
              {dashboard.expired_certificates > 0 && (
                <p>
                  {t('subcontractors.expired_certs', {
                    defaultValue: '{{count}} certificate(s) expired',
                    count: dashboard.expired_certificates,
                  })}
                </p>
              )}
              {dashboard.expiring_soon_certificates > 0 && (
                <p>
                  {t('subcontractors.expiring_soon_certs', {
                    defaultValue: '{{count}} certificate(s) expiring within 60 days',
                    count: dashboard.expiring_soon_certificates,
                  })}
                </p>
              )}
              {dashboard.blocked && dashboard.block_reasons.length > 0 && (
                <p className="font-medium">
                  {t('subcontractors.blocked_label', {
                    defaultValue: 'Payments blocked:',
                  })}{' '}
                  {dashboard.block_reasons.join('; ')}
                </p>
              )}
            </div>
          </div>
        )}

        {subQ.isLoading && !sub && (
          <div className="p-5">
            <SkeletonTable rows={4} columns={4} />
          </div>
        )}

        {subQ.isError && !sub && (
          <div className="p-5">
            <EmptyState
              icon={<ShieldAlert size={20} />}
              title={t('subcontractors.detail_error', {
                defaultValue: 'Could not load this subcontractor',
              })}
              description={getErrorMessage(subQ.error)}
              action={{
                label: t('common.retry', { defaultValue: 'Retry' }),
                onClick: () => {
                  void subQ.refetch();
                },
              }}
            />
          </div>
        )}

        {sub && (
          <>
            <div className="grid grid-cols-2 gap-3 p-5 text-sm border-b border-border-light sm:grid-cols-4">
              <KV
                label={t('subcontractors.col_status', { defaultValue: 'Status' })}
                value={
                  <Badge variant={PREQUAL_VARIANT[sub.prequalification_status]} dot>
                    {sub.prequalification_status}
                  </Badge>
                }
              />
              <KV
                label={t('subcontractors.col_rating', { defaultValue: 'Rating' })}
                value={<RatingStars score={sub.rating_score} />}
              />
              <KV
                label={t('subcontractors.col_insurance', {
                  defaultValue: 'Insurance',
                })}
                value={<InsuranceChip expiry={sub.insurance_expiry_date} />}
              />
              <KV
                label={t('subcontractors.prequal_score_label', {
                  defaultValue: 'Prequal score',
                })}
                value={
                  typeof sub.prequal_score === 'number' ? (
                    <span className="inline-flex items-center gap-1">
                      <Shield size={12} className="text-content-tertiary" />
                      <span className="tabular-nums">{sub.prequal_score}</span>
                    </span>
                  ) : (
                    <span className="text-content-tertiary">—</span>
                  )
                }
              />
              <KV
                label={t('subcontractors.col_country', { defaultValue: 'Country' })}
                value={sub.country || '—'}
              />
              <KV
                label={t('subcontractors.tax_id', { defaultValue: 'Tax ID' })}
                value={sub.tax_id || '—'}
              />
            </div>
            {sub.is_blocked && sub.blocked_reason && (
              <div className="border-b border-rose-200 bg-rose-50 px-5 py-2.5 text-xs text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-200">
                <span className="font-semibold">
                  {t('subcontractors.blocked_label', {
                    defaultValue: 'Blocked:',
                  })}
                </span>{' '}
                {sub.blocked_reason}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2 px-5 py-3 text-xs border-b border-border-light">
              <span className="text-content-tertiary">
                {t('subcontractors.related', { defaultValue: 'Related:' })}
              </span>
              <Link
                to="/bid-management"
                className="inline-flex items-center gap-1 rounded-md border border-border-light px-2 py-1 text-content-secondary hover:text-oe-blue hover:border-oe-blue transition-colors"
              >
                {t('subcontractors.invite_to_bid', {
                  defaultValue: 'Invite to a bid package',
                })}
              </Link>
              <Link
                to="/contracts"
                className="inline-flex items-center gap-1 rounded-md border border-border-light px-2 py-1 text-content-secondary hover:text-oe-blue hover:border-oe-blue transition-colors"
              >
                {t('subcontractors.subcontract', {
                  defaultValue: 'Subcontract agreement',
                })}
              </Link>
            </div>

            <div className="border-b border-border-light px-5">
              <nav className="flex gap-1 -mb-px">
                {(
                  [
                    {
                      id: 'scope',
                      label: t('subcontractors.tab_scope', { defaultValue: 'Scope' }),
                      icon: ClipboardList,
                    },
                    {
                      id: 'payments',
                      label: t('subcontractors.tab_payments', {
                        defaultValue: 'Payments',
                      }),
                      icon: DollarSign,
                    },
                    {
                      id: 'ratings',
                      label: t('subcontractors.tab_ratings', {
                        defaultValue: 'Ratings',
                      }),
                      icon: Star,
                    },
                    {
                      id: 'retention',
                      label: t('subcontractors.tab_retention', {
                        defaultValue: 'Retention',
                      }),
                      icon: Award,
                    },
                  ] as { id: DrawerTab; label: string; icon: React.ElementType }[]
                ).map((ti) => {
                  const Icon = ti.icon;
                  return (
                    <button
                      key={ti.id}
                      type="button"
                      onClick={() => setTab(ti.id)}
                      className={clsx(
                        'flex items-center gap-2 px-3 py-2.5 text-xs font-medium border-b-2 transition-colors',
                        tab === ti.id
                          ? 'border-oe-blue text-oe-blue'
                          : 'border-transparent text-content-secondary hover:text-content-primary',
                      )}
                    >
                      <Icon size={12} />
                      {ti.label}
                    </button>
                  );
                })}
              </nav>
            </div>

            <div className="p-5 space-y-3">
              {tab === 'scope' && (
                <ScopeTab agreements={agreements} loading={agreementsQ.isLoading} />
              )}
              {tab === 'payments' && (
                <PaymentsTab
                  agreement={firstAgreement}
                  agreements={agreements}
                />
              )}
              {tab === 'ratings' && (
                <RatingsTab
                  data={ratingsQ.data ?? []}
                  loading={ratingsQ.isLoading}
                />
              )}
              {tab === 'retention' && (
                <RetentionTab
                  agreement={firstAgreement}
                  agreements={agreements}
                />
              )}
            </div>

            {/* Certificates summary always visible at the bottom */}
            {(certsQ.data?.length ?? 0) > 0 && (
              <div className="border-t border-border-light px-5 py-4">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-secondary">
                  {t('subcontractors.certificates', {
                    defaultValue: 'Certificates',
                  })}
                </p>
                <div className="flex flex-wrap gap-2">
                  {(certsQ.data ?? []).map((c) => {
                    const today = new Date().toISOString().slice(0, 10);
                    const isExpired = !!c.valid_until && c.valid_until < today;
                    const expiresSoon =
                      !!c.valid_until &&
                      !isExpired &&
                      c.valid_until <=
                        new Date(Date.now() + 60 * 86_400_000)
                          .toISOString()
                          .slice(0, 10);
                    return (
                      <Badge
                        key={c.id}
                        variant={
                          c.revoked || isExpired
                            ? 'error'
                            : expiresSoon
                              ? 'warning'
                              : 'success'
                        }
                      >
                        {c.cert_type}
                        {c.valid_until ? ` · ${c.valid_until}` : ''}
                      </Badge>
                    );
                  })}
                </div>
              </div>
            )}
            {/* Lien waivers / W-9 / W-8 panel — magic-byte gated upload
                + list. Mounted always (not behind a tab) so the list
                is one scroll away from the Certificates summary. */}
            <div className="border-t border-border-light px-5 py-4">
              <LienWaiverPanel subcontractorId={sub.id} />
            </div>
          </>
        )}
      </div>

      {/* Edit modal — only mounts when the user clicks "Edit" AND the
          subcontractor record has finished loading. Reuses CreateModal
          in edit mode so the field layout stays consistent. */}
      {editOpen && sub && (
        <SubcontractorFormModal
          mode="edit"
          existing={sub}
          onClose={() => setEditOpen(false)}
        />
      )}
      {/* Prequal modal — re-runnable; seeds itself from the prior
          questionnaire so the user can iterate on answers. */}
      {prequalOpen && sub && (
        <PrequalModal subcontractor={sub} onClose={() => setPrequalOpen(false)} />
      )}
      {/* Delete confirmation — destructive action, intentionally requires
          a second click. The danger-variant ConfirmDialog already handles
          focus trapping + Escape. */}
      <ConfirmDialog
        open={deleteOpen}
        title={t('subcontractors.delete_title', {
          defaultValue: 'Delete subcontractor?',
        })}
        message={
          sub
            ? t('subcontractors.delete_message', {
                defaultValue:
                  'Delete "{{name}}"? This removes all agreements, work packages, payment applications, retention entries, certificates and ratings linked to this subcontractor. This action cannot be undone.',
                name: sub.legal_name,
              })
            : ''
        }
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        cancelLabel={t('common.cancel', { defaultValue: 'Cancel' })}
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setDeleteOpen(false)}
        loading={deleting}
      />
    </div>
  );
}

function ScopeTab({
  agreements,
  loading,
}: {
  agreements: Agreement[];
  loading: boolean;
}) {
  const { t } = useTranslation();
  if (loading) return <SkeletonTable rows={3} columns={4} />;
  if (agreements.length === 0) {
    return (
      <EmptyState
        icon={<FileText size={20} />}
        title={t('subcontractors.no_agreements', {
          defaultValue: 'No agreements yet',
        })}
        description={t('subcontractors.no_agreements_desc', {
          defaultValue: 'Subcontract agreements link this vendor to specific projects.',
        })}
      />
    );
  }
  return (
    <div className="space-y-3">
      {agreements.map((a) => (
        <AgreementRow key={a.id} agreement={a} />
      ))}
    </div>
  );
}

function AgreementRow({ agreement }: { agreement: Agreement }) {
  const { t } = useTranslation();
  const wpQ = useQuery({
    queryKey: ['subcontractors', 'workPackages', agreement.id],
    queryFn: () => listWorkPackages(agreement.id),
  });
  const packages = wpQ.data ?? [];

  return (
    <Card padding="sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-medium text-content-primary truncate">{agreement.title}</p>
          <p className="mt-0.5 text-xs text-content-tertiary">
            {agreement.start_date || '—'} → {agreement.end_date || '—'}
          </p>
        </div>
        <Badge variant={AGREEMENT_VARIANT[agreement.status]} dot>
          {agreement.status}
        </Badge>
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-content-secondary">
        <span>
          {t('subcontractors.retention', { defaultValue: 'Retention' })}:{' '}
          {toNum(agreement.retention_percent).toFixed(1)}%
        </span>
        <span className="font-medium text-content-primary">
          <MoneyDisplay
            amount={toNum(agreement.total_value)}
            currency={agreement.currency || undefined}
          />
        </span>
      </div>
      {packages.length > 0 && (
        <div className="mt-3 border-t border-border-light pt-3 space-y-1.5">
          {packages.map((wp) => (
            <div
              key={wp.id}
              className="flex items-center justify-between text-xs text-content-secondary"
            >
              <span className="truncate">{wp.name}</span>
              <span className="ml-2 tabular-nums">
                {toNum(wp.completion_percent).toFixed(0)}%
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function PaymentsTab({
  agreement,
  agreements,
}: {
  agreement: Agreement | undefined;
  agreements: Agreement[];
}) {
  const { t } = useTranslation();
  const [agreementId, setAgreementId] = useState(agreement?.id ?? '');
  const effectiveId = agreementId || agreement?.id || '';

  const paymentsQ = useQuery({
    queryKey: ['subcontractors', 'payments', effectiveId],
    queryFn: () => listPaymentApplications({ agreement_id: effectiveId }),
    enabled: !!effectiveId,
  });

  if (agreements.length === 0) {
    return (
      <EmptyState
        icon={<DollarSign size={20} />}
        title={t('subcontractors.no_payments', { defaultValue: 'No payments yet' })}
        description={t('subcontractors.no_payments_desc', {
          defaultValue: 'Create an agreement first to track payment applications.',
        })}
      />
    );
  }
  return (
    <div className="space-y-3">
      <select
        value={effectiveId}
        onChange={(e) => setAgreementId(e.target.value)}
        className={inputCls}
      >
        {agreements.map((a) => (
          <option key={a.id} value={a.id}>
            {a.title}
          </option>
        ))}
      </select>
      {paymentsQ.isLoading && <SkeletonTable rows={3} columns={3} />}
      {paymentsQ.isError && (
        <p className="text-sm text-semantic-error">
          {getErrorMessage(paymentsQ.error)}
        </p>
      )}
      {paymentsQ.data && paymentsQ.data.length === 0 && (
        <p className="text-sm text-content-tertiary">
          {t('subcontractors.no_payment_apps', {
            defaultValue: 'No payment applications under this agreement.',
          })}
        </p>
      )}
      {paymentsQ.data && paymentsQ.data.length > 0 && (
        <PaymentList rows={paymentsQ.data} />
      )}
    </div>
  );
}

function PaymentList({ rows }: { rows: PaymentApplication[] }) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto rounded-lg border border-border-light">
      <table className="w-full text-xs">
        <thead className="bg-surface-secondary text-content-tertiary uppercase tracking-wide">
          <tr>
            <th className="px-3 py-2 text-left">
              {t('subcontractors.payment_no', { defaultValue: 'App #' })}
            </th>
            <th className="px-3 py-2 text-left">
              {t('subcontractors.period', { defaultValue: 'Period' })}
            </th>
            <th className="px-3 py-2 text-right">
              {t('subcontractors.gross', { defaultValue: 'Gross' })}
            </th>
            <th className="px-3 py-2 text-right">
              {t('subcontractors.net', { defaultValue: 'Net' })}
            </th>
            <th className="px-3 py-2 text-left">
              {t('subcontractors.col_status', { defaultValue: 'Status' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.id} className="border-t border-border-light">
              <td className="px-3 py-2 font-mono">{p.application_number}</td>
              <td className="px-3 py-2 text-content-secondary">
                {p.period_start || '—'} → {p.period_end || '—'}
              </td>
              <td className="px-3 py-2 text-right">
                <MoneyDisplay
                  amount={toNum(p.gross_amount)}
                  currency={p.currency || undefined}
                />
              </td>
              <td className="px-3 py-2 text-right font-medium">
                <MoneyDisplay
                  amount={toNum(p.net_amount)}
                  currency={p.currency || undefined}
                />
              </td>
              <td className="px-3 py-2">
                <Badge variant={PAYMENT_VARIANT[p.status]} dot>
                  {p.status}
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RatingsTab({
  data,
  loading,
}: {
  data: Rating[];
  loading: boolean;
}) {
  const { t } = useTranslation();
  if (loading) return <SkeletonTable rows={4} columns={5} />;
  if (data.length === 0) {
    return (
      <div className="space-y-3">
        <ScorecardTile ratings={data} />
        <EmptyState
          icon={<Star size={20} />}
          title={t('subcontractors.no_ratings', { defaultValue: 'No ratings yet' })}
        />
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <ScorecardTile ratings={data} />
      <div className="overflow-x-auto rounded-lg border border-border-light">
      <table className="w-full text-xs">
        <thead className="bg-surface-secondary text-content-tertiary uppercase tracking-wide">
          <tr>
            <th className="px-3 py-2 text-left">
              {t('subcontractors.period', { defaultValue: 'Period' })}
            </th>
            <th className="px-3 py-2 text-right">
              {t('subcontractors.quality', { defaultValue: 'Quality' })}
            </th>
            <th className="px-3 py-2 text-right">
              {t('subcontractors.hse', { defaultValue: 'HSE' })}
            </th>
            <th className="px-3 py-2 text-right">
              {t('subcontractors.schedule', { defaultValue: 'Schedule' })}
            </th>
            <th className="px-3 py-2 text-right">
              {t('subcontractors.cost', { defaultValue: 'Cost' })}
            </th>
            <th className="px-3 py-2 text-right">
              {t('subcontractors.overall', { defaultValue: 'Overall' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {data.map((r) => (
            <tr key={r.id} className="border-t border-border-light">
              <td className="px-3 py-2 font-mono">{r.period}</td>
              <td className="px-3 py-2 text-right tabular-nums">
                {toNum(r.quality_score).toFixed(0)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {toNum(r.hse_score).toFixed(0)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {toNum(r.schedule_score).toFixed(0)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {toNum(r.cost_score).toFixed(0)}
              </td>
              <td className="px-3 py-2 text-right font-semibold tabular-nums">
                {toNum(r.overall_score).toFixed(0)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}

function RetentionTab({
  agreement,
  agreements,
}: {
  agreement: Agreement | undefined;
  agreements: Agreement[];
}) {
  const { t } = useTranslation();
  const [agreementId, setAgreementId] = useState(agreement?.id ?? '');
  const effectiveId = agreementId || agreement?.id || '';

  const ledgerQ = useQuery({
    queryKey: ['subcontractors', 'retention', effectiveId],
    queryFn: () => listRetentionLedger(effectiveId),
    enabled: !!effectiveId,
  });

  if (agreements.length === 0) {
    return (
      <EmptyState
        icon={<Award size={20} />}
        title={t('subcontractors.no_retention', {
          defaultValue: 'No retention ledger',
        })}
      />
    );
  }

  const entries = ledgerQ.data ?? [];
  const accrued = entries.reduce((s, e) => s + toNum(e.accrued_amount), 0);
  const released = entries.reduce((s, e) => s + toNum(e.released_amount), 0);
  const balance = accrued - released;
  // Empty currency → undefined so MoneyDisplay falls back to the user's
  // preferred currency rather than a hardcoded EUR.
  const currency =
    agreements.find((a) => a.id === effectiveId)?.currency || undefined;

  return (
    <div className="space-y-3">
      <select
        value={effectiveId}
        onChange={(e) => setAgreementId(e.target.value)}
        className={inputCls}
      >
        {agreements.map((a) => (
          <option key={a.id} value={a.id}>
            {a.title}
          </option>
        ))}
      </select>
      <div className="grid grid-cols-3 gap-2">
        <Card padding="sm">
          <p className="text-xs text-content-tertiary">
            {t('subcontractors.accrued', { defaultValue: 'Accrued' })}
          </p>
          <p className="mt-1 text-sm font-semibold">
            <MoneyDisplay amount={accrued} currency={currency} />
          </p>
        </Card>
        <Card padding="sm">
          <p className="text-xs text-content-tertiary">
            {t('subcontractors.released', { defaultValue: 'Released' })}
          </p>
          <p className="mt-1 text-sm font-semibold">
            <MoneyDisplay amount={released} currency={currency} />
          </p>
        </Card>
        <Card padding="sm">
          <p className="text-xs text-content-tertiary">
            {t('subcontractors.balance', { defaultValue: 'Balance' })}
          </p>
          <p className="mt-1 text-sm font-semibold">
            <MoneyDisplay amount={balance} currency={currency} />
          </p>
        </Card>
      </div>
      {ledgerQ.isLoading && <SkeletonTable rows={3} columns={3} />}
      {ledgerQ.isError && (
        <p className="text-xs text-semantic-error">
          {getErrorMessage(ledgerQ.error)}
        </p>
      )}
      {entries.length === 0 && !ledgerQ.isLoading && !ledgerQ.isError && (
        <p className="text-xs text-content-tertiary">
          {t('subcontractors.no_retention_entries', {
            defaultValue: 'No retention ledger entries yet.',
          })}
        </p>
      )}
      {entries.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-border-light">
          <table className="w-full text-xs">
            <thead className="bg-surface-secondary text-content-tertiary uppercase tracking-wide">
              <tr>
                <th className="px-3 py-2 text-left">
                  {t('subcontractors.released_at', { defaultValue: 'Released at' })}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('subcontractors.accrued', { defaultValue: 'Accrued' })}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('subcontractors.released', { defaultValue: 'Released' })}
                </th>
                <th className="px-3 py-2 text-left">
                  {t('subcontractors.reason', { defaultValue: 'Reason' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id} className="border-t border-border-light">
                  <td className="px-3 py-2 text-content-secondary">
                    {e.released_at ? <DateDisplay value={e.released_at} /> : '—'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    <MoneyDisplay
                      amount={toNum(e.accrued_amount)}
                      currency={currency}
                    />
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    <MoneyDisplay
                      amount={toNum(e.released_amount)}
                      currency={currency}
                    />
                  </td>
                  <td className="px-3 py-2 text-content-secondary">
                    {e.release_reason || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function KV({ label, value }: { label: React.ReactNode; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-content-tertiary">
        {label}
      </p>
      <p className="mt-0.5 text-sm text-content-primary">{value}</p>
    </div>
  );
}

/* ─── Form modal (create + edit) ─── */

interface SubcontractorFormState {
  legal_name: string;
  trade_name: string;
  tax_id: string;
  trade_categories: string;
  country: string;
  website: string;
  notes: string;
  prequalification_status: PrequalStatus;
}

function _toFormState(existing?: Subcontractor): SubcontractorFormState {
  return {
    legal_name: existing?.legal_name ?? '',
    trade_name: existing?.trade_name ?? '',
    tax_id: existing?.tax_id ?? '',
    trade_categories: existing?.trade_categories.join(', ') ?? '',
    country: existing?.country ?? '',
    website: existing?.website ?? '',
    notes: existing?.notes ?? '',
    prequalification_status: existing?.prequalification_status ?? 'pending',
  };
}

function _toPayload(form: SubcontractorFormState): CreateSubcontractorPayload {
  return {
    legal_name: form.legal_name.trim(),
    trade_name: form.trade_name.trim() || undefined,
    tax_id: form.tax_id.trim() || undefined,
    country: form.country.trim() || undefined,
    website: form.website.trim() || undefined,
    notes: form.notes.trim() || undefined,
    prequalification_status: form.prequalification_status,
    trade_categories: form.trade_categories
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean),
  };
}

interface SubcontractorFormModalProps {
  mode: 'create' | 'edit';
  existing?: Subcontractor;
  onClose: () => void;
}

function SubcontractorFormModal({
  mode,
  existing,
  onClose,
}: SubcontractorFormModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState<SubcontractorFormState>(() =>
    _toFormState(existing),
  );

  // Escape/backdrop dismissal + body scroll lock + initial focus are all
  // handled by <WideModal>; the `busy` prop disables them during in-flight
  // submits so users do not accidentally lose unsaved input.

  const submit = async () => {
    if (!form.legal_name.trim()) {
      addToast({
        type: 'error',
        title: t('subcontractors.legal_name_required', {
          defaultValue: 'Legal name is required',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      const payload = _toPayload(form);
      if (mode === 'edit' && existing) {
        // Diff against the original so server-managed columns (rating,
        // timestamps, etc.) aren't touched when only the trade name was
        // changed. Keeps PATCH requests small and audit logs readable.
        const originalPayload = _toPayload(_toFormState(existing));
        const diff: Partial<CreateSubcontractorPayload> = {};
        const originalRecord = originalPayload as unknown as Record<string, unknown>;
        const newRecord = payload as unknown as Record<string, unknown>;
        const diffRecord = diff as unknown as Record<string, unknown>;
        (Object.keys(payload) as (keyof CreateSubcontractorPayload)[]).forEach(
          (k) => {
            // trade_categories is an array — JSON-compare instead of strict ===.
            const a = originalRecord[k];
            const b = newRecord[k];
            const eq =
              Array.isArray(a) && Array.isArray(b)
                ? JSON.stringify(a) === JSON.stringify(b)
                : a === b;
            if (!eq) diffRecord[k] = b;
          },
        );
        if (Object.keys(diff).length === 0) {
          // Nothing changed — close without surprising the user with a
          // toast that says "updated" when nothing actually changed.
          onClose();
          return;
        }
        await updateSubcontractor(existing.id, diff);
        addToast({
          type: 'success',
          title: t('subcontractors.updated', {
            defaultValue: '{{name}} updated',
            name: form.legal_name.trim(),
          }),
        });
      } else {
        await createSubcontractor(payload);
        addToast({
          type: 'success',
          title: t('subcontractors.created', {
            defaultValue: 'Subcontractor created',
          }),
        });
      }
      qc.invalidateQueries({ queryKey: ['subcontractors'] });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const set = <K extends keyof SubcontractorFormState>(
    key: K,
    value: SubcontractorFormState[K],
  ): void => setForm((prev) => ({ ...prev, [key]: value }));

  const isEdit = mode === 'edit';

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      title={
        isEdit
          ? t('subcontractors.edit_title', { defaultValue: 'Edit subcontractor' })
          : t('subcontractors.new', { defaultValue: 'New Subcontractor' })
      }
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            icon={
              busy ? (
                <Loader2 size={14} />
              ) : isEdit ? (
                <Save size={14} />
              ) : (
                <Plus size={14} />
              )
            }
          >
            {isEdit
              ? t('common.save', { defaultValue: 'Save' })
              : t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <WideModalSection
        title={t('subcontractors.section_identity', {
          defaultValue: 'Identity',
        })}
        columns={2}
      >
        <WideModalField
          label={t('subcontractors.legal_name', { defaultValue: 'Legal name' })}
          required
          span={2}
        >
          <input
            value={form.legal_name}
            onChange={(e) => set('legal_name', e.target.value)}
            className={inputCls}
            placeholder="Acme Construction Ltd."
          />
        </WideModalField>
        <WideModalField
          label={t('subcontractors.trade_name', { defaultValue: 'Trade name' })}
        >
          <input
            value={form.trade_name}
            onChange={(e) => set('trade_name', e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('subcontractors.tax_id', { defaultValue: 'Tax ID' })}
        >
          <input
            value={form.tax_id}
            onChange={(e) => set('tax_id', e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('subcontractors.country_iso', {
            defaultValue: 'Country (ISO-2)',
          })}
        >
          <input
            value={form.country}
            onChange={(e) => set('country', e.target.value)}
            className={inputCls}
            maxLength={2}
            placeholder="DE / GB / US"
          />
        </WideModalField>
        <WideModalField
          label={t('subcontractors.website', { defaultValue: 'Website' })}
        >
          <input
            value={form.website}
            onChange={(e) => set('website', e.target.value)}
            className={inputCls}
            placeholder="https://"
          />
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('subcontractors.section_qualification', {
          defaultValue: 'Trades & qualification',
        })}
      >
        <WideModalField
          label={t('subcontractors.trade_categories', {
            defaultValue: 'Trade categories (comma-separated)',
          })}
          hint={t('subcontractors.trade_categories_hint', {
            defaultValue:
              'Free-form labels used for tendering filters — e.g. concrete, steel, mep, finishings.',
          })}
        >
          <input
            value={form.trade_categories}
            onChange={(e) => set('trade_categories', e.target.value)}
            className={inputCls}
            placeholder="concrete, steel, mep"
          />
        </WideModalField>
        <WideModalField
          label={t('subcontractors.prequal_status', {
            defaultValue: 'Prequalification status',
          })}
        >
          <select
            value={form.prequalification_status}
            onChange={(e) =>
              set('prequalification_status', e.target.value as PrequalStatus)
            }
            className={inputCls}
          >
            {(['pending', 'approved', 'suspended', 'rejected'] as PrequalStatus[]).map(
              (s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ),
            )}
          </select>
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('subcontractors.section_notes', { defaultValue: 'Notes' })}
      >
        <WideModalField label={t('subcontractors.notes', { defaultValue: 'Notes' })}>
          <textarea
            value={form.notes}
            onChange={(e) => set('notes', e.target.value)}
            rows={3}
            className={clsx(inputCls, 'h-auto py-2')}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}
