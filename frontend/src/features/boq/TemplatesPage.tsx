// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight,
  Building2,
  Factory,
  GraduationCap,
  Hospital,
  Hotel,
  Landmark,
  ShoppingBag,
  Warehouse,
  Check,
  Loader2,
} from 'lucide-react';
import { Button, Badge, Breadcrumb, DismissibleInfo } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useToastStore } from '@/stores/useToastStore';
import { apiGet, apiPost, ApiError } from '@/shared/lib/api';
import { fmtNumber } from '@/shared/lib/formatters';
import { useDisplayQuantity } from '@/shared/hooks/useDisplayQuantity';
import { parseDecimalInput } from '@/shared/lib/parseDecimal';
import { projectsApi, type Project } from '@/features/projects/api';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import type { BOQ } from './api';

/* ── Types ──────────────────────────────────────────────────────────── */

interface TemplatePosition {
  ordinal: string;
  description: string;
  unit: string;
  rate_per_m2: number;
  section: string;
}

interface BOQTemplate {
  id: string;
  name: string;
  description: string;
  building_type: string;
  icon: string;
  sections: number;
  positions: number;
  avg_cost_per_m2: number;
  template_positions: TemplatePosition[];
}

interface CreateFromTemplateData {
  template_id: string;
  project_id: string;
  boq_name?: string;
  area_m2: number;
}

/* ── Icon mapping ───────────────────────────────────────────────────── */

const ICON_MAP: Record<string, React.ReactNode> = {
  residential: <Building2 size={28} strokeWidth={1.5} />,
  office: <Landmark size={28} strokeWidth={1.5} />,
  warehouse: <Warehouse size={28} strokeWidth={1.5} />,
  school: <GraduationCap size={28} strokeWidth={1.5} />,
  hospital: <Hospital size={28} strokeWidth={1.5} />,
  hotel: <Hotel size={28} strokeWidth={1.5} />,
  retail: <ShoppingBag size={28} strokeWidth={1.5} />,
  infrastructure: <Factory size={28} strokeWidth={1.5} />,
};

/* ── Fallback templates (used when API returns 404) ─────────────────── */

