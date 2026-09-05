// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Production-Norm Expansion.
 *
 * Manage a library of production-norm coefficients (labor-hours, machine-hours
 * and material quantities per unit of a work item) and expand any work item and
 * quantity into the unpriced resource demand behind a rate - the hours and
 * material takeoff an estimator sees before any pricing is applied.
 *
 * Coefficients and expanded quantities arrive from the API as Decimal-as-string;
 * they are only ever formatted for display (fmtNumber) and never used in JS
 * arithmetic on the wire value.
 */

import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Plus,
  Trash2,
  ChevronRight,
  ChevronDown,
  Clock,
  Cog,
  Boxes,
  Coins,
  AlertTriangle,
  ArrowRight,
  ListPlus,
  X,
  Search,
  Network,
  Library,
  Calculator,
  Wallet,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, RecoveryCard, SkeletonTable, CollapsibleSection } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtList, fmtNumber } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { laborRatesApi, type LaborRateTemplate } from '@/features/labor-rates/api';
import {
  fetchNorms,
  createNorm,
  deleteNorm,
  addNormMaterial,
  deleteNormMaterial,
  expandWork,
  isValidQuantity,
  buildBuildAssemblyPayload,
  canRunBuildAssembly,
  buildNormResourceSplit,
  addNormSplitToBoqPosition,
  listBoqPickerProjects,
  listBoqPickerBoqs,
  listBoqPickerPositions,
  resourceBadge,
  withCurrency,
  type ProductionNorm,
  type ExpansionResult,
  type BuildAssemblyResult,
  type PricedComponent,
  type ResourceKind,
} from './api';
import { useBuildAssembly } from './useBuildAssembly';

const INPUT_CLS =
  'w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm ' +
  'text-content-primary placeholder:text-content-tertiary focus:border-oe-blue focus:outline-none ' +
  'focus:ring-2 focus:ring-blue-200 dark:focus:ring-blue-900/40';

const NORMS_KEY = ['norm-expansion-norms'];

/* ── How-it-works flow + module integrations ───────────────────────────── */

/** A compact inline link to a sibling module (keeps the flow copy readable). */
function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/**
 * Explains, in one glance, what a production norm is and how this page connects
 * to the rest of the platform: the norm is expanded into an unpriced takeoff,
 * priced from the Labour Rates / Waste Factors / Cost Database, saved as a
 * reusable Assembly, and applied to a BOQ. The founder's ask was that the
 * module make its integrations obvious, so every connected module is a link.
 */
