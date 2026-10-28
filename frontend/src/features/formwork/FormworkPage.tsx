// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * FormworkPage - price the temporary mould concrete is cast into.
 *
 * Formwork is bought or hired once and used many times, so its rate has two
 * parts and only one of them amortises: the panel cost divided by the reuses,
 * plus the erect-and-strike labour paid on every single use. The page keeps
 * that split visible everywhere, because pricing only the first half is the
 * standard way a concrete-heavy job comes in under.
 *
 * Two surfaces:
 *
 *   - Project. Every assignment on the active project, its rate build-up, its
 *     pour cycle, the rollup, and what the reuse assumption is worth against a
 *     no-reuse price. Validation runs over the whole set on demand.
 *   - Catalogue. The formwork systems themselves. Editing a rate here
 *     re-prices every assignment that depends on it, and the page says how
 *     many moved rather than leaving that invisible.
 *
 * Money and quantity values arrive as Decimal-as-string and are parsed to
 * numbers only for display formatting, never for arithmetic.
 */

import { Fragment, useState, useMemo, useCallback, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Boxes,
  Plus,
  Trash2,
  RefreshCw,
  ShieldCheck,
  AlertTriangle,
  ArrowRight,
  Info,
  Layers,
  CalendarClock,
  Wand2,
  PiggyBank,
  Ruler,
  Coins,
  Download,
  Send,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  Input,
  StatCard,
  EmptyState,
  Breadcrumb,
  CollapsibleSection,
  ConfirmDialog,
  SkeletonTable,
  PageHeader,
} from '@/shared/ui';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import {
  listSystems,
  createSystem,
  updateSystem,
  deleteSystem,
  seedDefaultSystems,
  repriceSystem,
  listAssignments,
  createAssignment,
  deleteAssignment,
  getCycle,
  deriveFromSchedule,
  listScheduleLines,
  addScheduleLine,
  deleteScheduleLine,
  getProjectSummary,
  validateProject,
  repriceProject,
  type FormworkSystem,
  type FormworkSystemType,
  type FormworkMaterial,
  type FormworkRateBasis,
  pushAssignmentToBoq,
  type FormworkAssignmentDetail,
  type FormworkFinding,
} from './api';
import { boqApi } from '@/features/boq/api';
import {
  SystemChooser,
  MATERIAL_LABELS,
  RATE_BASIS_LABELS,
  SYSTEM_TYPE_LABELS,
} from './SystemChooser';

/** What the chooser hands back when the estimator presses Add. */
interface AssignmentChoice {
  systemId: string;
  areaM2: string;
  reuseCount: number;
  wastePct: string;
}

/* ── Constants ─────────────────────────────────────────────────────────── */

const SYSTEM_TYPES: FormworkSystemType[] = [
  'wall',
  'slab',
  'column',
  'beam',
  'foundation',
  'climbing',
  'table',
  'tunnel',
  'props',
  'custom',
];

/** Every rate basis the catalogue accepts, in the order they are explained. */
const RATE_BASES: FormworkRateBasis[] = ['purchase', 'hire_per_use', 'subcontract'];

const MATERIALS: FormworkMaterial[] = [
  'plywood',
  'steel',
  'aluminium',
  'composite',
  'timber',
  'other',
];

/* ── Formatting ────────────────────────────────────────────────────────── */

/** Decimal-as-string to a locale-formatted number, for display only. */
function fmtNumber(value: string | number, locale: string, digits = 2): string {
  const n = typeof value === 'number' ? value : Number.parseFloat(value || '0');
  if (!Number.isFinite(n)) return String(value);
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n);
}

/** A money figure with its currency appended, or plain when the mix is unclear. */
function fmtMoney(value: string, locale: string, currency: string): string {
  const formatted = fmtNumber(value, locale);
  return currency ? `${formatted} ${currency}` : formatted;
}

/* ── Explainer ─────────────────────────────────────────────────────────── */

function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/**
 * One-glance map of the formwork workflow: define the system once, assign it
 * to the concrete work, describe the pour cycle, and let the cycle set the
 * reuse count the rate is amortised over. Every connected module is a link.
 */