const FALLBACK_TEMPLATES: BOQTemplate[] = [
  {
    id: 'tpl_residential',
    name: 'Residential Building',
    description: 'Multi-story residential with standard finishes, MEP, and exterior works',
    building_type: 'residential',
    icon: 'residential',
    sections: 9,
    positions: 35,
    avg_cost_per_m2: 1250,
    template_positions: [
      { ordinal: '01', description: 'Earthworks & Foundations', unit: '', rate_per_m2: 0, section: '01' },
      { ordinal: '01.01', description: 'Excavation', unit: 'm3', rate_per_m2: 45, section: '01' },
      { ordinal: '01.02', description: 'Foundation concrete C30/37', unit: 'm3', rate_per_m2: 85, section: '01' },
      { ordinal: '01.03', description: 'Foundation reinforcement', unit: 'kg', rate_per_m2: 22, section: '01' },
      { ordinal: '01.04', description: 'Waterproofing membrane', unit: 'm2', rate_per_m2: 18, section: '01' },
      { ordinal: '02', description: 'Structural Frame', unit: '', rate_per_m2: 0, section: '02' },
      { ordinal: '02.01', description: 'Reinforced concrete walls', unit: 'm3', rate_per_m2: 120, section: '02' },
      { ordinal: '02.02', description: 'RC floor slabs', unit: 'm2', rate_per_m2: 95, section: '02' },
      { ordinal: '02.03', description: 'Concrete columns', unit: 'pcs', rate_per_m2: 35, section: '02' },
      { ordinal: '02.04', description: 'Structural steel beams', unit: 'kg', rate_per_m2: 28, section: '02' },
      { ordinal: '03', description: 'Envelope & Facade', unit: '', rate_per_m2: 0, section: '03' },
      { ordinal: '03.01', description: 'External masonry walls', unit: 'm2', rate_per_m2: 65, section: '03' },
      { ordinal: '03.02', description: 'Thermal insulation ETICS', unit: 'm2', rate_per_m2: 42, section: '03' },
      { ordinal: '03.03', description: 'Windows triple-glazed', unit: 'pcs', rate_per_m2: 55, section: '03' },
      { ordinal: '03.04', description: 'Entrance doors', unit: 'pcs', rate_per_m2: 15, section: '03' },
      { ordinal: '04', description: 'Roofing', unit: '', rate_per_m2: 0, section: '04' },
      { ordinal: '04.01', description: 'Flat roof waterproofing', unit: 'm2', rate_per_m2: 38, section: '04' },
      { ordinal: '04.02', description: 'Roof insulation', unit: 'm2', rate_per_m2: 25, section: '04' },
      { ordinal: '04.03', description: 'Roof drainage', unit: 'lm', rate_per_m2: 12, section: '04' },
      { ordinal: '05', description: 'Interior Finishes', unit: '', rate_per_m2: 0, section: '05' },
      { ordinal: '05.01', description: 'Interior partitions drywall', unit: 'm2', rate_per_m2: 35, section: '05' },
      { ordinal: '05.02', description: 'Floor tiling ceramic', unit: 'm2', rate_per_m2: 48, section: '05' },
      { ordinal: '05.03', description: 'Laminate flooring', unit: 'm2', rate_per_m2: 32, section: '05' },
      { ordinal: '05.04', description: 'Wall painting', unit: 'm2', rate_per_m2: 18, section: '05' },
      { ordinal: '05.05', description: 'Suspended ceilings', unit: 'm2', rate_per_m2: 28, section: '05' },
      { ordinal: '06', description: 'Mechanical (HVAC)', unit: '', rate_per_m2: 0, section: '06' },
      { ordinal: '06.01', description: 'Heating system incl. radiators', unit: 'lsum', rate_per_m2: 65, section: '06' },
      { ordinal: '06.02', description: 'Ventilation system', unit: 'lsum', rate_per_m2: 45, section: '06' },
      { ordinal: '07', description: 'Plumbing', unit: '', rate_per_m2: 0, section: '07' },
      { ordinal: '07.01', description: 'Sanitary installations', unit: 'set', rate_per_m2: 55, section: '07' },
      { ordinal: '07.02', description: 'Water supply piping', unit: 'lm', rate_per_m2: 25, section: '07' },
      { ordinal: '07.03', description: 'Drainage piping', unit: 'lm', rate_per_m2: 22, section: '07' },
      { ordinal: '08', description: 'Electrical', unit: '', rate_per_m2: 0, section: '08' },
      { ordinal: '08.01', description: 'Power distribution', unit: 'lsum', rate_per_m2: 55, section: '08' },
      { ordinal: '08.02', description: 'Lighting installation', unit: 'pcs', rate_per_m2: 35, section: '08' },
      { ordinal: '08.03', description: 'Low-voltage systems', unit: 'lsum', rate_per_m2: 22, section: '08' },
      { ordinal: '09', description: 'External Works', unit: '', rate_per_m2: 0, section: '09' },
      { ordinal: '09.01', description: 'Landscaping & paving', unit: 'm2', rate_per_m2: 28, section: '09' },
      { ordinal: '09.02', description: 'Site utilities connections', unit: 'lsum', rate_per_m2: 32, section: '09' },
    ],
  },
  {
    id: 'tpl_office',
    name: 'Office Building',
    description: 'Modern office with open floor plans, raised floors, and advanced MEP',
    building_type: 'office',
    icon: 'office',
    sections: 7,
    positions: 28,
    avg_cost_per_m2: 1480,
    template_positions: [],
  },
  {
    id: 'tpl_warehouse',
    name: 'Warehouse / Logistics',
    description: 'Steel-frame industrial building with concrete slab and basic services',
    building_type: 'warehouse',
    icon: 'warehouse',
    sections: 5,
    positions: 18,
    avg_cost_per_m2: 620,
    template_positions: [],
  },
  {
    id: 'tpl_school',
    name: 'School / Educational',
    description: 'Educational facility with classrooms, assembly hall, and sports areas',
    building_type: 'school',
    icon: 'school',
    sections: 7,
    positions: 22,
    avg_cost_per_m2: 1350,
    template_positions: [],
  },
  {
    id: 'tpl_hospital',
    name: 'Hospital / Healthcare',
    description: 'Healthcare facility with specialized MEP, clean rooms, and medical gas',
    building_type: 'hospital',
    icon: 'hospital',
    sections: 8,
    positions: 25,
    avg_cost_per_m2: 2800,
    template_positions: [],
  },
  {
    id: 'tpl_hotel',
    name: 'Hotel / Hospitality',
    description: 'Multi-story hotel with standard rooms, lobby, restaurant, and spa',
    building_type: 'hotel',
    icon: 'hotel',
    sections: 7,
    positions: 20,
    avg_cost_per_m2: 1650,
    template_positions: [],
  },
  {
    id: 'tpl_retail',
    name: 'Retail / Commercial',
    description: 'Retail space with shopfronts, HVAC, and tenant fit-out allowances',
    building_type: 'retail',
    icon: 'retail',
    sections: 6,
    positions: 18,
    avg_cost_per_m2: 980,
    template_positions: [],
  },
  {
    id: 'tpl_infrastructure',
    name: 'Infrastructure',
    description: 'Civil works including roads, bridges, utilities, and drainage',
    building_type: 'infrastructure',
    icon: 'infrastructure',
    sections: 6,
    positions: 20,
    avg_cost_per_m2: 450,
    template_positions: [],
  },
];

