import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Leaf,
  Search,
  X,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Info,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import {
  EPD_MATERIALS,
  EPD_CATEGORIES,
  EU_CPR_BENCHMARKS,
  type EPDMaterial,
  type EPDCategory,
} from './data/epd-materials';

/* ── Types ─────────────────────────────────────────────────────────── */

interface PositionEntry {
  id: string;
  description: string;
  materialId: string;
  quantity: number;
  unit: string;
}

/* ── Helpers ───────────────────────────────────────────────────────── */

function computeGWP(material: EPDMaterial, quantity: number): number {
  return material.gwp * quantity;
}

function getComplianceLevel(gwpPerM2: number): 'excellent' | 'good' | 'acceptable' | 'non-compliant' {
  if (gwpPerM2 <= EU_CPR_BENCHMARKS.excellent) return 'excellent';
  if (gwpPerM2 <= EU_CPR_BENCHMARKS.good) return 'good';
  if (gwpPerM2 <= EU_CPR_BENCHMARKS.acceptable) return 'acceptable';
  return 'non-compliant';
}

const COMPLIANCE_STYLES = {
  excellent:       { bg: 'bg-emerald-50 dark:bg-emerald-950/30', text: 'text-emerald-700 dark:text-emerald-400', icon: CheckCircle2 },
  good:            { bg: 'bg-green-50 dark:bg-green-950/30', text: 'text-green-700 dark:text-green-400', icon: CheckCircle2 },
  acceptable:      { bg: 'bg-amber-50 dark:bg-amber-950/30', text: 'text-amber-700 dark:text-amber-400', icon: AlertTriangle },
  'non-compliant': { bg: 'bg-red-50 dark:bg-red-950/30', text: 'text-red-700 dark:text-red-400', icon: XCircle },
};

const materialMap = new Map(EPD_MATERIALS.map((m) => [m.id, m]));

/* ── Component ─────────────────────────────────────────────────────── */

