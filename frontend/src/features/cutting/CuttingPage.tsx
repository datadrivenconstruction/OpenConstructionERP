// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Cutting optimisation: turn a known cut list into cutting plans with a
 * measured yield, waste and cost, instead of a flat waste percentage.
 *
 * Left: the project's cutting jobs. Right: the selected job - settings, the
 * cut list (typed, pasted, or pulled from a bending schedule, linear takeoff,
 * a BOQ line or a CSV/XLSX file), the stock on offer (with inventory offcuts),
 * validation, and the latest plan with its diagrams, exports, the proposal to
 * the BOQ line and requisition, and the offcut return to site inventory.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardPaste,
  Download,
  FileUp,
  Loader2,
  PackageOpen,
  Play,
  Plus,
  Scissors,
  Trash2,
  Warehouse,
} from 'lucide-react';
import {
  Badge,
  BOQPicker,
  Button,
  Card,
  CollapsibleSection,
  ConfidenceBadge,
  EmptyState,
  Input,
  PageHeader,
  StatCard,
} from '@/shared/ui';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtCurrency, fmtList, fmtNumber } from '@/shared/lib/formatters';
import { normalizeRole, ROLE_RANK } from '@/shared/lib/roles';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { boqApi } from '@/features/boq/api';
import { fetchCutting as fetchRebarCutting, fetchImports as fetchRebarImports } from '@/features/rebar-schedule/api';
import { getRequisition, listRequisitions } from '@/features/procurement/requisitionsApi';
import {
  addInventoryStock,
  applyPlan,
  createJob,
  deleteJob,
  downloadPlan,
  fetchInventoryOffcuts,
  fetchJob,
  fetchJobs,
  fetchPlan,
  fetchProposal,
  importBoq,
  importFile,
  importRebar,
  importTakeoff,
  optimiseJob,
  returnOffcuts,
  savePieces,
  saveStocks,
  updateJob,
  validateJob,
  type CuttingJob,
  type CuttingPiece,
  type CuttingPlan,
  type CuttingStock,
  type ImportResult,
  type JobKind,
  type JobSettings,
  type ValidationReport,
} from './api';
import { LinearPlanDiagram, SheetPlanDiagram } from './CuttingDiagram';
import { nextRef, oversizePieces, parsePastedPieces, pieceCount, positiveDecimal, uniqueRefs } from './cuttingMath';

type TFn = (key: string, opts?: Record<string, unknown>) => string;

const QK = {
  jobs: (projectId: string | null) => ['cutting', 'jobs', projectId] as const,
  job: (jobId: string | null) => ['cutting', 'job', jobId] as const,
  plan: (planId: string | null) => ['cutting', 'plan', planId] as const,
};

function roleRank(role: string | null): number {
  const r = normalizeRole(role);
  return r in ROLE_RANK ? ROLE_RANK[r as keyof typeof ROLE_RANK] : -99;
}

function kindLabel(kind: JobKind, t: TFn): string {
  return kind === 'sheet'
    ? t('cutting.kind_sheet', { defaultValue: 'Sheets (2D)' })
    : t('cutting.kind_linear', { defaultValue: 'Bars and profiles (1D)' });
}

function statusLabel(status: string, t: TFn): string {
  switch (status) {
    case 'optimised':
      return t('cutting.status_optimised', { defaultValue: 'Optimised' });
    case 'applied':
      return t('cutting.status_applied', { defaultValue: 'Applied' });
    default:
      return t('cutting.status_draft', { defaultValue: 'Draft' });
  }
}

function sourceLabel(source: string, t: TFn): string {
  switch (source) {
    case 'rebar_schedule':
      return t('cutting.source_rebar_schedule', { defaultValue: 'From a bending schedule' });
    case 'takeoff':
      return t('cutting.source_takeoff', { defaultValue: 'From takeoff' });
    case 'boq':
      return t('cutting.source_boq', { defaultValue: 'From a BOQ line' });
    case 'import':
      return t('cutting.source_import', { defaultValue: 'From a file' });
    default:
      return t('cutting.source_manual', { defaultValue: 'Entered by hand' });
  }
}

