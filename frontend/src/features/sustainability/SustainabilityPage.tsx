import { useState, useMemo } from 'react';
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
} from 'lucide-react';
import { Card, CardHeader, CardContent, Button, EmptyState, Skeleton } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import {
  fetchSustainability,
  enrichCO2,
  assignPositionCO2,
  fetchEPDMaterials,
  type SustainabilityData,
  type PositionCO2Detail,
  type EPDMaterial,
} from './api';

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

function complianceStyle(level: string) {
  switch (level) {
    case 'excellent': return { bg: 'bg-emerald-50 dark:bg-emerald-950/30', text: 'text-emerald-700 dark:text-emerald-400', Icon: CheckCircle2, label: 'Excellent' };
    case 'good': return { bg: 'bg-green-50 dark:bg-green-950/30', text: 'text-green-700 dark:text-green-400', Icon: CheckCircle2, label: 'Good' };
    case 'acceptable': return { bg: 'bg-amber-50 dark:bg-amber-950/30', text: 'text-amber-700 dark:text-amber-400', Icon: AlertTriangle, label: 'Acceptable' };
    case 'non-compliant': return { bg: 'bg-red-50 dark:bg-red-950/30', text: 'text-red-700 dark:text-red-400', Icon: XCircle, label: 'Non-Compliant' };
    default: return { bg: 'bg-gray-50 dark:bg-gray-950/30', text: 'text-gray-500', Icon: Info, label: 'N/A' };
  }
}

const DONUT_COLORS = [
  '#2563eb', '#dc2626', '#16a34a', '#ca8a04', '#7c3aed',
  '#0891b2', '#ea580c', '#6366f1', '#be185d', '#065f46', '#9333ea',
];

/* ── Donut Chart ───────────────────────────────────────────────────── */

