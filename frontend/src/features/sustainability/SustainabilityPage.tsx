import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Leaf, Download } from 'lucide-react';
import { Card, CardHeader, CardContent, Button, EmptyState, Skeleton } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';

/* -- Types ----------------------------------------------------------------- */

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

interface CO2Breakdown {
  material: string;
  quantity: number;
  unit: string;
  co2_kg: number;
  percentage: number;
}

interface SustainabilityData {
  total_co2_kg: number;
  total_co2_tons: number;
  breakdown: CO2Breakdown[];
  benchmark_per_m2: number | null;
  rating: string;
  rating_label: string;
  project_area_m2: number | null;
  positions_analyzed: number;
  positions_matched: number;
}

/* -- Helpers ---------------------------------------------------------------- */

function ratingColor(rating: string): string {
  switch (rating) {
    case 'A':
      return '#16a34a';
    case 'B':
      return '#2563eb';
    case 'C':
      return '#ca8a04';
    case 'D':
      return '#dc2626';
    default:
      return '#6b7280';
  }
}

const DONUT_COLORS = [
  '#2563eb', // blue
  '#dc2626', // red
  '#16a34a', // green
  '#ca8a04', // yellow
  '#7c3aed', // purple
  '#0891b2', // teal
  '#ea580c', // orange
  '#6366f1', // indigo
  '#be185d', // pink
  '#065f46', // dark green
];

/* -- Donut Chart ----------------------------------------------------------- */

function DonutChart({ breakdown }: { breakdown: CO2Breakdown[] }) {
  const size = 180;
  const cx = size / 2;
  const cy = size / 2;
  const outerR = 80;
  const innerR = 52;

  const segments = useMemo(() => {
    let cumulative = 0;
    return breakdown.map((item, i) => {
      const startAngle = cumulative * 3.6; // percentage to degrees
      cumulative += item.percentage;
      const endAngle = cumulative * 3.6;
      const color = DONUT_COLORS[i % DONUT_COLORS.length];
      return { ...item, startAngle, endAngle, color };
    });
  }, [breakdown]);

  function polarToCartesian(
    centerX: number,
    centerY: number,
    radius: number,
    angleInDegrees: number,
  ) {
    const angleInRadians = ((angleInDegrees - 90) * Math.PI) / 180.0;
    return {
      x: centerX + radius * Math.cos(angleInRadians),
      y: centerY + radius * Math.sin(angleInRadians),
    };
  }

  function describeArc(startAngle: number, endAngle: number) {
    // Clamp to avoid floating point issues near 360
    const sweep = Math.min(endAngle - startAngle, 359.999);
    const largeArc = sweep > 180 ? 1 : 0;

    const outerStart = polarToCartesian(cx, cy, outerR, startAngle);
    const outerEnd = polarToCartesian(cx, cy, outerR, startAngle + sweep);
    const innerStart = polarToCartesian(cx, cy, innerR, startAngle + sweep);
    const innerEnd = polarToCartesian(cx, cy, innerR, startAngle);

    return [
      `M ${outerStart.x} ${outerStart.y}`,
      `A ${outerR} ${outerR} 0 ${largeArc} 1 ${outerEnd.x} ${outerEnd.y}`,
      `L ${innerStart.x} ${innerStart.y}`,
      `A ${innerR} ${innerR} 0 ${largeArc} 0 ${innerEnd.x} ${innerEnd.y}`,
      'Z',
    ].join(' ');
  }

  if (segments.length === 0) {
    return null;
  }

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0">
      {segments.map((seg, i) => (
        <path key={i} d={describeArc(seg.startAngle, seg.endAngle)} fill={seg.color} />
      ))}
      {/* Center circle for donut hole */}
      <circle cx={cx} cy={cy} r={innerR - 1} fill="var(--color-surface-primary, white)" />
      {/* Center text */}
      <text
        x={cx}
        y={cy - 6}
        textAnchor="middle"
        fontSize={10}
        className="fill-content-tertiary"
        fontFamily="system-ui"
      >
        CO2e
      </text>
      <text
        x={cx}
        y={cy + 10}
        textAnchor="middle"
        fontSize={13}
        fontWeight="bold"
        className="fill-content-primary"
        fontFamily="system-ui"
      >
        {segments.length}
      </text>
      <text
        x={cx}
        y={cy + 22}
        textAnchor="middle"
        fontSize={9}
        className="fill-content-tertiary"
        fontFamily="system-ui"
      >
        materials
      </text>
    </svg>
  );
}

/* -- Main Page ------------------------------------------------------------- */

