// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useMemo, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Leaf,
  Download,
  Zap,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Info,
  ChevronDown,
  ChevronUp,
  Plus,
  Settings2,
} from 'lucide-react';
import { Breadcrumb, Card, CardHeader, CardContent, Button, EmptyState, Skeleton, DismissibleInfo, IntroRichText, ModuleGuideButton } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { sustainabilityGuide } from './sustainabilityGuide';
import { apiGet } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useNumberLocale } from '@/stores/usePreferencesStore';
import { useDisplayQuantity } from '@/shared/hooks/useDisplayQuantity';
import {
  fetchSustainability,
  enrichCO2,
  assignPositionCO2,
  fetchEPDMaterials,
  createOwnMaterial,
  isDecimalString,
  type SustainabilityData,
  type PositionCO2Detail,
  type EPDMaterial,
} from './api';
import { fmtPercent, fmtFixed } from '@/shared/lib/formatters';

/* ── Types ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
  description: string;
  currency: string;
}

interface BOQ {
  id: string;
  project_id: string;
  name: string;
  status: string;
}

/* ── Helpers ────────────────────────────────────────────────────────── */

function ratingColor(rating: string): string {
  switch (rating) {
    case 'A': return '#16a34a';
    case 'B': return '#2563eb';
    case 'C': return '#ca8a04';
    case 'D': return '#dc2626';
    default: return '#6b7280';
  }
}

function complianceStyle(level: string, t: (key: string, opts?: Record<string, unknown>) => string) {
  switch (level) {
    case 'excellent': return { bg: 'bg-semantic-success-bg', text: 'text-semantic-success', Icon: CheckCircle2, label: t('sustainability.compliance_excellent', { defaultValue: 'Excellent' }) };
    case 'good': return { bg: 'bg-semantic-success-bg', text: 'text-semantic-success', Icon: CheckCircle2, label: t('sustainability.compliance_good', { defaultValue: 'Good' }) };
    case 'acceptable': return { bg: 'bg-semantic-warning-bg', text: 'text-semantic-warning', Icon: AlertTriangle, label: t('sustainability.compliance_acceptable', { defaultValue: 'Acceptable' }) };
    case 'non-compliant': return { bg: 'bg-semantic-error-bg', text: 'text-semantic-error', Icon: XCircle, label: t('sustainability.compliance_non_compliant', { defaultValue: 'Non-Compliant' }) };
    default: return { bg: 'bg-surface-secondary', text: 'text-content-secondary', Icon: Info, label: t('sustainability.compliance_na', { defaultValue: 'N/A' }) };
  }
}

const DONUT_COLORS = [
  '#2563eb', '#dc2626', '#16a34a', '#ca8a04', '#7c3aed',
  '#0891b2', '#ea580c', '#6366f1', '#be185d', '#065f46', '#9333ea',
];

/* ── Donut Chart ───────────────────────────────────────────────────── */

function DonutChart({ data }: { data: { label: string; value: number; pct: number }[] }) {
  const { t } = useTranslation();
  const size = 180;
  const cx = size / 2, cy = size / 2;
  const outerR = 80, innerR = 52;

  const segments = useMemo(() => {
    let cumulative = 0;
    return data.map((item, i) => {
      const startAngle = cumulative * 3.6;
      cumulative += item.pct;
      const endAngle = cumulative * 3.6;
      return { ...item, startAngle, endAngle, color: DONUT_COLORS[i % DONUT_COLORS.length] };
    });
  }, [data]);

  function polar(r: number, deg: number) {
    const rad = ((deg - 90) * Math.PI) / 180;
    return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
  }

  function arc(s: number, e: number) {
    const sweep = Math.min(e - s, 359.999);
    const large = sweep > 180 ? 1 : 0;
    const os = polar(outerR, s), oe = polar(outerR, s + sweep);
    const is_ = polar(innerR, s + sweep), ie = polar(innerR, s);
    return `M ${os.x} ${os.y} A ${outerR} ${outerR} 0 ${large} 1 ${oe.x} ${oe.y} L ${is_.x} ${is_.y} A ${innerR} ${innerR} 0 ${large} 0 ${ie.x} ${ie.y} Z`;
  }

  if (!segments.length) return null;

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0">
      {segments.map((seg) => (
        <path key={seg.label} d={arc(seg.startAngle, seg.endAngle)} fill={seg.color} />
      ))}
      <circle cx={cx} cy={cy} r={innerR - 1} fill="var(--color-surface-primary, white)" />
      <text x={cx} y={cy - 4} textAnchor="middle" fontSize={11} className="fill-content-tertiary" fontFamily="system-ui">CO2e</text>
      <text x={cx} y={cy + 12} textAnchor="middle" fontSize={14} fontWeight="bold" className="fill-content-primary" fontFamily="system-ui">{segments.length}</text>
      <text x={cx} y={cy + 24} textAnchor="middle" fontSize={9} className="fill-content-tertiary" fontFamily="system-ui">{t('sustainability.donut_categories', { defaultValue: 'categories' })}</text>
    </svg>
  );
}