function reasonLabel(reason: string, t: TFn): string {
  switch (reason) {
    case 'boq_locked':
      return t('cutting.reason_boq_locked', { defaultValue: 'The BOQ is locked' });
    case 'requisition_not_draft':
      return t('cutting.reason_requisition_not_draft', { defaultValue: 'The requisition is no longer a draft' });
    case 'pieces_unplaced':
      return t('cutting.reason_pieces_unplaced', { defaultValue: 'Some pieces are unplaced' });
    case 'unit_mass_missing':
      return t('cutting.reason_unit_mass_missing', { defaultValue: 'Set the mass per unit for a line in kg or t' });
    case 'not_found':
      return t('cutting.reason_not_found', { defaultValue: 'The linked line no longer exists' });
    default:
      return t('cutting.reason_unit_not_convertible', { defaultValue: 'The line unit cannot be derived from the plan' });
  }
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function CuttingPage() {
  const { t } = useTranslation();
  const params = useParams<{ projectId?: string }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectId = params.projectId ?? activeProjectId;
  const canEdit = roleRank(useAuthStore((s) => s.userRole)) >= ROLE_RANK.editor;
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  const jobsQuery = useQuery({
    queryKey: QK.jobs(projectId),
    queryFn: () => fetchJobs(projectId!),
    enabled: !!projectId,
  });
  const jobs = useMemo(() => jobsQuery.data ?? [], [jobsQuery.data]);

  useEffect(() => {
    if (!selectedJobId && jobs.length > 0) setSelectedJobId(jobs[0]!.id);
    if (selectedJobId && jobsQuery.isSuccess && !jobs.some((j) => j.id === selectedJobId)) {
      setSelectedJobId(jobs[0]?.id ?? null);
    }
  }, [jobs, jobsQuery.isSuccess, selectedJobId]);

  return (
    <div className="space-y-5">
      <PageHeader
        srTitle={t('cutting.title', { defaultValue: 'Cutting Optimisation' })}
        subtitle={t('cutting.subtitle', {
          defaultValue:
            'Turn a known cut list into cutting plans with measured yield, waste and cost, instead of a flat waste percentage.',
        })}
      />
      <Explainer t={t} />
      {!projectId ? (
        <EmptyState
          icon={<Scissors size={28} />}
          title={t('cutting.no_project', { defaultValue: 'Select a project' })}
          description={t('cutting.no_project_hint', {
            defaultValue: 'Cutting jobs belong to a project. Pick one in the project switcher to start.',
          })}
        />
      ) : (
        <div className="grid gap-5 lg:grid-cols-[18rem_minmax(0,1fr)]">
          <JobList
            projectId={projectId}
            jobs={jobs}
            loading={jobsQuery.isLoading}
            selectedJobId={selectedJobId}
            onSelect={setSelectedJobId}
            canEdit={canEdit}
          />
          {selectedJobId ? (
            <JobEditor key={selectedJobId} jobId={selectedJobId} projectId={projectId} canEdit={canEdit} />
          ) : (
            <EmptyState
              icon={<Scissors size={28} />}
              title={t('cutting.no_jobs', { defaultValue: 'No cutting jobs yet' })}
              description={t('cutting.no_jobs_hint', {
                defaultValue: 'Create a job for one material, for example rebar 16 mm or 18 mm plywood, then add its cut list.',
              })}
            />
          )}
        </div>
      )}
    </div>
  );
}

function Explainer({ t }: { t: TFn }) {
  const steps = [
    {
      num: 1,
      title: t('cutting.step1_title', { defaultValue: 'Create a job' }),
      desc: t('cutting.step1_desc', { defaultValue: 'one material, bars or sheets, with saw kerf and minimum usable offcut' }),
    },
    {
      num: 2,
      title: t('cutting.step2_title', { defaultValue: 'Add the cut list and stock' }),
      desc: t('cutting.step2_desc', {
        defaultValue: 'type or paste pieces, or pull them from a bending schedule, takeoff, a BOQ line or a file',
      }),
    },
    {
      num: 3,
      title: t('cutting.step3_title', { defaultValue: 'Optimise' }),
      desc: t('cutting.step3_desc', { defaultValue: 'get cutting plans with yield, waste, stock count and cost' }),
    },
    {
      num: 4,
      title: t('cutting.step4_title', { defaultValue: 'Confirm and use' }),
      desc: t('cutting.step4_desc', {
        defaultValue: 'print the cutting list, confirm the proposed BOQ and order quantities, return offcuts to inventory',
      }),
    },
  ];
  return (
    <CollapsibleSection
      storageKey="cutting.how"
      icon={<Scissors size={15} className="text-oe-blue" />}
      title={t('cutting.flow_title', { defaultValue: 'How cutting optimisation works' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('cutting.flow_intro', {
          defaultValue:
            'Where the cut list is known, the optimiser replaces a guessed waste factor with the waste the cutting plan really leaves.',
        })}
      </p>
      <ol className="mt-3 space-y-2">
        {steps.map((s) => (
          <li key={s.num} className="flex gap-3 text-xs">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-oe-blue/10 text-[10px] font-bold text-oe-blue-text">
              {s.num}
            </span>
            <div>
              <span className="font-medium text-content-primary">{s.title}</span>
              <span className="text-content-tertiary"> - {s.desc}</span>
            </div>
          </li>
        ))}
      </ol>
      <div className="mt-3 border-t border-border-light pt-3 text-2xs text-content-tertiary">
        <span className="font-medium text-content-secondary">{t('cutting.flow_related', { defaultValue: 'Related:' })}</span>{' '}
        <Link to="/rebar-schedule" className="font-medium text-oe-blue-text hover:underline">
          {t('cutting.mod_rebar', { defaultValue: 'Rebar schedule' })}
        </Link>
        {' · '}
        <Link to="/waste-factors" className="font-medium text-oe-blue-text hover:underline">
          {t('cutting.mod_waste', { defaultValue: 'Waste factors' })}
        </Link>
        {' · '}
        <Link to="/boq" className="font-medium text-oe-blue-text hover:underline">
          {t('cutting.mod_boq', { defaultValue: 'BOQ' })}
        </Link>
        {' · '}
        <Link to="/site-inventory" className="font-medium text-oe-blue-text hover:underline">
          {t('cutting.mod_inventory', { defaultValue: 'Site inventory' })}
        </Link>
      </div>
    </CollapsibleSection>
  );
}

// ---------------------------------------------------------------------------
// Job list
// ---------------------------------------------------------------------------

function JobList({
  projectId,
  jobs,
  loading,
  selectedJobId,
  onSelect,
  canEdit,
}: {
  projectId: string;
  jobs: Awaited<ReturnType<typeof fetchJobs>>;
  loading: boolean;
  selectedJobId: string | null;
  onSelect: (id: string) => void;
  canEdit: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [name, setName] = useState('');
  const [kind, setKind] = useState<JobKind>('linear');

  const createMut = useMutation({
    mutationFn: () =>
      createJob({
        project_id: projectId,
        name: name.trim(),
        kind,
        kerf_mm: kind === 'sheet' ? '4' : '3',
        min_offcut_mm: kind === 'sheet' ? '300' : '500',
      }),
    onSuccess: (job) => {
      setName('');
      queryClient.invalidateQueries({ queryKey: QK.jobs(projectId) });
      onSelect(job.id);
    },
    onError: (e) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  return (
    <Card className="space-y-3 p-4">
      <h2 className="text-sm font-semibold text-content-primary">{t('cutting.jobs', { defaultValue: 'Cutting jobs' })}</h2>
      {loading ? (
        <Loader2 className="animate-spin text-content-tertiary" size={18} />
      ) : (
        <ul className="space-y-1" aria-label={t('cutting.jobs', { defaultValue: 'Cutting jobs' })}>
          {jobs.map((job) => (
            <li key={job.id}>
              <button
                type="button"
                onClick={() => onSelect(job.id)}
                className={`w-full rounded-lg px-3 py-2 text-left text-sm transition ${
                  job.id === selectedJobId ? 'bg-oe-blue/10 text-content-primary' : 'hover:bg-surface-secondary'
                }`}
              >
                <div className="truncate font-medium">{job.name}</div>
                <div className="flex flex-wrap gap-x-2 text-2xs text-content-tertiary">
                  <span>{kindLabel(job.kind, t)}</span>
                  {job.material && <span>{job.material}</span>}
                  {job.latest_yield_pct !== null && (
                    <span className="tabular-nums">
                      {t('cutting.yield_short', { defaultValue: 'Yield {{value}} %', value: fmtNumber(job.latest_yield_pct, 1) })}
                    </span>
                  )}
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
      {canEdit && (
        <form
          className="space-y-2 border-t border-border-light pt-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) createMut.mutate();
          }}
        >
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('cutting.new_job_placeholder', { defaultValue: 'Job name, e.g. Rebar 16 mm level 2' })}
            aria-label={t('cutting.new_job_name', { defaultValue: 'New job name' })}
          />
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as JobKind)}
            className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm"
            aria-label={t('cutting.job_kind', { defaultValue: 'Kind' })}
          >
            <option value="linear">{kindLabel('linear', t)}</option>
            <option value="sheet">{kindLabel('sheet', t)}</option>
          </select>
          <Button type="submit" size="sm" icon={<Plus size={14} />} loading={createMut.isPending} disabled={!name.trim()}>
            {t('cutting.new_job', { defaultValue: 'New job' })}
          </Button>
        </form>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Job editor
// ---------------------------------------------------------------------------

function JobEditor({ jobId, projectId, canEdit }: { jobId: string; projectId: string; canEdit: boolean }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const jobQuery = useQuery({ queryKey: QK.job(jobId), queryFn: () => fetchJob(jobId) });
  const job = jobQuery.data;
  const [pieces, setPieces] = useState<CuttingPiece[]>([]);
  const [stocks, setStocks] = useState<CuttingStock[]>([]);
  const [dirty, setDirty] = useState(false);
  const [planId, setPlanId] = useState<string | null>(null);
  const [validation, setValidation] = useState<ValidationReport | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (job && !dirty) {
      setPieces(job.pieces);
      setStocks(job.stocks);
    }
  }, [job, dirty]);

  const planQuery = useQuery({
    queryKey: QK.plan(planId),
    queryFn: () => fetchPlan(planId!),
    enabled: !!planId,
  });
  const jobsList = queryClient.getQueryData<Awaited<ReturnType<typeof fetchJobs>>>(QK.jobs(projectId));
  const latestPlanId = jobsList?.find((j) => j.id === jobId)?.latest_plan_id ?? null;
  useEffect(() => {
    if (!planId && latestPlanId) setPlanId(latestPlanId);
  }, [latestPlanId, planId]);

  const onError = (e: unknown) =>
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });

  const refresh = (fresh?: CuttingJob) => {
    if (fresh) queryClient.setQueryData(QK.job(jobId), fresh);
    queryClient.invalidateQueries({ queryKey: QK.jobs(projectId) });
  };

  const saveMut = useMutation({
    mutationFn: async () => {
      await savePieces(jobId, uniqueRefs(pieces));
      return saveStocks(jobId, uniqueRefs(stocks));
    },
    onSuccess: (fresh) => {
      setDirty(false);
      refresh(fresh);
    },
    onError,
  });

  const optimiseMut = useMutation({
    mutationFn: async () => {
      if (dirty) {
        await savePieces(jobId, uniqueRefs(pieces));
        await saveStocks(jobId, uniqueRefs(stocks));
        setDirty(false);
      }
      return optimiseJob(jobId);
    },
    onSuccess: (plan) => {
      queryClient.setQueryData(QK.plan(plan.id), plan);
      setPlanId(plan.id);
      setValidation(plan.validation);
      refresh();
      queryClient.invalidateQueries({ queryKey: QK.job(jobId) });
    },
    onError,
  });

  const validateMut = useMutation({ mutationFn: () => validateJob(jobId), onSuccess: setValidation, onError });

  const deleteMut = useMutation({
    mutationFn: () => deleteJob(jobId),
    onSuccess: () => {
      setConfirmDelete(false);
      queryClient.invalidateQueries({ queryKey: QK.jobs(projectId) });
    },
    onError,
  });

  const onImported = (res: ImportResult) => {
    setDirty(false);
    refresh(res.job);
    addToast({
      type: 'success',
      title: t('cutting.imported', { defaultValue: 'Cut list imported' }),
      message: t('cutting.imported_detail', {
        defaultValue: '{{imported}} rows imported, {{skipped}} skipped',
        imported: res.imported,
        skipped: res.skipped,
      }),
    });
  };

  if (jobQuery.isLoading || !job) {
    return (
      <Card className="flex items-center justify-center p-10">
        <Loader2 className="animate-spin text-content-tertiary" size={22} />
      </Card>
    );
  }

  const oversize = oversizePieces(job.kind, pieces, stocks, job.trim_mm);
  const plan = planQuery.data ?? null;

  return (
    <div className="space-y-4">
      <Card className="space-y-4 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-content-primary">{job.name}</h2>
            <div className="flex flex-wrap gap-2 text-xs text-content-tertiary">
              <Badge variant="neutral">{kindLabel(job.kind, t)}</Badge>
              <Badge variant={job.status === 'applied' ? 'success' : job.status === 'optimised' ? 'blue' : 'neutral'}>
                {statusLabel(job.status, t)}
              </Badge>
              {job.source_type !== 'manual' && (
                <span>{sourceLabel(job.source_type, t)}</span>
              )}
            </div>
          </div>
          {canEdit && (
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" size="sm" onClick={() => validateMut.mutate()} loading={validateMut.isPending}>
                {t('cutting.validate', { defaultValue: 'Validate' })}
              </Button>
              <Button size="sm" icon={<Play size={14} />} onClick={() => optimiseMut.mutate()} loading={optimiseMut.isPending}>
                {t('cutting.optimise', { defaultValue: 'Optimise' })}
              </Button>
              <Button variant="ghost" size="sm" icon={<Trash2 size={14} />} onClick={() => setConfirmDelete(true)}>
                {t('cutting.delete_job', { defaultValue: 'Delete' })}
              </Button>
            </div>
          )}
        </div>
        <SettingsForm job={job} canEdit={canEdit} onSaved={refresh} />
      </Card>

      <Card className="space-y-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">
            {t('cutting.pieces_title', { defaultValue: 'Cut list, pieces: {{n}}', n: pieceCount(pieces) })}
          </h3>
          {canEdit && <ImportBar job={job} projectId={projectId} onImported={onImported} onError={onError} />}
        </div>
        <PiecesTable
          kind={job.kind}
          pieces={pieces}
          oversize={oversize}
          canEdit={canEdit}
          onChange={(rows) => {
            setPieces(rows);
            setDirty(true);
          }}
        />
        {oversize.length > 0 && (
          <p className="flex items-center gap-1 text-xs text-semantic-error">
            <AlertTriangle size={13} />
            {t('cutting.oversize_hint', {
              defaultValue: 'These pieces fit no stock entry: {{refs}}',
              refs: fmtList(oversize),
            })}
          </p>
        )}
      </Card>

      <Card className="space-y-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">{t('cutting.stock_title', { defaultValue: 'Stock on offer' })}</h3>
          {canEdit && <InventoryPicker job={job} projectId={projectId} onAdded={refresh} onError={onError} />}
        </div>
        <StocksTable
          kind={job.kind}
          stocks={stocks}
          currency={job.currency}
          canEdit={canEdit}
          onChange={(rows) => {
            setStocks(rows);
            setDirty(true);
          }}
        />
        {canEdit && dirty && (
          <div className="flex justify-end">
            <Button size="sm" onClick={() => saveMut.mutate()} loading={saveMut.isPending}>
              {t('cutting.save_lists', { defaultValue: 'Save cut list and stock' })}
            </Button>
          </div>
        )}
      </Card>

      {validation && <ValidationPanel report={validation} />}

      {plan && (
        <PlanPanel
          job={job}
          plan={plan}
          canEdit={canEdit}
          locale={i18n.language}
          onChanged={() => {
            queryClient.invalidateQueries({ queryKey: QK.plan(plan.id) });
            refresh();
          }}
        />
      )}

      <ConfirmDialog
        open={confirmDelete}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => deleteMut.mutate()}
        loading={deleteMut.isPending}
        title={t('cutting.delete_title', { defaultValue: 'Delete this cutting job?' })}
        message={t('cutting.delete_message', {
          defaultValue: 'The cut list, the stock and every plan of this job are deleted. BOQ and inventory entries stay.',
        })}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

function SettingsForm({ job, canEdit, onSaved }: { job: CuttingJob; canEdit: boolean; onSaved: (job: CuttingJob) => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState<JobSettings>(() => settingsOf(job));
  const [boqId, setBoqId] = useState<string | null>(null);
  const [reqId, setReqId] = useState<string>('');
  useEffect(() => setForm(settingsOf(job)), [job]);

  const positionsQuery = useQuery({
    queryKey: ['cutting', 'boq-positions', boqId],
    queryFn: () => boqApi.get(boqId!),
    enabled: !!boqId,
  });
  const reqsQuery = useQuery({
    queryKey: ['cutting', 'requisitions', job.project_id],
    queryFn: () => listRequisitions(job.project_id, 'draft'),
    enabled: canEdit,
  });
  const reqQuery = useQuery({ queryKey: ['cutting', 'requisition', reqId], queryFn: () => getRequisition(reqId), enabled: !!reqId });

  const saveMut = useMutation({
    mutationFn: () => updateJob(job.id, form),
    onSuccess: onSaved,
    onError: (e) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  const field = (key: keyof JobSettings, label: string, suffix?: string) => (
    <label className="space-y-1 text-xs text-content-secondary">
      <span>
        {label}
        {suffix ? ` (${suffix})` : ''}
      </span>
      <Input
        value={(form[key] as string | null) ?? ''}
        disabled={!canEdit}
        onChange={(e) => setForm({ ...form, [key]: e.target.value === '' && key === 'unit_mass_kg' ? null : e.target.value })}
      />
    </label>
  );

  const changed = JSON.stringify(form) !== JSON.stringify(settingsOf(job));
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {field('name', t('cutting.field_name', { defaultValue: 'Name' }))}
        {field('material', t('cutting.field_material', { defaultValue: 'Material' }))}
        {field('kerf_mm', t('cutting.field_kerf', { defaultValue: 'Saw kerf' }), 'mm')}
        {field('trim_mm', t('cutting.field_trim', { defaultValue: 'End / edge trim' }), 'mm')}
        {field('min_offcut_mm', t('cutting.field_min_offcut', { defaultValue: 'Minimum usable offcut' }), 'mm')}
        {field('yield_threshold_pct', t('cutting.field_yield_threshold', { defaultValue: 'Yield threshold' }), '%')}
        {field(
          'unit_mass_kg',
          t('cutting.field_unit_mass', { defaultValue: 'Mass per unit' }),
          job.kind === 'sheet' ? 'kg/m2' : 'kg/m',
        )}
        {field('currency', t('cutting.field_currency', { defaultValue: 'Currency' }))}
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="space-y-1 text-xs text-content-secondary">
          <span>{t('cutting.link_boq', { defaultValue: 'BOQ line to update' })}</span>
          {form.boq_position_id && (
            <div className="truncate text-2xs text-content-tertiary">
              {t('cutting.linked', { defaultValue: 'Linked: {{id}}', id: form.boq_position_id })}
            </div>
          )}
          {canEdit && (
            <div className="flex flex-wrap gap-2">
              <BOQPicker projectId={job.project_id} selectedBoqId={boqId} onSelectBoq={setBoqId} showProjectSelector={false} />
              {positionsQuery.data && (
                <select
                  className="min-w-0 flex-1 rounded-lg border border-border bg-surface-primary px-2 py-1.5 text-sm"
                  value={form.boq_position_id ?? ''}
                  onChange={(e) => setForm({ ...form, boq_position_id: e.target.value || null })}
                  aria-label={t('cutting.link_boq', { defaultValue: 'BOQ line to update' })}
                >
                  <option value="">{t('cutting.none', { defaultValue: 'None' })}</option>
                  {positionsQuery.data.positions
                    .filter((p) => p.unit)
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {`${p.ordinal} ${p.description}`.slice(0, 90)}
                      </option>
                    ))}
                </select>
              )}
            </div>
          )}
        </div>
        <div className="space-y-1 text-xs text-content-secondary">
          <span>{t('cutting.link_requisition', { defaultValue: 'Requisition line to update (draft)' })}</span>
          {form.procurement_req_item_id && (
            <div className="truncate text-2xs text-content-tertiary">
              {t('cutting.linked', { defaultValue: 'Linked: {{id}}', id: form.procurement_req_item_id })}
            </div>
          )}
          {canEdit && (
            <div className="flex flex-wrap gap-2">
              <select
                className="rounded-lg border border-border bg-surface-primary px-2 py-1.5 text-sm"
                value={reqId}
                onChange={(e) => setReqId(e.target.value)}
                aria-label={t('cutting.requisition', { defaultValue: 'Requisition' })}
              >
                <option value="">{t('cutting.choose_requisition', { defaultValue: 'Choose a requisition' })}</option>
                {(reqsQuery.data?.items ?? []).map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.req_number || r.title || r.id}
                  </option>
                ))}
              </select>
              {reqQuery.data && (
                <select
                  className="min-w-0 flex-1 rounded-lg border border-border bg-surface-primary px-2 py-1.5 text-sm"
                  value={form.procurement_req_item_id ?? ''}
                  onChange={(e) => setForm({ ...form, procurement_req_item_id: e.target.value || null })}
                  aria-label={t('cutting.link_requisition', { defaultValue: 'Requisition line to update (draft)' })}
                >
                  <option value="">{t('cutting.none', { defaultValue: 'None' })}</option>
                  {reqQuery.data.items.map((item) => (
                    <option key={item.id} value={item.id}>
                      {`${item.description} (${item.unit ?? ''})`.slice(0, 90)}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}
        </div>
      </div>
      {canEdit && changed && (
        <div className="flex justify-end">
          <Button size="sm" variant="secondary" onClick={() => saveMut.mutate()} loading={saveMut.isPending}>
            {t('cutting.save_settings', { defaultValue: 'Save settings' })}
          </Button>
        </div>
      )}
    </div>
  );
}

function settingsOf(job: CuttingJob): JobSettings {
  return {
    name: job.name,
    material: job.material,
    kerf_mm: job.kerf_mm,
    trim_mm: job.trim_mm,
    min_offcut_mm: job.min_offcut_mm,
    yield_threshold_pct: job.yield_threshold_pct,
    unit_mass_kg: job.unit_mass_kg,
    currency: job.currency,
    boq_position_id: job.boq_position_id,
    procurement_req_item_id: job.procurement_req_item_id,
    notes: job.notes,
  };
}

// ---------------------------------------------------------------------------
// Cut list and stock tables
// ---------------------------------------------------------------------------

function cellInput(value: string, onChange: (v: string) => void, label: string, disabled: boolean, invalid = false) {
  return (
    <input
      value={value}
      disabled={disabled}
      aria-label={label}
      aria-invalid={invalid || undefined}
      onChange={(e) => onChange(e.target.value)}
      className={`w-full rounded border bg-surface-primary px-2 py-1 text-sm tabular-nums ${
        invalid ? 'border-semantic-error' : 'border-border-light'
      }`}
    />
  );
}

function PiecesTable({
  kind,
  pieces,
  oversize,
  canEdit,
  onChange,
}: {
  kind: JobKind;
  pieces: CuttingPiece[];
  oversize: string[];
  canEdit: boolean;
  onChange: (rows: CuttingPiece[]) => void;
}) {
  const { t } = useTranslation();
  const [paste, setPaste] = useState('');
  const [showPaste, setShowPaste] = useState(false);
  const set = (i: number, patch: Partial<CuttingPiece>) => onChange(pieces.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-sm">
          <thead className="text-left text-2xs uppercase text-content-tertiary">
            <tr>
              <th className="px-1 py-1">{t('cutting.col_ref', { defaultValue: 'Mark' })}</th>
              <th className="px-1 py-1">{t('cutting.col_length', { defaultValue: 'Length (mm)' })}</th>
              {kind === 'sheet' && <th className="px-1 py-1">{t('cutting.col_width', { defaultValue: 'Width (mm)' })}</th>}
              <th className="px-1 py-1">{t('cutting.col_qty', { defaultValue: 'Qty' })}</th>
              {kind === 'sheet' && <th className="px-1 py-1">{t('cutting.col_rotatable', { defaultValue: 'May rotate' })}</th>}
              <th className="px-1 py-1">{t('cutting.col_label', { defaultValue: 'Description' })}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {pieces.map((p, i) => (
              <tr key={i}>
                <td className="w-24 px-1 py-0.5">{cellInput(p.ref, (v) => set(i, { ref: v }), t('cutting.col_ref', { defaultValue: 'Mark' }), !canEdit, oversize.includes(p.ref))}</td>
                <td className="w-28 px-1 py-0.5">
                  {cellInput(p.length_mm, (v) => set(i, { length_mm: v }), t('cutting.col_length', { defaultValue: 'Length (mm)' }), !canEdit, !positiveDecimal(p.length_mm))}
                </td>
                {kind === 'sheet' && (
                  <td className="w-28 px-1 py-0.5">
                    {cellInput(p.width_mm ?? '', (v) => set(i, { width_mm: v }), t('cutting.col_width', { defaultValue: 'Width (mm)' }), !canEdit, !positiveDecimal(p.width_mm ?? ''))}
                  </td>
                )}
                <td className="w-20 px-1 py-0.5">
                  {cellInput(String(p.quantity), (v) => set(i, { quantity: Math.max(1, Math.floor(Number(v) || 1)) }), t('cutting.col_qty', { defaultValue: 'Qty' }), !canEdit)}
                </td>
                {kind === 'sheet' && (
                  <td className="px-1 py-0.5 text-center">
                    <input
                      type="checkbox"
                      checked={p.rotatable}
                      disabled={!canEdit}
                      aria-label={t('cutting.col_rotatable', { defaultValue: 'May rotate' })}
                      onChange={(e) => set(i, { rotatable: e.target.checked })}
                    />
                  </td>
                )}
                <td className="px-1 py-0.5">{cellInput(p.label, (v) => set(i, { label: v }), t('cutting.col_label', { defaultValue: 'Description' }), !canEdit)}</td>
                <td className="w-8 px-1 py-0.5">
                  {canEdit && (
                    <button
                      type="button"
                      onClick={() => onChange(pieces.filter((_, j) => j !== i))}
                      aria-label={t('cutting.remove_row', { defaultValue: 'Remove row' })}
                      className="text-content-tertiary hover:text-semantic-error"
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canEdit && (
        <div className="flex flex-wrap gap-2">
          <Button
            variant="ghost"
            size="sm"
            icon={<Plus size={14} />}
            onClick={() =>
              onChange([
                ...pieces,
                { ref: nextRef(pieces, 'P'), label: '', length_mm: '', width_mm: kind === 'sheet' ? '' : null, quantity: 1, rotatable: true },
              ])
            }
          >
            {t('cutting.add_piece', { defaultValue: 'Add piece' })}
          </Button>
          <Button variant="ghost" size="sm" icon={<ClipboardPaste size={14} />} onClick={() => setShowPaste((v) => !v)}>
            {t('cutting.paste_rows', { defaultValue: 'Paste from spreadsheet' })}
          </Button>
        </div>
      )}
      {showPaste && (
        <div className="space-y-2">
          <textarea
            value={paste}
            onChange={(e) => setPaste(e.target.value)}
            rows={5}
            className="w-full rounded-lg border border-border bg-surface-primary p-2 font-mono text-xs"
            placeholder={
              kind === 'sheet'
                ? t('cutting.paste_hint_sheet', { defaultValue: 'Mark, length, width, quantity, description - one piece per line' })
                : t('cutting.paste_hint_linear', { defaultValue: 'Mark, length, quantity, description - one piece per line' })
            }
            aria-label={t('cutting.paste_rows', { defaultValue: 'Paste from spreadsheet' })}
          />
          <Button
            size="sm"
            onClick={() => {
              const rows = parsePastedPieces(paste, kind);
              onChange(uniqueRefs([...pieces, ...rows]));
              setPaste('');
              setShowPaste(false);
            }}
          >
            {t('cutting.paste_add', { defaultValue: 'Add pasted rows' })}
          </Button>
        </div>
      )}
    </div>
  );
}

function StocksTable({
  kind,
  stocks,
  currency,
  canEdit,
  onChange,
}: {
  kind: JobKind;
  stocks: CuttingStock[];
  currency: string;
  canEdit: boolean;
  onChange: (rows: CuttingStock[]) => void;
}) {
  const { t } = useTranslation();
  const set = (i: number, patch: Partial<CuttingStock>) => onChange(stocks.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-sm">
          <thead className="text-left text-2xs uppercase text-content-tertiary">
            <tr>
              <th className="px-1 py-1">{t('cutting.col_ref', { defaultValue: 'Mark' })}</th>
              <th className="px-1 py-1">{t('cutting.col_length', { defaultValue: 'Length (mm)' })}</th>
              {kind === 'sheet' && <th className="px-1 py-1">{t('cutting.col_width', { defaultValue: 'Width (mm)' })}</th>}
              <th className="px-1 py-1">
                {t('cutting.col_unit_cost', { defaultValue: 'Cost per piece' })}
                {currency ? ` (${currency})` : ''}
              </th>
              <th className="px-1 py-1">{t('cutting.col_available', { defaultValue: 'Available (empty = unlimited)' })}</th>
              <th className="px-1 py-1">{t('cutting.col_label', { defaultValue: 'Description' })}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {stocks.map((s, i) => (
              <tr key={i} className={s.is_offcut ? 'bg-emerald-500/5' : undefined}>
                <td className="w-24 px-1 py-0.5">{cellInput(s.ref, (v) => set(i, { ref: v }), t('cutting.col_ref', { defaultValue: 'Mark' }), !canEdit)}</td>
                <td className="w-28 px-1 py-0.5">
                  {cellInput(s.length_mm, (v) => set(i, { length_mm: v }), t('cutting.col_length', { defaultValue: 'Length (mm)' }), !canEdit || s.is_offcut, !positiveDecimal(s.length_mm))}
                </td>
                {kind === 'sheet' && (
                  <td className="w-28 px-1 py-0.5">
                    {cellInput(s.width_mm ?? '', (v) => set(i, { width_mm: v }), t('cutting.col_width', { defaultValue: 'Width (mm)' }), !canEdit || s.is_offcut, !positiveDecimal(s.width_mm ?? ''))}
                  </td>
                )}
                <td className="w-28 px-1 py-0.5">
                  {s.is_offcut ? (
                    <span className="text-2xs text-emerald-700 dark:text-emerald-300">{t('cutting.from_inventory', { defaultValue: 'From inventory' })}</span>
                  ) : (
                    cellInput(s.unit_cost, (v) => set(i, { unit_cost: v }), t('cutting.col_unit_cost', { defaultValue: 'Cost per piece' }), !canEdit)
                  )}
                </td>
                <td className="w-28 px-1 py-0.5">
                  {cellInput(
                    s.available === null ? '' : String(s.available),
                    (v) => set(i, { available: v.trim() === '' ? null : Math.max(0, Math.floor(Number(v) || 0)) }),
                    t('cutting.col_available', { defaultValue: 'Available (empty = unlimited)' }),
                    !canEdit,
                  )}
                </td>
                <td className="px-1 py-0.5">{cellInput(s.label, (v) => set(i, { label: v }), t('cutting.col_label', { defaultValue: 'Description' }), !canEdit)}</td>
                <td className="w-8 px-1 py-0.5">
                  {canEdit && (
                    <button
                      type="button"
                      onClick={() => onChange(stocks.filter((_, j) => j !== i))}
                      aria-label={t('cutting.remove_row', { defaultValue: 'Remove row' })}
                      className="text-content-tertiary hover:text-semantic-error"
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canEdit && (
        <Button
          variant="ghost"
          size="sm"
          icon={<Plus size={14} />}
          onClick={() =>
            onChange([
              ...stocks,
              {
                ref: nextRef(stocks, 'S'),
                label: '',
                length_mm: kind === 'sheet' ? '2500' : '12000',
                width_mm: kind === 'sheet' ? '1250' : null,
                unit_cost: '0',
                available: null,
                is_offcut: false,
                inventory_item_id: null,
              },
            ])
          }
        >
          {t('cutting.add_stock', { defaultValue: 'Add stock size' })}
        </Button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Imports and inventory
// ---------------------------------------------------------------------------

type ImportMode = '' | 'rebar' | 'takeoff' | 'boq' | 'file';

function ImportBar({
  job,
  projectId,
  onImported,
  onError,
}: {
  job: CuttingJob;
  projectId: string;
  onImported: (res: ImportResult) => void;
  onError: (e: unknown) => void;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<ImportMode>('');
  const [rebarImportId, setRebarImportId] = useState('');
  const [diameter, setDiameter] = useState('');
  const [group, setGroup] = useState('');
  const [boqId, setBoqId] = useState<string | null>(null);
  const [positionId, setPositionId] = useState('');
  const [pieceLength, setPieceLength] = useState('');
  const [pieceWidth, setPieceWidth] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  const rebarImports = useQuery({
    queryKey: ['cutting', 'rebar-imports', projectId],
    queryFn: () => fetchRebarImports(projectId),
    enabled: mode === 'rebar',
  });
  const rebarDiameters = useQuery({
    queryKey: ['cutting', 'rebar-cutting', rebarImportId],
    queryFn: () => fetchRebarCutting(rebarImportId),
    enabled: mode === 'rebar' && !!rebarImportId,
  });
  const boqPositions = useQuery({
    queryKey: ['cutting', 'boq-positions', boqId],
    queryFn: () => boqApi.get(boqId!),
    enabled: mode === 'boq' && !!boqId,
  });

  const importMut = useMutation({
    mutationFn: async (file?: File): Promise<ImportResult> => {
      if (file) return importFile(job.id, file);
      if (mode === 'rebar') return importRebar(job.id, rebarImportId, diameter);
      if (mode === 'takeoff') return importTakeoff(job.id, group.trim() || null);
      return importBoq(job.id, positionId, pieceLength, job.kind === 'sheet' ? pieceWidth : null);
    },
    onSuccess: (res) => {
      setMode('');
      onImported(res);
    },
    onError,
  });

  const ready =
    (mode === 'rebar' && rebarImportId && diameter) ||
    mode === 'takeoff' ||
    (mode === 'boq' && positionId && positiveDecimal(pieceLength) && (job.kind !== 'sheet' || positiveDecimal(pieceWidth)));

  return (
    <div className="flex flex-wrap items-center gap-2">
      <select
        value={mode}
        onChange={(e) => {
          const next = e.target.value as ImportMode;
          if (next === 'file') {
            fileRef.current?.click();
            return;
          }
          setMode(next);
        }}
        className="rounded-lg border border-border bg-surface-primary px-2 py-1.5 text-sm"
        aria-label={t('cutting.import_from', { defaultValue: 'Import cut list from' })}
      >
        <option value="">{t('cutting.import_from', { defaultValue: 'Import cut list from' })}</option>
        {job.kind === 'linear' && <option value="rebar">{t('cutting.import_rebar', { defaultValue: 'Bending schedule' })}</option>}
        {job.kind === 'linear' && <option value="takeoff">{t('cutting.import_takeoff', { defaultValue: 'Linear takeoff' })}</option>}
        <option value="boq">{t('cutting.import_boq', { defaultValue: 'BOQ line' })}</option>
        <option value="file">{t('cutting.import_file', { defaultValue: 'CSV / XLSX file' })}</option>
      </select>
      <input
        ref={fileRef}
        type="file"
        accept=".csv,.txt,.xlsx"
        className="hidden"
        data-testid="cutting-file-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) importMut.mutate(file);
          e.target.value = '';
        }}
      />
      {mode === 'rebar' && (
        <>
          <select
            value={rebarImportId}
            onChange={(e) => setRebarImportId(e.target.value)}
            className="rounded-lg border border-border bg-surface-primary px-2 py-1.5 text-sm"
            aria-label={t('cutting.import_rebar', { defaultValue: 'Bending schedule' })}
          >
            <option value="">{t('cutting.choose_schedule', { defaultValue: 'Choose a schedule' })}</option>
            {(rebarImports.data?.items ?? []).map((imp) => (
              <option key={imp.id} value={imp.id}>
                {imp.filename}
              </option>
            ))}
          </select>
          <select
            value={diameter}
            onChange={(e) => setDiameter(e.target.value)}
            className="rounded-lg border border-border bg-surface-primary px-2 py-1.5 text-sm"
            aria-label={t('cutting.diameter', { defaultValue: 'Bar diameter' })}
          >
            <option value="">{t('cutting.diameter', { defaultValue: 'Bar diameter' })}</option>
            {(rebarDiameters.data ?? [])
              .filter((d) => d.diameter_mm !== null)
              .map((d) => (
                <option key={String(d.diameter_mm)} value={String(d.diameter_mm)}>
                  {t('cutting.diameter_option', { defaultValue: '{{d}} mm ({{bars}} bars)', d: d.diameter_mm, bars: d.bars })}
                </option>
              ))}
          </select>
        </>
      )}
      {mode === 'takeoff' && (
        <Input
          value={group}
          onChange={(e) => setGroup(e.target.value)}
          placeholder={t('cutting.takeoff_group', { defaultValue: 'Measurement group (optional)' })}
          aria-label={t('cutting.takeoff_group', { defaultValue: 'Measurement group (optional)' })}
          className="w-56"
        />
      )}
      {mode === 'boq' && (
        <>
          <BOQPicker projectId={projectId} selectedBoqId={boqId} onSelectBoq={setBoqId} showProjectSelector={false} />
          {boqPositions.data && (
            <select
              value={positionId}
              onChange={(e) => setPositionId(e.target.value)}
              className="max-w-[16rem] rounded-lg border border-border bg-surface-primary px-2 py-1.5 text-sm"
              aria-label={t('cutting.import_boq', { defaultValue: 'BOQ line' })}
            >
              <option value="">{t('cutting.choose_position', { defaultValue: 'Choose a line' })}</option>
              {boqPositions.data.positions
                .filter((p) => p.unit)
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {`${p.ordinal} ${p.description} (${p.quantity} ${p.unit})`.slice(0, 90)}
                  </option>
                ))}
            </select>
          )}
          <Input
            value={pieceLength}
            onChange={(e) => setPieceLength(e.target.value)}
            placeholder={t('cutting.piece_length', { defaultValue: 'Piece length (mm)' })}
            aria-label={t('cutting.piece_length', { defaultValue: 'Piece length (mm)' })}
            className="w-36"
          />
          {job.kind === 'sheet' && (
            <Input
              value={pieceWidth}
              onChange={(e) => setPieceWidth(e.target.value)}
              placeholder={t('cutting.piece_width', { defaultValue: 'Piece width (mm)' })}
              aria-label={t('cutting.piece_width', { defaultValue: 'Piece width (mm)' })}
              className="w-36"
            />
          )}
        </>
      )}
      {mode && mode !== 'file' && (
        <Button size="sm" icon={<FileUp size={14} />} disabled={!ready} loading={importMut.isPending} onClick={() => importMut.mutate(undefined)}>
          {t('cutting.import_run', { defaultValue: 'Import' })}
        </Button>
      )}
    </div>
  );
}

function InventoryPicker({
  job,
  projectId,
  onAdded,
  onError,
}: {
  job: CuttingJob;
  projectId: string;
  onAdded: (job: CuttingJob) => void;
  onError: (e: unknown) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const offcuts = useQuery({
    queryKey: ['cutting', 'inventory', projectId, job.kind, job.material],
    queryFn: () => fetchInventoryOffcuts(projectId, job.kind, job.material),
    enabled: open,
  });
  const addMut = useMutation({
    mutationFn: () => addInventoryStock(job.id, picked),
    onSuccess: (fresh) => {
      setOpen(false);
      setPicked([]);
      onAdded(fresh);
    },
    onError,
  });
  return (
    <div className="relative">
      <Button variant="ghost" size="sm" icon={<Warehouse size={14} />} onClick={() => setOpen((v) => !v)}>
        {t('cutting.use_inventory', { defaultValue: 'Use inventory offcuts' })}
      </Button>
      {open && (
        <Card className="absolute right-0 z-20 mt-1 w-80 space-y-2 p-3 shadow-lg">
          {offcuts.isLoading ? (
            <Loader2 className="animate-spin" size={16} />
          ) : (offcuts.data ?? []).length === 0 ? (
            <p className="text-xs text-content-tertiary">
              {t('cutting.no_inventory_offcuts', { defaultValue: 'No matching offcuts on hand in site inventory.' })}
            </p>
          ) : (
            <ul className="max-h-60 space-y-1 overflow-auto">
              {(offcuts.data ?? []).map((o) => (
                <li key={o.inventory_item_id}>
                  <label className="flex items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      checked={picked.includes(o.inventory_item_id)}
                      onChange={(e) =>
                        setPicked(e.target.checked ? [...picked, o.inventory_item_id] : picked.filter((id) => id !== o.inventory_item_id))
                      }
                    />
                    <span className="flex-1 truncate">{o.name}</span>
                    <span className="tabular-nums text-content-tertiary">
                      {t('cutting.on_hand', { defaultValue: 'On hand: {{n}}', n: o.on_hand })}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
          <Button size="sm" disabled={picked.length === 0} loading={addMut.isPending} onClick={() => addMut.mutate()}>
            {t('cutting.add_selected', { defaultValue: 'Add selected' })}
          </Button>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Validation and plan
// ---------------------------------------------------------------------------

function ValidationPanel({ report }: { report: ValidationReport }) {
  const { t } = useTranslation();
  const failed = report.results.filter((r) => !r.passed);
  const tone = report.errors > 0 ? 'text-semantic-error' : report.warnings > 0 ? 'text-semantic-warning' : 'text-semantic-success';
  return (
    <Card className="space-y-2 p-4" data-testid="cutting-validation">
      <h3 className={`flex items-center gap-2 text-sm font-semibold ${tone}`}>
        {failed.length === 0 ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
        {t('cutting.validation_title', {
          defaultValue: 'Validation: {{errors}} errors, {{warnings}} warnings',
          errors: report.errors,
          warnings: report.warnings,
        })}
      </h3>
      {failed.length > 0 && (
        <ul className="space-y-1 text-xs">
          {failed.map((r, i) => (
            <li key={`${r.rule_id}-${i}`} className="flex gap-2">
              <Badge variant={r.severity === 'error' ? 'error' : r.severity === 'warning' ? 'warning' : 'neutral'}>
                {r.severity === 'error'
                  ? t('cutting.severity_error', { defaultValue: 'Error' })
                  : r.severity === 'warning'
                    ? t('cutting.severity_warning', { defaultValue: 'Warning' })
                    : t('cutting.severity_info', { defaultValue: 'Info' })}
              </Badge>
              <span className="text-content-primary">{r.message}</span>
              {r.suggestion && <span className="text-content-tertiary">{r.suggestion}</span>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function PlanPanel({
  job,
  plan,
  canEdit,
  locale,
  onChanged,
}: {
  job: CuttingJob;
  plan: CuttingPlan;
  canEdit: boolean;
  locale: string;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [showProposal, setShowProposal] = useState(false);
  const unit = plan.kind === 'sheet' ? 'm2' : 'm';
  const proposalQuery = useQuery({
    queryKey: ['cutting', 'proposal', plan.id],
    queryFn: () => fetchProposal(plan.id),
    enabled: showProposal,
  });
  const onError = (e: unknown) =>
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });
  const applyMut = useMutation({
    mutationFn: () => applyPlan(plan.id, true, true),
    onSuccess: (res) => {
      const applied = res.results.filter((r) => r.applied).length;
      addToast({
        type: applied ? 'success' : 'warning',
        title: t('cutting.applied', { defaultValue: 'Proposal applied' }),
        message: t('cutting.applied_detail', { defaultValue: 'Lines updated: {{n}}', n: applied }),
      });
      setShowProposal(false);
      onChanged();
    },
    onError,
  });
  const returnMut = useMutation({
    mutationFn: () => returnOffcuts(plan.id),
    onSuccess: (res) => {
      addToast({
        type: 'success',
        title: t('cutting.offcuts_returned', { defaultValue: 'Inventory updated' }),
        message: t('cutting.offcuts_returned_detail', {
          defaultValue: '{{returned}} offcuts received, {{consumed}} reused offcuts consumed',
          returned: res.returned,
          consumed: res.consumed,
        }),
      });
      onChanged();
    },
    onError,
  });

  return (
    <Card className="space-y-4 p-4" data-testid="cutting-plan">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">
          {t('cutting.plan_title', { defaultValue: 'Cutting plan' })}
          {plan.proven_optimal && (
            <Badge variant="success" className="ml-2">
              {t('cutting.proven_optimal', { defaultValue: 'Proven optimal' })}
            </Badge>
          )}
        </h3>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" icon={<Download size={14} />} onClick={() => void downloadPlan(plan.id, 'pdf', locale)}>
            {t('cutting.export_pdf', { defaultValue: 'Cutting list PDF' })}
          </Button>
          <Button variant="secondary" size="sm" icon={<Download size={14} />} onClick={() => void downloadPlan(plan.id, 'xlsx', locale)}>
            {t('cutting.export_xlsx', { defaultValue: 'Workbook' })}
          </Button>
          {canEdit && (job.boq_position_id || job.procurement_req_item_id) && (
            <Button size="sm" onClick={() => setShowProposal((v) => !v)}>
              {t('cutting.propose', { defaultValue: 'Propose quantities' })}
            </Button>
          )}
          {canEdit && !plan.inventory_synced_at && (plan.offcuts.length > 0 || plan.stock_usage.some((u) => u.is_offcut)) && (
            <Button variant="secondary" size="sm" icon={<PackageOpen size={14} />} loading={returnMut.isPending} onClick={() => returnMut.mutate()}>
              {t('cutting.return_offcuts', { defaultValue: 'Book offcuts in inventory' })}
            </Button>
          )}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatCard label={t('cutting.stat_yield', { defaultValue: 'Yield' })} value={`${fmtNumber(plan.yield_pct, 1)} %`} />
        <StatCard
          label={t('cutting.stat_waste', { defaultValue: 'Waste' })}
          value={`${fmtNumber(plan.waste_pct, 1)} %`}
          sub={`${fmtNumber(plan.scrap_total, 2)} ${unit}`}
        />
        <StatCard
          label={t('cutting.stat_stock', { defaultValue: 'Stock pieces' })}
          value={plan.stock_count}
          sub={`${fmtNumber(plan.stock_total, 2)} ${unit}`}
        />
        <StatCard
          label={t('cutting.stat_offcuts', { defaultValue: 'Reusable offcuts' })}
          value={`${fmtNumber(plan.offcut_total, 2)} ${unit}`}
        />
        <StatCard
          label={t('cutting.stat_cost', { defaultValue: 'Stock cost' })}
          value={plan.currency ? fmtCurrency(plan.cost, plan.currency) : fmtNumber(plan.cost, 2)}
        />
      </div>

      {plan.pieces_unplaced > 0 && (
        <p className="flex items-center gap-1 text-xs text-semantic-error">
          <AlertTriangle size={13} />
          {t('cutting.unplaced_hint', {
            defaultValue: 'Pieces not placed ({{n}}): {{refs}}',
            n: plan.pieces_unplaced,
            refs: fmtList(plan.unplaced.map((u) => `${u.ref} x${u.quantity}`)),
          })}
        </p>
      )}

      {showProposal && (
        <div className="space-y-2 rounded-lg border border-oe-blue/30 bg-oe-blue/5 p-3" data-testid="cutting-proposal">
          {proposalQuery.isLoading || !proposalQuery.data ? (
            <Loader2 className="animate-spin" size={16} />
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-medium">
                  {t('cutting.proposal_factor', {
                    defaultValue: 'Measured waste factor {{factor}} (waste {{waste}} %)',
                    factor: proposalQuery.data.waste_factor,
                    waste: fmtNumber(proposalQuery.data.waste_pct, 1),
                  })}
                </span>
                <ConfidenceBadge score={proposalQuery.data.confidence} showScore />
              </div>
              <table className="w-full text-xs">
                <thead className="text-left text-content-tertiary">
                  <tr>
                    <th className="py-1">{t('cutting.proposal_line', { defaultValue: 'Line' })}</th>
                    <th className="py-1">{t('cutting.proposal_current', { defaultValue: 'Current' })}</th>
                    <th className="py-1">{t('cutting.proposal_new', { defaultValue: 'Proposed' })}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {proposalQuery.data.lines.map((line) => (
                    <tr key={line.target_id}>
                      <td className="py-1">{line.label || line.target_id}</td>
                      <td className="py-1 tabular-nums">{`${fmtNumber(line.current_quantity, 2)} ${line.unit}`}</td>
                      <td className="py-1 font-medium tabular-nums">
                        {line.appliable ? `${fmtNumber(line.proposed_quantity, 2)} ${line.unit}` : '-'}
                      </td>
                      <td className="py-1 text-content-tertiary">
                        {line.reason ? reasonLabel(line.reason, t) : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="text-2xs text-content-tertiary">
                {t('cutting.proposal_note', {
                  defaultValue: 'Nothing is written until you confirm. The previous quantity is kept in the line history.',
                })}
              </p>
              <Button
                size="sm"
                disabled={!proposalQuery.data.lines.some((l) => l.appliable)}
                loading={applyMut.isPending}
                onClick={() => applyMut.mutate()}
              >
                {t('cutting.confirm_apply', { defaultValue: 'Confirm and update lines' })}
              </Button>
            </>
          )}
        </div>
      )}

      {plan.kind === 'sheet' ? (
        <SheetPlanDiagram sheets={plan.layout.sheets ?? []} />
      ) : (
        <LinearPlanDiagram bars={plan.layout.bars ?? []} trimMm={plan.layout.trim_mm} />
      )}
    </Card>
  );
}