function DonutChart({ data }: { data: { label: string; value: number; pct: number }[] }) {
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
      <text x={cx} y={cy + 24} textAnchor="middle" fontSize={9} className="fill-content-tertiary" fontFamily="system-ui">categories</text>
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
  return (
    <select
      value={currentId || ''}
      onChange={(e) => { if (e.target.value) onSelect(e.target.value); }}
      disabled={disabled}
      className="w-full max-w-[220px] rounded border border-border-light bg-surface-primary px-1.5 py-1 text-xs text-content-primary outline-none focus:border-oe-blue transition-colors truncate"
    >
      <option value="">-- none --</option>
      {materials.map((m) => (
        <option key={m.id} value={m.id}>
          {m.name} ({m.gwp} kg/{m.unit})
        </option>
      ))}
    </select>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────── */

export function SustainabilityPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [selectedBoqId, setSelectedBoqId] = useState('');
  const [areaM2, setAreaM2] = useState(2000);
  const [calculated, setCalculated] = useState(false);
  const [showAllPositions, setShowAllPositions] = useState(false);

  // Projects & BOQs
  const { data: projects, isLoading: projectsLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/').catch(() => []),
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

  // EPD materials for dropdown
  const { data: epdData } = useQuery({
    queryKey: ['epd-materials'],
    queryFn: () => fetchEPDMaterials(),
  });
  const epdMaterials = epdData?.materials || [];

  // Enrich mutation
  const enrichMut = useMutation({
    mutationFn: () => enrichCO2(selectedBoqId),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['sustainability'] });
      refetch();
      alert(`CO2 enriched: ${res.enriched} positions (${res.skipped} skipped)`);
    },
    onError: (err: Error) => {
      alert(`CO2 enrichment failed: ${err.message}`);
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
      console.error('Failed to assign CO2 data:', err.message);
    },
  });

  function handleCalculate() {
    if (!selectedBoqId) return;
    setCalculated(true);
    refetch();
  }

  const data: SustainabilityData | undefined = calculated ? sustainability : undefined;
  const cpr = data?.eu_cpr_compliance ? complianceStyle(data.eu_cpr_compliance) : null;

  // Positions to display (limit to 20 unless expanded)
  const visiblePositions: PositionCO2Detail[] = useMemo(() => {
    if (!data?.positions_detail) return [];
    const sorted = [...data.positions_detail].sort((a, b) => Math.abs(b.gwp_total) - Math.abs(a.gwp_total));
    return showAllPositions ? sorted : sorted.slice(0, 20);
  }, [data, showAllPositions]);

  const dataQualityLabel = data?.data_quality === 'enriched'
    ? 'Enriched (stored)'
    : data?.data_quality === 'mixed'
    ? 'Mixed (stored + auto)'
    : 'Estimated (auto-detected)';

  return (
    <div className="w-full animate-fade-in">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#16a34a]/10 text-[#16a34a]">
            <Leaf size={20} strokeWidth={1.75} />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-content-primary">
              {t('sustainability.title', 'Sustainability / CO2 Analysis')}
            </h1>
            <p className="text-sm text-content-secondary">
              {t('sustainability.subtitle', 'Embodied carbon analysis based on EPD data (EN 15804, A1-A3)')}
            </p>
          </div>
        </div>
      </div>

      {/* Selectors */}
      <Card className="mb-6">
        <CardContent>
          <div className="flex flex-wrap items-end gap-4">
            <div className="flex-1 min-w-[200px]">
              <label className="block text-xs font-medium uppercase tracking-wider text-content-tertiary mb-1.5">
                {t('sustainability.project', 'Project')}
              </label>
              <select
                value={selectedProjectId}
                onChange={(e) => { setSelectedProjectId(e.target.value); setSelectedBoqId(''); setCalculated(false); }}
                disabled={projectsLoading}
                className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary outline-none focus:border-oe-blue focus:ring-1 focus:ring-oe-blue transition-colors"
              >
                <option value="">{projectsLoading ? t('common.loading', 'Loading...') : t('sustainability.select_project', '-- Select project --')}</option>
                {projects?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
            <div className="flex-1 min-w-[200px]">
              <label className="block text-xs font-medium uppercase tracking-wider text-content-tertiary mb-1.5">
                {t('sustainability.boq', 'BOQ')}
              </label>
              <select
                value={selectedBoqId}
                onChange={(e) => { setSelectedBoqId(e.target.value); setCalculated(false); }}
                disabled={!selectedProjectId || boqsLoading}
                className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary outline-none focus:border-oe-blue focus:ring-1 focus:ring-oe-blue transition-colors"
              >
                <option value="">{boqsLoading ? t('common.loading', 'Loading...') : t('sustainability.select_boq', '-- Select BOQ --')}</option>
                {boqs?.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </div>
            <div className="min-w-[140px]">
              <label className="block text-xs font-medium uppercase tracking-wider text-content-tertiary mb-1.5">
                {t('sustainability.area', 'GFA (m2)')}
              </label>
              <input
                type="number" value={areaM2} onChange={(e) => setAreaM2(Number(e.target.value) || 0)}
                min={0} step={100}
                className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary outline-none focus:border-oe-blue focus:ring-1 focus:ring-oe-blue transition-colors tabular-nums"
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
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3 mb-6">
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
                  <span className="text-3xl font-bold tabular-nums text-content-primary">
                    {data.total_co2_tons.toLocaleString('de-DE', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
                  </span>
                  <span className="text-lg text-content-secondary">t CO2e</span>
                </div>
                {data.rating && (
                  <div className="flex items-center gap-3 mb-2">
                    <div className="flex h-11 w-11 items-center justify-center rounded-xl text-xl font-bold text-white"
                      style={{ backgroundColor: ratingColor(data.rating) }}>{data.rating}</div>
                    <div>
                      <div className="text-sm font-semibold text-content-primary">{data.rating_label}</div>
                      <div className="text-xs text-content-tertiary">{data.benchmark_per_m2} kg CO2/m2</div>
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
                  EU CPR 2024/3110
                </div>
                {cpr ? (
                  <div className={`rounded-lg p-4 ${cpr.bg}`}>
                    <div className="flex items-center gap-2 mb-2">
                      <cpr.Icon size={20} className={cpr.text} />
                      <span className={`text-lg font-bold ${cpr.text}`}>{cpr.label}</span>
                    </div>
                    <div className="text-sm text-content-secondary">
                      {data.eu_cpr_gwp_per_m2_year?.toFixed(2)} kg CO2e/m2/yr
                    </div>
                    <div className="text-xs text-content-tertiary mt-1">50-year RSP</div>
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
                  {data.positions_matched} / {data.positions_analyzed} positions with CO2 data
                </div>
                {data.positions_analyzed > 0 && (
                  <div className="w-full h-2 rounded-full bg-border-light overflow-hidden">
                    <div className="h-full rounded-full bg-[#16a34a] transition-all"
                      style={{ width: `${(data.positions_matched / data.positions_analyzed) * 100}%` }} />
                  </div>
                )}
                <div className="text-xs text-content-tertiary mt-2">
                  Sources: OKOBAUDAT, ICE v3.0, EU Level(s)
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
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-border-light">
                          <th className="py-2 pr-4 text-left text-xs font-medium uppercase tracking-wider text-content-tertiary">Category</th>
                          <th className="py-2 px-4 text-right text-xs font-medium uppercase tracking-wider text-content-tertiary">Positions</th>
                          <th className="py-2 px-4 text-right text-xs font-medium uppercase tracking-wider text-content-tertiary">%</th>
                          <th className="py-2 pl-4 text-right text-xs font-medium uppercase tracking-wider text-content-tertiary">CO2 (t)</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border-light">
                        {data.breakdown.map((item, i) => (
                          <tr key={item.category}>
                            <td className="py-2.5 pr-4">
                              <div className="flex items-center gap-2">
                                <div className="h-3 w-3 rounded-sm shrink-0" style={{ backgroundColor: DONUT_COLORS[i % DONUT_COLORS.length] }} />
                                <span className="text-content-primary font-medium">{item.material}</span>
                              </div>
                            </td>
                            <td className="py-2.5 px-4 text-right tabular-nums text-content-secondary">{item.positions_count}</td>
                            <td className="py-2.5 px-4 text-right tabular-nums text-content-secondary">{item.percentage.toFixed(1)}%</td>
                            <td className="py-2.5 pl-4 text-right tabular-nums font-medium text-content-primary">
                              {(item.co2_kg / 1000).toLocaleString('de-DE', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} t
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
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border-light">
                        <th className="py-2 pr-3 text-left text-xs font-medium uppercase tracking-wider text-content-tertiary w-[60px]">#</th>
                        <th className="py-2 px-3 text-left text-xs font-medium uppercase tracking-wider text-content-tertiary">Description</th>
                        <th className="py-2 px-3 text-right text-xs font-medium uppercase tracking-wider text-content-tertiary w-[80px]">Qty</th>
                        <th className="py-2 px-3 text-center text-xs font-medium uppercase tracking-wider text-content-tertiary w-[50px]">Unit</th>
                        <th className="py-2 px-3 text-left text-xs font-medium uppercase tracking-wider text-content-tertiary w-[220px]">EPD Material</th>
                        <th className="py-2 px-3 text-right text-xs font-medium uppercase tracking-wider text-content-tertiary w-[90px]">GWP/unit</th>
                        <th className="py-2 pl-3 text-right text-xs font-medium uppercase tracking-wider text-content-tertiary w-[100px]">GWP Total</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-light">
                      {visiblePositions.map((pos) => (
                        <tr key={pos.position_id} className={pos.source === 'none' ? 'opacity-50' : ''}>
                          <td className="py-2 pr-3 tabular-nums text-content-secondary text-xs">{pos.ordinal}</td>
                          <td className="py-2 px-3 text-content-primary truncate max-w-[300px]" title={pos.description}>{pos.description}</td>
                          <td className="py-2 px-3 text-right tabular-nums text-content-secondary">{pos.quantity.toLocaleString('de-DE', { maximumFractionDigits: 2 })}</td>
                          <td className="py-2 px-3 text-center text-content-tertiary">{pos.unit}</td>
                          <td className="py-2 px-3">
                            <EPDSelect
                              currentId={pos.epd_id}
                              materials={epdMaterials}
                              onSelect={(epdId) => assignMut.mutate({ posId: pos.position_id, epdId })}
                              disabled={assignMut.isPending}
                            />
                          </td>
                          <td className="py-2 px-3 text-right tabular-nums text-content-secondary text-xs">
                            {pos.gwp_per_unit ? `${pos.gwp_per_unit}` : '-'}
                          </td>
                          <td className="py-2 pl-3 text-right tabular-nums font-medium text-content-primary">
                            {pos.gwp_total ? (
                              <span className={pos.gwp_total < 0 ? 'text-emerald-600' : ''}>
                                {pos.gwp_total.toLocaleString('de-DE', { maximumFractionDigits: 1 })} kg
                              </span>
                            ) : '-'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {data.positions_detail.length > 20 && (
                  <div className="mt-3 text-center">
                    <button
                      onClick={() => setShowAllPositions(!showAllPositions)}
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

          {/* Rating Scale + Export */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              {[
                { label: 'A: <80', color: '#16a34a', key: 'a' },
                { label: 'B: 80-150', color: '#2563eb', key: 'b' },
                { label: 'C: 150-250', color: '#ca8a04', key: 'c' },
                { label: 'D: >250', color: '#dc2626', key: 'd' },
              ].map((r) => (
                <div key={r.key} className="flex items-center gap-1.5 text-xs text-content-tertiary">
                  <div className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: r.color }} />
                  {t(`sustainability.rating_${r.key}`, { defaultValue: r.label })} kg/m²
                </div>
              ))}
            </div>
            <Button variant="secondary" size="sm" icon={<Download size={14} />}
              onClick={() => { /* PDF export placeholder */ }}>
              {t('sustainability.export_pdf', 'Export CO2 Report')}
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