/* ── Number formatters ──────────────────────────────────────────────── */
//
// Per call, not per import. An `Intl.NumberFormat` built at module scope
// reads the language once, when this lazy chunk first loads, and the
// language switcher does not reload the app - so the area beside a template
// kept the separators of whatever language the page opened in.

const fmt = { format: (value: number) => fmtNumber(value, 0) };

const fmtCurrency = { format: (value: number) => fmtNumber(value, 2) };

/* ══════════════════════════════════════════════════════════════════════ */
/*  TemplatesPage                                                       */
/* ══════════════════════════════════════════════════════════════════════ */

export function TemplatesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  // Display-only measurement-system conversion for the benchmark cost-per-area
  // badge. The area INPUT below stays metric-canonical (it is editable and is
  // sent to the backend as `area_m2`), so its label and the generated BOQ-name
  // string deliberately remain in m².
  const q = useDisplayQuantity();
  // "cost per m²" is a reciprocal rate: divide by how many display units one
  // m² becomes so the per-unit figure rescales correctly (e.g. EUR/m² -> EUR/ft²).
  const areaUnitScale = q.convert(1, 'm²').value || 1;
  const areaRateUnit = q.unitFor('m²');

  /* ── State ───────────────────────────────────────────────────────── */

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [area, setArea] = useState('1000');
  const activeProjectId = useActiveProjectId();
  const [projectId, setProjectId] = useState<string>(activeProjectId);
  const [boqName, setBoqName] = useState('');

  // Follow the global project switcher so this page reacts to a project change
  // like the rest of the app, not just at mount.
  useEffect(() => {
    if (activeProjectId && activeProjectId !== projectId) setProjectId(activeProjectId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeProjectId]);

  /* ── Fetch templates from API (fall back to local data) ──────────── */

  // Only a 404 means "this deployment has no template endpoint", which is the
  // case the built-in list exists for. Anything else is a real failure and has
  // to surface: swallowing a 500 or a dropped connection here used to show the
  // built-in templates as if they had come from the server, so a broken backend
  // looked like a working one.
  const {
    data,
    isPending: templatesPending,
    isError: templatesFailed,
    error: templatesError,
    refetch: refetchTemplates,
  } = useQuery({
    queryKey: ['boq-templates'],
    queryFn: async () => {
      try {
        return await apiGet<BOQTemplate[]>('/v1/boq/boqs/templates/');
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          return FALLBACK_TEMPLATES;
        }
        throw err;
      }
    },
    staleTime: 5 * 60 * 1000,
  });
  const templates = data ?? [];

  /* ── Fetch projects for selector ─────────────────────────────────── */

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: () => projectsApi.list(),
    retry: (failCount, error) => {
      if (error instanceof ApiError && error.status === 404) return false;
      return failCount < 3;
    },
    staleTime: 5 * 60_000,
  });

  /* ── Create from template mutation ───────────────────────────────── */

  const createMutation = useMutation({
    mutationFn: (data: CreateFromTemplateData) =>
      apiPost<BOQ>('/v1/boq/boqs/from-template/', data),
    onSuccess: (boq) => {
      queryClient.invalidateQueries({ queryKey: ['boqs'] });
      queryClient.invalidateQueries({ queryKey: ['all-boqs'] });
      addToast({
        type: 'success',
        title: t('boq.template_created', { defaultValue: 'BOQ created from template' }),
      });
      navigate(`/boq/${boq.id}`);
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('boq.template_error', { defaultValue: 'Failed to create BOQ from template' }),
        message: e.message,
      });
    },
  });

  /* ── Derived state ───────────────────────────────────────────────── */

  const selected = useMemo(
    () => templates.find((tpl) => tpl.id === selectedId) ?? null,
    [templates, selectedId],
  );

  const areaNum = parseDecimalInput(area) ?? 1000;

  const estimatedTotal = useMemo(() => {
    if (!selected) return 0;
    return selected.avg_cost_per_m2 * areaNum;
  }, [selected, areaNum]);

  const generatedName = useMemo(() => {
    if (!selected) return '';
    return `${selected.name} - ${fmt.format(areaNum)}m\u00B2`;
  }, [selected, areaNum]);

  /* ── Auto-populate BOQ name when template or area changes ────────── */

  const handleSelectTemplate = useCallback(
    (id: string) => {
      setSelectedId((prev) => (prev === id ? null : id));
      const tpl = templates.find((t) => t.id === id);
      if (tpl) {
        setBoqName(`${tpl.name} - ${fmt.format(areaNum)}m\u00B2`);
      }
    },
    [templates, areaNum],
  );

  const handleAreaChange = useCallback(
    (raw: string) => {
      setArea(raw);
      const val = parseDecimalInput(raw);
      if (val !== null && selected) {
        setBoqName(`${selected.name} - ${fmt.format(val)}m\u00B2`);
      }
    },
    [selected],
  );

  const handleCreate = useCallback(() => {
    if (!selected || !projectId) return;
    createMutation.mutate({
      template_id: selected.id,
      project_id: projectId,
      boq_name: boqName || generatedName || undefined,
      area_m2: areaNum,
    });
  }, [selected, projectId, boqName, generatedName, areaNum, createMutation]);

  /* ── Render ──────────────────────────────────────────────────────── */

  return (
    <div className="space-y-5 animate-fade-in pb-12">
      <Breadcrumb items={[{ label: t('boq.templates', { defaultValue: 'BOQ Templates' }) }]} />
      {/* Canonical top block - module name + icon come from the global top
          bar; the page renders only its subtitle. */}
      <PageHeader
        srTitle={t('boq.templates', { defaultValue: 'BOQ Templates' })}
        subtitle={t('boq.templates_subtitle', {
          defaultValue:
            'Start with a professional template for your building type. Select a template, set the area, and generate a complete BOQ instantly.',
        })}
      />

      <DismissibleInfo
        storageKey="templates"
        title={t('boq_templates.intro_title', { defaultValue: 'Skip the blank-page start on an estimate' })}
        links={[
          { label: t('nav.boq', { defaultValue: 'Bill of Quantities' }), onClick: () => navigate('/boq') },
          { label: t('nav.costs', { defaultValue: 'Cost Database' }), onClick: () => navigate('/costs') },
        ]}
      >
        {t('boq_templates.intro_body', {
          defaultValue:
            'Pick a building type, set the floor area and generate a complete structured BOQ with sections, positions and benchmark rates per square metre. The result opens in the BOQ editor on your chosen project, ready to refine.',
        })}
      </DismissibleInfo>

      {/* The list used to be seeded with the built-in templates, so a failed
          fetch was indistinguishable from a working one. Say which of the two
          is happening instead. */}
      {templatesPending && (
        <div className="flex items-center gap-2 text-content-tertiary text-sm">
          <Loader2 size={14} className="animate-spin" />
          {t('boq_templates.loading', { defaultValue: 'Loading templates' })}
        </div>
      )}

      {templatesFailed && (
        <div className="rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm dark:border-red-900 dark:bg-red-950/40">
          <p className="font-medium text-red-700 dark:text-red-300">
            {t('boq_templates.load_failed', { defaultValue: 'Could not load the templates' })}
          </p>
          <p className="mt-1 text-red-600 dark:text-red-400">
            {templatesError instanceof Error
              ? templatesError.message
              : t('boq_templates.load_failed_generic', {
                  defaultValue: 'The server did not answer.',
                })}
          </p>
          <Button variant="secondary" className="mt-3" onClick={() => void refetchTemplates()}>
            {t('common.retry', { defaultValue: 'Retry' })}
          </Button>
        </div>
      )}

      {/* ── Template grid ────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {templates.map((tpl) => {
          const isSelected = selectedId === tpl.id;
          return (
            <button
              key={tpl.id}
              onClick={() => handleSelectTemplate(tpl.id)}
              className={`
                group relative flex flex-col items-center gap-3 rounded-2xl border-2 px-4 py-6
                text-center transition-all duration-200 cursor-pointer
                ${
                  isSelected
                    ? 'border-oe-blue bg-oe-blue-subtle/40 shadow-md ring-2 ring-oe-blue/20'
                    : 'border-border-light bg-surface-elevated hover:border-content-tertiary hover:bg-surface-secondary hover:shadow-sm'
                }
              `}
            >
              {/* Selection indicator */}
              {isSelected && (
                <div className="absolute top-3 right-3 flex h-5 w-5 items-center justify-center rounded-full bg-oe-blue text-white animate-scale-in">
                  <Check size={12} strokeWidth={3} />
                </div>
              )}

              {/* Icon */}
              <div
                className={`
                  flex h-14 w-14 items-center justify-center rounded-2xl transition-colors duration-200
                  ${
                    isSelected
                      ? 'bg-oe-blue text-white'
                      : 'bg-surface-secondary text-content-tertiary group-hover:bg-surface-tertiary group-hover:text-content-secondary'
                  }
                `}
              >
                {ICON_MAP[tpl.icon] ?? <Building2 size={28} strokeWidth={1.5} />}
              </div>

              {/* Name */}
              <div>
                <p
                  className={`text-sm font-semibold ${isSelected ? 'text-oe-blue' : 'text-content-primary'}`}
                >
                  {tpl.name}
                </p>
                <p className="mt-0.5 text-xs text-content-tertiary">
                  {t('boq.item_count', {
                    count: tpl.positions,
                    defaultValue_one: '{{count}} item',
                    defaultValue_other: '{{count}} items',
                  })}
                </p>
              </div>

              {/* Cost indicator - benchmark rate per unit area (reciprocal). */}
              <Badge variant={isSelected ? 'blue' : 'neutral'} size="sm">
                ~{fmt.format(tpl.avg_cost_per_m2 / areaUnitScale)} EUR/{areaRateUnit}
              </Badge>
            </button>
          );
        })}
      </div>

      {/* ── Configuration panel (shown when template selected) ────────── */}
      {selected && (
        <div className="mt-8 animate-fade-in">
          <div className="rounded-2xl border border-border-light bg-surface-elevated shadow-sm overflow-hidden">
            {/* Panel header */}
            <div className="px-6 pt-6 pb-4 border-b border-border-light bg-surface-tertiary/30">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue text-white">
                  {ICON_MAP[selected.icon] ?? <Building2 size={22} strokeWidth={1.5} />}
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-content-primary">{selected.name}</h2>
                  <p className="text-sm text-content-secondary">{selected.description}</p>
                </div>
              </div>
            </div>

            {/* Panel body */}
            <div className="px-6 py-6 space-y-5">
              {/* Project selector */}
              <div>
                <label className="block text-sm font-medium text-content-primary mb-1.5">
                  {t('boq.project', { defaultValue: 'Project' })}
                </label>
                <select
                  value={projectId}
                  onChange={(e) => setProjectId(e.target.value)}
                  className="w-full rounded-lg border border-border-light bg-surface-elevated px-3.5 py-2.5 text-sm text-content-primary outline-none transition-colors focus:border-oe-blue focus:ring-2 focus:ring-oe-blue/20 appearance-none cursor-pointer"
                >
                  <option value="">
                    {t('boq.select_project', { defaultValue: 'Select a project...' })}
                  </option>
                  {(projects ?? []).map((p: Project) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>

              {/* Area input */}
              <div>
                {/* Editable metric input (sent as area_m2) \u2014 label stays
                    canonical m\u00B2 so the user types the value that is stored. */}
                <label className="block text-sm font-medium text-content-primary mb-1.5">
                  {t('boq.area_m2', { defaultValue: 'Area (m\u00B2)' })}
                </label>
                <input
                  type="text"
                  inputMode="decimal"
                  value={area}
                  onChange={(e) => handleAreaChange(e.target.value)}
                  className="w-full rounded-lg border border-border-light bg-surface-elevated px-3.5 py-2.5 text-sm text-content-primary outline-none transition-colors focus:border-oe-blue focus:ring-2 focus:ring-oe-blue/20 tabular-nums"
                />
              </div>

              {/* BOQ Name */}
              <div>
                <label className="block text-sm font-medium text-content-primary mb-1.5">
                  {t('boq.boq_name', { defaultValue: 'BOQ Name' })}
                </label>
                <input
                  type="text"
                  value={boqName}
                  onChange={(e) => setBoqName(e.target.value)}
                  placeholder={generatedName}
                  className="w-full rounded-lg border border-border-light bg-surface-elevated px-3.5 py-2.5 text-sm text-content-primary placeholder:text-content-tertiary outline-none transition-colors focus:border-oe-blue focus:ring-2 focus:ring-oe-blue/20"
                />
              </div>

              {/* Preview stats */}
              <div className="flex items-center gap-6 rounded-xl bg-surface-secondary px-5 py-4">
                <div>
                  <p className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                    {t('boq.preview', { defaultValue: 'Preview' })}
                  </p>
                  <p className="mt-0.5 text-sm text-content-primary">
                    {selected.sections} {t('boq.sections', { defaultValue: 'sections' })},{' '}
                    {selected.positions} {t('boq.positions', { defaultValue: 'positions' })}
                  </p>
                </div>
                <div className="h-8 w-px bg-border-light" />
                <div>
                  <p className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                    {t('boq.estimated_total', { defaultValue: 'Estimated total' })}
                  </p>
                  <p className="mt-0.5 text-lg font-bold text-content-primary tabular-nums">
                    ~{fmtCurrency.format(estimatedTotal)}{' '}
                    <span className="text-sm font-normal text-content-secondary">EUR</span>
                  </p>
                </div>
              </div>

              {/* Create button */}
              <Button
                variant="primary"
                size="lg"
                icon={
                  createMutation.isPending ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <ArrowRight size={16} />
                  )
                }
                onClick={handleCreate}
                disabled={!projectId || createMutation.isPending}
                className="w-full btn-shimmer"
              >
                {createMutation.isPending
                  ? t('boq.creating', { defaultValue: 'Creating...' })
                  : t('boq.create_from_template', { defaultValue: 'Create BOQ from Template' })}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