/* ── EPD Dropdown ──────────────────────────────────────────────────── */

function EPDSelect({
  currentId,
  materials,
  onSelect,
  disabled,
}: {
  currentId: string | null;
  materials: EPDMaterial[];
  onSelect: (epdId: string) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <select
      value={currentId || ''}
      onChange={(e) => { if (e.target.value) onSelect(e.target.value); }}
      disabled={disabled}
      aria-label={t('sustainability.epd_material_select', { defaultValue: 'Select EPD material' })}
      className="oe-select oe-input-sm max-w-[220px] truncate"
    >
      <option value="">{t('sustainability.epd_none', { defaultValue: '-- none --' })}</option>
      {materials.some((m) => m.own) && (
        <optgroup label={t('sustainability.own_materials_group', { defaultValue: 'My materials' })}>
          {materials.filter((m) => m.own).map((m) => (
            <option key={m.id} value={m.id}>{m.name} ({m.gwp} kg/{m.unit})</option>
          ))}
        </optgroup>
      )}
      <optgroup label={t('sustainability.reference_materials_group', { defaultValue: 'Reference library' })}>
        {materials.filter((m) => !m.own).map((m) => (
          <option key={m.id} value={m.id}>
            {m.name} ({m.gwp} kg/{m.unit})
          </option>
        ))}
      </optgroup>
    </select>
  );
}

/* ── Own material: toolbar + quick form ────────────────────────────── */

function OwnMaterialBar({
  categories,
  ownCount,
  onManage,
}: {
  categories: { id: string; label: string }[];
  ownCount: number;
  onManage: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [category, setCategory] = useState(categories[0]?.id ?? 'concrete');
  const [unit, setUnit] = useState('m3');
  const [gwp, setGwp] = useState('');
  const gwpValid = isDecimalString(gwp);
  const canSave = name.trim().length > 0 && unit.trim().length > 0 && gwpValid;

  const saveMut = useMutation({
    mutationFn: () => createOwnMaterial({ name: name.trim(), category, unit: unit.trim(), gwp: gwp.trim() }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['epd-materials'] });
      addToast({ type: 'success', title: t('sustainability.own_saved', { defaultValue: 'Material added. Pick it in the EPD Material column.' }) });
      setName('');
      setGwp('');
      setOpen(false);
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('sustainability.own_save_failed', { defaultValue: 'Could not save the material' }), message: err.message });
    },
  });

  return (
    <div className="mb-3 rounded-lg border border-border-light bg-surface-secondary p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={() => setOpen((v) => !v)}>
          {t('sustainability.own_add', { defaultValue: 'Add own material' })}
        </Button>
        <Button variant="ghost" size="sm" icon={<Settings2 size={14} />} onClick={onManage}>
          {t('sustainability.own_manage', { defaultValue: 'Manage materials' })}
        </Button>
        {ownCount === 0 && !open && (
          <span className="text-xs text-content-tertiary">
            {t('sustainability.own_empty_hint', {
              defaultValue: 'Missing a product? Add it with its EPD value (kg CO2e per unit) and pick it for any position. Edit or delete it later under Carbon & ESG, EPDs.',
            })}
          </span>
        )}
      </div>
      {open && (
        <form
          className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-5 sm:items-end"
          onSubmit={(e) => { e.preventDefault(); if (canSave) saveMut.mutate(); }}
        >
          <label className="sm:col-span-2 text-xs text-content-secondary">
            {t('sustainability.own_name', { defaultValue: 'Material name' })}
            <input className="oe-input oe-input-sm mt-1 w-full" value={name} onChange={(e) => setName(e.target.value)} maxLength={500} required />
          </label>
          <label className="text-xs text-content-secondary">
            {t('sustainability.col_category', { defaultValue: 'Category' })}
            <select className="oe-select oe-input-sm mt-1 w-full" value={category} onChange={(e) => setCategory(e.target.value)}>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>{t(`sustainability.cat_${c.id}`, { defaultValue: c.label })}</option>
              ))}
            </select>
          </label>
          <label className="text-xs text-content-secondary">
            {t('sustainability.col_unit', { defaultValue: 'Unit' })}
            <input className="oe-input oe-input-sm mt-1 w-full" value={unit} onChange={(e) => setUnit(e.target.value)} maxLength={20} required />
          </label>
          <label className="text-xs text-content-secondary">
            {t('sustainability.own_gwp', { defaultValue: 'GWP A1-A3 (kg CO2e per unit)' })}
            <input
              className="oe-input oe-input-sm mt-1 w-full tabular-nums"
              inputMode="decimal"
              value={gwp}
              onChange={(e) => setGwp(e.target.value.replace(',', '.'))}
              aria-invalid={gwp !== '' && !gwpValid}
              required
            />
          </label>
          <div className="sm:col-span-5 flex gap-2">
            <Button type="submit" variant="primary" size="sm" disabled={!canSave} loading={saveMut.isPending}>
              {t('common.save', { defaultValue: 'Save' })}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(false)}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────── */