export default function SustainabilityModule() {
  const { t } = useTranslation();

  // EPD browser state
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<EPDCategory | 'all'>('all');
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set());

  // Calculator state
  const [gfa, setGfa] = useState(1000);
  const [positions, setPositions] = useState<PositionEntry[]>([
    { id: '1', description: 'Foundation concrete', materialId: 'c30-37', quantity: 120, unit: 'm3' },
    { id: '2', description: 'Structural steel', materialId: 'steel-structural', quantity: 8500, unit: 'kg' },
    { id: '3', description: 'Mineral wool insulation', materialId: 'insul-mineral', quantity: 2200, unit: 'kg' },
  ]);

  // Filter materials
  const filteredMaterials = useMemo(() => {
    let items = EPD_MATERIALS;
    if (selectedCategory !== 'all') {
      items = items.filter((m) => m.category === selectedCategory);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      items = items.filter(
        (m) =>
          m.name.toLowerCase().includes(q) ||
          m.category.toLowerCase().includes(q) ||
          m.id.includes(q),
      );
    }
    return items;
  }, [search, selectedCategory]);

  // Group filtered materials by category
  const groupedMaterials = useMemo(() => {
    const groups = new Map<EPDCategory, EPDMaterial[]>();
    for (const m of filteredMaterials) {
      const arr = groups.get(m.category) || [];
      arr.push(m);
      groups.set(m.category, arr);
    }
    return groups;
  }, [filteredMaterials]);

  // Carbon calculation
  const carbonBreakdown = useMemo(() => {
    const items = positions.map((pos) => {
      const material = materialMap.get(pos.materialId);
      const gwp = material ? computeGWP(material, pos.quantity) : 0;
      return { ...pos, material, gwp };
    });
    const totalGWP = items.reduce((sum, i) => sum + i.gwp, 0);
    const gwpPerM2 = gfa > 0 ? totalGWP / gfa : 0;
    const gwpPerM2Year = gwpPerM2 / 50; // 50-year reference service period
    const compliance = getComplianceLevel(gwpPerM2Year);
    return { items, totalGWP, gwpPerM2, gwpPerM2Year, compliance };
  }, [positions, gfa]);

  // Category chart data
  const categoryTotals = useMemo(() => {
    const totals = new Map<string, number>();
    for (const item of carbonBreakdown.items) {
      if (!item.material) continue;
      const cat = EPD_CATEGORIES.find((c) => c.id === item.material!.category);
      const label = cat?.label ?? item.material.category;
      totals.set(label, (totals.get(label) ?? 0) + Math.abs(item.gwp));
    }
    return [...totals.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([label, value]) => ({ label, value }));
  }, [carbonBreakdown]);

  const maxCategoryValue = Math.max(...categoryTotals.map((c) => c.value), 1);

  const toggleCategory = (cat: string) => {
    setExpandedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  const addPosition = () => {
    setPositions((prev) => [
      ...prev,
      {
        id: String(Date.now()),
        description: '',
        materialId: EPD_MATERIALS[0]!.id,
        quantity: 0,
        unit: EPD_MATERIALS[0]!.unit,
      },
    ]);
  };

  const removePosition = (id: string) => {
    setPositions((prev) => prev.filter((p) => p.id !== id));
  };

  const updatePosition = (id: string, field: keyof PositionEntry, value: string | number) => {
    setPositions((prev) =>
      prev.map((p) => {
        if (p.id !== id) return p;
        const updated = { ...p, [field]: value };
        if (field === 'materialId') {
          const mat = materialMap.get(value as string);
          if (mat) updated.unit = mat.unit;
        }
        return updated;
      }),
    );
  };

  const cStyle = COMPLIANCE_STYLES[carbonBreakdown.compliance];
  const CIcon = cStyle.icon;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-100 dark:bg-emerald-900/30">
          <Leaf className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-content-primary">
            {t('sustainability.epd_title', { defaultValue: 'EPD / Embodied Carbon' })}
          </h1>
          <p className="text-sm text-content-tertiary">
            {t('sustainability.epd_subtitle', { defaultValue: 'EU CPR 2024/3110 compliance — GWP calculation per position' })}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* ── Left: EPD Material Database Browser ─────────────────────── */}
        <div className="xl:col-span-1 rounded-xl border border-border bg-surface-primary p-4">
          <h2 className="text-sm font-semibold text-content-primary mb-3">
            {t('sustainability.material_database', { defaultValue: 'EPD Material Database' })}
          </h2>

          {/* Search */}
          <div className="relative mb-3">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-content-quaternary" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('common.search', { defaultValue: 'Search materials...' })}
              className="w-full rounded-lg border border-border bg-surface-secondary py-2 pl-9 pr-8 text-sm text-content-primary placeholder:text-content-quaternary focus:border-oe-blue focus:outline-none"
            />
            {search && (
              <button
                onClick={() => setSearch('')}
                className="absolute right-2 top-1/2 -translate-y-1/2"
                aria-label={t('common.clear_search', { defaultValue: 'Clear search' })}
              >
                <X className="h-4 w-4 text-content-quaternary hover:text-content-secondary" />
              </button>
            )}
          </div>

          {/* Category filter */}
          <select
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value as EPDCategory | 'all')}
            className="w-full mb-3 rounded-lg border border-border bg-surface-secondary py-1.5 px-3 text-sm text-content-primary"
            aria-label={t('sustainability.filter_category', { defaultValue: 'Filter by category' })}
          >
            <option value="all">{t('common.all_categories', { defaultValue: 'All Categories' })}</option>
            {EPD_CATEGORIES.map((c) => (
              <option key={c.id} value={c.id}>{c.label}</option>
            ))}
          </select>

          {/* Material tree */}
          <div className="max-h-[500px] overflow-y-auto space-y-1">
            {[...groupedMaterials.entries()].map(([cat, materials]) => {
              const catInfo = EPD_CATEGORIES.find((c) => c.id === cat);
              const isExpanded = expandedCategories.has(cat);
              return (
                <div key={cat}>
                  <button
                    onClick={() => toggleCategory(cat)}
                    className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-xs font-semibold text-content-secondary hover:bg-surface-secondary"
                    aria-expanded={isExpanded}
                    aria-label={t('sustainability.toggle_category', { defaultValue: 'Toggle {{category}}', category: catInfo?.label ?? cat })}
                  >
                    {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                    {catInfo?.label ?? cat}
                    <span className="ml-auto text-content-quaternary">{materials.length}</span>
                  </button>
                  {isExpanded && (
                    <div className="ml-4 space-y-0.5">
                      {materials.map((m) => (
                        <div
                          key={m.id}
                          className="flex items-center justify-between rounded px-2 py-1 text-xs hover:bg-surface-secondary"
                        >
                          <span className="text-content-primary truncate">{m.name}</span>
                          <span className={`ml-2 whitespace-nowrap font-mono ${m.gwp < 0 ? 'text-emerald-600' : 'text-content-tertiary'}`}>
                            {m.gwp < 0 ? '' : '+'}{m.gwp.toFixed(m.gwp < 1 ? 3 : 1)} {m.unit}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
            {groupedMaterials.size === 0 && (
              <p className="text-xs text-content-quaternary text-center py-4">
                {t('common.no_results', { defaultValue: 'No materials found' })}
              </p>
            )}
          </div>

          <p className="mt-3 text-2xs text-content-quaternary flex items-start gap-1">
            <Info className="h-3 w-3 mt-0.5 shrink-0" />
            {t('sustainability.data_sources', { defaultValue: 'Data: Okobaudat, ICE v3.0 (Bath), EU Level(s). GWP A1-A3 (cradle to gate).' })}
          </p>
        </div>

        {/* ── Center: Carbon Calculator ───────────────────────────────── */}
        <div className="xl:col-span-2 space-y-4">
          {/* GFA input + Compliance badge */}
          <div className="flex items-center gap-4 flex-wrap">
            <label className="flex items-center gap-2 text-sm text-content-secondary">
              {t('sustainability.gfa', { defaultValue: 'Gross Floor Area (m2)' })}
              <input
                type="number"
                value={gfa}
                onChange={(e) => setGfa(Number(e.target.value) || 0)}
                className="w-28 rounded-lg border border-border bg-surface-secondary px-3 py-1.5 text-sm text-content-primary"
              />
            </label>

            <div className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${cStyle.bg} ${cStyle.text}`}>
              <CIcon className="h-4 w-4" />
              {t('sustainability.eu_cpr_label', { defaultValue: 'EU CPR' })}:{' '}
              {carbonBreakdown.compliance.replace('-', ' ')}
              <span className="text-xs opacity-75">
                ({carbonBreakdown.gwpPerM2Year.toFixed(1)} kg CO2e/m2/yr)
              </span>
            </div>
          </div>

          {/* Positions table */}
          <div className="rounded-xl border border-border bg-surface-primary overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-surface-secondary/50">
                  <th className="px-3 py-2 text-left text-xs font-medium text-content-tertiary">
                    {t('common.description', { defaultValue: 'Description' })}
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-content-tertiary">
                    {t('sustainability.material', { defaultValue: 'Material' })}
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-content-tertiary">
                    {t('common.quantity', { defaultValue: 'Qty' })}
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-content-tertiary">
                    {t('common.unit', { defaultValue: 'Unit' })}
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-content-tertiary">
                    {t('sustainability.gwp_column', { defaultValue: 'GWP (kg CO2e)' })}
                  </th>
                  <th className="px-3 py-2 w-8" />
                </tr>
              </thead>
              <tbody>
                {carbonBreakdown.items.map((item) => (
                  <tr key={item.id} className="border-b border-border/50 hover:bg-surface-secondary/30">
                    <td className="px-3 py-2">
                      <input
                        type="text"
                        value={item.description}
                        onChange={(e) => updatePosition(item.id, 'description', e.target.value)}
                        className="w-full bg-transparent text-content-primary outline-none"
                        placeholder={t('sustainability.position_desc_placeholder', { defaultValue: 'Position description' })}
                        aria-label={t('common.description', { defaultValue: 'Description' })}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <select
                        value={item.materialId}
                        onChange={(e) => updatePosition(item.id, 'materialId', e.target.value)}
                        className="w-full rounded border border-border bg-surface-secondary px-2 py-1 text-xs text-content-primary"
                        aria-label={t('sustainability.material', { defaultValue: 'Material' })}
                      >
                        {EPD_CATEGORIES.map((cat) => (
                          <optgroup key={cat.id} label={cat.label}>
                            {EPD_MATERIALS.filter((m) => m.category === cat.id).map((m) => (
                              <option key={m.id} value={m.id}>
                                {m.name} ({m.gwp} / {m.unit})
                              </option>
                            ))}
                          </optgroup>
                        ))}
                      </select>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <input
                        type="number"
                        value={item.quantity}
                        onChange={(e) => updatePosition(item.id, 'quantity', Number(e.target.value) || 0)}
                        className="w-20 text-right bg-transparent text-content-primary outline-none"
                        aria-label={t('common.quantity', { defaultValue: 'Quantity' })}
                      />
                    </td>
                    <td className="px-3 py-2 text-xs text-content-tertiary">{item.unit}</td>
                    <td className={`px-3 py-2 text-right font-mono text-xs ${item.gwp < 0 ? 'text-emerald-600' : 'text-content-primary'}`}>
                      {item.gwp < 0 ? '' : '+'}{item.gwp.toLocaleString('en', { maximumFractionDigits: 0 })}
                    </td>
                    <td className="px-3 py-2">
                      <button
                        onClick={() => removePosition(item.id)}
                        className="text-content-quaternary hover:text-red-500"
                        aria-label={t('sustainability.remove_position', { defaultValue: 'Remove position' })}
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-border bg-surface-secondary/30">
                  <td colSpan={4} className="px-3 py-2 text-sm font-semibold text-content-primary">
                    {t('common.total', { defaultValue: 'Total' })}
                  </td>
                  <td className={`px-3 py-2 text-right font-mono text-sm font-bold ${carbonBreakdown.totalGWP < 0 ? 'text-emerald-600' : 'text-content-primary'}`}>
                    {carbonBreakdown.totalGWP.toLocaleString('en', { maximumFractionDigits: 0 })} kg
                  </td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>

          <button
            onClick={addPosition}
            className="text-sm text-oe-blue hover:text-oe-blue-dark font-medium"
          >
            + {t('sustainability.add_position', { defaultValue: 'Add position' })}
          </button>

          {/* Summary cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="rounded-xl border border-border bg-surface-primary p-4">
              <p className="text-xs text-content-tertiary mb-1">
                {t('sustainability.total_gwp', { defaultValue: 'Total Embodied Carbon' })}
              </p>
              <p className="text-xl font-bold text-content-primary">
                {(carbonBreakdown.totalGWP / 1000).toFixed(1)} <span className="text-sm font-normal">t CO2e</span>
              </p>
            </div>
            <div className="rounded-xl border border-border bg-surface-primary p-4">
              <p className="text-xs text-content-tertiary mb-1">
                {t('sustainability.gwp_per_m2', { defaultValue: 'Carbon per m2 GFA' })}
              </p>
              <p className="text-xl font-bold text-content-primary">
                {carbonBreakdown.gwpPerM2.toFixed(1)} <span className="text-sm font-normal">kg CO2e/m2</span>
              </p>
            </div>
            <div className="rounded-xl border border-border bg-surface-primary p-4">
              <p className="text-xs text-content-tertiary mb-1">
                {t('sustainability.gwp_annual', { defaultValue: 'Annual (50yr RSP)' })}
              </p>
              <p className="text-xl font-bold text-content-primary">
                {carbonBreakdown.gwpPerM2Year.toFixed(2)} <span className="text-sm font-normal">kg/m2/yr</span>
              </p>
            </div>
          </div>

          {/* Category breakdown chart */}
          {categoryTotals.length > 0 && (
            <div className="rounded-xl border border-border bg-surface-primary p-4">
              <h3 className="text-sm font-semibold text-content-primary mb-3">
                {t('sustainability.breakdown', { defaultValue: 'Carbon Breakdown by Category' })}
              </h3>
              <div className="space-y-2">
                {categoryTotals.map((cat) => (
                  <div key={cat.label} className="flex items-center gap-3">
                    <span className="w-40 text-xs text-content-secondary truncate">{cat.label}</span>
                    <div className="flex-1 h-5 bg-surface-secondary rounded-full overflow-hidden">
                      <div
                        className="h-full bg-emerald-500 dark:bg-emerald-600 rounded-full transition-all"
                        style={{ width: `${(cat.value / maxCategoryValue) * 100}%` }}
                      />
                    </div>
                    <span className="w-24 text-right text-xs font-mono text-content-tertiary">
                      {cat.value.toLocaleString('en', { maximumFractionDigits: 0 })} kg
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* EU CPR info */}
          <div className="rounded-xl border border-border bg-surface-secondary/30 p-4 text-xs text-content-tertiary">
            <p className="font-semibold text-content-secondary mb-1">
              {t('sustainability.cpr_benchmarks_title', { defaultValue: 'EU CPR 2024/3110 — GWP Benchmarks (A1-A3, 50yr RSP)' })}
            </p>
            <div className="flex flex-wrap gap-4 mt-2">
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-emerald-500" /> {t('sustainability.level_excellent', { defaultValue: 'Excellent' })}: &le; {EU_CPR_BENCHMARKS.excellent} kg/m2/yr</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-green-500" /> {t('sustainability.level_good', { defaultValue: 'Good' })}: &le; {EU_CPR_BENCHMARKS.good} kg/m2/yr</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-amber-500" /> {t('sustainability.level_acceptable', { defaultValue: 'Acceptable' })}: &le; {EU_CPR_BENCHMARKS.acceptable} kg/m2/yr</span>
              <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-red-500" /> {t('sustainability.level_non_compliant', { defaultValue: 'Non-compliant' })}: &gt; {EU_CPR_BENCHMARKS.limit} kg/m2/yr</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
