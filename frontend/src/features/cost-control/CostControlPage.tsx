// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cost control: what will the project cost in the end, and why.
//
// The page answers three questions in the order a cost meeting asks them:
// where do we stand (four numbers), what needs a look (a short list), and
// where does each figure come from (the table, one click deeper the line).
// Nothing is typed in twice: budget, estimate, contracts, changes and claims
// already live in their own modules, and each line's forecast takes the most
// reliable of them. A person can still overrule a line, with a reason.
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ArrowRight, FilePenLine, Info, Save, Scale, Search, TrendingUp, Wallet } from 'lucide-react';

import {
  Breadcrumb,
  Button,
  Card,
  DismissibleInfo,
  EmptyState,
  KpiBand,
  ModuleGuideButton,
  Skeleton,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { TabBar } from '@/shared/ui/TabBar';
import { fmtCurrency, fmtPercent } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { costControlApi, num, type CostControlAxis, type CostControlFinding, type CostControlRow } from './api';
import { costControlGuide } from './costControlGuide';
import { ExportMenu } from './ExportMenu';
import { ForecastMethodCard } from './ForecastMethodCard';
import { PhaseComparison } from './PhaseComparison';
import { SnapshotCompare } from './SnapshotCompare';
import { SnapshotDrawer } from './SnapshotDrawer';
import { CostControlTable } from './CostControlTable';
import { ForecastHistory } from './ForecastHistory';
import { AssignDrawer } from './AssignDrawer';
import { ChainPanel } from './ChainPanel';
import { LineDrawer } from './LineDrawer';
import { PaymentsPanel } from './PaymentsPanel';
import { SaveForecastDialog } from './SaveForecastDialog';
import { SOURCE_PRIORITY, findingHint, findingTitle, sourceLabel, sourceTone } from './labels';

function Findings({
  findings,
  rows,
  currency,
  onOpen,
  onAssign,
}: {
  findings: CostControlFinding[];
  rows: CostControlRow[];
  currency: string;
  onOpen: (row: CostControlRow) => void;
  onAssign: () => void;
}) {
  const { t } = useTranslation();
  const [showAll, setShowAll] = useState(false);
  if (findings.length === 0) {
    return (
      <p className="text-sm text-content-secondary">
        {t('cost_control.findings_none', { defaultValue: 'Nothing needs a look right now.' })}
      </p>
    );
  }
  const shown = showAll ? findings : findings.slice(0, 5);
  return (
    <div>
      <ul className="space-y-2">
        {shown.map((f, i) => {
          const row = f.line_key ? rows.find((r) => r.key === f.line_key) : undefined;
          const action =
            f.rule_id === 'cost_control.unassigned_money' ? onAssign : row ? () => onOpen(row) : undefined;
          const Icon = f.severity === 'warning' ? AlertTriangle : Info;
          return (
            <li key={`${f.rule_id}-${f.line_key ?? i}`}>
              <button
                type="button"
                disabled={!action}
                onClick={action}
                className="flex w-full items-start gap-3 rounded-lg px-2 py-1.5 text-left enabled:hover:bg-surface-secondary/60"
              >
                <Icon
                  size={16}
                  className={`mt-0.5 shrink-0 ${f.severity === 'warning' ? 'text-amber-500' : 'text-sky-500'}`}
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm text-content-primary">{findingTitle(t, f)}</span>
                  <span className="block text-xs text-content-tertiary">{findingHint(t, f)}</span>
                </span>
                {num(f.amount) !== 0 && (
                  <span className="shrink-0 text-sm tabular-nums text-content-secondary">
                    {fmtCurrency(f.amount, currency)}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
      {findings.length > 5 && (
        <button
          type="button"
          className="mt-2 text-xs font-medium text-oe-blue hover:underline"
          onClick={() => setShowAll((v) => !v)}
        >
          {showAll
            ? t('cost_control.findings_less', { defaultValue: 'Show fewer' })
            : t('cost_control.findings_more', { defaultValue: 'Show all ({{n}})', n: findings.length })}
        </button>
      )}
    </div>
  );
}

export function CostControlPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const projectName = useProjectContextStore((s) => s.activeProjectName);
  const canEdit = useHasPermission('costmodel.write');
  const canManage = useHasPermission('costmodel.manage');
  const canEditPayments = useHasPermission('payment_release.write');
  const canReleasePayments = useHasPermission('payment_release.release');

  const [axis, setAxis] = useState<CostControlAxis>('cost_line');
  /** The table can also show the phase comparison, which reads the cost line axis. */
  const [view, setView] = useState<CostControlAxis | 'phases'>('cost_line');
  const [openSnapshot, setOpenSnapshot] = useState<string | null>(null);
  const [pendingLine, setPendingLine] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [onlyOver, setOnlyOver] = useState(false);
  const [openRow, setOpenRow] = useState<CostControlRow | null>(null);
  const [assigning, setAssigning] = useState(false);
  const [saving, setSaving] = useState(false);

  const report = useQuery({
    queryKey: ['cost-control', 'report', projectId, axis],
    queryFn: () => costControlApi.report(projectId!, axis),
    enabled: !!projectId,
  });
  const snapshots = useQuery({
    queryKey: ['cost-control', 'snapshots', projectId],
    queryFn: () => costControlApi.snapshots(projectId!),
    enabled: !!projectId,
  });

  const panel = useQuery({
    queryKey: ['cost-control', 'forecast-panel', projectId],
    queryFn: () => costControlApi.forecastPanel(projectId!),
    enabled: !!projectId,
  });
  const openDraft = panel.data?.open_draft ?? null;

  const saveSnapshot = useMutation({
    mutationFn: (body: Parameters<typeof costControlApi.createSnapshot>[1]) =>
      costControlApi.createSnapshot(projectId!, body),
    onSuccess: (created) => {
      setSaving(false);
      queryClient.invalidateQueries({ queryKey: ['cost-control'] });
      setOpenSnapshot(created.id);
      addToast({ type: 'success', title: t('cost_control.draft_started', { defaultValue: 'Draft started' }) });
    },
    onError: (err: unknown) =>
      addToast({
        type: 'error',
        title: t('cost_control.save_failed', { defaultValue: 'Could not save the forecast' }),
        message: getErrorMessage(err),
      }),
  });

  const deleteSnapshot = useMutation({
    mutationFn: (id: string) => costControlApi.deleteSnapshot(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cost-control'] }),
    onError: (err: unknown) =>
      addToast({
        type: 'error',
        title: t('cost_control.snapshot_delete_failed', { defaultValue: 'Could not delete the saved forecast' }),
        message: getErrorMessage(err),
      }),
  });

  const data = report.data;
  const currency = data?.currency || 'EUR';

  // A finding names a cost line by its key; on the contract axis that line is not a row, so switch first.
  useEffect(() => {
    if (!pendingLine || !data || data.axis !== 'cost_line') return;
    const row = data.rows.find((r) => r.key === pendingLine);
    if (row) setOpenRow(row);
    setPendingLine(null);
  }, [pendingLine, data]);
  const openLine = (key: string) => {
    if (axis !== 'cost_line') {
      setAxis('cost_line');
      setView('cost_line');
    }
    setPendingLine(key);
  };
  const totals = data?.totals ?? {};

  const rows = useMemo(() => {
    const all = data?.rows ?? [];
    const q = search.trim().toLowerCase();
    return all.filter((r) => {
      if (onlyOver && !(num(r.planned) > 0 && num(r.variance) > 0.005)) return false;
      if (!q) return true;
      return r.code.toLowerCase().includes(q) || r.description.toLowerCase().includes(q);
    });
  }, [data, search, onlyOver]);

  if (!projectId) {
    return (
      <EmptyState
        icon={<Scale size={28} />}
        title={t('cost_control.no_project', { defaultValue: 'Open a project first' })}
        description={t('cost_control.no_project_desc', {
          defaultValue: 'Cost control works on one project at a time. Pick the project, then come back here.',
        })}
        action={{ label: t('cost_control.go_projects', { defaultValue: 'Go to projects' }), onClick: () => navigate('/projects') }}
      />
    );
  }

  const variance = num(totals.variance);
  const pendingCount = Number(totals.pending_count ?? 0);
  const hasNothing = !!data && data.rows.length === 0;

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          { label: projectName || t('cost_control.project', { defaultValue: 'Project' }), to: `/projects/${projectId}` },
          { label: t('nav.cost_control', { defaultValue: 'Cost control' }) },
        ]}
      />
      <PageHeader
        srTitle={t('nav.cost_control', { defaultValue: 'Cost control' })}
        subtitle={t('cost_control.subtitle', {
          defaultValue: 'What the project will cost in the end, where each figure comes from, and how it moved.',
        })}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <ModuleGuideButton content={costControlGuide} />
            {!hasNothing && <ExportMenu projectId={projectId} />}
            {!hasNothing && openDraft ? (
              <Button
                variant="primary"
                size="sm"
                icon={<FilePenLine size={14} />}
                onClick={() => setOpenSnapshot(openDraft.id)}
              >
                {t('cost_control.draft_open', { defaultValue: 'Open the draft' })}
              </Button>
            ) : canEdit && !hasNothing ? (
              <Button variant="primary" size="sm" icon={<Save size={14} />} onClick={() => setSaving(true)}>
                {t('cost_control.draft_start', { defaultValue: 'Start snapshot' })}
              </Button>
            ) : null}
          </div>
        }
      />

      <DismissibleInfo
        storageKey="cost-control-how-it-works"
        title={t('cost_control.how_title', { defaultValue: 'How the forecast works' })}
      >
        <ol className="list-decimal space-y-1 pl-5 text-sm text-content-secondary">
          <li>
            {t('cost_control.how_1', {
              defaultValue:
                'Every cost line takes the most reliable figure it already has. You do not type the forecast in.',
            })}
          </li>
          <li>
            {t('cost_control.how_2', {
              defaultValue:
                'If you know more than the data, for example a new offer, enter your own forecast on the line. A reason is required and stays in the history.',
            })}
          </li>
          <li>
            {t('cost_control.how_3', {
              defaultValue: 'Save the forecast once a month. The saved forecasts show how the cost moved and why.',
            })}
          </li>
          <li>
            {t('cost_control.how_4', {
              defaultValue:
                'Supplier invoices are checked against what is measured, and each one shows how its payment is worked out: retention, earlier payments, rounding and discount. A manager confirms the release.',
            })}
          </li>
          <li>
            {t('cost_control.how_5', {
              defaultValue:
                'Choose how the forecast is read: the most reliable figure, the highest one, or projected from progress. Each month start a snapshot, write the reason behind every large move, then freeze it. Frozen snapshots never change.',
            })}
          </li>
        </ol>
        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-content-tertiary">
          <span>{t('cost_control.how_order', { defaultValue: 'Most reliable first:' })}</span>
          {SOURCE_PRIORITY.map((s, i) => (
            <span key={s} className="flex items-center gap-1.5">
              <span className={`rounded px-1.5 py-px font-medium ${sourceTone(s)}`}>{sourceLabel(t, s)}</span>
              {i < SOURCE_PRIORITY.length - 1 && <ArrowRight size={12} />}
            </span>
          ))}
        </div>
      </DismissibleInfo>

      {report.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : report.error ? (
        <Card className="text-sm text-semantic-error">{getErrorMessage(report.error)}</Card>
      ) : hasNothing ? (
        <EmptyState
          icon={<Scale size={28} />}
          title={t('cost_control.empty_title', { defaultValue: 'No cost lines yet' })}
          description={t('cost_control.empty_desc', {
            defaultValue:
              'Cost control reads the cost lines of the project. Create them from the bill of quantities on the 5D cost model page, then the budget, contracts and claims fill this page by themselves.',
          })}
          action={{ label: t('cost_control.go_5d', { defaultValue: 'Open the 5D cost model' }), onClick: () => navigate('/5d') }}
        />
      ) : null}

      {/* Supplier invoices and their releases exist without cost lines too, so the panel is never hidden behind the empty state. */}
      {hasNothing && (
        <Card>
          <PaymentsPanel
            projectId={projectId}
            currency={currency}
            canEdit={canEditPayments}
            canRelease={canReleasePayments}
          />
        </Card>
      )}

      {report.isLoading || report.error || hasNothing ? null : data ? (
        <>
          <KpiBand
            columns={4}
            items={[
              {
                key: 'planned',
                label: t('cost_control.kpi_planned', { defaultValue: 'Planned' }),
                value: fmtCurrency(totals.planned, currency),
                sub: t('cost_control.kpi_planned_sub', { defaultValue: 'Budget, or the estimate where no budget is set' }),
                icon: Scale,
              },
              {
                key: 'forecast',
                label: t('cost_control.kpi_forecast', { defaultValue: 'Expected final cost' }),
                value: fmtCurrency(totals.forecast, currency),
                sub:
                  pendingCount > 0
                    ? t('cost_control.kpi_forecast_pending', {
                        defaultValue: 'plus {{amount}} in undecided changes',
                        amount: fmtCurrency(totals.pending_changes, currency),
                      })
                    : t('cost_control.kpi_forecast_sub', { defaultValue: 'From the most reliable figure per line' }),
                icon: TrendingUp,
              },
              {
                key: 'variance',
                label: t('cost_control.kpi_variance', { defaultValue: 'Difference to plan' }),
                value: `${variance > 0 ? '+' : ''}${fmtCurrency(variance, currency)}`,
                sub: totals.variance_pct ? `${variance > 0 ? '+' : ''}${fmtPercent(totals.variance_pct)}` : undefined,
                tone: variance > 0.005 ? 'danger' : variance < -0.005 ? 'success' : 'default',
                tintValue: true,
                icon: AlertTriangle,
              },
              {
                key: 'paid',
                label: t('cost_control.kpi_paid', { defaultValue: 'Paid so far' }),
                value: fmtCurrency(totals.paid, currency),
                sub: t('cost_control.kpi_paid_sub', {
                  defaultValue: 'of {{amount}} certified',
                  amount: fmtCurrency(totals.certified, currency),
                }),
                icon: Wallet,
              },
            ]}
          />

          <Card>
            <h2 className="mb-3 text-sm font-semibold text-content-primary">
              {t('cost_control.findings_title', { defaultValue: 'Worth a look' })}
            </h2>
            <Findings
              findings={data.findings}
              rows={data.rows}
              currency={currency}
              onOpen={setOpenRow}
              onAssign={() => setAssigning(true)}
            />
          </Card>

          <Card>
            <ForecastMethodCard
              projectId={projectId}
              currency={currency}
              canManage={canManage}
              onOpenLine={openLine}
              onOpenDraft={setOpenSnapshot}
            />
          </Card>

          <Card>
            <ChainPanel projectId={projectId} currency={currency} canEdit={canEdit} />
          </Card>

          <div className="flex flex-wrap items-center gap-3">
            <TabBar
              variant="segmented"
              size="sm"
              ariaLabel={t('cost_control.axis_label', { defaultValue: 'Group the table' })}
              activeId={view}
              onChange={(next) => {
                setView(next);
                if (next !== 'phases') setAxis(next);
              }}
              tabs={[
                { id: 'cost_line', label: t('cost_control.axis_cost_line', { defaultValue: 'By cost line' }) },
                { id: 'contract', label: t('cost_control.axis_contract', { defaultValue: 'By contract' }) },
                { id: 'phases', label: t('cost_control.axis_phases', { defaultValue: 'Phase comparison' }) },
              ]}
            />
            {view !== 'phases' && (
              <>
            <label className="relative ms-auto flex items-center">
              <Search size={14} className="pointer-events-none absolute start-2.5 text-content-quaternary" />
              <input
                className="h-8 w-56 rounded-lg border border-border bg-surface-primary ps-8 pe-3 text-sm"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('cost_control.search', { defaultValue: 'Find a code or name' })}
                aria-label={t('cost_control.search', { defaultValue: 'Find a code or name' })}
              />
            </label>
            <label className="flex items-center gap-2 text-sm text-content-secondary">
              <input type="checkbox" checked={onlyOver} onChange={(e) => setOnlyOver(e.target.checked)} />
              {t('cost_control.only_over', { defaultValue: 'Only lines above plan' })}
            </label>
              </>
            )}
          </div>

          {view === 'phases' ? (
            <PhaseComparison projectId={projectId} currency={currency} />
          ) : (
            <CostControlTable
              axis={axis}
              rows={rows}
              totals={totals}
              accounts={data.accounts}
              currency={currency}
              onOpenLine={setOpenRow}
              onOpenUnassigned={() => setAssigning(true)}
            />
          )}

          <Card>
            <PaymentsPanel
              projectId={projectId}
              currency={currency}
              canEdit={canEditPayments}
              canRelease={canReleasePayments}
            />
          </Card>

          <Card>
            <h2 className="mb-3 text-sm font-semibold text-content-primary">
              {t('cost_control.history_section', { defaultValue: 'Saved forecasts' })}
            </h2>
            <ForecastHistory
              snapshots={snapshots.data?.items ?? []}
              currency={currency}
              canDelete={canEdit}
              onDelete={(id) => deleteSnapshot.mutate(id)}
              onOpen={setOpenSnapshot}
            />
          </Card>

          <Card>
            <h2 className="mb-3 text-sm font-semibold text-content-primary">
              {t('cost_control.compare_section', { defaultValue: 'How the forecast moved' })}
            </h2>
            <SnapshotCompare projectId={projectId} snapshots={snapshots.data?.items ?? []} currency={currency} />
          </Card>
        </>
      ) : null}

      <LineDrawer
        projectId={projectId}
        row={openRow}
        currency={currency}
        canEdit={canEdit}
        onClose={() => setOpenRow(null)}
      />
      <SnapshotDrawer
        projectId={projectId}
        snapshotId={openSnapshot}
        currency={currency}
        canEdit={canEdit}
        onClose={() => setOpenSnapshot(null)}
      />
      <AssignDrawer
        open={assigning}
        projectId={projectId}
        currency={currency}
        canEdit={canEdit}
        onClose={() => setAssigning(false)}
        onOpen5d={() => navigate('/5d')}
      />
      <SaveForecastDialog
        open={saving}
        busy={saveSnapshot.isPending}
        onClose={() => setSaving(false)}
        onSave={(body) => saveSnapshot.mutate(body)}
      />
    </div>
  );
}