export function SustainabilityPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // Issue #270 - measurement-system-aware display. Embodied-carbon MASS stays in
  // the domain-standard kg / t CO2e (EN 15804 / EU CPR use these identically in
  // metric and imperial markets, so converting to lb/ton would misrepresent the
  // figures). What DOES follow the preference is the AREA dimension: the per-m2
  // benchmark + EU-CPR rates convert RECIPROCALLY (kg/m2 -> kg/ft2), and each
  // BOQ position quantity converts as an ABSOLUTE (its own unit), with its GWP
  // per-unit rate converted reciprocally so per-unit x qty still equals the kg
  // total. The GFA INPUT stays metric/editable (m2) and is never converted.
  const q = useDisplayQuantity();
  const areaUnit = q.unitFor('m²');
  // Reciprocal area factor (1 metric, 10.7639 imperial) for "per m2" rates.
  const areaRateFactor = q.convert(1, 'm²').value;
  // The user's number locale (replaces the previously hardcoded de-DE so CO2
  // figures group/decimal the way the rest of the user's app does). Through
  // the shared resolver, which follows the UI language until the reader picks
  // a format of their own.
  const numberLocale = useNumberLocale();
  const [searchParams, setSearchParams] = useSearchParams();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  // Deep-link preselect (e.g. from the BOQ toolbar "Carbon footprint" action:
  // /sustainability?project_id=&boq_id=) wins on mount; otherwise start from the
  // globally selected project so the page is never blank for someone who picked
  // a project in the top bar.
  const [selectedProjectId, setSelectedProjectId] = useState(
    () => searchParams.get('project_id') ?? activeProjectId ?? '',
  );
  const [selectedBoqId, setSelectedBoqId] = useState(
    () => searchParams.get('boq_id') ?? '',
  );
  const [areaM2, setAreaM2] = useState(2000);
  const [calculated, setCalculated] = useState(false);
  const [showAllPositions, setShowAllPositions] = useState(false);
  // Guards the one-shot auto-calculate so a user who later changes the
  // selectors isn't force-recalculated against the original deep-link.
  const autoCalcDone = useRef(false);

  // Follow the global project switcher. Skip the first run so a
  // ?project_id= deep link survives mount (the initial state above already
  // honoured the global selection when there was no deep link); afterwards
  // the effect fires only when the top-bar selection changes, so an in-page
  // pick is preserved while switching project globally re-scopes this page
  // too (fixes "selection only affects one tab").
  const projectSyncMounted = useRef(false);
  useEffect(() => {
    if (!projectSyncMounted.current) {
      projectSyncMounted.current = true;
      return;
    }
    if (activeProjectId && activeProjectId !== selectedProjectId) {
      setSelectedProjectId(activeProjectId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeProjectId]);

  // Projects & BOQs
  const { data: projects, isLoading: projectsLoading } = useQuery({
    queryKey: ['projects'],
    // No catch to an empty list: this entry is shared with the header switcher,
    // which would read a cached [] as "every project is gone". A failed read
    // leaves the data undefined, which this page already treats as no projects.
    queryFn: () => fetchProjectList<Project[]>(),
    staleTime: 5 * 60_000,
  });
  const { data: boqs, isLoading: boqsLoading } = useQuery({
    queryKey: ['boqs', selectedProjectId],
    queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${selectedProjectId}`).catch(() => []),
    enabled: !!selectedProjectId,
  });

  // Sustainability data
  const { data: sustainability, isLoading: sustainLoading, refetch } = useQuery({
    queryKey: ['sustainability', selectedBoqId, areaM2],
    queryFn: () => fetchSustainability(selectedBoqId, areaM2),
    enabled: false,
  });

  // When the page is opened deep-linked with project_id + boq_id, run the
  // analysis automatically once the BOQ list confirms the BOQ exists. After
  // it fires we strip the params and never auto-run again, so manual changes
  // to the selectors behave normally.
  useEffect(() => {
    if (autoCalcDone.current) return;
    if (!selectedProjectId || !selectedBoqId) return;
    // Wait until the project's BOQs have loaded; only auto-calculate when the
    // linked BOQ is genuinely present (avoids a request for a stale id).
    if (boqsLoading) return;
    const exists = (boqs ?? []).some((b) => b.id === selectedBoqId);
    if (!exists) {
      autoCalcDone.current = true;
      if (searchParams.has('project_id') || searchParams.has('boq_id')) {
        setSearchParams({}, { replace: true });
      }
      return;
    }
    autoCalcDone.current = true;
    setCalculated(true);
    refetch();
    if (searchParams.has('project_id') || searchParams.has('boq_id')) {
      setSearchParams({}, { replace: true });
    }
  }, [
    selectedProjectId,
    selectedBoqId,
    boqs,
    boqsLoading,
    refetch,
    searchParams,
    setSearchParams,
  ]);

  // EPD materials for dropdown
  const { data: epdData } = useQuery({
    queryKey: ['epd-materials'],
    queryFn: () => fetchEPDMaterials(),
  });
  const epdMaterials = epdData?.materials || [];
  const epdCategories = epdData?.categories || [];
  const ownMaterialCount = epdMaterials.filter((m) => m.own).length;

  // Enrich mutation
  const enrichMut = useMutation({
    mutationFn: () => enrichCO2(selectedBoqId),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['sustainability'] });
      refetch();
      addToast({ type: 'success', title: t('sustainability.enrich_success', { defaultValue: 'CO2 enriched: {{enriched}} positions ({{skipped}} skipped)', enriched: res.enriched, skipped: res.skipped }) });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('sustainability.enrich_failed', { defaultValue: 'CO2 enrichment failed' }), message: err.message });
    },
  });

  // Assign CO2 mutation
  const assignMut = useMutation({
    mutationFn: ({ posId, epdId }: { posId: string; epdId: string }) =>
      assignPositionCO2(posId, epdId),
    onSuccess: () => {
      refetch();
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('sustainability.assign_failed', { defaultValue: 'Failed to assign CO2 data' }), message: err.message });
    },
  });

  function handleCalculate() {
    if (!selectedBoqId) return;
    setCalculated(true);
    refetch();
  }

  const data: SustainabilityData | undefined = calculated ? sustainability : undefined;
  const cpr = data?.eu_cpr_compliance ? complianceStyle(data.eu_cpr_compliance, t) : null;

  // Positions to display (limit to 20 unless expanded)
  const visiblePositions: PositionCO2Detail[] = useMemo(() => {
    if (!data?.positions_detail) return [];
    const sorted = [...data.positions_detail].sort((a, b) => Math.abs(b.gwp_total) - Math.abs(a.gwp_total));
    return showAllPositions ? sorted : sorted.slice(0, 20);
  }, [data, showAllPositions]);

  const dataQualityLabel = data?.data_quality === 'enriched'
    ? t('sustainability.quality_enriched', { defaultValue: 'Enriched (stored)' })
    : data?.data_quality === 'mixed'
    ? t('sustainability.quality_mixed', { defaultValue: 'Mixed (stored + auto)' })
    : t('sustainability.quality_estimated', { defaultValue: 'Estimated (auto-detected)' });

  // Client-side CSV export of the loaded CO2 analysis (header summary +
  // category breakdown + position-level detail). No server round-trip.
  function handleExportCsv() {
    if (!data) return;
    try {
      const csvCell = (val: string | number | null | undefined): string => {
        const s = val === null || val === undefined ? '' : String(val);
        return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
      };
      const lines: string[] = [];
      // Issue #270 - this write-only CSV honours the measurement system at the
      // export boundary. CO2 mass columns (total_co2_tons, co2_kg, gwp_total_kg)
      // stay in the EN 15804 standard kg/t. Physical quantities convert as
      // ABSOLUTE values (with their unit relabelled); the benchmark and the GWP
      // per-unit columns are "per area/per unit" RATES converted RECIPROCALLY so
      // per-unit x qty still equals the kg total.
      lines.push(['section', 'key', 'value'].join(','));
      lines.push(['summary', 'total_co2_tons', data.total_co2_tons].map(csvCell).join(','));
      // RATE (reciprocal): kg CO2 per m2 -> per ft2. Header carries the unit.
      lines.push(
        ['summary', `benchmark_per_${areaUnit}_kg`, data.benchmark_per_m2 != null ? data.benchmark_per_m2 / areaRateFactor : '']
          .map(csvCell)
          .join(','),
      );
      lines.push(['summary', 'rating', data.rating].map(csvCell).join(','));
      lines.push(['summary', 'eu_cpr_compliance', data.eu_cpr_compliance].map(csvCell).join(','));
      lines.push('');
      // Breakdown by category. quantity = ABSOLUTE (convert), co2_kg stays kg.
      lines.push(['breakdown', 'material', 'category', 'quantity', 'unit', 'co2_kg', 'percentage'].join(','));
      for (const b of data.breakdown) {
        const bq = q.convert(Number(b.quantity), b.unit); // ABSOLUTE
        lines.push(
          ['breakdown', b.material, b.category, bq.value, bq.unit, b.co2_kg, b.percentage]
            .map(csvCell)
            .join(','),
        );
      }
      lines.push('');
      // Position-level detail. quantity = ABSOLUTE (convert); gwp_per_unit =
      // RATE per the position unit (reciprocal); gwp_total stays kg.
      lines.push(
        ['position', 'ordinal', 'description', 'quantity', 'unit', 'epd_material', 'gwp_per_unit', 'gwp_total_kg', 'category', 'source'].join(','),
      );
      for (const p of data.positions_detail) {
        const pq = q.convert(Number(p.quantity), p.unit); // ABSOLUTE
        const unitFactor = q.convert(1, p.unit).value; // 1 unless p.unit is convertible
        const gwpPerUnit = p.gwp_per_unit / unitFactor; // RATE (reciprocal)
        lines.push(
          ['position', p.ordinal, p.description, pq.value, pq.unit, p.epd_name ?? '', gwpPerUnit, p.gwp_total, p.category, p.source]
            .map(csvCell)
            .join(','),
        );
      }
      const csv = lines.join('\r\n');
      // Prepend a UTF-8 BOM so Excel opens non-ASCII material names correctly.
      const blob = new Blob(['\uFEFF', csv], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'co2-report.csv';
      document.body.appendChild(a);
      a.click();
      setTimeout(() => {
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }, 200);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      addToast({ type: 'error', title: t('sustainability.export_failed', { defaultValue: 'Could not export CO2 report' }), message });
    }
  }

  const selectedProject = projects?.find((p) => p.id === selectedProjectId);

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(selectedProject
            ? [{ label: selectedProject.name, to: `/projects/${selectedProject.id}` }]
            : []),
          { label: t('nav.sustainability', { defaultValue: 'Sustainability' }) },
        ]}
      />
      <PageHeader
        srTitle={t('nav.sustainability', { defaultValue: 'Sustainability' })}
        subtitle={t('sustainability.subtitle', 'Embodied carbon analysis based on EPD data (EN 15804, A1-A3)')}
        actions={<ModuleGuideButton content={sustainabilityGuide} />}
      />

      <DismissibleInfo
        storageKey="sustainability"
        title={t('sustainability.intro_title', {
          defaultValue: "Read a BOQ's carbon footprint position by position",
        })}
        more={t('sustainability.intro_more', { defaultValue: '' }) ? <IntroRichText text={t('sustainability.intro_more')} /> : undefined}
        links={[
          { label: t('sustainability.intro_link_carbon', { defaultValue: 'Carbon & ESG' }), onClick: () => navigate('/carbon') },
          { label: t('sustainability.intro_link_boq', { defaultValue: 'Open BOQ' }), onClick: () => navigate('/boq') },
        ]}
      >
        {t('sustainability.intro_body', {
          defaultValue:
            'Select a project and BOQ, enrich it with EPD material factors, then calculate to see total CO2, a per-square-metre benchmark and a breakdown by material category down to each position. Export the CO2 report as PDF or CSV. This is the per-BOQ view; the Carbon module holds full inventories, scopes, targets and standards reporting.',
        })}
      </DismissibleInfo>

      {/* Selectors */}
      <Card>
        <CardContent>
          <div className="flex flex-wrap items-end gap-4">
            <div className="flex-1 min-w-[200px]">
              <label htmlFor="sust-project-select" className="oe-label tracking-wider">
                {t('sustainability.project', 'Project')}
              </label>
              <select
                id="sust-project-select"
                value={selectedProjectId}
                onChange={(e) => { setSelectedProjectId(e.target.value); setSelectedBoqId(''); setCalculated(false); }}
                disabled={projectsLoading}
                className="oe-select"
              >
                <option value="">{projectsLoading ? t('common.loading', 'Loading...') : t('sustainability.select_project', '-- Select project --')}</option>
                {projects?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
            <div className="flex-1 min-w-[200px]">
              <label htmlFor="sust-boq-select" className="oe-label tracking-wider">
                {t('sustainability.boq', 'BOQ')}
              </label>
              <select
                id="sust-boq-select"
                value={selectedBoqId}
                onChange={(e) => { setSelectedBoqId(e.target.value); setCalculated(false); }}
                disabled={!selectedProjectId || boqsLoading}
                className="oe-select"
              >
                <option value="">{boqsLoading ? t('common.loading', 'Loading...') : t('sustainability.select_boq', '-- Select BOQ --')}</option>
                {boqs?.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </div>
            <div className="min-w-[140px]">
              <label htmlFor="sust-gfa-input" className="oe-label tracking-wider">
                {t('sustainability.area', 'GFA (m2)')}
              </label>
              <input
                id="sust-gfa-input"
                type="number" value={areaM2} onChange={(e) => setAreaM2(Number(e.target.value) || 0)}
                min={0} step={100}
                className="oe-input tabular-nums"
              />
            </div>
            <Button variant="secondary" size="md" icon={<Zap size={16} />}
              onClick={() => enrichMut.mutate()} disabled={!selectedBoqId} loading={enrichMut.isPending}>
              {t('sustainability.enrich', 'Enrich CO2')}
            </Button>
            <Button variant="primary" size="md" icon={<Leaf size={16} />}
              onClick={handleCalculate} disabled={!selectedBoqId} loading={sustainLoading}>
              {t('sustainability.calculate', 'Calculate')}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Loading */}
      {sustainLoading && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <Skeleton height={160} className="w-full" rounded="lg" />
          <Skeleton height={160} className="w-full" rounded="lg" />
          <Skeleton height={160} className="w-full" rounded="lg" />
        </div>
      )}

      {/* Results */}
      {data && !sustainLoading && (
        <div className="space-y-6 animate-fade-in">
          {/* KPI Cards */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            {/* Total CO2 + Rating */}
            <Card padding="none">
              <div className="p-5">
                <div className="text-xs font-medium uppercase tracking-wider text-content-tertiary mb-2">
                  {t('sustainability.total_co2', 'Total Embodied Carbon')}
                </div>
                <div className="flex items-baseline gap-2 mb-2">
                  <span className="text-3xl font-semibold tabular-nums text-content-primary">
                    {/* ABSOLUTE CO2 mass - kept in t CO2e (EN 15804 standard) */}
                    {data.total_co2_tons.toLocaleString(numberLocale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
                  </span>
                  <span className="text-lg text-content-secondary">t CO2e</span>
                </div>
                {data.rating && (
                  <div className="flex items-center gap-3 mb-2">
                    <div className="flex h-11 w-11 items-center justify-center rounded-xl text-xl font-semibold text-white"
                      style={{ backgroundColor: ratingColor(data.rating) }}>{data.rating}</div>
                    <div>
                      <div className="text-sm font-semibold text-content-primary">{data.rating_label}</div>
                      {/* RATE (reciprocal): kg CO2 per m2 -> per ft2 for imperial; mass stays kg */}
                      {data.benchmark_per_m2 != null && (
                        <div className="text-xs text-content-tertiary">
                          {(data.benchmark_per_m2 / areaRateFactor).toLocaleString(numberLocale, { maximumFractionDigits: 1 })} kg CO2/{areaUnit}
                        </div>
                      )}
                    </div>
                  </div>
                )}
                <div className="text-xs text-content-tertiary">
                  {data.positions_matched}/{data.positions_analyzed} {t('sustainability.positions_matched', 'positions matched')}
                  {' '}&middot; {data.lifecycle_stages}
                </div>
              </div>
            </Card>

            {/* EU CPR Compliance */}
            <Card padding="none">
              <div className="p-5">
                <div className="text-xs font-medium uppercase tracking-wider text-content-tertiary mb-2">
                  {t('sustainability.eu_cpr_title', { defaultValue: 'EU CPR 2024/3110' })}
                </div>
                {cpr ? (
                  <div className={`rounded-lg p-4 ${cpr.bg}`}>
                    <div className="flex items-center gap-2 mb-2">
                      <cpr.Icon size={20} className={cpr.text} />
                      <span className={`text-lg font-bold ${cpr.text}`}>{cpr.label}</span>
                    </div>
                    <div className="text-sm text-content-secondary">
                      {/* RATE (reciprocal): kg CO2e per m2 per year -> per ft2/yr; mass + time stay */}
                      {data.eu_cpr_gwp_per_m2_year != null
                        ? fmtFixed(data.eu_cpr_gwp_per_m2_year / areaRateFactor, 2)
                        : data.eu_cpr_gwp_per_m2_year}{' '}
                      kg CO2e/{areaUnit}/yr
                    </div>
                    <div className="text-xs text-content-tertiary mt-1">{t('sustainability.rsp_label', { defaultValue: '50-year RSP' })}</div>
                  </div>
                ) : (
                  <p className="text-sm text-content-secondary">
                    {t('sustainability.no_area', 'Enter GFA to see EU CPR compliance')}
                  </p>
                )}
              </div>
            </Card>

            {/* Data Quality */}
            <Card padding="none">
              <div className="p-5">
                <div className="text-xs font-medium uppercase tracking-wider text-content-tertiary mb-2">
                  {t('sustainability.data_quality', 'Data Quality')}
                </div>
                <div className="text-lg font-semibold text-content-primary mb-1">{dataQualityLabel}</div>
                <div className="text-sm text-content-secondary mb-3">
                  {t('sustainability.positions_with_data', { defaultValue: '{{matched}} / {{total}} positions with CO2 data', matched: data.positions_matched, total: data.positions_analyzed })}
                </div>
                {data.positions_analyzed > 0 && (
                  <div className="w-full h-2 rounded-full bg-border-light overflow-hidden">
                    <div className="h-full rounded-full bg-semantic-success transition-all"
                      style={{ width: `${(data.positions_matched / data.positions_analyzed) * 100}%` }} />
                  </div>
                )}
                <div className="text-xs text-content-tertiary mt-2">
                  {t('sustainability.sources', { defaultValue: 'Sources: OKOBAUDAT, ICE v3.0, EU Level(s)' })}
                </div>
              </div>
            </Card>
          </div>

          {/* Breakdown by Category */}
          {data.breakdown.length > 0 && (
            <Card>
              <CardHeader title={t('sustainability.breakdown_title', 'Breakdown by Material Category')} />
              <CardContent>
                <div className="flex flex-col lg:flex-row items-start gap-8">
                  <DonutChart
                    data={data.breakdown.map((b) => ({ label: b.material, value: b.co2_kg, pct: b.percentage }))}
                  />
                  <div className="flex-1 min-w-0">
                    <table className="oe-table">
                      <thead>
                        <tr>
                          <th className="pr-4">{t('sustainability.col_category', { defaultValue: 'Category' })}</th>
                          <th className="text-right">{t('sustainability.col_positions', { defaultValue: 'Positions' })}</th>
                          <th className="text-right">%</th>
                          <th className="pl-4 text-right">{t('sustainability.col_co2', { defaultValue: 'CO2 (t)' })}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.breakdown.map((item, i) => (
                          <tr key={item.category}>
                            <td className="pr-4">
                              <div className="flex items-center gap-2">
                                <div className="h-3 w-3 rounded-sm shrink-0" style={{ backgroundColor: DONUT_COLORS[i % DONUT_COLORS.length] }} />
                                <span className="text-content-primary font-medium">{item.material}</span>
                              </div>
                            </td>
                            <td className="text-right tabular-nums text-content-secondary">{item.positions_count}</td>
                            <td className="text-right tabular-nums text-content-secondary">{fmtPercent(item.percentage)}</td>
                            <td className="pl-4 text-right tabular-nums">
                              {/* ABSOLUTE CO2 mass - kept in t CO2e (EN 15804 standard) */}
                              {(item.co2_kg / 1000).toLocaleString(numberLocale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} t
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Positions Detail Table */}
          {data.positions_detail.length > 0 && (
            <Card>
              <CardHeader title={t('sustainability.positions_title', 'Position-Level CO2 Data')} />
              <CardContent>
                <OwnMaterialBar
                  categories={epdCategories}
                  ownCount={ownMaterialCount}
                  onManage={() => navigate('/carbon?tab=epds')}
                />
                <div className="overflow-x-auto">
                  <table className="oe-table">
                    <thead>
                      <tr>
                        <th className="pr-3 w-[60px]">#</th>
                        <th>{t('sustainability.col_description', { defaultValue: 'Description' })}</th>
                        <th className="text-right w-[80px]">{t('sustainability.col_qty', { defaultValue: 'Qty' })}</th>
                        <th className="text-center w-[50px]">{t('sustainability.col_unit', { defaultValue: 'Unit' })}</th>
                        <th className="w-[220px]">{t('sustainability.col_epd_material', { defaultValue: 'EPD Material' })}</th>
                        <th className="text-right w-[90px]">{t('sustainability.col_gwp_unit', { defaultValue: 'GWP/unit' })}</th>
                        <th className="pl-3 text-right w-[100px]">{t('sustainability.col_gwp_total', { defaultValue: 'GWP Total' })}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visiblePositions.map((pos) => {
                        // ABSOLUTE quantity in the position's own unit (m2/m3/m/
                        // kg/pcs...). q.convert multiplies + relabels; unmapped
                        // units (pcs, lsum) pass through with factor 1.
                        const pq = q.convert(pos.quantity, pos.unit);
                        // GWP/unit is "kg CO2e per <pos.unit>" - a RATE, so it is
                        // converted RECIPROCALLY (kg/m2 -> kg/ft2) so per-unit x
                        // qty still equals the unchanged kg gwp_total.
                        const unitFactor = q.convert(1, pos.unit).value;
                        const gwpPerUnit = pos.gwp_per_unit / unitFactor;
                        return (
                        <tr key={pos.position_id} className={pos.source === 'none' ? 'opacity-50' : ''}>
                          <td className="pr-3 tabular-nums text-content-secondary">{pos.ordinal}</td>
                          <td className="truncate max-w-[300px]" title={pos.description}>{pos.description}</td>
                          <td className="text-right tabular-nums text-content-secondary">{pq.value.toLocaleString(numberLocale, { maximumFractionDigits: 2 })}</td>
                          <td className="text-center text-content-tertiary">{pq.unit}</td>
                          <td>
                            <EPDSelect
                              currentId={pos.epd_id}
                              materials={epdMaterials}
                              onSelect={(epdId) => assignMut.mutate({ posId: pos.position_id, epdId })}
                              disabled={assignMut.isPending}
                            />
                          </td>
                          <td className="text-right tabular-nums text-content-secondary">
                            {/* RATE (reciprocal) per the displayed unit */}
                            {pos.gwp_per_unit ? `${gwpPerUnit.toLocaleString(numberLocale, { maximumFractionDigits: 4 })}` : '-'}
                          </td>
                          <td className="pl-3 text-right tabular-nums">
                            {pos.gwp_total ? (
                              <span className={pos.gwp_total < 0 ? 'text-semantic-success' : ''}>
                                {/* ABSOLUTE CO2 mass - kept in kg CO2e */}
                                {pos.gwp_total.toLocaleString(numberLocale, { maximumFractionDigits: 1 })} kg
                              </span>
                            ) : '-'}
                          </td>
                        </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {data.positions_detail.length > 20 && (
                  <div className="mt-3 text-center">
                    <button
                      onClick={() => setShowAllPositions(!showAllPositions)}
                      aria-expanded={showAllPositions}
                      className="inline-flex items-center gap-1 text-sm text-oe-blue hover:underline"
                    >
                      {showAllPositions ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      {showAllPositions
                        ? t('sustainability.show_less', { defaultValue: 'Show less' })
                        : t('sustainability.show_all_positions', { defaultValue: 'Show all {{count}} positions', count: data.positions_detail.length })}
                    </button>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Rating Scale + Export. The A-D thresholds are an industry scale
              defined in kg CO2 per m2 GFA (the same basis the backend rates
              against). For imperial we reciprocal-convert the boundary numbers
              (kg/m2 -> kg/ft2) and relabel the suffix, so the legend stays
              consistent with the converted per-area KPI above. The band numbers
              are built numerically (not from the baked translation) so they can
              convert; for metric the output is identical to before. */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              {(() => {
                // kg CO2/m2 boundaries; null = open end.
                const nf = (v: number) =>
                  (v / areaRateFactor).toLocaleString(numberLocale, { maximumFractionDigits: areaRateFactor === 1 ? 0 : 1 });
                const bands: { key: string; color: string; lo: number | null; hi: number | null }[] = [
                  { key: 'a', color: '#16a34a', lo: null, hi: 80 },
                  { key: 'b', color: '#2563eb', lo: 80, hi: 150 },
                  { key: 'c', color: '#ca8a04', lo: 150, hi: 250 },
                  { key: 'd', color: '#dc2626', lo: 250, hi: null },
                ];
                return bands.map((b) => {
                  const range =
                    b.lo === null && b.hi !== null
                      ? `<${nf(b.hi)}`
                      : b.hi === null && b.lo !== null
                        ? `>${nf(b.lo)}`
                        : `${nf(b.lo as number)}-${nf(b.hi as number)}`;
                  return (
                    <div key={b.key} className="flex items-center gap-1.5 text-xs text-content-tertiary">
                      <div className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: b.color }} />
                      {b.key.toUpperCase()}: {range} kg/{areaUnit}
                    </div>
                  );
                });
              })()}
            </div>
            <Button variant="secondary" size="sm" icon={<Download size={14} />}
              onClick={handleExportCsv}>
              {t('sustainability.export_csv', 'Export CO2 Report (CSV)')}
            </Button>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!data && !sustainLoading && !calculated && (
        <EmptyState
          icon={<Leaf size={28} strokeWidth={1.5} />}
          title={t('sustainability.empty_title', 'Embodied Carbon Analysis')}
          description={t(
            'sustainability.empty_desc',
            'Select a project and BOQ, then click "Enrich CO2" to auto-detect materials from 77 EPD entries (OKOBAUDAT, ICE v3.0). Click "Calculate" to see the full CO2 analysis with EU CPR 2024/3110 compliance.',
          )}
        />
      )}
    </div>
  );
}