export function SustainabilityPage() {
  const { t } = useTranslation();
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [selectedBoqId, setSelectedBoqId] = useState<string>('');
  const [areaM2, setAreaM2] = useState<number>(2000);
  const [calculated, setCalculated] = useState(false);

  const { data: projects, isLoading: projectsLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/').catch(() => []),
  });

  const { data: boqs, isLoading: boqsLoading } = useQuery({
    queryKey: ['boqs', selectedProjectId],
    queryFn: () =>
      apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${selectedProjectId}`).catch(() => []),
    enabled: !!selectedProjectId,
  });

  const {
    data: sustainability,
    isLoading: sustainabilityLoading,
    refetch,
  } = useQuery({
    queryKey: ['sustainability', selectedBoqId, areaM2],
    queryFn: () =>
      apiGet<SustainabilityData>(
        `/v1/boq/boqs/${selectedBoqId}/sustainability?area_m2=${areaM2}`,
      ),
    enabled: false,
  });

  function handleCalculate() {
    if (!selectedBoqId) return;
    setCalculated(true);
    refetch();
  }

  function handleProjectChange(e: React.ChangeEvent<HTMLSelectElement>) {
    setSelectedProjectId(e.target.value);
    setSelectedBoqId('');
    setCalculated(false);
  }

  function handleBoqChange(e: React.ChangeEvent<HTMLSelectElement>) {
    setSelectedBoqId(e.target.value);
    setCalculated(false);
  }

  const data = calculated ? sustainability : undefined;

  return (
    <div className="max-w-content mx-auto animate-fade-in">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#16a34a]/10 text-[#16a34a]">
            <Leaf size={20} strokeWidth={1.75} />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-content-primary">
              {t('sustainability.title', 'Sustainability / CO2')}
            </h1>
            <p className="text-sm text-content-secondary">
              {t(
                'sustainability.subtitle',
                'Select project and BOQ to analyze CO2 footprint',
              )}
            </p>
          </div>
        </div>
      </div>

      {/* Selectors */}
      <Card className="mb-6">
        <CardContent>
          <div className="flex flex-wrap items-end gap-4">
            {/* Project selector */}
            <div className="flex-1 min-w-[200px]">
              <label className="block text-xs font-medium uppercase tracking-wider text-content-tertiary mb-1.5">
                {t('sustainability.project', 'Project')}
              </label>
              <select
                value={selectedProjectId}
                onChange={handleProjectChange}
                disabled={projectsLoading}
                className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary outline-none focus:border-oe-blue focus:ring-1 focus:ring-oe-blue transition-colors"
              >
                <option value="">
                  {projectsLoading
                    ? t('common.loading', 'Loading...')
                    : t('sustainability.select_project', '-- Select project --')}
                </option>
                {projects?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>

            {/* BOQ selector */}
            <div className="flex-1 min-w-[200px]">
              <label className="block text-xs font-medium uppercase tracking-wider text-content-tertiary mb-1.5">
                {t('sustainability.boq', 'BOQ')}
              </label>
              <select
                value={selectedBoqId}
                onChange={handleBoqChange}
                disabled={!selectedProjectId || boqsLoading}
                className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary outline-none focus:border-oe-blue focus:ring-1 focus:ring-oe-blue transition-colors"
              >
                <option value="">
                  {boqsLoading
                    ? t('common.loading', 'Loading...')
                    : t('sustainability.select_boq', '-- Select BOQ --')}
                </option>
                {boqs?.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </div>

            {/* Area input */}
            <div className="min-w-[140px]">
              <label className="block text-xs font-medium uppercase tracking-wider text-content-tertiary mb-1.5">
                {t('sustainability.area', 'Area (m2)')}
              </label>
              <input
                type="number"
                value={areaM2}
                onChange={(e) => setAreaM2(Number(e.target.value) || 0)}
                min={0}
                step={100}
                className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary outline-none focus:border-oe-blue focus:ring-1 focus:ring-oe-blue transition-colors tabular-nums"
              />
            </div>

            {/* Calculate button */}
            <Button
              variant="primary"
              size="md"
              icon={<Leaf size={16} />}
              onClick={handleCalculate}
              disabled={!selectedBoqId}
              loading={sustainabilityLoading}
            >
              {t('sustainability.calculate', 'Calculate')}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Loading state */}
      {sustainabilityLoading && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 mb-6">
          <Skeleton height={160} className="w-full" rounded="lg" />
          <Skeleton height={160} className="w-full" rounded="lg" />
        </div>
      )}

      {/* Results */}
      {data && !sustainabilityLoading && (
        <div className="space-y-6 animate-fade-in">
          {/* KPI Cards Row */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {/* Total CO2 */}
            <Card padding="none">
              <div className="p-6">
                <div className="text-xs font-medium uppercase tracking-wider text-content-tertiary mb-3">
                  {t('sustainability.total_co2', 'Total CO2')}
                </div>
                <div className="flex items-baseline gap-2 mb-3">
                  <span className="text-3xl font-bold tabular-nums text-content-primary">
                    {data.total_co2_tons.toLocaleString('en-US', {
                      minimumFractionDigits: 1,
                      maximumFractionDigits: 1,
                    })}
                  </span>
                  <span className="text-lg text-content-secondary">t CO2e</span>
                </div>
                {data.rating && (
                  <div className="flex items-center gap-3">
                    <div
                      className={`flex h-12 w-12 items-center justify-center rounded-xl text-xl font-bold text-white`}
                      style={{ backgroundColor: ratingColor(data.rating) }}
                    >
                      {data.rating}
                    </div>
                    <div>
                      <div className="text-sm font-semibold text-content-primary">
                        {t('sustainability.rating', 'Rating')}: {data.rating}
                      </div>
                      <div className="text-xs text-content-secondary">
                        ({data.rating_label})
                      </div>
                    </div>
                  </div>
                )}
                <div className="mt-3 text-xs text-content-tertiary">
                  {data.positions_matched} / {data.positions_analyzed}{' '}
                  {t('sustainability.positions_matched', 'positions matched')}
                </div>
              </div>
            </Card>

            {/* Benchmark */}
            <Card padding="none">
              <div className="p-6">
                <div className="text-xs font-medium uppercase tracking-wider text-content-tertiary mb-3">
                  {t('sustainability.benchmark', 'Benchmark')}
                </div>
                {data.benchmark_per_m2 !== null ? (
                  <>
                    <div className="flex items-baseline gap-2 mb-3">
                      <span className="text-3xl font-bold tabular-nums text-content-primary">
                        {data.benchmark_per_m2.toLocaleString('en-US', {
                          minimumFractionDigits: 1,
                          maximumFractionDigits: 1,
                        })}
                      </span>
                      <span className="text-lg text-content-secondary">kg CO2/m2</span>
                    </div>
                    <div className="text-xs text-content-secondary mb-4">
                      ({data.project_area_m2?.toLocaleString()} m2{' '}
                      {t('sustainability.project_area', 'project')})
                    </div>
                    {/* Rating scale */}
                    <div className="space-y-1.5">
                      {[
                        { label: 'A: <80', color: '#16a34a', key: 'A' },
                        { label: 'B: 80-150', color: '#2563eb', key: 'B' },
                        { label: 'C: 150-250', color: '#ca8a04', key: 'C' },
                        { label: 'D: >250', color: '#dc2626', key: 'D' },
                      ].map((r) => (
                        <div
                          key={r.key}
                          className={`flex items-center gap-2 rounded-md px-2 py-1 text-xs ${
                            data.rating === r.key ? 'font-semibold' : 'text-content-tertiary'
                          }`}
                          style={
                            data.rating === r.key
                              ? { backgroundColor: `${r.color}15`, color: r.color }
                              : undefined
                          }
                        >
                          <div
                            className="h-2.5 w-2.5 rounded-full"
                            style={{ backgroundColor: r.color }}
                          />
                          {r.label} kg CO2/m2
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="text-sm text-content-secondary">
                    {t(
                      'sustainability.no_area',
                      'Enter project area to see benchmark per m2',
                    )}
                  </p>
                )}
              </div>
            </Card>
          </div>

          {/* Breakdown */}
          {data.breakdown.length > 0 && (
            <Card>
              <CardHeader
                title={t('sustainability.breakdown_title', 'Breakdown by Material')}
              />
              <CardContent>
                <div className="flex flex-col lg:flex-row items-start gap-8">
                  {/* Donut chart */}
                  <DonutChart breakdown={data.breakdown} />

                  {/* Legend table */}
                  <div className="flex-1 min-w-0">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-border-light">
                          <th className="py-2 pr-4 text-left text-xs font-medium uppercase tracking-wider text-content-tertiary">
                            {t('sustainability.material', 'Material')}
                          </th>
                          <th className="py-2 px-4 text-right text-xs font-medium uppercase tracking-wider text-content-tertiary">
                            %
                          </th>
                          <th className="py-2 pl-4 text-right text-xs font-medium uppercase tracking-wider text-content-tertiary">
                            CO2 (t)
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border-light">
                        {data.breakdown.map((item, i) => (
                          <tr key={item.material}>
                            <td className="py-2.5 pr-4">
                              <div className="flex items-center gap-2">
                                <div
                                  className="h-3 w-3 rounded-sm shrink-0"
                                  style={{
                                    backgroundColor:
                                      DONUT_COLORS[i % DONUT_COLORS.length],
                                  }}
                                />
                                <span className="text-content-primary font-medium truncate">
                                  {item.material}
                                </span>
                              </div>
                            </td>
                            <td className="py-2.5 px-4 text-right tabular-nums text-content-secondary">
                              {item.percentage.toFixed(1)}%
                            </td>
                            <td className="py-2.5 pl-4 text-right tabular-nums font-medium text-content-primary">
                              {(item.co2_kg / 1000).toLocaleString('en-US', {
                                minimumFractionDigits: 1,
                                maximumFractionDigits: 1,
                              })}{' '}
                              t
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

          {/* Export button */}
          <div className="flex justify-end">
            <Button
              variant="secondary"
              size="sm"
              icon={<Download size={14} />}
              onClick={() => {
                /* PDF export placeholder */
              }}
            >
              {t('sustainability.export_pdf', 'Export CO2 Report PDF')}
            </Button>
          </div>
        </div>
      )}

      {/* Empty state before calculation */}
      {!data && !sustainabilityLoading && !calculated && (
        <EmptyState
          icon={<Leaf size={24} strokeWidth={1.5} />}
          title={t('sustainability.empty_title', 'CO2 footprint analysis')}
          description={t(
            'sustainability.empty_desc',
            'Select a project and BOQ above, then click Calculate to analyze CO2 emissions based on material types.',
          )}
        />
      )}
    </div>
  );
}