function HowNormsWork() {
  const { t } = useTranslation();

  const steps: { icon: ReactNode; title: string; desc: string }[] = [
    {
      icon: <Library size={14} className="text-oe-blue" />,
      title: t('normExpansion.flow_1_title', { defaultValue: 'Norm library' }),
      desc: t('normExpansion.flow_1_desc', {
        defaultValue: 'Labour-hours, machine-hours and materials per unit of a work item.',
      }),
    },
    {
      icon: <Calculator size={14} className="text-oe-blue" />,
      title: t('normExpansion.flow_2_title', { defaultValue: 'Expand' }),
      desc: t('normExpansion.flow_2_desc', {
        defaultValue: 'Enter a quantity to see the unpriced hours and material takeoff behind it.',
      }),
    },
    {
      icon: <Wallet size={14} className="text-oe-blue" />,
      title: t('normExpansion.flow_3_title', { defaultValue: 'Price it' }),
      desc: t('normExpansion.flow_3_desc', {
        defaultValue:
          'Hours priced from your labour rates, materials matched to the cost database and grossed up for waste.',
      }),
    },
    {
      icon: <Coins size={14} className="text-oe-blue" />,
      title: t('normExpansion.flow_4_title', { defaultValue: 'Save as assembly' }),
      desc: t('normExpansion.flow_4_desc', {
        defaultValue: 'The built-up unit rate is saved as a reusable assembly.',
      }),
    },
    {
      icon: <ListPlus size={14} className="text-oe-blue" />,
      title: t('normExpansion.flow_5_title', { defaultValue: 'Use in a BOQ' }),
      desc: t('normExpansion.flow_5_desc', {
        defaultValue: 'Drop the assembly or the raw resource split onto a BOQ position.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="normExpansion.how"
      icon={<Network size={15} className="text-oe-blue" />}
      title={t('normExpansion.flow_title', { defaultValue: 'How production norms fit together' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('normExpansion.flow_intro', {
          defaultValue:
            'A production norm turns one unit of work into the hours and materials behind it, then into a priced rate you can reuse across estimates. This page is where that build-up starts.',
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
            {t('normExpansion.flow_pulls', { defaultValue: 'Pulls from:' })}
          </span>{' '}
          <ModLink to="/labor-rates">
            {t('normExpansion.mod_labor_rates', { defaultValue: 'Labour rates' })}
          </ModLink>{' '}
          ·{' '}
          <ModLink to="/waste-factors">
            {t('normExpansion.mod_waste', { defaultValue: 'Waste factors' })}
          </ModLink>{' '}
          ·{' '}
          <ModLink to="/costs">
            {t('normExpansion.mod_costs', { defaultValue: 'Cost database' })}
          </ModLink>
        </span>
        <span>
          <span className="font-medium text-content-secondary">
            {t('normExpansion.flow_feeds', { defaultValue: 'Feeds:' })}
          </span>{' '}
          <ModLink to="/assemblies">
            {t('normExpansion.mod_assemblies', { defaultValue: 'Assemblies' })}
          </ModLink>{' '}
          ·{' '}
          <ModLink to="/boq">{t('normExpansion.mod_boq', { defaultValue: 'BOQ' })}</ModLink> ·{' '}
          <ModLink to="/resource-summary">
            {t('normExpansion.mod_resource_summary', { defaultValue: 'Resource summary' })}
          </ModLink>
        </span>
      </div>
    </CollapsibleSection>
  );
}

/* ── Expand panel ──────────────────────────────────────────────────────── */

function ExpandPanel({ norms }: { norms: ProductionNorm[] }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [workKey, setWorkKey] = useState('');
  const [quantity, setQuantity] = useState('1');
  const [result, setResult] = useState<ExpansionResult | null>(null);

  const selectedNorm = useMemo(
    () => norms.find((n) => n.work_key === workKey),
    [norms, workKey],
  );

  const mutation = useMutation({
    mutationFn: () => expandWork({ work_key: workKey, quantity: quantity.trim() }),
    onSuccess: (data) => setResult(data),
    onError: (err) => {
      setResult(null);
      addToast({
        type: 'error',
        title: t('normExpansion.expand_failed', { defaultValue: 'Could not expand work item' }),
        message: getErrorMessage(err),
      });
    },
  });

  const canExpand = !!selectedNorm && isValidQuantity(quantity);

  return (
    <Card padding="md">
      <h2 className="mb-1 text-sm font-semibold text-content-primary">
        {t('normExpansion.expand_title', { defaultValue: 'Expand a work item' })}
      </h2>
      <p className="mb-3 text-xs text-content-tertiary">
        {t('normExpansion.expand_help', {
          defaultValue:
            'Pick a work item and enter a quantity to see the labor-hours, machine-hours and materials behind it, before any pricing.',
        })}
      </p>

      <div className="grid grid-cols-1 items-end gap-2 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto]">
        <div>
          <label className="mb-1 block text-xs font-medium text-content-secondary">
            {t('normExpansion.work_item', { defaultValue: 'Work item' })}
          </label>
          <select
            className={INPUT_CLS}
            value={workKey}
            onChange={(e) => {
              setWorkKey(e.target.value);
              setResult(null);
            }}
            aria-label={t('normExpansion.select_work_item', { defaultValue: 'Select a work item' })}
            data-testid="norm-expand-select"
          >
            <option value="">
              {t('normExpansion.choose_work_item', { defaultValue: 'Choose a work item...' })}
            </option>
            {norms.map((n) => (
              <option key={n.id} value={n.work_key}>
                {n.name ? `${n.name} (${n.unit})` : `${n.work_key} (${n.unit})`}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-content-secondary">
            {t('normExpansion.quantity', { defaultValue: 'Quantity' })}
            {selectedNorm ? ` (${selectedNorm.unit})` : ''}
          </label>
          <input
            className={INPUT_CLS}
            inputMode="decimal"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            placeholder="1"
            data-testid="norm-expand-quantity"
          />
        </div>
        <Button
          variant="primary"
          size="sm"
          disabled={!canExpand || mutation.isPending}
          onClick={() => mutation.mutate()}
          data-testid="norm-expand-run"
        >
          {t('normExpansion.expand_action', { defaultValue: 'Expand' })}
        </Button>
      </div>

      {result && <ExpansionResultView result={result} norm={selectedNorm} />}
    </Card>
  );
}

function ResourceTile({
  icon,
  label,
  value,
  unit,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  unit: string;
}) {
  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3">
      <div className="flex items-center gap-1.5 text-2xs uppercase tracking-wide text-content-tertiary">
        {icon}
        {label}
      </div>
      <div className="mt-1 text-lg font-bold tabular-nums text-content-primary">
        {fmtNumber(value, 2)}
        <span className="ml-1 text-xs font-normal text-content-tertiary">{unit}</span>
      </div>
    </div>
  );
}

function ExpansionResultView({
  result,
  norm,
}: {
  result: ExpansionResult;
  norm?: ProductionNorm;
}) {
  const { t } = useTranslation();
  const hoursUnit = t('normExpansion.hours_unit', { defaultValue: 'h' });

  return (
    <div className="mt-4 space-y-3" data-testid="norm-expand-result">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <ResourceTile
          icon={<Clock size={12} className="text-oe-blue" />}
          label={t('normExpansion.labor_hours', { defaultValue: 'Labor hours' })}
          value={result.labor_hours}
          unit={hoursUnit}
        />
        <ResourceTile
          icon={<Cog size={12} className="text-oe-blue" />}
          label={t('normExpansion.machine_hours', { defaultValue: 'Machine hours' })}
          value={result.machine_hours}
          unit={hoursUnit}
        />
        <ResourceTile
          icon={<Boxes size={12} className="text-oe-blue" />}
          label={t('normExpansion.material_lines', { defaultValue: 'Material lines' })}
          value={String(result.materials.length)}
          unit=""
        />
      </div>

      {result.materials.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[360px] text-sm">
            <thead>
              <tr className="border-b border-border-light text-left text-2xs uppercase tracking-wide text-content-tertiary">
                <th className="py-2 pr-3 font-medium">
                  {t('normExpansion.col_material', { defaultValue: 'Material' })}
                </th>
                <th className="py-2 pr-3 text-right font-medium">
                  {t('normExpansion.col_quantity', { defaultValue: 'Quantity' })}
                </th>
                <th className="py-2 pr-3 font-medium">
                  {t('normExpansion.col_unit', { defaultValue: 'Unit' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {result.materials.map((m, idx) => (
                <tr
                  key={`${m.name}-${idx}`}
                  className="border-b border-border-light/60 hover:bg-surface-secondary/40"
                >
                  <td className="py-2 pr-3 text-content-primary">{m.name}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-content-secondary">
                    {fmtNumber(m.qty, 3)}
                  </td>
                  <td className="py-2 pr-3 text-content-tertiary">{m.unit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {norm && <AddToBoqPanel norm={norm} />}
    </div>
  );
}

/* ── Add-to-BOQ panel (interoperability F5: norm split → BOQ position) ──── */

/**
 * Attach the norm's per-unit resource split (labour-hours, machine-hours,
 * materials) onto an EXISTING BOQ position, without first building a priced
 * assembly. The estimator picks project → BOQ → position; the split is written
 * to that position's ``metadata.resources`` in the same shape the costs → BOQ
 * path uses. The lines are unpriced, so the BOQ shows them ready to be priced.
 */
function AddToBoqPanel({ norm }: { norm: ProductionNorm }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [open, setOpen] = useState(false);
  const [projectId, setProjectId] = useState('');
  const [boqId, setBoqId] = useState('');
  const [positionId, setPositionId] = useState('');

  // The per-unit split is derived once from the norm's coefficients (verbatim
  // Decimal strings). Materials keep their own name; labour / machine use
  // localized labels.
  const resources = useMemo(
    () =>
      buildNormResourceSplit(norm, {
        labor: t('normExpansion.res_labor', { defaultValue: 'Labour' }),
        machine: t('normExpansion.res_machine', { defaultValue: 'Machine' }),
        hoursUnit: t('normExpansion.hours_unit', { defaultValue: 'h' }),
      }),
    [norm, t],
  );

  const projectsQuery = useQuery({
    queryKey: ['norm-boq-projects'],
    queryFn: listBoqPickerProjects,
    enabled: open,
  });
  const boqsQuery = useQuery({
    queryKey: ['norm-boq-boqs', projectId],
    queryFn: () => listBoqPickerBoqs(projectId),
    enabled: open && projectId !== '',
  });
  const positionsQuery = useQuery({
    queryKey: ['norm-boq-positions', boqId],
    queryFn: () => listBoqPickerPositions(boqId),
    enabled: open && boqId !== '',
  });

  // Auto-select the first project / BOQ so the picker lands ready to use; the
  // target POSITION is always chosen explicitly (never auto-picked).
  useEffect(() => {
    const list = projectsQuery.data;
    if (open && list && list.length > 0 && projectId === '') setProjectId(list[0]!.id);
  }, [open, projectsQuery.data, projectId]);
  useEffect(() => {
    const list = boqsQuery.data;
    if (list && list.length > 0 && boqId === '') setBoqId(list[0]!.id);
  }, [boqsQuery.data, boqId]);

  const addMut = useMutation({
    mutationFn: () => addNormSplitToBoqPosition(positionId, resources),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('normExpansion.boq_attach_success', {
          defaultValue: 'Resource breakdown added to the BOQ position',
        }),
        message: t('normExpansion.boq_attach_success_hint', {
          defaultValue: 'Open the BOQ to price the labour, machine and material lines.',
        }),
      });
      setOpen(false);
      setPositionId('');
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('normExpansion.boq_attach_failed', {
          defaultValue: 'Could not add to the BOQ position',
        }),
        message: getErrorMessage(err),
      }),
  });

  const projects = projectsQuery.data ?? [];
  const boqs = boqsQuery.data ?? [];
  const positions = positionsQuery.data ?? [];
  const canAdd = positionId !== '' && resources.length > 0 && !addMut.isPending;

  const close = () => {
    setOpen(false);
    setPositionId('');
  };

  // Nothing to attach (norm has no positive labour, machine or material lines).
  if (resources.length === 0) return null;

  return (
    <div className="mt-3 border-t border-border-light pt-3">
      {!open ? (
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setOpen(true)}
          data-testid="norm-add-to-boq"
        >
          <ListPlus size={14} className="mr-1 shrink-0" />
          {t('normExpansion.add_to_boq', { defaultValue: 'Add to BOQ position...' })}
        </Button>
      ) : (
        <div className="space-y-3 rounded-lg border border-border-light bg-surface-secondary/40 p-3">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold text-content-primary">
                {t('normExpansion.add_to_boq_title', {
                  defaultValue: 'Add resource breakdown to a BOQ position',
                })}
              </h3>
              <p className="mt-0.5 text-2xs text-content-tertiary">
                {t('normExpansion.add_to_boq_help', {
                  defaultValue:
                    'Attaches the per-unit labour, machine and material lines to the chosen position. The lines are unpriced - price them in the BOQ to build up the position rate.',
                })}
              </p>
            </div>
            <button
              type="button"
              onClick={close}
              className="rounded p-1 text-content-tertiary hover:bg-surface-secondary"
              aria-label={t('normExpansion.add_to_boq_close', { defaultValue: 'Close' })}
            >
              <X size={14} />
            </button>
          </div>

          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-content-secondary">
                {t('normExpansion.boq_project', { defaultValue: 'Project' })}
              </label>
              <select
                className={INPUT_CLS}
                value={projectId}
                onChange={(e) => {
                  setProjectId(e.target.value);
                  setBoqId('');
                  setPositionId('');
                }}
                data-testid="norm-boq-project"
              >
                <option value="">
                  {projectsQuery.isLoading
                    ? t('normExpansion.loading', { defaultValue: 'Loading...' })
                    : t('normExpansion.boq_choose_project', { defaultValue: 'Choose a project...' })}
                </option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-content-secondary">
                {t('normExpansion.boq_boq', { defaultValue: 'BOQ' })}
              </label>
              <select
                className={INPUT_CLS}
                value={boqId}
                onChange={(e) => {
                  setBoqId(e.target.value);
                  setPositionId('');
                }}
                disabled={projectId === ''}
                data-testid="norm-boq-boq"
              >
                <option value="">
                  {boqsQuery.isLoading
                    ? t('normExpansion.loading', { defaultValue: 'Loading...' })
                    : t('normExpansion.boq_choose_boq', { defaultValue: 'Choose a BOQ...' })}
                </option>
                {boqs.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-content-secondary">
                {t('normExpansion.boq_position', { defaultValue: 'Position' })}
              </label>
              <select
                className={INPUT_CLS}
                value={positionId}
                onChange={(e) => setPositionId(e.target.value)}
                disabled={boqId === ''}
                data-testid="norm-boq-position"
              >
                <option value="">
                  {positionsQuery.isLoading
                    ? t('normExpansion.loading', { defaultValue: 'Loading...' })
                    : t('normExpansion.boq_choose_position', {
                        defaultValue: 'Choose a position...',
                      })}
                </option>
                {positions.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.description ? `${p.ordinal} · ${p.description}` : p.ordinal} ({p.unit})
                  </option>
                ))}
              </select>
            </div>
          </div>

          {boqId !== '' && !positionsQuery.isLoading && positions.length === 0 && (
            <p className="text-2xs text-content-tertiary">
              {t('normExpansion.boq_no_positions', {
                defaultValue:
                  'This BOQ has no priceable positions yet. Add a position in the BOQ first.',
              })}
            </p>
          )}

          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              disabled={!canAdd}
              onClick={() => addMut.mutate()}
              data-testid="norm-boq-add"
            >
              <ListPlus size={14} className="mr-1 shrink-0" />
              {t('normExpansion.boq_add_action', { defaultValue: 'Add to position' })}
            </Button>
            <Button variant="ghost" size="sm" onClick={close}>
              {t('normExpansion.boq_cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Build priced assembly panel ───────────────────────────────────────── */

function BuildAssemblyPanel({ norms }: { norms: ProductionNorm[] }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [normId, setNormId] = useState('');
  const [laborRateTemplateId, setLaborRateTemplateId] = useState('');
  const [machineRateTemplateId, setMachineRateTemplateId] = useState('');
  const [region, setRegion] = useState('');
  const [applyWaste, setApplyWaste] = useState(true);
  const [result, setResult] = useState<BuildAssemblyResult | null>(null);

  // The equipment rate reuses the labour-rate templates (an all-in hourly
  // rate); we read that list here but never mutate the labour-rates feature.
  const templatesQuery = useQuery({
    queryKey: ['labor-rates', 'templates'],
    queryFn: laborRatesApi.listTemplates,
  });
  const templates: LaborRateTemplate[] = templatesQuery.data ?? [];
  // Only the server saying "none" counts as none. A failed request leaves
  // `data` undefined as well, and reading that as an empty list would both
  // claim there are no templates and open the gate below on a guess.
  const noTemplates = templatesQuery.isSuccess && templates.length === 0;

  const buildMut = useBuildAssembly();

  const selectedNorm = useMemo(() => norms.find((n) => n.id === normId), [norms, normId]);
  // A labour rate is required to price the labour hours, except when there are
  // no templates to pick from at all - see canRunBuildAssembly for why.
  const canBuild = canRunBuildAssembly({
    normSelected: !!selectedNorm,
    laborRateTemplateId,
    noTemplates,
    pending: buildMut.isPending,
  });

  const templateLabel = (tpl: LaborRateTemplate): string =>
    tpl.all_in_rate ? `${tpl.name} · ${withCurrency(tpl.all_in_rate, tpl.currency)}` : tpl.name;

  const run = () => {
    if (!selectedNorm) return;
    const body = buildBuildAssemblyPayload({
      laborRateTemplateId,
      machineRateTemplateId,
      region,
      applyWaste,
    });
    buildMut.mutate(
      { normId: selectedNorm.id, body },
      {
        onSuccess: (data) => setResult(data),
        onError: (err) => {
          setResult(null);
          addToast({
            type: 'error',
            title: t('normExpansion.build_failed', { defaultValue: 'Could not build assembly' }),
            message: getErrorMessage(err),
          });
        },
      },
    );
  };

  return (
    <Card padding="md">
      <h2 className="mb-1 flex items-center gap-1.5 text-sm font-semibold text-content-primary">
        <Coins size={15} className="text-oe-blue" />
        {t('normExpansion.build_title', { defaultValue: 'Build priced assembly' })}
      </h2>
      <p className="mb-2 text-xs text-content-tertiary">
        {t('normExpansion.build_help', {
          defaultValue:
            'Turn a norm into a saved, priced unit rate: labour priced from a labour rate, materials matched to cost items and grossed up for waste. You can then apply the assembly to a BOQ position.',
        })}
      </p>
      <p className="mb-3 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-2xs text-content-tertiary">
        <span className="font-medium text-content-secondary">
          {t('normExpansion.build_uses', { defaultValue: 'Uses' })}
        </span>
        <ModLink to="/labor-rates">
          {t('normExpansion.mod_labor_rates', { defaultValue: 'Labour rates' })}
        </ModLink>
        <span>{t('normExpansion.build_uses_hours', { defaultValue: 'for hours,' })}</span>
        <ModLink to="/costs">
          {t('normExpansion.mod_costs', { defaultValue: 'Cost database' })}
        </ModLink>
        <span>{t('normExpansion.build_uses_prices', { defaultValue: 'for material prices,' })}</span>
        <ModLink to="/waste-factors">
          {t('normExpansion.mod_waste', { defaultValue: 'Waste factors' })}
        </ModLink>
        <span>{t('normExpansion.build_uses_gross', { defaultValue: 'for gross quantities.' })}</span>
        <span>{t('normExpansion.build_uses_saved', { defaultValue: 'Saved to' })}</span>
        <ModLink to="/assemblies">
          {t('normExpansion.mod_assemblies', { defaultValue: 'Assemblies' })}
        </ModLink>
      </p>

      <div className="space-y-3">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-content-secondary">
              {t('normExpansion.build_norm', { defaultValue: 'Work item' })}
            </label>
            <select
              className={INPUT_CLS}
              value={normId}
              onChange={(e) => {
                setNormId(e.target.value);
                setResult(null);
              }}
              aria-label={t('normExpansion.select_work_item', { defaultValue: 'Select a work item' })}
              data-testid="norm-build-select"
            >
              <option value="">
                {t('normExpansion.choose_work_item', { defaultValue: 'Choose a work item...' })}
              </option>
              {norms.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.name ? `${n.name} (${n.unit})` : `${n.work_key} (${n.unit})`}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-content-secondary">
              {t('normExpansion.build_labor_rate', { defaultValue: 'Labour rate (required)' })}
            </label>
            <select
              className={INPUT_CLS}
              value={laborRateTemplateId}
              onChange={(e) => setLaborRateTemplateId(e.target.value)}
              aria-label={t('normExpansion.build_labor_rate', {
                defaultValue: 'Labour rate (required)',
              })}
              data-testid="norm-build-labor"
            >
              <option value="">
                {templatesQuery.isLoading
                  ? t('normExpansion.loading', { defaultValue: 'Loading...' })
                  : t('normExpansion.choose_labor_rate', { defaultValue: 'Choose a labour rate...' })}
              </option>
              {templates.map((tpl) => (
                <option key={tpl.id} value={tpl.id}>
                  {templateLabel(tpl)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-content-secondary">
              {t('normExpansion.build_machine_rate', { defaultValue: 'Machine rate (optional)' })}
            </label>
            <select
              className={INPUT_CLS}
              value={machineRateTemplateId}
              onChange={(e) => setMachineRateTemplateId(e.target.value)}
              aria-label={t('normExpansion.build_machine_rate', {
                defaultValue: 'Machine rate (optional)',
              })}
              data-testid="norm-build-machine"
            >
              <option value="">
                {t('normExpansion.build_machine_none', { defaultValue: 'None' })}
              </option>
              {templates.map((tpl) => (
                <option key={tpl.id} value={tpl.id}>
                  {templateLabel(tpl)}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-1 items-end gap-2 sm:grid-cols-[1fr_auto_auto]">
          <div>
            <label className="mb-1 block text-xs font-medium text-content-secondary">
              {t('normExpansion.build_region', { defaultValue: 'Region (optional)' })}
            </label>
            <input
              className={INPUT_CLS}
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              placeholder={t('normExpansion.build_region_ph', { defaultValue: 'e.g. Berlin' })}
              data-testid="norm-build-region"
            />
          </div>
          <label className="flex h-9 cursor-pointer items-center gap-2 text-sm text-content-secondary">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-border-light text-oe-blue focus:ring-oe-blue"
              checked={applyWaste}
              onChange={(e) => setApplyWaste(e.target.checked)}
              data-testid="norm-build-waste"
            />
            {t('normExpansion.apply_waste', { defaultValue: 'Apply waste factors' })}
          </label>
          <Button
            variant="primary"
            size="sm"
            disabled={!canBuild}
            onClick={run}
            data-testid="norm-build-run"
          >
            <Coins size={14} className="mr-1 shrink-0" />
            {t('normExpansion.build_action', { defaultValue: 'Build priced assembly' })}
          </Button>
        </div>

        {noTemplates && (
          <p className="text-xs text-content-tertiary">
            {t('normExpansion.build_no_templates', {
              defaultValue: 'No labour-rate templates yet. Create one on the Labour Rates page first.',
            })}{' '}
            <Link to="/labor-rates" className="text-oe-blue-text underline hover:no-underline">
              {t('normExpansion.build_open_labor_rates', { defaultValue: 'Open Labour Rates' })}
            </Link>
          </p>
        )}
      </div>

      {result && <BuildAssemblyResultView result={result} />}
    </Card>
  );
}

function BuildAssemblyResultView({ result }: { result: BuildAssemblyResult }) {
  const { t } = useTranslation();
  const curSuffix = result.currency ? ` (${result.currency})` : '';
  const hasUnpriced = result.unpriced.length > 0;
  const hasUnmatched = result.waste_applied && result.waste_unmatched.length > 0;

  const kindLabel = (kind: ResourceKind): string => {
    switch (kind) {
      case 'labor':
        return t('normExpansion.res_labor', { defaultValue: 'Labour' });
      case 'equipment':
        return t('normExpansion.res_equipment', { defaultValue: 'Equipment' });
      case 'material':
        return t('normExpansion.res_material', { defaultValue: 'Material' });
      default:
        return t('normExpansion.res_other', { defaultValue: 'Other' });
    }
  };

  return (
    <div className="mt-4 space-y-3" data-testid="norm-build-result">
      {/* Headline: saved assembly + built-up unit rate */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border-light bg-surface-secondary/40 p-3">
        <div className="min-w-0">
          <div className="text-2xs uppercase tracking-wide text-content-tertiary">
            {t('normExpansion.build_saved', { defaultValue: 'Saved as assembly' })}
          </div>
          <Link
            to={`/assemblies/${result.id}`}
            className="inline-flex items-center gap-1 text-sm font-semibold text-oe-blue-text hover:underline"
            data-testid="norm-build-assembly-link"
          >
            {result.code}
            <ArrowRight size={13} className="shrink-0" />
          </Link>
          <div className="text-2xs text-content-tertiary">
            {t('normExpansion.build_apply_hint', {
              defaultValue: 'Open the assembly to apply it to a BOQ position.',
            })}
          </div>
        </div>
        <div className="text-right">
          <div className="text-2xs uppercase tracking-wide text-content-tertiary">
            {t('normExpansion.build_unit_rate', { defaultValue: 'Unit rate' })}
          </div>
          <div
            className="text-lg font-bold tabular-nums text-content-primary"
            data-testid="norm-build-total-rate"
          >
            {withCurrency(result.total_rate, result.currency)}
            <span className="ml-1 text-xs font-normal text-content-tertiary">/ {result.unit}</span>
          </div>
        </div>
      </div>

      {/* Flags: unpriced lines and materials with no waste factor */}
      {hasUnpriced && (
        <div className="flex items-start gap-2 rounded-lg border border-semantic-error/30 bg-semantic-error-bg/50 p-2.5 text-xs text-semantic-error">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span>
            {t('normExpansion.build_unpriced', {
              defaultValue:
                '{{count}} line(s) could not be priced and need a rate: {{names}}',
              count: result.unpriced.length,
              names: fmtList(result.unpriced),
            })}
          </span>
        </div>
      )}
      {hasUnmatched && (
        <div className="flex items-start gap-2 rounded-lg border border-semantic-warning/30 bg-semantic-warning-bg/50 p-2.5 text-xs text-[#b45309]">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span>
            {t('normExpansion.build_unmatched', {
              defaultValue:
                'No waste factor for: {{names}}. These materials were priced at their net quantity.',
              names: fmtList(result.waste_unmatched),
            })}
          </span>
        </div>
      )}

      {/* Priced build-up table (one row per component) */}
      {result.components.length === 0 ? (
        <p className="text-xs text-content-tertiary">
          {t('normExpansion.build_no_lines', {
            defaultValue: 'This norm has no labour, machine or material lines to price.',
          })}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-border-light text-left text-2xs uppercase tracking-wide text-content-tertiary">
                <th className="py-2 pr-3 font-medium">
                  {t('normExpansion.col_type', { defaultValue: 'Type' })}
                </th>
                <th className="py-2 pr-3 font-medium">
                  {t('normExpansion.col_description', { defaultValue: 'Description' })}
                </th>
                <th className="py-2 pr-3 text-right font-medium">
                  {t('normExpansion.col_net_qty', { defaultValue: 'Net qty' })}
                </th>
                <th className="py-2 pr-3 text-right font-medium">
                  {t('normExpansion.col_waste', { defaultValue: 'Waste %' })}
                </th>
                <th className="py-2 pr-3 text-right font-medium">
                  {t('normExpansion.col_gross_qty', { defaultValue: 'Gross qty' })}
                </th>
                <th className="py-2 pr-3 text-right font-medium">
                  {t('normExpansion.col_unit_cost', { defaultValue: 'Unit cost' })}
                  {curSuffix}
                </th>
                <th className="py-2 pr-3 text-right font-medium">
                  {t('normExpansion.col_line_total', { defaultValue: 'Line total' })}
                  {curSuffix}
                </th>
              </tr>
            </thead>
            <tbody>
              {result.components.map((c, idx) => (
                <BuildRow
                  key={`${c.description}-${idx}`}
                  component={c}
                  wasteApplied={result.waste_applied}
                  kindLabel={kindLabel}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function BuildRow({
  component: c,
  wasteApplied,
  kindLabel,
}: {
  component: PricedComponent;
  wasteApplied: boolean;
  kindLabel: (kind: ResourceKind) => string;
}) {
  const { t } = useTranslation();
  const badge = resourceBadge(c.resource_type);
  // Labour / equipment have no net-gross split, so fall back to the coefficient.
  const netCell = c.net_qty ?? c.quantity;
  const isMaterial = badge.kind === 'material';
  const unmatched = wasteApplied && isMaterial && c.waste_matched === false;

  return (
    <tr
      className={`border-b border-border-light/60 hover:bg-surface-secondary/40 ${
        c.priced ? '' : 'bg-semantic-error-bg/40'
      }`}
    >
      <td className="py-2 pr-3">
        <span title={kindLabel(badge.kind)}>
          <Badge variant={badge.variant} size="sm">
            {badge.letter}
          </Badge>
        </span>
      </td>
      <td className="py-2 pr-3 text-content-primary">
        <div className="flex flex-wrap items-center gap-1.5">
          <span>{c.description}</span>
          {!c.priced && (
            <Badge variant="error" size="sm">
              {t('normExpansion.badge_unpriced', { defaultValue: 'Unpriced' })}
            </Badge>
          )}
          {unmatched && (
            <Badge variant="warning" size="sm">
              {t('normExpansion.badge_no_waste', { defaultValue: 'No waste factor' })}
            </Badge>
          )}
        </div>
        {!c.priced && c.unpriced_reason && (
          <div className="text-2xs text-content-tertiary">{c.unpriced_reason}</div>
        )}
      </td>
      <td className="py-2 pr-3 text-right tabular-nums text-content-secondary">
        {netCell}
        <span className="ml-1 text-2xs text-content-tertiary">{c.unit}</span>
      </td>
      <td className="py-2 pr-3 text-right tabular-nums text-content-secondary">
        {c.waste_pct !== null ? `${c.waste_pct}%` : '-'}
      </td>
      <td className="py-2 pr-3 text-right tabular-nums text-content-secondary">
        {c.gross_qty !== null ? (
          <>
            {c.gross_qty}
            <span className="ml-1 text-2xs text-content-tertiary">{c.unit}</span>
          </>
        ) : (
          '-'
        )}
      </td>
      <td className="py-2 pr-3 text-right tabular-nums text-content-secondary">{c.unit_cost}</td>
      <td className="py-2 pr-3 text-right tabular-nums font-medium text-content-primary">
        {c.total}
      </td>
    </tr>
  );
}

/* ── Create-norm form ──────────────────────────────────────────────────── */

const EMPTY_NORM = {
  work_key: '',
  name: '',
  unit: '',
  category: '',
  labor_hours_per_unit: '',
  machine_hours_per_unit: '',
};

function CreateNormForm({ onCreated }: { onCreated: () => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState({ ...EMPTY_NORM });

  const mutation = useMutation({
    mutationFn: () =>
      createNorm({
        work_key: form.work_key.trim(),
        name: form.name.trim(),
        unit: form.unit.trim(),
        category: form.category.trim() || undefined,
        labor_hours_per_unit: form.labor_hours_per_unit.trim() || '0',
        machine_hours_per_unit: form.machine_hours_per_unit.trim() || '0',
      }),
    onSuccess: () => {
      setForm({ ...EMPTY_NORM });
      onCreated();
      addToast({
        type: 'success',
        title: t('normExpansion.norm_created', { defaultValue: 'Production norm created' }),
      });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('normExpansion.norm_create_failed', { defaultValue: 'Could not create norm' }),
        message: getErrorMessage(err),
      }),
  });

  const set = (key: keyof typeof form, value: string) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const canCreate = form.work_key.trim() !== '' && form.unit.trim() !== '';

  return (
    <div className="grid grid-cols-2 items-end gap-2 rounded-lg border border-dashed border-border-light p-3 sm:grid-cols-7">
      <input
        className={INPUT_CLS}
        placeholder={t('normExpansion.col_work_key', { defaultValue: 'Work key' })}
        value={form.work_key}
        onChange={(e) => set('work_key', e.target.value)}
      />
      <input
        className={`${INPUT_CLS} sm:col-span-2`}
        placeholder={t('normExpansion.col_name', { defaultValue: 'Name' })}
        value={form.name}
        onChange={(e) => set('name', e.target.value)}
      />
      <input
        className={INPUT_CLS}
        placeholder={t('normExpansion.col_unit', { defaultValue: 'Unit' })}
        value={form.unit}
        onChange={(e) => set('unit', e.target.value)}
      />
      <input
        className={INPUT_CLS}
        inputMode="decimal"
        placeholder={t('normExpansion.col_labor', { defaultValue: 'Labor h/unit' })}
        value={form.labor_hours_per_unit}
        onChange={(e) => set('labor_hours_per_unit', e.target.value)}
      />
      <input
        className={INPUT_CLS}
        inputMode="decimal"
        placeholder={t('normExpansion.col_machine', { defaultValue: 'Machine h/unit' })}
        value={form.machine_hours_per_unit}
        onChange={(e) => set('machine_hours_per_unit', e.target.value)}
      />
      <Button
        variant="secondary"
        size="sm"
        disabled={!canCreate || mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        <Plus size={14} className="mr-1 shrink-0" />
        {t('normExpansion.add', { defaultValue: 'Add' })}
      </Button>
    </div>
  );
}

/* ── Material editor (per norm) ────────────────────────────────────────── */

function MaterialEditor({ norm, onChanged }: { norm: ProductionNorm; onChanged: () => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [name, setName] = useState('');
  const [unit, setUnit] = useState('');
  const [qty, setQty] = useState('');

  const addMut = useMutation({
    mutationFn: () =>
      addNormMaterial(norm.id, { name: name.trim(), unit: unit.trim(), qty_per_unit: qty.trim() || '0' }),
    onSuccess: () => {
      setName('');
      setUnit('');
      setQty('');
      onChanged();
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('normExpansion.material_add_failed', { defaultValue: 'Could not add material' }),
        message: getErrorMessage(err),
      }),
  });

  const deleteMut = useMutation({
    mutationFn: (materialId: string) => deleteNormMaterial(materialId),
    onSuccess: () => onChanged(),
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('normExpansion.material_delete_failed', { defaultValue: 'Could not delete material' }),
        message: getErrorMessage(err),
      }),
  });

  const canAdd = name.trim() !== '' && unit.trim() !== '';

  return (
    <div className="space-y-2 bg-surface-secondary/30 p-3">
      {norm.materials.length === 0 ? (
        <p className="text-xs text-content-tertiary">
          {t('normExpansion.no_materials', {
            defaultValue: 'No materials yet. Add the materials this work item consumes per unit.',
          })}
        </p>
      ) : (
        <ul className="space-y-1">
          {norm.materials.map((m) => (
            <li
              key={m.id}
              className="flex items-center justify-between rounded border border-border-light bg-surface-primary px-2 py-1 text-sm"
            >
              <span className="text-content-primary">{m.name}</span>
              <span className="flex items-center gap-3">
                <span className="tabular-nums text-content-secondary">
                  {fmtNumber(m.qty_per_unit, 3)} {m.unit}/{norm.unit}
                </span>
                <button
                  type="button"
                  onClick={() => deleteMut.mutate(m.id)}
                  className="rounded p-1 text-content-tertiary hover:bg-red-50 hover:text-semantic-error dark:hover:bg-red-900/20"
                  aria-label={t('normExpansion.delete_material', { defaultValue: 'Delete material' })}
                >
                  <Trash2 size={13} />
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="grid grid-cols-2 items-end gap-2 sm:grid-cols-4">
        <input
          className={INPUT_CLS}
          placeholder={t('normExpansion.col_material', { defaultValue: 'Material' })}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <input
          className={INPUT_CLS}
          placeholder={t('normExpansion.col_unit', { defaultValue: 'Unit' })}
          value={unit}
          onChange={(e) => setUnit(e.target.value)}
        />
        <input
          className={INPUT_CLS}
          inputMode="decimal"
          placeholder={t('normExpansion.col_qty_per_unit', { defaultValue: 'Qty/unit' })}
          value={qty}
          onChange={(e) => setQty(e.target.value)}
        />
        <Button
          variant="ghost"
          size="sm"
          disabled={!canAdd || addMut.isPending}
          onClick={() => addMut.mutate()}
        >
          <Plus size={14} className="mr-1 shrink-0" />
          {t('normExpansion.add_material', { defaultValue: 'Add material' })}
        </Button>
      </div>
    </div>
  );
}

/* ── Norm library ──────────────────────────────────────────────────────── */

function NormLibrary({
  norms,
  onChanged,
}: {
  norms: ProductionNorm[];
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');

  const deleteMut = useMutation({
    mutationFn: (normId: string) => deleteNorm(normId),
    onSuccess: () => {
      onChanged();
      addToast({
        type: 'success',
        title: t('normExpansion.norm_deleted', { defaultValue: 'Production norm deleted' }),
      });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('normExpansion.norm_delete_failed', { defaultValue: 'Could not delete norm' }),
        message: getErrorMessage(err),
      }),
  });

  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const n of norms) {
      const c = n.category?.trim();
      if (c) set.add(c);
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [norms]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return norms.filter((n) => {
      if (category && n.category !== category) return false;
      if (!q) return true;
      return (
        n.work_key.toLowerCase().includes(q) ||
        (n.name ?? '').toLowerCase().includes(q) ||
        (n.category ?? '').toLowerCase().includes(q)
      );
    });
  }, [norms, search, category]);

  if (norms.length === 0) {
    return (
      <EmptyState
        title={t('normExpansion.no_norms', { defaultValue: 'No production norms yet' })}
        description={t('normExpansion.no_norms_desc', {
          defaultValue:
            'Add a work item with its labor-hours, machine-hours and material coefficients per unit to build the library.',
        })}
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search
            size={14}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            className={`${INPUT_CLS} pl-8`}
            placeholder={t('normExpansion.search_ph', {
              defaultValue: 'Search work key, name or category',
            })}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label={t('normExpansion.search_ph', {
              defaultValue: 'Search work key, name or category',
            })}
            data-testid="norm-library-search"
          />
        </div>
        {categories.length > 0 && (
          <select
            className={`${INPUT_CLS} sm:w-56`}
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            aria-label={t('normExpansion.filter_category', { defaultValue: 'Filter by category' })}
            data-testid="norm-library-category"
          >
            <option value="">
              {t('normExpansion.all_categories', { defaultValue: 'All categories' })}
            </option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        )}
      </div>

      {visible.length === 0 ? (
        <p className="py-6 text-center text-xs text-content-tertiary">
          {t('normExpansion.no_matches', { defaultValue: 'No norms match your search.' })}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-border-light text-left text-2xs uppercase tracking-wide text-content-tertiary">
                <th className="py-2 pr-3 font-medium" />
            <th className="py-2 pr-3 font-medium">
              {t('normExpansion.col_work_key', { defaultValue: 'Work key' })}
            </th>
            <th className="py-2 pr-3 font-medium">
              {t('normExpansion.col_name', { defaultValue: 'Name' })}
            </th>
            <th className="py-2 pr-3 font-medium">
              {t('normExpansion.col_unit', { defaultValue: 'Unit' })}
            </th>
            <th className="py-2 pr-3 text-right font-medium">
              {t('normExpansion.col_labor', { defaultValue: 'Labor h/unit' })}
            </th>
            <th className="py-2 pr-3 text-right font-medium">
              {t('normExpansion.col_machine', { defaultValue: 'Machine h/unit' })}
            </th>
            <th className="py-2 pr-3 text-right font-medium">
              {t('normExpansion.col_materials', { defaultValue: 'Materials' })}
            </th>
            <th className="py-2 pl-1" />
          </tr>
        </thead>
        <tbody>
          {visible.map((n) => {
            const isOpen = expandedId === n.id;
            return (
              <Fragment key={n.id}>
                <tr className="border-b border-border-light/60 hover:bg-surface-secondary/40">
                  <td className="py-2 pr-1">
                    <button
                      type="button"
                      onClick={() => setExpandedId(isOpen ? null : n.id)}
                      className="rounded p-1 text-content-tertiary hover:bg-surface-secondary"
                      aria-label={t('normExpansion.toggle_materials', {
                        defaultValue: 'Show materials',
                      })}
                      aria-expanded={isOpen}
                    >
                      {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </button>
                  </td>
                  <td className="py-2 pr-3 font-medium text-content-primary">{n.work_key}</td>
                  <td className="py-2 pr-3 text-content-secondary">{n.name || '-'}</td>
                  <td className="py-2 pr-3 text-content-tertiary">{n.unit}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-content-secondary">
                    {fmtNumber(n.labor_hours_per_unit, 3)}
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums text-content-secondary">
                    {fmtNumber(n.machine_hours_per_unit, 3)}
                  </td>
                  <td className="py-2 pr-3 text-right">
                    <Badge variant="neutral">{n.materials.length}</Badge>
                  </td>
                  <td className="py-2 pl-1 text-right">
                    <button
                      type="button"
                      onClick={() => deleteMut.mutate(n.id)}
                      className="rounded p-1 text-content-tertiary hover:bg-red-50 hover:text-semantic-error dark:hover:bg-red-900/20"
                      aria-label={t('normExpansion.delete_norm', { defaultValue: 'Delete norm' })}
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
                {isOpen && (
                  <tr>
                    <td colSpan={8} className="p-0">
                      <MaterialEditor norm={n} onChanged={onChanged} />
                    </td>
                  </tr>
                )}
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

/* ── Main page ─────────────────────────────────────────────────────────── */

export function NormExpansionPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);

  const {
    data: norms = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: NORMS_KEY,
    queryFn: () => fetchNorms(),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: NORMS_KEY });

  return (
    <div className="space-y-6">
      <PageHeader
        srTitle={t('normExpansion.title', { defaultValue: 'Production-Norm Expansion' })}
        subtitle={t('normExpansion.subtitle', {
          defaultValue:
            'Expand a work item into the labor-hours, machine-hours and material takeoff behind its rate, from a library of production-norm coefficients, before any pricing.',
        })}
        actions={
          <Button variant="primary" size="sm" onClick={() => setShowCreate((v) => !v)}>
            <Plus size={16} className="mr-1.5 shrink-0" />
            {t('normExpansion.new_norm', { defaultValue: 'New norm' })}
          </Button>
        }
      />

      {isLoading ? (
        <SkeletonTable rows={4} columns={5} />
      ) : isError ? (
        <RecoveryCard error={error} onRetry={() => refetch()} />
      ) : (
        <>
          <HowNormsWork />

          {norms.length > 0 && (
            <>
              <ExpandPanel norms={norms} />
              <BuildAssemblyPanel norms={norms} />
            </>
          )}

          <Card padding="md">
            <h2 className="mb-3 text-sm font-semibold text-content-primary">
              {t('normExpansion.library', { defaultValue: 'Norm library' })}
              {norms.length > 0 ? ` (${norms.length})` : ''}
            </h2>
            {showCreate && (
              <div className="mb-3">
                <CreateNormForm
                  onCreated={() => {
                    invalidate();
                    setShowCreate(false);
                  }}
                />
              </div>
            )}
            <NormLibrary norms={norms} onChanged={invalidate} />
          </Card>
        </>
      )}
    </div>
  );
}