function HowFormworkWorks() {
  const { t } = useTranslation();

  const steps: { icon: ReactNode; title: string; desc: string }[] = [
    {
      icon: <Boxes size={14} className="text-oe-blue" />,
      title: t('formwork.flow_1_title', { defaultValue: 'Define the system' }),
      desc: t('formwork.flow_1_desc', {
        defaultValue:
          'Panel rate, erect-and-strike rate, reuse limit and striking time - once, in the catalogue.',
      }),
    },
    {
      icon: <Layers size={14} className="text-oe-blue" />,
      title: t('formwork.flow_2_title', { defaultValue: 'Assign it to the work' }),
      desc: t('formwork.flow_2_desc', {
        defaultValue: 'Give it the area to be formed and link it to the concrete BOQ position.',
      }),
    },
    {
      icon: <CalendarClock size={14} className="text-oe-blue" />,
      title: t('formwork.flow_3_title', { defaultValue: 'Describe the pour cycle' }),
      desc: t('formwork.flow_3_desc', {
        defaultValue: 'List the lifts. The largest one sizes the panel set you actually buy.',
      }),
    },
    {
      icon: <PiggyBank size={14} className="text-oe-blue" />,
      title: t('formwork.flow_4_title', { defaultValue: 'Amortise and check' }),
      desc: t('formwork.flow_4_desc', {
        defaultValue:
          'The cycle sets the reuse count, the rate follows, and validation says whether it holds.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="formwork.how"
      icon={<Boxes size={15} className="text-oe-blue" />}
      title={t('formwork.flow_title', { defaultValue: 'How formwork pricing fits together' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('formwork.flow_intro', {
          defaultValue:
            'Formwork is the mould concrete is cast into. The panels are bought or hired once and turned around many times, so their cost is divided by the reuses; the labour to erect and strike them is paid on every use and is not divided at all. Getting that split wrong is the usual reason a concrete-heavy job comes in under.',
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
            {t('formwork.flow_pulls', { defaultValue: 'Pulls from:' })}
          </span>{' '}
          <ModLink to="/boq">{t('formwork.mod_boq', { defaultValue: 'BOQ' })}</ModLink> ·{' '}
          <ModLink to="/takeoff">{t('formwork.mod_takeoff', { defaultValue: 'Takeoff' })}</ModLink>
        </span>
        <span>
          <span className="font-medium text-content-secondary">
            {t('formwork.flow_feeds', { defaultValue: 'Feeds:' })}
          </span>{' '}
          <ModLink to="/costs">{t('formwork.mod_costs', { defaultValue: 'Costs' })}</ModLink> ·{' '}
          <ModLink to="/schedule">
            {t('formwork.mod_schedule', { defaultValue: 'Schedule' })}
          </ModLink>
        </span>
        <span>
          <span className="font-medium text-content-secondary">
            {t('formwork.flow_related', { defaultValue: 'Related:' })}
          </span>{' '}
          <ModLink to="/temporary-works">
            {t('formwork.mod_temporary_works', { defaultValue: 'Temporary Works' })}
          </ModLink>
        </span>
      </div>
    </CollapsibleSection>
  );
}

/* ── Validation findings ───────────────────────────────────────────────── */

function severityVariant(severity: string): 'error' | 'warning' | 'blue' {
  if (severity === 'error') return 'error';
  if (severity === 'warning') return 'warning';
  return 'blue';
}

interface FindingListProps {
  findings: FormworkFinding[];
  emptyLabel: string;
}

function FindingList({ findings, emptyLabel }: FindingListProps) {
  const { t } = useTranslation();
  if (findings.length === 0) {
    return (
      <p className="text-sm text-content-secondary flex items-center gap-2">
        <ShieldCheck size={15} className="text-semantic-success" />
        {emptyLabel}
      </p>
    );
  }
  return (
    <ul className="space-y-2.5">
      {findings.map((finding) => (
        <li
          key={`${finding.rule_id}-${finding.element_ref ?? ''}`}
          className="rounded-lg border border-border bg-surface-secondary px-3 py-2.5"
        >
          <div className="flex items-start gap-2">
            <Badge variant={severityVariant(finding.severity)} size="sm">
              {finding.severity}
            </Badge>
            <div className="min-w-0 flex-1">
              <p className="text-sm text-content-primary">{finding.message}</p>
              {finding.suggestion && (
                <p className="mt-1 text-xs text-content-secondary">
                  {t('formwork.validation.suggestionPrefix', { defaultValue: 'Fix:' })}{' '}
                  {finding.suggestion}
                </p>
              )}
              <p className="mt-1 text-[11px] font-mono text-content-tertiary">{finding.rule_id}</p>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

/* ── Pour cycle panel ──────────────────────────────────────────────────── */

interface CyclePanelProps {
  assignment: FormworkAssignmentDetail;
  projectId: string;
  onClose: () => void;
}

function CyclePanel({ assignment, projectId, onClose }: CyclePanelProps) {
  const { t } = useTranslation();
  const locale = getNumberLocale();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [pourNo, setPourNo] = useState('1');
  const [levelLabel, setLevelLabel] = useState('');
  const [pourArea, setPourArea] = useState('');
  const [pourDate, setPourDate] = useState('');

  const linesQuery = useQuery({
    queryKey: ['formwork', 'lines', assignment.id],
    queryFn: () => listScheduleLines(assignment.id),
  });
  const cycleQuery = useQuery({
    queryKey: ['formwork', 'cycle', assignment.id],
    queryFn: () => getCycle(assignment.id),
  });

  const lines = linesQuery.data ?? [];
  const cycle = cycleQuery.data;

  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['formwork', 'lines', assignment.id] });
    queryClient.invalidateQueries({ queryKey: ['formwork', 'cycle', assignment.id] });
    queryClient.invalidateQueries({ queryKey: ['formwork', 'assignments', projectId] });
    queryClient.invalidateQueries({ queryKey: ['formwork', 'summary', projectId] });
  }, [queryClient, assignment.id, projectId]);

  const reportError = useCallback(
    (error: Error) => {
      addToast({
        type: 'error',
        title: t('toasts.error', { defaultValue: 'Error' }),
        message: error.message,
      });
    },
    [addToast, t],
  );

  const addMutation = useMutation({
    mutationFn: () =>
      addScheduleLine(assignment.id, {
        pour_no: Number.parseInt(pourNo, 10) || 1,
        level_label: levelLabel,
        area_m2: pourArea || '0',
        pour_date: pourDate || null,
      }),
    onSuccess: () => {
      setLevelLabel('');
      setPourArea('');
      setPourDate('');
      setPourNo(String((Number.parseInt(pourNo, 10) || 1) + 1));
      invalidate();
    },
    onError: reportError,
  });

  const removeMutation = useMutation({
    mutationFn: (lineId: string) => deleteScheduleLine(lineId),
    onSuccess: invalidate,
    onError: reportError,
  });

  const deriveMutation = useMutation({
    mutationFn: () => deriveFromSchedule(assignment.id),
    onSuccess: (result) => {
      invalidate();
      addToast({
        type: result.changed ? 'success' : 'info',
        title: result.changed
          ? t('formwork.toast.derived', { defaultValue: 'Assignment derived from the pour cycle' })
          : t('formwork.toast.alreadyInSync', {
              defaultValue: 'The assignment already matches its pour cycle',
            }),
      });
    },
    onError: reportError,
  });

  return (
    <Card className="p-4 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-content-primary flex items-center gap-2">
            <CalendarClock size={15} />
            {t('formwork.cycle.title', { defaultValue: 'Pour cycle' })}
          </h3>
          <p className="mt-1 text-xs text-content-secondary max-w-2xl">
            {t('formwork.cycle.help', {
              defaultValue:
                'The panel set you have to buy or hire is the largest single pour, not the total. The total divided by that set is how many times the set turns around, and that is the reuse count the panel rate may honestly be amortised over.',
            })}
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose}>
          {t('common.close', { defaultValue: 'Close' })}
        </Button>
      </div>

      {cycle && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            size="sm"
            icon={Ruler}
            label={t('formwork.cycle.panelSet', { defaultValue: 'Panel set needed' })}
            value={`${fmtNumber(cycle.peak_pour_area_m2, locale)} m2`}
            sub={t('formwork.cycle.panelSetSub', { defaultValue: 'Largest single pour' })}
          />
          <StatCard
            size="sm"
            icon={RefreshCw}
            label={t('formwork.cycle.turnarounds', { defaultValue: 'Turnarounds delivered' })}
            value={String(cycle.derived_reuse_count)}
            sub={t('formwork.cycle.turnaroundsSub', {
              defaultValue: 'Priced at {{count}}',
              count: cycle.current_reuse_count,
            })}
            tone={cycle.current_reuse_count > cycle.derived_reuse_count ? 'warning' : 'success'}
            tintValue
          />
          <StatCard
            size="sm"
            icon={Layers}
            label={t('formwork.cycle.totalArea', { defaultValue: 'Total pour area' })}
            value={`${fmtNumber(cycle.total_pour_area_m2, locale)} m2`}
            sub={t('formwork.cycle.pourCount', {
              defaultValue: '{{count}} pours',
              count: cycle.pour_count,
            })}
          />
          <StatCard
            size="sm"
            icon={CalendarClock}
            label={t('formwork.cycle.stripTime', { defaultValue: 'Striking time' })}
            value={t('formwork.cycle.days', {
              defaultValue: '{{count}} d',
              count: cycle.strip_time_days,
            })}
            sub={
              cycle.min_gap_days == null
                ? t('formwork.cycle.noDates', { defaultValue: 'No pour dates set' })
                : t('formwork.cycle.shortestGap', {
                    defaultValue: 'Shortest gap {{count}} d',
                    count: cycle.min_gap_days,
                  })
            }
            tone={cycle.conflicts.length > 0 ? 'danger' : 'default'}
          />
        </div>
      )}

      {cycle && cycle.conflicts.length > 0 && (
        <div className="rounded-lg border border-semantic-error/40 bg-semantic-error-bg px-3 py-2.5">
          <p className="text-sm text-semantic-error flex items-center gap-2">
            <AlertTriangle size={15} />
            {t('formwork.cycle.conflictTitle', {
              defaultValue:
                'One panel set cannot serve these pours - they are closer together than the striking time',
            })}
          </p>
          <ul className="mt-1.5 space-y-0.5 text-xs text-content-secondary">
            {cycle.conflicts.map((conflict) => (
              <li key={`${conflict.from_pour_no}-${conflict.to_pour_no}`}>
                {t('formwork.cycle.conflictRow', {
                  defaultValue:
                    'Pour {{from}} to pour {{to}}: {{gap}} d apart, {{required}} d needed',
                  from: conflict.from_pour_no,
                  to: conflict.to_pour_no,
                  gap: conflict.gap_days,
                  required: conflict.required_days,
                })}
              </li>
            ))}
          </ul>
        </div>
      )}

      {linesQuery.isLoading ? (
        <SkeletonTable rows={3} columns={4} />
      ) : lines.length === 0 ? (
        <p className="text-sm text-content-secondary">
          {t('formwork.cycle.empty', {
            defaultValue: 'No pours yet. Add the lifts this formwork set will be used for.',
          })}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-content-secondary border-b border-border">
                <th className="py-1.5 pr-3 font-medium">
                  {t('formwork.cycle.colPour', { defaultValue: 'Pour' })}
                </th>
                <th className="py-1.5 pr-3 font-medium">
                  {t('formwork.cycle.colLevel', { defaultValue: 'Level' })}
                </th>
                <th className="py-1.5 pr-3 font-medium text-right">
                  {t('formwork.cycle.colArea', { defaultValue: 'Area m2' })}
                </th>
                <th className="py-1.5 pr-3 font-medium">
                  {t('formwork.cycle.colDate', { defaultValue: 'Pour date' })}
                </th>
                <th className="py-1.5" />
              </tr>
            </thead>
            <tbody>
              {lines.map((line) => (
                <tr key={line.id} className="border-b border-border-light last:border-0">
                  <td className="py-1.5 pr-3 tabular-nums">{line.pour_no}</td>
                  <td className="py-1.5 pr-3">{line.level_label}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">
                    {fmtNumber(line.area_m2, locale)}
                  </td>
                  <td className="py-1.5 pr-3 text-content-secondary">{line.pour_date ?? '-'}</td>
                  <td className="py-1.5 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<Trash2 size={14} />}
                      aria-label={t('common.delete', { defaultValue: 'Delete' })}
                      onClick={() => removeMutation.mutate(line.id)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid gap-2 sm:grid-cols-5 items-end">
        <Input
          label={t('formwork.cycle.colPour', { defaultValue: 'Pour' })}
          type="number"
          min={1}
          value={pourNo}
          onChange={(e) => setPourNo(e.target.value)}
        />
        <Input
          label={t('formwork.cycle.colLevel', { defaultValue: 'Level' })}
          value={levelLabel}
          placeholder={t('formwork.cycle.levelPlaceholder', { defaultValue: 'L02 core walls' })}
          onChange={(e) => setLevelLabel(e.target.value)}
        />
        <Input
          label={t('formwork.cycle.colArea', { defaultValue: 'Area m2' })}
          type="number"
          min={0}
          step="0.01"
          value={pourArea}
          onChange={(e) => setPourArea(e.target.value)}
        />
        <Input
          label={t('formwork.cycle.colDate', { defaultValue: 'Pour date' })}
          type="date"
          value={pourDate}
          onChange={(e) => setPourDate(e.target.value)}
        />
        <Button
          variant="secondary"
          icon={<Plus size={15} />}
          loading={addMutation.isPending}
          disabled={!pourArea}
          onClick={() => addMutation.mutate()}
        >
          {t('formwork.cycle.addPour', { defaultValue: 'Add pour' })}
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-border-light">
        <Button
          variant="primary"
          icon={<Wand2 size={15} />}
          loading={deriveMutation.isPending}
          disabled={lines.length === 0}
          onClick={() => deriveMutation.mutate()}
        >
          {t('formwork.cycle.derive', { defaultValue: 'Take area and reuse from the cycle' })}
        </Button>
        <span className="text-xs text-content-secondary">
          {t('formwork.cycle.deriveHelp', {
            defaultValue:
              'Replaces the typed area and reuse count with what the pours actually deliver, and re-prices the assignment.',
          })}
        </span>
      </div>
    </Card>
  );
}

/* ── Catalogue form ────────────────────────────────────────────────────── */

interface SystemFormState {
  name: string;
  system_type: FormworkSystemType;
  material: FormworkMaterial;
  supplier: string;
  reuses_max: string;
  unit_rate: string;
  erect_strike_rate: string;
  strip_time_days: string;
  rate_basis: FormworkRateBasis;
  typical_reuses: string;
  cycle_days: string;
  currency: string;
}

const EMPTY_SYSTEM_FORM: SystemFormState = {
  name: '',
  system_type: 'wall',
  material: 'steel',
  supplier: '',
  reuses_max: '50',
  unit_rate: '0.00',
  erect_strike_rate: '0.00',
  strip_time_days: '1',
  rate_basis: 'purchase',
  // Blank rather than zero: the column is nullable and NULL means "no
  // published figure", which is not the same claim as "reused zero times".
  typical_reuses: '',
  cycle_days: '0',
  currency: 'EUR',
};

/* ── Main page ─────────────────────────────────────────────────────────── */

export function FormworkPage() {
  const { t, i18n } = useTranslation();
  const locale = getNumberLocale();
  const queryClient = useQueryClient();
  const { confirm, ...confirmProps } = useConfirm();
  const addToast = useToastStore((s) => s.addToast);
  const { activeProjectId } = useProjectContextStore();
  const projectId = activeProjectId ?? '';

  const [tab, setTab] = useState<'project' | 'catalogue'>('project');
  const [openCycleId, setOpenCycleId] = useState('');
  const [systemForm, setSystemForm] = useState<SystemFormState>(EMPTY_SYSTEM_FORM);
  const [showSystemForm, setShowSystemForm] = useState(false);

  // The chooser owns the new-assignment inputs now and hands back one object
  // on Add, so the page holds no loose strings that could disagree with what
  // was on screen when Add was pressed.
  // Which assignment is being sent to a bill, and to which bill.
  const [pushingAssignmentId, setPushingAssignmentId] = useState('');
  const [pushBoqId, setPushBoqId] = useState('');

  const reportError = useCallback(
    (error: Error) => {
      addToast({
        type: 'error',
        title: t('toasts.error', { defaultValue: 'Error' }),
        message: error.message,
      });
    },
    [addToast, t],
  );

  const systemsQuery = useQuery({
    queryKey: ['formwork', 'systems'],
    queryFn: () => listSystems({ limit: 500 }),
  });
  const systems = useMemo(() => systemsQuery.data ?? [], [systemsQuery.data]);

  const assignmentsQuery = useQuery({
    queryKey: ['formwork', 'assignments', projectId],
    queryFn: () => listAssignments(projectId),
    enabled: !!projectId,
  });
  const assignments = assignmentsQuery.data ?? [];

  const summaryQuery = useQuery({
    queryKey: ['formwork', 'summary', projectId],
    queryFn: () => getProjectSummary(projectId),
    enabled: !!projectId,
  });
  const summary = summaryQuery.data;

  const validationQuery = useQuery({
    queryKey: ['formwork', 'validation', projectId],
    queryFn: () => validateProject(projectId, i18n.language),
    enabled: !!projectId,
  });
  const validation = validationQuery.data;

  const invalidateProject = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['formwork', 'assignments', projectId] });
    queryClient.invalidateQueries({ queryKey: ['formwork', 'summary', projectId] });
    queryClient.invalidateQueries({ queryKey: ['formwork', 'validation', projectId] });
  }, [queryClient, projectId]);

  /* ── Mutations ──────────────────────────────────────────────────────── */

  const createAssignmentMutation = useMutation({
    mutationFn: (choice: AssignmentChoice) =>
      createAssignment({
        project_id: projectId,
        formwork_system_id: choice.systemId,
        area_m2: choice.areaM2 || '0',
        reuse_count: choice.reuseCount,
        waste_pct: choice.wastePct || '0',
        notes: null,
      }),
    onSuccess: () => {
      invalidateProject();
      addToast({
        type: 'success',
        title: t('formwork.toast.assignmentAdded', { defaultValue: 'Formwork assignment added' }),
      });
    },
    onError: reportError,
  });

  // Bills of the active project, so "send to bill" can name a target rather
  // than guess one: a project can carry several, and the backend refuses a
  // push whose bill belongs elsewhere.
  const boqsQuery = useQuery({
    queryKey: ['formwork', 'boqs', projectId],
    queryFn: () => boqApi.list(projectId),
    enabled: !!projectId,
  });
  const boqs = useMemo(() => boqsQuery.data ?? [], [boqsQuery.data]);

  const pushToBoqMutation = useMutation({
    mutationFn: ({ assignmentId, boqId }: { assignmentId: string; boqId: string }) =>
      pushAssignmentToBoq(assignmentId, { boq_id: boqId }),
    onSuccess: (result) => {
      setPushingAssignmentId('');
      invalidateProject();
      addToast({
        type: 'success',
        // Pushing twice re-prices one position rather than adding a second, so
        // the message has to distinguish the two or it would imply a new line
        // every time and quietly teach the estimator to expect double-billing.
        // `ordinal` is a reserved i18next option, not a free interpolation name:
        // it selects ordinal plural forms and is typed boolean. Passing the
        // position through `replace` keeps the placeholder spelled {{ordinal}}
        // in every locale string while leaving the reserved option untouched.
        title: result.created
          ? t('formwork.toast.pushedToBoq', {
              defaultValue: 'Added to the bill as {{ordinal}}',
              replace: { ordinal: result.ordinal },
            })
          : t('formwork.toast.repricedInBoq', {
              defaultValue: 'Re-priced {{ordinal}} in the bill',
              replace: { ordinal: result.ordinal },
            }),
      });
    },
    onError: reportError,
  });

  const deleteAssignmentMutation = useMutation({
    mutationFn: (assignmentId: string) => deleteAssignment(assignmentId),
    onSuccess: () => {
      setOpenCycleId('');
      invalidateProject();
    },
    onError: reportError,
  });

  const repriceProjectMutation = useMutation({
    mutationFn: () => repriceProject(projectId),
    onSuccess: (result) => {
      invalidateProject();
      addToast({
        type: 'success',
        title: t('formwork.toast.repriced', {
          defaultValue: '{{repriced}} of {{examined}} assignments re-priced',
          repriced: result.repriced,
          examined: result.examined,
        }),
      });
    },
    onError: reportError,
  });

  const createSystemMutation = useMutation({
    mutationFn: () =>
      createSystem({
        name: systemForm.name,
        system_type: systemForm.system_type,
        material: systemForm.material,
        supplier: systemForm.supplier || null,
        reuses_max: Number.parseInt(systemForm.reuses_max, 10) || 1,
        unit_rate: systemForm.unit_rate || '0',
        erect_strike_rate: systemForm.erect_strike_rate || '0',
        strip_time_days: Number.parseInt(systemForm.strip_time_days, 10) || 0,
        rate_basis: systemForm.rate_basis,
        // Blank stays null, not zero: the column is nullable and NULL means
        // "no published figure", which is a different claim from "never
        // reused". Coercing the blank to 0 would also fail the >= 1 bound.
        typical_reuses: systemForm.typical_reuses
          ? Number.parseInt(systemForm.typical_reuses, 10) || null
          : null,
        cycle_days: systemForm.cycle_days || '0',
        currency: systemForm.currency,
      }),
    onSuccess: () => {
      setSystemForm(EMPTY_SYSTEM_FORM);
      setShowSystemForm(false);
      queryClient.invalidateQueries({ queryKey: ['formwork', 'systems'] });
      addToast({
        type: 'success',
        title: t('formwork.toast.systemAdded', { defaultValue: 'Formwork system added' }),
      });
    },
    onError: reportError,
  });

  const rateMutation = useMutation({
    // The field is named explicitly rather than spread from a computed key: a
    // computed key widens the payload to a string index signature, which no
    // longer matches the typed update shape.
    mutationFn: (args: {
      systemId: string;
      field: 'unit_rate' | 'erect_strike_rate';
      value: string;
    }) =>
      updateSystem(
        args.systemId,
        args.field === 'unit_rate'
          ? { unit_rate: args.value }
          : { erect_strike_rate: args.value },
      ),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['formwork', 'systems'] });
      invalidateProject();
      addToast({
        type: 'success',
        title: t('formwork.toast.catalogueRepriced', {
          defaultValue: 'Rate saved, {{repriced}} assignment(s) re-priced',
          repriced: result.reprice.repriced,
        }),
        message:
          result.reprice.examined > 0
            ? t('formwork.toast.catalogueRepricedDetail', {
                defaultValue: 'Across {{examined}} assignment(s) using this system.',
                examined: result.reprice.examined,
              })
            : undefined,
      });
    },
    onError: reportError,
  });

  const deleteSystemMutation = useMutation({
    mutationFn: (systemId: string) => deleteSystem(systemId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['formwork', 'systems'] });
    },
    onError: reportError,
  });

  const repriceSystemMutation = useMutation({
    mutationFn: (systemId: string) => repriceSystem(systemId),
    onSuccess: (result) => {
      invalidateProject();
      addToast({
        type: 'success',
        title: t('formwork.toast.repriced', {
          defaultValue: '{{repriced}} of {{examined}} assignments re-priced',
          repriced: result.repriced,
          examined: result.examined,
        }),
      });
    },
    onError: reportError,
  });

  const seedMutation = useMutation({
    mutationFn: () => seedDefaultSystems(),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['formwork', 'systems'] });
      addToast({
        type: 'success',
        title: t('formwork.toast.seeded', {
          defaultValue: '{{inserted}} starter systems added, {{skipped}} already present',
          inserted: result.inserted,
          skipped: result.skipped,
        }),
      });
    },
    onError: reportError,
  });

  const handleDeleteSystem = useCallback(
    async (system: FormworkSystem) => {
      const ok = await confirm({
        title: t('formwork.confirmDeleteSystem', { defaultValue: 'Delete this formwork system?' }),
        message: t('formwork.confirmDeleteSystemBody', {
          defaultValue:
            'The system is removed from the catalogue. Assignments already priced off it keep their totals, but the system cannot be deleted while any of them exist.',
        }),
        confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
        variant: 'danger',
      });
      if (ok) deleteSystemMutation.mutate(system.id);
    },
    [confirm, t, deleteSystemMutation],
  );

  const handleDeleteAssignment = useCallback(
    async (assignmentId: string) => {
      const ok = await confirm({
        title: t('formwork.confirmDeleteAssignment', {
          defaultValue: 'Delete this formwork assignment?',
        }),
        message: t('formwork.confirmDeleteAssignmentBody', {
          defaultValue: 'Its pour cycle is deleted with it.',
        }),
        confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
        variant: 'danger',
      });
      if (ok) deleteAssignmentMutation.mutate(assignmentId);
    },
    [confirm, t, deleteAssignmentMutation],
  );

  const openAssignment = assignments.find((a) => a.id === openCycleId);
  const currency = summary?.currency ?? '';

  /* ── Render ─────────────────────────────────────────────────────────── */

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb items={[{ label: t('formwork.title', { defaultValue: 'Formwork' }) }]} />

      <PageHeader
        srTitle={t('formwork.title', { defaultValue: 'Formwork' })}
        subtitle={t('formwork.subtitle', {
          defaultValue:
            'Price the moulds concrete is cast into, amortised over the reuses the programme actually delivers',
        })}
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant={tab === 'project' ? 'primary' : 'secondary'}
              onClick={() => setTab('project')}
            >
              {t('formwork.tab.project', { defaultValue: 'Project' })}
            </Button>
            <Button
              variant={tab === 'catalogue' ? 'primary' : 'secondary'}
              onClick={() => setTab('catalogue')}
            >
              {t('formwork.tab.catalogue', { defaultValue: 'Catalogue' })}
            </Button>
          </div>
        }
      />

      {/* Page-level explainer, ABOVE the surface switch: an explainer wired
          into one tab disappears when the other is selected and the reader
          stops believing an explanation exists at all. */}
      <HowFormworkWorks />

      {tab === 'project' && !projectId && (
        <RequiresProject
          emptyHint={t('formwork.selectProjectDesc', {
            defaultValue: 'Select a project to price its formwork.',
          })}
        >
          {null}
        </RequiresProject>
      )}

      {/* ── Project surface ──────────────────────────────────────────── */}

      {tab === 'project' && projectId && (
        <>
          {/* First on the page, always open. Choosing the system is the whole
              point of the module, so it is not something to go looking for. */}
          <SystemChooser
            catalogueEmpty={!systemsQuery.isLoading && systems.length === 0}
            onSeedCatalogue={() => seedMutation.mutate()}
            seeding={seedMutation.isPending}
            adding={createAssignmentMutation.isPending}
            onAdd={(choice) => createAssignmentMutation.mutate(choice)}
          />

          {summaryQuery.isLoading ? (
            <SkeletonTable rows={2} columns={4} />
          ) : summary ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard
                icon={Ruler}
                label={t('formwork.summary.area', { defaultValue: 'Formed area' })}
                value={`${fmtNumber(summary.total_area_m2, locale)} m2`}
                sub={t('formwork.summary.assignments', {
                  defaultValue: '{{count}} assignments',
                  count: summary.assignment_count,
                })}
              />
              <StatCard
                icon={Coins}
                label={t('formwork.summary.total', { defaultValue: 'Formwork cost' })}
                value={fmtMoney(summary.total_cost, locale, currency)}
                sub={t('formwork.summary.split', {
                  defaultValue: 'Panels {{material}}, labour {{labour}}',
                  material: fmtNumber(summary.material_cost, locale, 0),
                  labour: fmtNumber(summary.labour_cost, locale, 0),
                })}
              />
              <StatCard
                icon={PiggyBank}
                tone="success"
                tintValue
                label={t('formwork.summary.saving', { defaultValue: 'Worth of the reuse claim' })}
                value={fmtMoney(summary.amortisation_saving, locale, currency)}
                sub={t('formwork.summary.savingSub', {
                  defaultValue: '{{pct}}% under a no-reuse price',
                  pct: fmtNumber(summary.amortisation_saving_pct, locale, 1),
                })}
              />
              <StatCard
                icon={Boxes}
                tone={summary.unlinked_to_boq > 0 ? 'warning' : 'default'}
                label={t('formwork.summary.unlinked', { defaultValue: 'Not on the bill' })}
                value={String(summary.unlinked_to_boq)}
                sub={t('formwork.summary.unlinkedSub', {
                  defaultValue: 'Assignments with no BOQ position',
                })}
              />
            </div>
          ) : null}

          {summary?.currency_mixed && (
            <div className="rounded-lg border border-semantic-error/40 bg-semantic-error-bg px-3 py-2.5 text-sm text-semantic-error flex items-center gap-2">
              <AlertTriangle size={15} />
              {t('formwork.mixedCurrency', {
                defaultValue:
                  'This project prices formwork in more than one currency, so the totals above are a sum of unlike units.',
              })}
            </div>
          )}

          <Card className="p-4 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-content-primary flex items-center gap-2">
                <Layers size={15} />
                {t('formwork.assignments.title', { defaultValue: 'Formwork on this project' })}
              </h2>
              <Button
                variant="secondary"
                size="sm"
                icon={<RefreshCw size={14} />}
                loading={repriceProjectMutation.isPending}
                onClick={() => repriceProjectMutation.mutate()}
              >
                {t('formwork.reprice', { defaultValue: 'Re-price from the catalogue' })}
              </Button>
            </div>

            {assignmentsQuery.isLoading ? (
              <SkeletonTable rows={3} columns={6} />
            ) : assignments.length === 0 ? (
              <EmptyState
                icon={<Boxes size={26} strokeWidth={1.5} />}
                title={t('formwork.assignments.emptyTitle', {
                  defaultValue: 'No formwork priced yet',
                })}
                description={t('formwork.assignments.emptyBody', {
                  defaultValue:
                    'Pick a system from the catalogue and give it the area to be formed. The rate is built from the panel cost divided by the reuses plus the erect-and-strike labour.',
                })}
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-content-secondary border-b border-border">
                      <th className="py-1.5 pr-3 font-medium">
                        {t('formwork.col.system', { defaultValue: 'System' })}
                      </th>
                      <th className="py-1.5 pr-3 font-medium text-right">
                        {t('formwork.col.area', { defaultValue: 'Area m2' })}
                      </th>
                      <th className="py-1.5 pr-3 font-medium text-right">
                        {t('formwork.col.reuses', { defaultValue: 'Reuses' })}
                      </th>
                      <th className="py-1.5 pr-3 font-medium text-right">
                        {t('formwork.col.panelRate', { defaultValue: 'Panels /m2' })}
                      </th>
                      <th className="py-1.5 pr-3 font-medium text-right">
                        {t('formwork.col.labourRate', { defaultValue: 'Erect+strike /m2' })}
                      </th>
                      <th className="py-1.5 pr-3 font-medium text-right">
                        {t('formwork.col.unitCost', { defaultValue: 'Rate /m2' })}
                      </th>
                      <th className="py-1.5 pr-3 font-medium text-right">
                        {t('formwork.col.total', { defaultValue: 'Total' })}
                      </th>
                      <th className="py-1.5" />
                    </tr>
                  </thead>
                  <tbody>
                    {assignments.map((assignment) => (
                      <tr
                        key={assignment.id}
                        className="border-b border-border-light last:border-0"
                      >
                        <td className="py-2 pr-3">
                          <div className="font-medium text-content-primary">
                            {assignment.system_name}
                          </div>
                          <div className="mt-0.5 flex items-center gap-1.5">
                            {assignment.system_type && (
                              <Badge variant="neutral" size="sm">
                                {assignment.system_type}
                              </Badge>
                            )}
                            {assignment.boq_position_id ? null : (
                              <Badge variant="warning" size="sm">
                                {t('formwork.badge.notOnBill', { defaultValue: 'Not on the bill' })}
                              </Badge>
                            )}
                          </div>
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums">
                          {fmtNumber(assignment.area_m2, locale)}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums">
                          {assignment.reuse_count} / {assignment.reuses_max}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums text-content-secondary">
                          {fmtNumber(assignment.material_unit_cost, locale)}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums text-content-secondary">
                          {fmtNumber(assignment.labour_unit_cost, locale)}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums font-medium">
                          {fmtNumber(assignment.computed_unit_cost, locale)}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums font-medium">
                          {fmtMoney(assignment.computed_total, locale, assignment.currency)}
                        </td>
                        <td className="py-2 text-right whitespace-nowrap">
                          <Button
                            variant="ghost"
                            size="sm"
                            icon={<CalendarClock size={14} />}
                            onClick={() =>
                              setOpenCycleId(openCycleId === assignment.id ? '' : assignment.id)
                            }
                          >
                            {assignment.schedule_line_count > 0
                              ? String(assignment.schedule_line_count)
                              : t('formwork.cycle.open', { defaultValue: 'Cycle' })}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            icon={<Send size={14} />}
                            aria-label={t('formwork.push.action', {
                              defaultValue: 'Send to bill',
                            })}
                            // A rate that never reaches the bill is a
                            // calculator. The link is shown when it exists so
                            // the row says whether it has been sent already.
                            title={
                              assignment.boq_position_id
                                ? t('formwork.push.alreadyLinked', {
                                    defaultValue: 'Already in a bill - sending again re-prices it',
                                  })
                                : t('formwork.push.action', { defaultValue: 'Send to bill' })
                            }
                            onClick={() => {
                              setPushingAssignmentId(assignment.id);
                              setPushBoqId(boqs[0]?.id ?? '');
                            }}
                          />
                          <Button
                            variant="ghost"
                            size="sm"
                            icon={<Trash2 size={14} />}
                            aria-label={t('common.delete', { defaultValue: 'Delete' })}
                            onClick={() => handleDeleteAssignment(assignment.id)}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* The chooser above this card is where a system is picked now.
                This used to be a bare <select> plus four inputs wedged under
                the table: on an empty project it sat below an empty state,
                offering options nobody had loaded. */}
          </Card>

          {openAssignment && (
            <CyclePanel
              assignment={openAssignment}
              projectId={projectId}
              onClose={() => setOpenCycleId('')}
            />
          )}

          {/* Naming the bill is not optional: a project can carry several and
              the backend refuses a push aimed at another project's bill. */}
          {pushingAssignmentId && (
            <Card className="p-4 space-y-3">
              <h3 className="text-sm font-semibold text-content-primary flex items-center gap-2">
                <Send size={14} />
                {t('formwork.push.title', { defaultValue: 'Send this formwork to a bill' })}
              </h3>
              {boqs.length === 0 ? (
                <p className="text-xs text-content-secondary">
                  {t('formwork.push.noBoq', {
                    defaultValue:
                      'This project has no bill of quantities yet. Create one in the BOQ module first.',
                  })}
                </p>
              ) : (
                <>
                  <p className="text-xs text-content-secondary">
                    {t('formwork.push.explain', {
                      defaultValue:
                        'The contact area becomes the quantity and the reuse-aware rate becomes the unit rate. Sending the same assignment again re-prices that position instead of adding a second one.',
                    })}
                  </p>
                  <div className="flex flex-wrap items-end gap-2">
                    <div className="min-w-56">
                      <label
                        className="block text-xs font-medium text-content-secondary mb-1"
                        htmlFor="formwork-push-boq"
                      >
                        {t('formwork.push.targetBoq', { defaultValue: 'Bill of quantities' })}
                      </label>
                      <select
                        id="formwork-push-boq"
                        className="w-full h-9 rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary"
                        value={pushBoqId}
                        onChange={(e) => setPushBoqId(e.target.value)}
                      >
                        {boqs.map((boq) => (
                          <option key={boq.id} value={boq.id}>
                            {boq.name}
                          </option>
                        ))}
                      </select>
                    </div>
                    <Button
                      variant="primary"
                      loading={pushToBoqMutation.isPending}
                      disabled={!pushBoqId}
                      onClick={() =>
                        pushToBoqMutation.mutate({
                          assignmentId: pushingAssignmentId,
                          boqId: pushBoqId,
                        })
                      }
                    >
                      {t('formwork.push.confirm', { defaultValue: 'Send to bill' })}
                    </Button>
                    <Button variant="secondary" onClick={() => setPushingAssignmentId('')}>
                      {t('common.cancel', { defaultValue: 'Cancel' })}
                    </Button>
                  </div>
                </>
              )}
            </Card>
          )}

          <Card className="p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-content-primary flex items-center gap-2">
                <ShieldCheck size={15} />
                {t('formwork.validation.title', { defaultValue: 'Formwork validation' })}
              </h2>
              <div className="flex items-center gap-2">
                {validation && (
                  <>
                    <Badge variant={validation.error_count > 0 ? 'error' : 'neutral'} size="sm">
                      {t('formwork.validation.errors', {
                        defaultValue: '{{count}} errors',
                        count: validation.error_count,
                      })}
                    </Badge>
                    <Badge variant={validation.warning_count > 0 ? 'warning' : 'neutral'} size="sm">
                      {t('formwork.validation.warnings', {
                        defaultValue: '{{count}} warnings',
                        count: validation.warning_count,
                      })}
                    </Badge>
                  </>
                )}
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<RefreshCw size={14} />}
                  loading={validationQuery.isFetching}
                  onClick={() => validationQuery.refetch()}
                >
                  {t('formwork.validation.run', { defaultValue: 'Re-run' })}
                </Button>
              </div>
            </div>
            <p className="text-xs text-content-secondary">
              {t('formwork.validation.help', {
                defaultValue:
                  'Checks the reuse count against the manufacturer limit and against the pour cycle, the waste allowance, the striking time, and across the project: one currency, one formwork assignment per bill position.',
              })}
            </p>
            {validation && validation.unsupported_rule_sets.length > 0 && (
              <p className="text-sm text-semantic-warning flex items-center gap-2">
                <Info size={15} />
                {t('formwork.validation.notRun', {
                  defaultValue: 'The formwork rules did not run, so this is not a clean result.',
                })}
              </p>
            )}
            {validationQuery.isLoading ? (
              <SkeletonTable rows={2} columns={2} />
            ) : (
              <FindingList
                findings={validation?.findings ?? []}
                emptyLabel={t('formwork.validation.clean', {
                  defaultValue: 'Every formwork check passed.',
                })}
              />
            )}
          </Card>

          {summary && summary.by_system_type.length > 0 && (
            <Card className="p-4 space-y-3">
              <h2 className="text-sm font-semibold text-content-primary">
                {t('formwork.breakdown.title', { defaultValue: 'Formwork cost by system type' })}
              </h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-content-secondary border-b border-border">
                      <th className="py-1.5 pr-3 font-medium">
                        {t('formwork.col.type', { defaultValue: 'Type' })}
                      </th>
                      <th className="py-1.5 pr-3 font-medium text-right">
                        {t('formwork.col.area', { defaultValue: 'Area m2' })}
                      </th>
                      <th className="py-1.5 pr-3 font-medium text-right">
                        {t('formwork.col.total', { defaultValue: 'Total' })}
                      </th>
                      <th className="py-1.5 font-medium text-right">
                        {t('formwork.col.share', { defaultValue: 'Share' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.by_system_type.map((row) => (
                      <tr key={row.system_type} className="border-b border-border-light last:border-0">
                        <td className="py-1.5 pr-3">{row.system_type}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">
                          {fmtNumber(row.area_m2, locale)}
                        </td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">
                          {fmtMoney(row.total, locale, currency)}
                        </td>
                        <td className="py-1.5 text-right tabular-nums">
                          {fmtNumber(row.share_pct, locale, 1)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}

      {/* ── Catalogue surface ────────────────────────────────────────── */}

      {tab === 'catalogue' && (
        <Card className="p-4 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold text-content-primary flex items-center gap-2">
                <Boxes size={15} />
                {t('formwork.catalogue.title', { defaultValue: 'Formwork systems' })}
              </h2>
              <p className="mt-1 text-xs text-content-secondary max-w-3xl">
                {t('formwork.catalogue.help', {
                  defaultValue:
                    'Changing a rate here re-prices every assignment on every project that uses this system, and the toast says how many moved.',
                })}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                icon={<Download size={14} />}
                loading={seedMutation.isPending}
                onClick={() => seedMutation.mutate()}
              >
                {t('formwork.catalogue.seed', { defaultValue: 'Add starter systems' })}
              </Button>
              <Button
                variant="primary"
                size="sm"
                icon={<Plus size={14} />}
                onClick={() => setShowSystemForm((open) => !open)}
              >
                {t('formwork.catalogue.new', { defaultValue: 'New system' })}
              </Button>
            </div>
          </div>

          {showSystemForm && (
            <div className="grid gap-2 sm:grid-cols-4 items-end rounded-lg border border-border bg-surface-secondary p-3">
              <Input
                label={t('formwork.col.name', { defaultValue: 'Name' })}
                value={systemForm.name}
                onChange={(e) => setSystemForm({ ...systemForm, name: e.target.value })}
              />
              <div>
                <label
                  className="block text-xs font-medium text-content-secondary mb-1"
                  htmlFor="formwork-new-type"
                >
                  {t('formwork.col.type', { defaultValue: 'Type' })}
                </label>
                <select
                  id="formwork-new-type"
                  className="w-full h-9 rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary"
                  value={systemForm.system_type}
                  onChange={(e) =>
                    setSystemForm({
                      ...systemForm,
                      system_type: e.target.value as FormworkSystemType,
                    })
                  }
                >
                  {SYSTEM_TYPES.map((value) => (
                    <option key={value} value={value}>
                      {t(`formwork.type.${value}`, { defaultValue: SYSTEM_TYPE_LABELS[value] })}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label
                  className="block text-xs font-medium text-content-secondary mb-1"
                  htmlFor="formwork-new-material"
                >
                  {t('formwork.col.material', { defaultValue: 'Material' })}
                </label>
                <select
                  id="formwork-new-material"
                  className="w-full h-9 rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary"
                  value={systemForm.material}
                  onChange={(e) =>
                    setSystemForm({ ...systemForm, material: e.target.value as FormworkMaterial })
                  }
                >
                  {MATERIALS.map((value) => (
                    <option key={value} value={value}>
                      {t(`formwork.material.${value}`, { defaultValue: MATERIAL_LABELS[value] })}
                    </option>
                  ))}
                </select>
              </div>
              <Input
                label={t('formwork.col.supplier', { defaultValue: 'Supplier' })}
                value={systemForm.supplier}
                onChange={(e) => setSystemForm({ ...systemForm, supplier: e.target.value })}
              />
              <Input
                label={t('formwork.col.reusesMax', { defaultValue: 'Reuse limit' })}
                type="number"
                min={1}
                value={systemForm.reuses_max}
                onChange={(e) => setSystemForm({ ...systemForm, reuses_max: e.target.value })}
              />
              <Input
                label={t('formwork.col.panelRate', { defaultValue: 'Panels /m2' })}
                type="number"
                min={0}
                step="0.01"
                hint={t('formwork.hint.panelRate', { defaultValue: 'Divided by the reuse count' })}
                value={systemForm.unit_rate}
                onChange={(e) => setSystemForm({ ...systemForm, unit_rate: e.target.value })}
              />
              <Input
                label={t('formwork.col.labourRate', { defaultValue: 'Erect+strike /m2' })}
                type="number"
                min={0}
                step="0.01"
                hint={t('formwork.hint.labourRate', { defaultValue: 'Paid on every use' })}
                value={systemForm.erect_strike_rate}
                onChange={(e) =>
                  setSystemForm({ ...systemForm, erect_strike_rate: e.target.value })
                }
              />
              <Input
                label={t('formwork.col.stripTime', { defaultValue: 'Striking time (days)' })}
                hint={t('formwork.hint.stripTime', {
                  defaultValue: 'Earliest the panels can come off',
                })}
                type="number"
                min={0}
                value={systemForm.strip_time_days}
                onChange={(e) => setSystemForm({ ...systemForm, strip_time_days: e.target.value })}
              />
              <Input
                label={t('formwork.col.cycleDays', { defaultValue: 'Cycle (days)' })}
                hint={t('formwork.hint.cycleDays', {
                  defaultValue: 'Pour to pour, including clean and set',
                })}
                type="number"
                min={0}
                step="0.5"
                value={systemForm.cycle_days}
                onChange={(e) => setSystemForm({ ...systemForm, cycle_days: e.target.value })}
              />
              <Input
                label={t('formwork.col.typicalReuses', { defaultValue: 'Typical reuses' })}
                hint={t('formwork.hint.typicalReuses', {
                  defaultValue: 'Leave blank if not published',
                })}
                type="number"
                min={1}
                value={systemForm.typical_reuses}
                onChange={(e) => setSystemForm({ ...systemForm, typical_reuses: e.target.value })}
              />
              <div>
                <label
                  className="block text-xs font-medium text-content-secondary mb-1"
                  htmlFor="formwork-new-basis"
                >
                  {t('formwork.col.rateBasis', { defaultValue: 'Rate basis' })}
                </label>
                <select
                  id="formwork-new-basis"
                  className="w-full h-9 rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary"
                  value={systemForm.rate_basis}
                  onChange={(e) =>
                    setSystemForm({
                      ...systemForm,
                      rate_basis: e.target.value as FormworkRateBasis,
                    })
                  }
                >
                  {RATE_BASES.map((value) => (
                    <option key={value} value={value}>
                      {t(`formwork.basis.${value}`, { defaultValue: RATE_BASIS_LABELS[value] })}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-content-secondary">
                  {t('formwork.hint.rateBasis', {
                    defaultValue: 'Only a bought rate is divided by the reuses',
                  })}
                </p>
              </div>
              <Input
                label={t('formwork.col.currency', { defaultValue: 'Currency' })}
                maxLength={3}
                value={systemForm.currency}
                onChange={(e) =>
                  setSystemForm({ ...systemForm, currency: e.target.value.toUpperCase() })
                }
              />
              <Button
                variant="primary"
                icon={<Plus size={15} />}
                loading={createSystemMutation.isPending}
                disabled={!systemForm.name}
                onClick={() => createSystemMutation.mutate()}
              >
                {t('formwork.catalogue.create', { defaultValue: 'Create system' })}
              </Button>
            </div>
          )}

          {systemsQuery.isLoading ? (
            <SkeletonTable rows={4} columns={6} />
          ) : systems.length === 0 ? (
            <EmptyState
              icon={<Boxes size={26} strokeWidth={1.5} />}
              title={t('formwork.catalogue.emptyTitle', { defaultValue: 'No formwork systems yet' })}
              description={t('formwork.catalogue.emptyBody', {
                defaultValue:
                  'Add the systems you actually hire, or start from the shipped set and re-rate it against your own hire terms.',
              })}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-content-secondary border-b border-border">
                    <th className="py-1.5 pr-3 font-medium">
                      {t('formwork.col.name', { defaultValue: 'Name' })}
                    </th>
                    <th className="py-1.5 pr-3 font-medium">
                      {t('formwork.col.type', { defaultValue: 'Type' })}
                    </th>
                    <th className="py-1.5 pr-3 font-medium text-right">
                      {t('formwork.col.reusesMax', { defaultValue: 'Reuse limit' })}
                    </th>
                    <th className="py-1.5 pr-3 font-medium text-right">
                      {t('formwork.col.panelRate', { defaultValue: 'Panels /m2' })}
                    </th>
                    <th className="py-1.5 pr-3 font-medium text-right">
                      {t('formwork.col.labourRate', { defaultValue: 'Erect+strike /m2' })}
                    </th>
                    <th className="py-1.5 pr-3 font-medium text-right">
                      {t('formwork.col.stripTime', { defaultValue: 'Striking time (days)' })}
                    </th>
                    <th className="py-1.5" />
                  </tr>
                </thead>
                <tbody>
                  {systems.map((system) => (
                    <tr key={system.id} className="border-b border-border-light last:border-0">
                      <td className="py-2 pr-3">
                        <div className="font-medium text-content-primary">{system.name}</div>
                        {system.supplier && (
                          <div className="text-xs text-content-secondary">{system.supplier}</div>
                        )}
                      </td>
                      <td className="py-2 pr-3">
                        <Badge variant="neutral" size="sm">
                          {system.system_type}
                        </Badge>
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">{system.reuses_max}</td>
                      <td className="py-2 pr-3 text-right">
                        <input
                          type="number"
                          min={0}
                          step="0.01"
                          defaultValue={system.unit_rate}
                          aria-label={t('formwork.col.panelRate', { defaultValue: 'Panels /m2' })}
                          className="w-24 h-8 rounded-md border border-border bg-surface-primary px-2 text-right text-sm tabular-nums"
                          onBlur={(e) => {
                            if (e.target.value !== system.unit_rate) {
                              rateMutation.mutate({
                                systemId: system.id,
                                field: 'unit_rate',
                                value: e.target.value,
                              });
                            }
                          }}
                        />
                      </td>
                      <td className="py-2 pr-3 text-right">
                        <input
                          type="number"
                          min={0}
                          step="0.01"
                          defaultValue={system.erect_strike_rate}
                          aria-label={t('formwork.col.labourRate', {
                            defaultValue: 'Erect+strike /m2',
                          })}
                          className="w-24 h-8 rounded-md border border-border bg-surface-primary px-2 text-right text-sm tabular-nums"
                          onBlur={(e) => {
                            if (e.target.value !== system.erect_strike_rate) {
                              rateMutation.mutate({
                                systemId: system.id,
                                field: 'erect_strike_rate',
                                value: e.target.value,
                              });
                            }
                          }}
                        />
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">
                        {system.strip_time_days}
                      </td>
                      <td className="py-2 text-right whitespace-nowrap">
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<RefreshCw size={14} />}
                          aria-label={t('formwork.repriceSystem', {
                            defaultValue: 'Re-price assignments using this system',
                          })}
                          onClick={() => repriceSystemMutation.mutate(system.id)}
                        />
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<Trash2 size={14} />}
                          aria-label={t('common.delete', { defaultValue: 'Delete' })}
                          onClick={() => handleDeleteSystem(system)}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

export default FormworkPage;
