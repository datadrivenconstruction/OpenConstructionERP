// OpenConstructionERP — DataDrivenConstruction (DDC)
// CWICR AI Estimation Engine
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// DDC-CWICR-OE-2026
import { useState, useCallback, useRef, useEffect, useMemo, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams, useLocation, Link } from 'react-router-dom';
import {
  Sparkles,
  ArrowRight,
  Download,
  RotateCcw,
  Save,
  AlertCircle,
  Zap,
  Pencil,
  Camera,
  FileText,
  FileSpreadsheet,
  HardHat,
  ClipboardPaste,
  Upload,
  X,
  Image as ImageIcon,
  FileArchive,
  Info,
  CheckCircle2,
  XCircle,
  ExternalLink,
  ChevronDown,
  ChevronRight,
  Layers,
  FileInput,
  Loader2,
  Trash2,
  HardDrive,
  Star,
  Database,
} from 'lucide-react';
import clsx from 'clsx';
import { Card, CardContent, Button, Badge } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { aiApi, type QuickEstimateRequest, type EstimateJobResponse, type EstimateItem, type CadExtractResponse, type EnrichResult, type EnrichedItem, type CadColumnsResponse, type CadGroupResponse } from './api';
import { apiGet, apiPost } from '@/shared/lib/api';
import { getIntlLocale } from '@/shared/lib/formatters';

// ── Tab types ────────────────────────────────────────────────────────────────

type InputTab = 'text' | 'photo' | 'pdf' | 'excel' | 'cad' | 'paste';

interface TabDef {
  id: InputTab;
  label: string;
  labelKey: string;
  icon: React.ReactNode;
  descKey: string;
  descFallback: string;
  color: string;
}

const TABS: TabDef[] = [
  { id: 'text', label: 'Text', labelKey: 'ai.tab_text', icon: <Pencil size={22} />, descKey: 'ai.tab_text_desc', descFallback: 'Describe your project in plain text', color: 'from-blue-500/10 to-cyan-500/10 text-blue-600' },
  { id: 'photo', label: 'Photo / Scan', labelKey: 'ai.tab_photo', icon: <Camera size={22} />, descKey: 'ai.tab_photo_desc', descFallback: 'Building photo or scanned document', color: 'from-violet-500/10 to-purple-500/10 text-violet-600' },
  { id: 'pdf', label: 'PDF', labelKey: 'ai.tab_pdf', icon: <FileText size={22} />, descKey: 'ai.tab_pdf_desc', descFallback: 'BOQ sheets, specs, tender docs', color: 'from-red-500/10 to-orange-500/10 text-red-600' },
  { id: 'excel', label: 'Excel / CSV', labelKey: 'ai.tab_excel', icon: <FileSpreadsheet size={22} />, descKey: 'ai.tab_excel_desc', descFallback: 'Spreadsheet with BOQ data', color: 'from-green-500/10 to-emerald-500/10 text-green-600' },
  { id: 'paste', label: 'Paste', labelKey: 'ai.tab_paste', icon: <ClipboardPaste size={22} />, descKey: 'ai.tab_paste_desc', descFallback: 'Copy-paste from any app', color: 'from-slate-500/10 to-gray-500/10 text-slate-600' },
];

// ── Option data ──────────────────────────────────────────────────────────────

const BUILDING_TYPES = [
  { value: '', labelKey: 'ai.building_any', fallback: 'Any type' },
  { value: 'residential', labelKey: 'ai.building_residential', fallback: 'Residential' },
  { value: 'commercial_office', labelKey: 'ai.building_commercial', fallback: 'Commercial / Office' },
  { value: 'industrial', labelKey: 'ai.building_industrial', fallback: 'Industrial' },
  { value: 'retail', labelKey: 'ai.building_retail', fallback: 'Retail' },
  { value: 'healthcare', labelKey: 'ai.building_healthcare', fallback: 'Healthcare' },
  { value: 'education', labelKey: 'ai.building_education', fallback: 'Education' },
  { value: 'hospitality', labelKey: 'ai.building_hospitality', fallback: 'Hospitality' },
  { value: 'infrastructure', labelKey: 'ai.building_infrastructure', fallback: 'Infrastructure' },
  { value: 'mixed_use', labelKey: 'ai.building_mixed', fallback: 'Mixed Use' },
];

const STANDARDS: Array<{ value: string; label?: string; labelKey?: string; fallback?: string }> = [
  { value: '', labelKey: 'ai.standard_auto', fallback: 'Auto-detect' },
  { value: 'din276', label: 'DIN 276' },
  { value: 'nrm', label: 'NRM 1/2' },
  { value: 'masterformat', label: 'MasterFormat' },
  { value: 'uniformat', label: 'UniFormat' },
];

const CURRENCIES: Array<{ value: string; label?: string; labelKey?: string; fallback?: string }> = [
  { value: '', labelKey: 'ai.currency_auto', fallback: 'Auto' },
  { value: 'EUR', label: 'EUR' },
  { value: 'USD', label: 'USD' },
  { value: 'GBP', label: 'GBP' },
  { value: 'CHF', label: 'CHF' },
  { value: 'CAD', label: 'CAD' },
  { value: 'AUD', label: 'AUD' },
  { value: 'JPY', label: 'JPY' },
  { value: 'CNY', label: 'CNY' },
  { value: 'INR', label: 'INR' },
  { value: 'AED', label: 'AED' },
];

// ── File accept maps ─────────────────────────────────────────────────────────

type FileTab = 'photo' | 'pdf' | 'excel' | 'cad';

const ACCEPT_MAP: { [K in FileTab]: string } = {
  photo: '.jpg,.jpeg,.png,.tiff,.webp',
  pdf: '.pdf',
  excel: '.xlsx,.xls,.csv',
  cad: '.rvt,.ifc,.dwg,.dgn',
};

const FORMAT_LABELS: { [K in FileTab]: string } = {
  photo: 'JPG, PNG, TIFF, WebP',
  pdf: 'PDF',
  excel: 'Excel (.xlsx), CSV (.csv)',
  cad: 'Revit (.rvt), IFC (.ifc), DWG (.dwg), DGN (.dgn)',
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatNumber(n: number, currency?: string): string {
  try {
    return new Intl.NumberFormat(getIntlLocale(), {
      style: currency ? 'currency' : 'decimal',
      currency: currency || undefined,
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    }).format(n);
  } catch {
    return n.toLocaleString();
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getFileExtension(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : '';
}

// ── Shimmer loading rows ─────────────────────────────────────────────────────

function ShimmerRow() {
  return (
    <tr className="animate-pulse">
      <td className="px-4 py-3">
        <div className="h-4 w-12 rounded bg-surface-tertiary" />
      </td>
      <td className="px-4 py-3">
        <div className="h-4 w-48 rounded bg-surface-tertiary" />
      </td>
      <td className="px-4 py-3">
        <div className="h-4 w-8 rounded bg-surface-tertiary" />
      </td>
      <td className="px-4 py-3 text-right">
        <div className="ml-auto h-4 w-14 rounded bg-surface-tertiary" />
      </td>
      <td className="px-4 py-3 text-right">
        <div className="ml-auto h-4 w-16 rounded bg-surface-tertiary" />
      </td>
      <td className="px-4 py-3 text-right">
        <div className="ml-auto h-4 w-20 rounded bg-surface-tertiary" />
      </td>
    </tr>
  );
}

function LoadingState() {
  const { t } = useTranslation();
  return (
    <div className="animate-card-in" style={{ animationDelay: '100ms' }}>
      <Card>
        <div className="px-6 pt-6 pb-2">
          <div className="flex items-center gap-3 mb-4">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-oe-blue-subtle">
              <Sparkles size={16} className="text-oe-blue animate-pulse" />
            </div>
            <div>
              <p className="text-sm font-semibold text-content-primary">
                {t('ai.analyzing', { defaultValue: 'AI is analyzing your input...' })}
              </p>
              <p className="text-xs text-content-tertiary">
                {t('ai.generating', { defaultValue: 'Generating cost breakdown and quantities' })}
              </p>
            </div>
          </div>
          <div className="h-1 w-full overflow-hidden rounded-full bg-surface-secondary">
            <div className="h-full w-1/3 animate-shimmer rounded-full bg-oe-blue opacity-60 bg-[length:200%_100%]" />
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light text-left">
                <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide">
                  {t('boq.pos', { defaultValue: 'Pos' })}
                </th>
                <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide">
                  {t('boq.description', { defaultValue: 'Description' })}
                </th>
                <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide">
                  {t('boq.unit', { defaultValue: 'Unit' })}
                </th>
                <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide text-right">
                  {t('boq.quantity', { defaultValue: 'Qty' })}
                </th>
                <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide text-right">
                  {t('boq.unit_rate', { defaultValue: 'Rate' })}
                </th>
                <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide text-right">
                  {t('boq.total', { defaultValue: 'Total' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: 8 }).map((_, i) => (
                <ShimmerRow key={i} />
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

// ── Save to BOQ dialog ───────────────────────────────────────────────────────

interface SaveDialogProps {
  open: boolean;
  onClose: () => void;
  onSave: (projectId: string, boqName: string) => void;
  saving: boolean;
}

interface ProjectSummary {
  id: string;
  name: string;
}

function SaveToBOQDialog({ open, onClose, onSave, saving }: SaveDialogProps) {
  const { t } = useTranslation();
  const [selectedProject, setSelectedProject] = useState('');
  const [boqName, setBOQName] = useState('AI Quick Estimate');

  const { data: projects } = useQuery({
    queryKey: ['projects-list-simple'],
    queryFn: () => apiGet<ProjectSummary[]>('/v1/projects/?page_size=100'),
    enabled: open,
  });

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" aria-hidden="true" onClick={onClose} />
      <div role="dialog" aria-modal="true" aria-labelledby="save-boq-dialog-title" className="relative w-full max-w-md animate-card-in rounded-2xl border border-border-light bg-surface-elevated p-6 shadow-xl">
        <h3 id="save-boq-dialog-title" className="text-lg font-semibold text-content-primary mb-4">
          {t('ai.save_to_boq', { defaultValue: 'Save as BOQ' })}
        </h3>

        <div className="space-y-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-content-primary">
              {t('ai.select_project', { defaultValue: 'Select Project' })}
            </label>
            <select
              value={selectedProject}
              onChange={(e) => setSelectedProject(e.target.value)}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary cursor-pointer appearance-none"
            >
              <option value="" disabled>
                {t('ai.choose_project', { defaultValue: '-- Choose a project --' })}
              </option>
              {projects?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-content-primary">
              {t('ai.boq_name', { defaultValue: 'BOQ Name' })}
            </label>
            <input
              type="text"
              value={boqName}
              onChange={(e) => setBOQName(e.target.value)}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent transition-all duration-fast ease-oe hover:border-content-tertiary"
              placeholder={t('ai.boq_name_placeholder', { defaultValue: 'Name for this BOQ...' })}
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 mt-6">
          <Button variant="secondary" onClick={onClose} disabled={saving}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => onSave(selectedProject, boqName)}
            disabled={!selectedProject || !boqName.trim() || saving}
            loading={saving}
            icon={<Save size={15} />}
          >
            {t('ai.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Results table ────────────────────────────────────────────────────────────

function ResultsTable({ result, selectedCurrency, enrichResult }: { result: EstimateJobResponse; selectedCurrency?: string; enrichResult?: EnrichResult | null }) {
  const { t } = useTranslation();
  const currency = selectedCurrency || result.currency || 'EUR';

  // Build a lookup map from enrichment results by index
  const enrichMap = new Map<number, EnrichedItem>();
  if (enrichResult?.items) {
    for (const ei of enrichResult.items) {
      enrichMap.set(ei.index, ei);
    }
  }

  let currentCategory = '';

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border-light text-left">
            <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide w-20">
              {t('ai.col_pos', { defaultValue: 'Pos' })}
            </th>
            <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide">
              {t('ai.col_description', { defaultValue: 'Description' })}
            </th>
            <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide w-16">
              {t('ai.col_unit', { defaultValue: 'Unit' })}
            </th>
            <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide text-right w-24">
              {t('ai.col_qty', { defaultValue: 'Qty' })}
            </th>
            <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide text-right w-28">
              {t('ai.col_rate', { defaultValue: 'Unit Rate' })}
            </th>
            <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide text-right w-32">
              {t('ai.col_total', { defaultValue: 'Total' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {result.items.map((item: EstimateItem, idx: number) => {
            const showCategory = item.category && item.category !== currentCategory;
            if (item.category) currentCategory = item.category;
            const enriched = enrichMap.get(idx);
            const bestMatch = enriched?.best_match ?? null;

            return (
              <>
                {showCategory && (
                  <tr key={`cat-${idx}`} className="bg-surface-secondary/50">
                    <td
                      colSpan={6}
                      className="px-4 py-2 text-xs font-semibold text-content-secondary uppercase tracking-wider"
                    >
                      {item.category}
                    </td>
                  </tr>
                )}
                <tr
                  key={item.ordinal}
                  className="border-b border-border-light/50 transition-colors duration-fast hover:bg-surface-secondary/30"
                  style={{ animationDelay: `${idx * 30}ms` }}
                >
                  <td className="px-4 py-3 font-mono text-xs text-content-tertiary">
                    {item.ordinal}
                  </td>
                  <td className="px-4 py-3 text-content-primary">
                    {item.description}
                    {Object.keys(item.classification).length > 0 && (
                      <div className="mt-0.5 flex gap-1">
                        {Object.entries(item.classification).map(([std, code]) => (
                          <Badge key={std} variant="neutral" size="sm">
                            {std}: {code}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-content-secondary">{item.unit}</td>
                  <td className="px-4 py-3 text-right font-mono text-content-primary">
                    {formatNumber(item.quantity)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-content-secondary">
                    {bestMatch ? (
                      <div className="flex flex-col items-end gap-0.5">
                        <span className="line-through text-content-quaternary text-xs">
                          {formatNumber(item.unit_rate)}
                        </span>
                        <span className="text-emerald-600 font-semibold" title={`CWICR: ${bestMatch.code} (${Math.round(bestMatch.score * 100)}% match)`}>
                          {formatNumber(bestMatch.rate)}
                        </span>
                        <span className="text-[10px] text-emerald-600/70 font-normal">
                          {bestMatch.code}
                        </span>
                      </div>
                    ) : (
                      formatNumber(item.unit_rate)
                    )}
                  </td>
                  <td className="px-4 py-3 text-right font-mono font-medium text-content-primary">
                    {bestMatch ? (
                      <div className="flex flex-col items-end gap-0.5">
                        <span className="line-through text-content-quaternary text-xs">
                          {formatNumber(item.total)}
                        </span>
                        <span className="text-emerald-600 font-semibold">
                          {formatNumber(item.quantity * bestMatch.rate)}
                        </span>
                      </div>
                    ) : (
                      formatNumber(item.total)
                    )}
                  </td>
                </tr>
              </>
            );
          })}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-border">
            <td
              colSpan={5}
              className="px-4 py-4 text-right text-base font-semibold text-content-primary"
            >
              {t('ai.grand_total', { defaultValue: 'Grand Total' })}
            </td>
            <td className="px-4 py-4 text-right font-mono text-lg font-bold text-oe-blue">
              {enrichMap.size > 0 ? (
                <div className="flex flex-col items-end gap-0.5">
                  <span className="line-through text-content-quaternary text-sm font-normal">
                    {formatNumber(result.grand_total, currency)}
                  </span>
                  <span className="text-emerald-600">
                    {formatNumber(
                      result.items.reduce((sum, item, idx) => {
                        const ei = enrichMap.get(idx);
                        return sum + item.quantity * (ei?.best_match?.rate ?? item.unit_rate);
                      }, 0),
                      currency,
                    )}
                  </span>
                </div>
              ) : (
                formatNumber(result.grand_total, currency)
              )}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

// ── Quantity Tables result (CAD extraction, no AI) ──────────────────────────

function QuantityTablesResult({ data }: { data: CadExtractResponse }) {
  const { t } = useTranslation();
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(
    () => new Set(data.groups.map((g) => g.category)),
  );

  const toggleGroup = (cat: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  const fmtNum = (v: number) => {
    if (v === 0) return '-';
    return v.toLocaleString(getIntlLocale(), { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  };

  return (
    <div className="space-y-3">
      {data.groups.map((group) => {
        const isExpanded = expandedGroups.has(group.category);
        return (
          <div
            key={group.category}
            className="rounded-xl border border-border-light overflow-hidden"
          >
            {/* Category header */}
            <button
              type="button"
              onClick={() => toggleGroup(group.category)}
              className="w-full flex items-center gap-3 px-4 py-3 bg-surface-secondary/50 hover:bg-surface-secondary transition-colors text-left"
            >
              {isExpanded ? (
                <ChevronDown size={16} className="text-content-tertiary shrink-0" />
              ) : (
                <ChevronRight size={16} className="text-content-tertiary shrink-0" />
              )}
              <span className="text-sm font-semibold text-content-primary flex-1">
                {group.category}
              </span>
              <span className="text-xs text-content-tertiary">
                {group.items.length} {group.items.length === 1 ? 'type' : 'types'}
              </span>
              <div className="flex items-center gap-3 text-xs text-content-tertiary ml-3">
                {group.totals.count > 0 && (
                  <span>{fmtNum(group.totals.count)} pcs</span>
                )}
                {group.totals.volume_m3 > 0 && (
                  <span>{fmtNum(group.totals.volume_m3)} m&sup3;</span>
                )}
                {group.totals.area_m2 > 0 && (
                  <span>{fmtNum(group.totals.area_m2)} m&sup2;</span>
                )}
                {group.totals.length_m > 0 && (
                  <span>{fmtNum(group.totals.length_m)} m</span>
                )}
              </div>
            </button>

            {/* Items table */}
            {isExpanded && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border-light/50 text-left">
                      <th className="px-4 py-2 text-xs font-semibold text-content-tertiary uppercase tracking-wide">
                        {t('ai.cad_col_type', { defaultValue: 'Type' })}
                      </th>
                      <th className="px-4 py-2 text-xs font-semibold text-content-tertiary uppercase tracking-wide">
                        {t('ai.cad_col_material', { defaultValue: 'Material' })}
                      </th>
                      <th className="px-4 py-2 text-xs font-semibold text-content-tertiary uppercase tracking-wide text-right w-20">
                        {t('ai.cad_col_count', { defaultValue: 'Count' })}
                      </th>
                      <th className="px-4 py-2 text-xs font-semibold text-content-tertiary uppercase tracking-wide text-right w-28">
                        {t('ai.cad_col_volume', { defaultValue: 'Volume (m\u00b3)' })}
                      </th>
                      <th className="px-4 py-2 text-xs font-semibold text-content-tertiary uppercase tracking-wide text-right w-28">
                        {t('ai.cad_col_area', { defaultValue: 'Area (m\u00b2)' })}
                      </th>
                      <th className="px-4 py-2 text-xs font-semibold text-content-tertiary uppercase tracking-wide text-right w-24">
                        {t('ai.cad_col_length', { defaultValue: 'Length (m)' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.items.map((item, idx) => (
                      <tr
                        key={idx}
                        className="border-b border-border-light/30 hover:bg-surface-secondary/20 transition-colors"
                      >
                        <td className="px-4 py-2 text-content-primary">{item.type}</td>
                        <td className="px-4 py-2 text-content-secondary text-xs">{item.material || '-'}</td>
                        <td className="px-4 py-2 text-right font-mono text-content-primary">{fmtNum(item.count)}</td>
                        <td className="px-4 py-2 text-right font-mono text-content-primary">{fmtNum(item.volume_m3)}</td>
                        <td className="px-4 py-2 text-right font-mono text-content-primary">{fmtNum(item.area_m2)}</td>
                        <td className="px-4 py-2 text-right font-mono text-content-primary">{fmtNum(item.length_m)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="border-t border-border bg-surface-secondary/30">
                      <td colSpan={2} className="px-4 py-2 text-xs font-semibold text-content-secondary uppercase">
                        {t('ai.cad_subtotal', { defaultValue: 'Subtotal' })}
                      </td>
                      <td className="px-4 py-2 text-right font-mono font-semibold text-content-primary">{fmtNum(group.totals.count)}</td>
                      <td className="px-4 py-2 text-right font-mono font-semibold text-content-primary">{fmtNum(group.totals.volume_m3)}</td>
                      <td className="px-4 py-2 text-right font-mono font-semibold text-content-primary">{fmtNum(group.totals.area_m2)}</td>
                      <td className="px-4 py-2 text-right font-mono font-semibold text-content-primary">{fmtNum(group.totals.length_m)}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
          </div>
        );
      })}

      {/* Grand totals */}
      <div className="rounded-xl border-2 border-oe-blue/20 bg-oe-blue-subtle/30 px-4 py-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-bold text-content-primary">
            {t('ai.cad_grand_total', { defaultValue: 'Grand Total' })}
          </span>
          <div className="flex items-center gap-4 text-sm font-mono font-bold text-oe-blue">
            {data.grand_totals.count > 0 && <span>{fmtNum(data.grand_totals.count)} pcs</span>}
            {data.grand_totals.volume_m3 > 0 && <span>{fmtNum(data.grand_totals.volume_m3)} m&sup3;</span>}
            {data.grand_totals.area_m2 > 0 && <span>{fmtNum(data.grand_totals.area_m2)} m&sup2;</span>}
            {data.grand_totals.length_m > 0 && <span>{fmtNum(data.grand_totals.length_m)} m</span>}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Drop Zone (reusable file upload area) ────────────────────────────────────

function FileDropZone({
  accept,
  formatLabel,
  onFileSelect,
  disabled,
  hint,
}: {
  accept: string;
  formatLabel: string;
  onFileSelect: (file: File) => void;
  disabled?: boolean;
  hint?: string;
}) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (disabled) return;
      const file = e.dataTransfer.files?.[0];
      if (file) onFileSelect(file);
    },
    [onFileSelect, disabled],
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) onFileSelect(file);
      e.target.value = '';
    },
    [onFileSelect],
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      onClick={() => !disabled && inputRef.current?.click()}
      className={`
        flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed
        px-6 py-8 text-center cursor-pointer transition-all duration-200
        ${dragOver ? 'border-oe-blue bg-oe-blue-subtle/30 scale-[1.01]' : 'border-border-light hover:border-content-tertiary hover:bg-surface-secondary/50'}
        ${disabled ? 'opacity-50 pointer-events-none' : ''}
      `}
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-surface-secondary">
        <Upload size={22} className="text-content-tertiary" strokeWidth={1.5} />
      </div>
      <div>
        <p className="text-sm font-medium text-content-primary">
          {t('ai.drop_file', { defaultValue: 'Drop your file here, or click to browse' })}
        </p>
        <p className="mt-1 text-xs text-content-tertiary">
          {t('ai.supported_formats', { defaultValue: 'Supports: {{formats}}', formats: formatLabel })}
        </p>
        {hint && <p className="mt-1 text-xs text-content-tertiary">{hint}</p>}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={handleChange}
        disabled={disabled}
      />
    </div>
  );
}

// ── File preview (shows selected file with remove option) ────────────────────

function FilePreview({
  file,
  imagePreviewUrl,
  onRemove,
  disabled,
}: {
  file: File;
  imagePreviewUrl: string | null;
  onRemove: () => void;
  disabled?: boolean;
}) {
  const ext = getFileExtension(file.name);
  const isImage = ['jpg', 'jpeg', 'png', 'tiff', 'webp', 'gif'].includes(ext);

  const iconForExt = () => {
    if (isImage) return <ImageIcon size={20} className="text-oe-blue" />;
    if (ext === 'pdf') return <FileText size={20} className="text-red-500" />;
    if (['xlsx', 'xls', 'csv'].includes(ext))
      return <FileSpreadsheet size={20} className="text-green-600" />;
    if (['rvt', 'ifc', 'dwg', 'dgn'].includes(ext))
      return <FileArchive size={20} className="text-amber-600" />;
    return <FileText size={20} className="text-content-tertiary" />;
  };

  return (
    <div className="mt-4 flex items-center gap-3 rounded-xl bg-surface-secondary px-4 py-3">
      {imagePreviewUrl ? (
        <img
          src={imagePreviewUrl}
          alt={file.name}
          className="h-14 w-14 shrink-0 rounded-lg object-cover border border-border-light"
        />
      ) : (
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-surface-primary border border-border-light">
          {iconForExt()}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-content-primary truncate">{file.name}</p>
        <p className="text-xs text-content-tertiary">
          {formatFileSize(file.size)}
          {ext && (
            <>
              {' '}
              <Badge variant="neutral" size="sm" className="ml-1">
                .{ext}
              </Badge>
            </>
          )}
        </p>
      </div>
      {!disabled && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-tertiary hover:text-content-primary transition-colors"
        >
          <X size={16} />
        </button>
      )}
    </div>
  );
}

// ── Selector row (location + currency, compact) ──────────────────────────────

function CompactOptions({
  location,
  setLocation,
  currency,
  setCurrency,
  standard,
  setStandard,
  disabled,
}: {
  location: string;
  setLocation: (v: string) => void;
  currency: string;
  setCurrency: (v: string) => void;
  standard: string;
  setStandard: (v: string) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const selectClass =
    'h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue hover:border-content-tertiary cursor-pointer appearance-none';
  const inputClass =
    'h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all duration-fast ease-oe hover:border-content-tertiary';

  return (
    <div className="mt-4 grid grid-cols-3 gap-3">
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
          {t('ai.location', { defaultValue: 'Location' })}
        </label>
        <input
          type="text"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          placeholder={t('ai.location_placeholder', { defaultValue: 'e.g. Berlin' })}
          className={inputClass}
          disabled={disabled}
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
          {t('ai.currency_label', { defaultValue: 'Currency' })}
        </label>
        <select
          value={currency}
          onChange={(e) => setCurrency(e.target.value)}
          className={selectClass}
          disabled={disabled}
        >
          {CURRENCIES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
          {t('ai.standard_label', { defaultValue: 'Standard' })}
        </label>
        <select
          value={standard}
          onChange={(e) => setStandard(e.target.value)}
          className={selectClass}
          disabled={disabled}
        >
          {STANDARDS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

// ── Converter color map ──────────────────────────────────────────────────────

const CONVERTER_COLORS: Record<string, { bg: string; border: string; icon: string }> = {
  dwg: { bg: 'from-red-500/8 to-orange-500/8', border: 'border-red-200 dark:border-red-900/30', icon: 'bg-gradient-to-br from-red-500 to-orange-500' },
  rvt: { bg: 'from-blue-500/8 to-indigo-500/8', border: 'border-blue-200 dark:border-blue-900/30', icon: 'bg-gradient-to-br from-blue-500 to-indigo-500' },
  ifc: { bg: 'from-emerald-500/8 to-green-500/8', border: 'border-emerald-200 dark:border-emerald-900/30', icon: 'bg-gradient-to-br from-emerald-500 to-green-500' },
  dgn: { bg: 'from-purple-500/8 to-violet-500/8', border: 'border-purple-200 dark:border-purple-900/30', icon: 'bg-gradient-to-br from-purple-500 to-violet-500' },
};

// ── Full Converter Section (for /cad-takeoff) ──────────────────────────────

interface CadConverterSectionProps {
  converters: { id: string; name: string; description: string; engine: string; extensions: string[]; exe: string; version: string; size_mb: number; installed: boolean; path: string | null }[];
  installedCount: number;
  totalCount: number;
  installingId: string | null;
  installElapsed: number;
  installResult: { message: string } | null;
  installError: string | null;
  onInstall: (c: CadConverterSectionProps['converters'][0]) => void;
  onUninstall: (c: CadConverterSectionProps['converters'][0]) => void;
  onDismissProgress: () => void;
  t: ReturnType<typeof useTranslation>['t'];
}

function CadConverterSection({
  converters, installedCount, totalCount,
  installingId, installElapsed, installResult, installError,
  onInstall, onUninstall, onDismissProgress, t,
}: CadConverterSectionProps) {
  const installingName = converters.find((c) => c.id === installingId)?.name ?? '';

  // Progress phase simulation
  const phase = installElapsed < 5 ? 0 : installElapsed < 15 ? 1 : installElapsed < 30 ? 2 : 3;
  const phaseLabels = [
    t('quantities.phase_downloading', { defaultValue: 'Downloading from GitHub...' }),
    t('quantities.phase_extracting', { defaultValue: 'Extracting converter files...' }),
    t('quantities.phase_verifying', { defaultValue: 'Verifying executable...' }),
    t('quantities.phase_finalizing', { defaultValue: 'Finalizing...' }),
  ];
  const progressPct = installError ? 100 : installResult ? 100
    : !installingId ? 0
    : Math.min(95, phase === 0 ? installElapsed * 8 : phase === 1 ? 40 + (installElapsed - 5) * 3 : phase === 2 ? 70 + (installElapsed - 15) * 1.5 : 92 + (installElapsed - 30) * 0.1);

  return (
    <div className="mt-6 space-y-4">
      {/* Section header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <HardHat size={18} className="text-oe-blue" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('ai.cad_converters_title', { defaultValue: 'DDC Converter Modules' })}
          </h3>
          <Badge variant={installedCount > 0 ? 'success' : 'warning'} size="sm">
            {installedCount}/{totalCount} {t('ai.cad_installed', { defaultValue: 'installed' })}
          </Badge>
        </div>
      </div>

      {/* How it works */}
      <div className="flex items-center gap-4 text-xs text-content-tertiary">
        {[
          { num: '1', label: t('ai.cad_step_upload', { defaultValue: 'Upload CAD/BIM file' }) },
          { num: '2', label: t('ai.cad_step_convert', { defaultValue: 'Auto-convert via DDC' }) },
          { num: '3', label: t('ai.cad_step_extract', { defaultValue: 'Get quantities & elements' }) },
        ].map((s, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-oe-blue/10 text-2xs font-bold text-oe-blue">
              {s.num}
            </span>
            <span>{s.label}</span>
            {i < 2 && <ArrowRight size={12} className="text-content-quaternary ml-1" />}
          </div>
        ))}
      </div>

      {/* Install progress panel */}
      {(installingId || installResult || installError) && (
        <div className="rounded-xl border border-border-light bg-surface-elevated overflow-hidden shadow-sm">
          <div className="px-4 pt-4 pb-3">
            <div className="flex items-center gap-3 mb-3">
              {installError ? (
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-red-50 dark:bg-red-900/20">
                  <XCircle size={20} className="text-red-500" />
                </div>
              ) : installResult ? (
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-semantic-success-bg">
                  <CheckCircle2 size={20} className="text-semantic-success" />
                </div>
              ) : (
                <div className="relative flex h-9 w-9 items-center justify-center rounded-lg bg-oe-blue-subtle">
                  <HardDrive size={18} className="text-oe-blue" />
                  <div className="absolute -top-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-oe-blue animate-ping" />
                  <div className="absolute -top-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-oe-blue" />
                </div>
              )}
              <div className="flex-1 min-w-0">
                <h4 className="text-sm font-semibold text-content-primary">
                  {installError ? t('quantities.install_failed', { defaultValue: 'Installation failed' })
                    : installResult ? t('quantities.install_success', { defaultValue: 'Converter installed successfully' })
                    : t('quantities.installing_converter', { defaultValue: `Installing ${installingName}...`, name: installingName })}
                </h4>
                <p className="text-xs text-content-tertiary mt-0.5">
                  {installError ?? (installResult ? t('quantities.install_ready', { defaultValue: 'Converter is ready to use.' }) : phaseLabels[phase])}
                </p>
              </div>
              {(installResult || installError) && (
                <button onClick={onDismissProgress} className="text-content-quaternary hover:text-content-secondary">
                  <X size={16} />
                </button>
              )}
            </div>
            {/* Progress bar */}
            <div className="h-2 w-full overflow-hidden rounded-full bg-surface-secondary">
              <div
                className={clsx(
                  'h-full rounded-full transition-all duration-1000 ease-out',
                  installError ? 'bg-red-500' : installResult ? 'bg-semantic-success' : 'bg-gradient-to-r from-oe-blue via-blue-400 to-oe-blue bg-[length:200%_100%] animate-shimmer',
                )}
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
        </div>
      )}

      {/* Converter cards grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {converters.map((c) => {
          const colors = CONVERTER_COLORS[c.id] ?? CONVERTER_COLORS['dwg']!;
          const isInstalling = installingId === c.id;
          return (
            <div
              key={c.id}
              className={clsx(
                'group relative flex flex-col rounded-xl border p-4 transition-all duration-200',
                c.installed
                  ? 'border-emerald-300 dark:border-emerald-800/50 bg-gradient-to-br from-emerald-500/5 to-teal-500/5'
                  : clsx('bg-gradient-to-br', colors.bg, colors.border),
              )}
            >
              {/* Recommended badge */}
              {!c.installed && !isInstalling && (
                <div className="absolute -top-2 left-3 z-10">
                  <span className="inline-flex items-center gap-1 rounded-full bg-gradient-to-r from-amber-400 to-orange-500 px-2 py-0.5 text-2xs font-bold text-white shadow-sm">
                    <Star size={9} />
                    {t('quantities.recommended', { defaultValue: 'Recommended' })}
                  </span>
                </div>
              )}

              {/* Status badge */}
              <div className="absolute top-2.5 right-2.5">
                {isInstalling ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 dark:bg-blue-900/30 px-2 py-0.5 text-2xs font-semibold text-blue-700 dark:text-blue-400">
                    <Loader2 size={10} className="animate-spin" />
                    {t('quantities.converter_installing', { defaultValue: 'Installing...' })}
                  </span>
                ) : c.installed ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 dark:bg-emerald-900/30 px-2 py-0.5 text-2xs font-semibold text-emerald-700 dark:text-emerald-400">
                    <CheckCircle2 size={10} />
                    {t('quantities.converter_installed', { defaultValue: 'Installed' })}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 dark:bg-amber-900/30 px-2 py-0.5 text-2xs font-semibold text-amber-700 dark:text-amber-400">
                    <Download size={10} />
                    {t('quantities.converter_available', { defaultValue: 'Available' })}
                  </span>
                )}
              </div>

              {/* Icon + Name */}
              <div className="flex items-center gap-3">
                <div className={clsx('flex h-9 w-9 items-center justify-center rounded-lg text-white', c.installed ? 'bg-gradient-to-br from-emerald-500 to-teal-500' : colors.icon)}>
                  <FileInput size={18} strokeWidth={1.75} />
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-content-primary">{c.name}</h4>
                  <p className="text-2xs text-content-quaternary">{c.engine}</p>
                </div>
              </div>

              {/* Description */}
              <p className="mt-2 text-xs text-content-tertiary leading-relaxed line-clamp-2">{c.description}</p>

              {/* Extensions */}
              <div className="mt-2 flex flex-wrap gap-1">
                {c.extensions.map((ext) => (
                  <span key={ext} className="inline-flex rounded bg-surface-tertiary px-1.5 py-0.5 text-2xs font-mono text-content-secondary">
                    {ext}
                  </span>
                ))}
              </div>

              {/* Footer */}
              <div className="mt-3 flex items-center justify-between pt-2 border-t border-border-light">
                <span className="text-2xs text-content-quaternary">
                  v{c.version} &middot; {c.size_mb >= 1024 ? `${(c.size_mb / 1024).toFixed(1)} GB` : `${c.size_mb} MB`}
                </span>
                {c.installed ? (
                  <button
                    onClick={() => onUninstall(c)}
                    disabled={!!installingId}
                    className="inline-flex items-center gap-1 rounded bg-red-50 dark:bg-red-900/20 px-2 py-1 text-2xs font-medium text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/30 transition-colors"
                  >
                    <Trash2 size={10} />
                    {t('quantities.uninstall', { defaultValue: 'Uninstall' })}
                  </button>
                ) : (
                  <button
                    onClick={() => onInstall(c)}
                    disabled={!!installingId}
                    className="inline-flex items-center gap-1 rounded bg-oe-blue/10 px-2 py-1 text-2xs font-medium text-oe-blue hover:bg-oe-blue/20 transition-colors"
                  >
                    {isInstalling ? <Loader2 size={10} className="animate-spin" /> : <Download size={10} />}
                    {t('quantities.install_with_size', { defaultValue: 'Install ({{size}} MB)', size: c.size_mb })}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Info note */}
      <div className="flex items-start gap-2 rounded-lg bg-oe-blue-subtle/50 px-3 py-2.5">
        <Info size={14} className="shrink-0 mt-0.5 text-oe-blue" />
        <p className="text-xs text-oe-blue leading-relaxed">
          {t('ai.cad_module_info_extract', {
            defaultValue: 'CAD/BIM files are converted using DDC converters and quantities are extracted directly — no AI API key required.',
          })}
        </p>
      </div>
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

export function QuickEstimatePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  // Active tab — read initial value from ?tab= URL param
  const [searchParams] = useSearchParams();
  const routeLocation = useLocation();
  const isCadRoute = routeLocation.pathname === '/cad-takeoff';
  const initialTab = isCadRoute ? 'cad' : ((searchParams.get('tab') as InputTab | null) ?? 'text');
  const [activeTab, setActiveTab] = useState<InputTab>(
    ['text', 'photo', 'pdf', 'excel', 'cad', 'paste'].includes(initialTab) ? initialTab : 'text',
  );

  // Text form state
  const [description, setDescription] = useState('');
  const [location, setLocation] = useState('');
  const [currency, setCurrency] = useState('');
  const [standard, setStandard] = useState('');
  const [buildingType, setBuildingType] = useState('');
  const [areaM2, setAreaM2] = useState('');

  // Paste form state
  const [pasteText, setPasteText] = useState('');

  // File state (shared across file tabs)
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);

  // Result state
  const [result, setResult] = useState<EstimateJobResponse | null>(null);
  const [cadResult, setCadResult] = useState<CadExtractResponse | null>(null);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);

  // CAD interactive grouping state
  const [cadColumnsData, setCadColumnsData] = useState<CadColumnsResponse | null>(null);
  const [selectedGroupBy, setSelectedGroupBy] = useState<string[]>([]);
  const [selectedSumCols, setSelectedSumCols] = useState<string[]>([]);
  const [cadGroupResult, setCadGroupResult] = useState<CadGroupResponse | null>(null);
  const [cadGrouping, setCadGrouping] = useState(false);
  const [activePreset, setActivePreset] = useState<string>('standard');
  const [showCustom, setShowCustom] = useState(false);
  const [hideEmptyGroups, setHideEmptyGroups] = useState(true);
  const [deletedGroupKeys, setDeletedGroupKeys] = useState<Set<string>>(new Set());

  // Cost DB enrichment state
  const [enrichRegion, setEnrichRegion] = useState('DE_BERLIN');
  const [enrichResult, setEnrichResult] = useState<EnrichResult | null>(null);
  const [enriching, setEnriching] = useState(false);

  // Check if AI is configured
  const { data: aiSettings } = useQuery({
    queryKey: ['ai-settings'],
    queryFn: aiApi.getSettings,
    retry: false,
  });

  const isConfigured = !!(
    aiSettings?.anthropic_api_key_set ||
    aiSettings?.openai_api_key_set ||
    aiSettings?.gemini_api_key_set
  );

  // ── Converter status (for CAD tab) ────────────────────────────────────
  interface ConverterFull {
    id: string;
    name: string;
    description: string;
    engine: string;
    extensions: string[];
    exe: string;
    version: string;
    size_mb: number;
    installed: boolean;
    path: string | null;
  }
  const { data: convertersData } = useQuery<{
    converters: ConverterFull[];
    installed_count: number;
    total_count: number;
  }>({
    queryKey: ['takeoff', 'converters'],
    queryFn: () => apiGet('/v1/takeoff/converters'),
    staleTime: 60_000,
    enabled: activeTab === 'cad' || isCadRoute,
  });

  // ── Converter install/uninstall state (for /cad-takeoff route) ──────
  const [installingId, setInstallingId] = useState<string | null>(null);
  const [installElapsed, setInstallElapsed] = useState(0);
  const [installResult, setInstallResult] = useState<{ message: string } | null>(null);
  const [installError, setInstallError] = useState<string | null>(null);

  useEffect(() => {
    if (!installingId) { setInstallElapsed(0); return; }
    const iv = setInterval(() => setInstallElapsed((e) => e + 1), 1000);
    return () => clearInterval(iv);
  }, [installingId]);

  const handleConverterInstall = useCallback(async (c: ConverterFull) => {
    setInstallingId(c.id);
    setInstallResult(null);
    setInstallError(null);
    try {
      const data = await apiPost<{ message: string }>(`/v1/takeoff/converters/${c.id}/install`);
      setInstallResult(data);
      addToast({ type: 'success', title: `${c.name} installed`, message: data.message });
      queryClient.invalidateQueries({ queryKey: ['takeoff', 'converters'] });
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Installation failed';
      setInstallError(msg);
      addToast({ type: 'error', title: `Failed to install ${c.name}`, message: msg });
    } finally {
      setInstallingId(null);
    }
  }, [addToast, queryClient]);

  const handleConverterUninstall = useCallback(async (c: ConverterFull) => {
    try {
      await apiPost(`/v1/takeoff/converters/${c.id}/uninstall`);
      addToast({ type: 'success', title: `${c.name} uninstalled` });
      queryClient.invalidateQueries({ queryKey: ['takeoff', 'converters'] });
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Uninstall failed';
      addToast({ type: 'error', title: `Failed to uninstall ${c.name}`, message: msg });
    }
  }, [addToast, queryClient]);

  // ── File selection handler ────────────────────────────────────────────

  const handleFileSelect = useCallback(
    (file: File) => {
      setSelectedFile(file);
      // Generate image preview for photo tab
      const ext = getFileExtension(file.name);
      if (['jpg', 'jpeg', 'png', 'webp', 'gif', 'tiff'].includes(ext)) {
        const url = URL.createObjectURL(file);
        setImagePreviewUrl(url);
      } else {
        setImagePreviewUrl(null);
      }
    },
    [],
  );

  const handleRemoveFile = useCallback(() => {
    if (imagePreviewUrl) {
      URL.revokeObjectURL(imagePreviewUrl);
    }
    setSelectedFile(null);
    setImagePreviewUrl(null);
  }, [imagePreviewUrl]);

  // ── Tab switching (clears file but keeps text/options) ────────────────

  const handleTabChange = useCallback(
    (tab: InputTab) => {
      setActiveTab(tab);
      // Clear file when switching tabs since accept types differ
      if (selectedFile) {
        handleRemoveFile();
      }
    },
    [selectedFile, handleRemoveFile],
  );

  // ── Text estimate mutation ────────────────────────────────────────────

  const textEstimateMutation = useMutation({
    mutationFn: aiApi.quickEstimate,
    onSuccess: (data) => {
      setResult(data);
      addToast({
        type: 'success',
        title: t('ai.estimate_complete', { defaultValue: 'Estimate generated' }),
        message: t('ai.estimate_complete_msg', {
          defaultValue: `${data.items.length} items in ${(data.duration_ms / 1000).toFixed(1)}s`,
          count: data.items.length,
          duration: (data.duration_ms / 1000).toFixed(1),
        }),
      });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('ai.estimate_failed', { defaultValue: 'Estimation failed' }),
        message: err.message,
      });
    },
  });

  // ── Photo estimate mutation ───────────────────────────────────────────

  const photoEstimateMutation = useMutation({
    mutationFn: aiApi.photoEstimate,
    onSuccess: (data) => {
      setResult(data);
      addToast({
        type: 'success',
        title: t('ai.estimate_complete', { defaultValue: 'Estimate generated' }),
        message: t('ai.estimate_complete_msg', {
          defaultValue: `${data.items.length} items in ${(data.duration_ms / 1000).toFixed(1)}s`,
          count: data.items.length,
          duration: (data.duration_ms / 1000).toFixed(1),
        }),
      });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('ai.estimate_failed', { defaultValue: 'Estimation failed' }),
        message: err.message,
      });
    },
  });

  // ── File estimate mutation (PDF, Excel, CSV, CAD) ───────────────────

  const fileEstimateMutation = useMutation({
    mutationFn: aiApi.fileEstimate,
    onSuccess: (data) => {
      setResult(data);
      addToast({
        type: 'success',
        title: t('ai.estimate_complete', { defaultValue: 'Estimate generated' }),
        message: t('ai.estimate_complete_msg', {
          defaultValue: `${data.items.length} items in ${(data.duration_ms / 1000).toFixed(1)}s`,
          count: data.items.length,
          duration: (data.duration_ms / 1000).toFixed(1),
        }),
      });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('ai.estimate_failed', { defaultValue: 'Estimation failed' }),
        message: err.message,
      });
    },
  });

  // ── CAD extract mutation (no AI, deterministic grouping) ────────────

  const cadExtractMutation = useMutation({
    mutationFn: aiApi.cadExtract,
    onSuccess: (data) => {
      setCadResult(data);
      addToast({
        type: 'success',
        title: t('ai.cad_extract_complete', { defaultValue: 'Quantities extracted' }),
        message: t('ai.cad_extract_msg', {
          defaultValue: `${data.total_elements} elements in ${data.groups.length} categories`,
          count: data.total_elements,
          groups: data.groups.length,
        }),
      });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('ai.cad_extract_failed', { defaultValue: 'CAD extraction failed' }),
        message: err.message,
      });
    },
  });

  // ── CAD columns mutation (interactive grouping step 1) ──────────────

  const cadColumnsMutation = useMutation({
    mutationFn: aiApi.cadColumns,
    onSuccess: (data) => {
      setCadColumnsData(data);
      // Auto-select the "standard" preset if available, else fall back to suggested
      const standardPreset = data.presets?.standard;
      if (standardPreset) {
        setActivePreset('standard');
        setSelectedGroupBy(standardPreset.group_by);
        setSelectedSumCols(standardPreset.sum_columns);
      } else {
        setSelectedGroupBy(data.suggested_grouping || []);
        setSelectedSumCols(data.suggested_quantities || []);
      }
      setShowCustom(false);
      addToast({
        type: 'success',
        title: t('ai.cad_columns_ready', { defaultValue: 'Columns detected' }),
        message: t('ai.cad_columns_msg', {
          defaultValue: `${data.total_elements} elements, ${data.columns.grouping.length + data.columns.quantity.length} columns available`,
          count: data.total_elements,
        }),
      });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('ai.cad_columns_failed', { defaultValue: 'Column detection failed' }),
        message: err.message,
      });
    },
  });

  // ── Save as BOQ mutation ──────────────────────────────────────────────

  const saveMutation = useMutation({
    mutationFn: ({ projectId, boqName }: { projectId: string; boqName: string }) => {
      if (!result) throw new Error('No estimate to save');
      return aiApi.createBOQFromEstimate(result.id, {
        project_id: projectId,
        boq_name: boqName,
      });
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      queryClient.invalidateQueries({ queryKey: ['boqs'] });
      setSaveDialogOpen(false);
      addToast({
        type: 'success',
        title: t('ai.boq_saved', { defaultValue: 'BOQ saved successfully' }),
      });
      navigate(`/boq/${data.boq_id}`);
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('ai.save_failed', { defaultValue: 'Failed to save BOQ' }),
        message: err.message,
      });
    },
  });

  // ── Cost DB enrichment handler ─────────────────────────────────────

  const handleEnrich = useCallback(async () => {
    if (!result?.id) return;
    setEnriching(true);
    try {
      const data = await aiApi.enrichEstimate(result.id, enrichRegion, currency || 'EUR');
      setEnrichResult(data);
      addToast({
        type: 'success',
        title: t('ai.enrich_complete', { defaultValue: 'Cost DB matching complete' }),
        message: t('ai.enrich_complete_msg', {
          defaultValue: 'Matched {{matched}}/{{total}} items',
          matched: data.total_matched,
          total: data.total_items,
        }),
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Enrichment failed';
      addToast({
        type: 'error',
        title: t('ai.enrich_failed', { defaultValue: 'Cost DB matching failed' }),
        message: msg,
      });
    } finally {
      setEnriching(false);
    }
  }, [result?.id, enrichRegion, currency, addToast, t]);

  // ── Determine if any mutation is pending ──────────────────────────────

  const isPending =
    textEstimateMutation.isPending || photoEstimateMutation.isPending || fileEstimateMutation.isPending || cadExtractMutation.isPending || cadColumnsMutation.isPending || cadGrouping;
  const isError =
    (textEstimateMutation.isError && !textEstimateMutation.isPending) ||
    (photoEstimateMutation.isError && !photoEstimateMutation.isPending) ||
    (fileEstimateMutation.isError && !fileEstimateMutation.isPending) ||
    (cadExtractMutation.isError && !cadExtractMutation.isPending) ||
    (cadColumnsMutation.isError && !cadColumnsMutation.isPending);
  const mutationError =
    (textEstimateMutation.error as Error | null) ||
    (photoEstimateMutation.error as Error | null) ||
    (fileEstimateMutation.error as Error | null) ||
    (cadExtractMutation.error as Error | null) ||
    (cadColumnsMutation.error as Error | null);

  // ── Submit handlers per tab ───────────────────────────────────────────

  const handleTextSubmit = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      if (!description.trim()) return;

      const request: QuickEstimateRequest = {
        description: description.trim(),
      };
      if (location.trim()) request.location = location.trim();
      if (currency) request.currency = currency;
      if (standard) request.standard = standard;
      if (buildingType) request.project_type = buildingType;
      if (areaM2 && Number(areaM2) > 0) request.area_m2 = Number(areaM2);

      setResult(null);
      textEstimateMutation.mutate(request);
    },
    [description, location, currency, standard, buildingType, areaM2, textEstimateMutation],
  );

  const handlePhotoSubmit = useCallback(() => {
    if (!selectedFile) return;
    setResult(null);
    photoEstimateMutation.mutate({
      file: selectedFile,
      location: location.trim() || undefined,
      currency: currency || undefined,
      standard: standard || undefined,
    });
  }, [selectedFile, location, currency, standard, photoEstimateMutation]);

  const handleFileSubmit = useCallback(() => {
    if (!selectedFile) return;
    setResult(null);
    fileEstimateMutation.mutate({
      file: selectedFile,
      location: location.trim() || undefined,
      currency: currency || undefined,
      standard: standard || undefined,
    });
  }, [selectedFile, location, currency, standard, fileEstimateMutation]);

  const handleCadSubmit = useCallback(() => {
    if (!selectedFile) return;
    setResult(null);
    setCadResult(null);
    setCadColumnsData(null);
    setCadGroupResult(null);
    if (isCadRoute) {
      cadColumnsMutation.mutate(selectedFile);
    } else {
      cadExtractMutation.mutate(selectedFile);
    }
  }, [selectedFile, cadExtractMutation, cadColumnsMutation, isCadRoute]);

  const handleApplyGrouping = useCallback(async () => {
    if (!cadColumnsData || selectedGroupBy.length === 0) return;
    setCadGrouping(true);
    try {
      const data = await aiApi.cadGroup({
        session_id: cadColumnsData.session_id,
        group_by: selectedGroupBy,
        sum_columns: selectedSumCols,
      });
      setCadGroupResult(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Grouping failed';
      addToast({
        type: 'error',
        title: t('ai.cad_group_failed', { defaultValue: 'Grouping failed' }),
        message: msg,
      });
    } finally {
      setCadGrouping(false);
    }
  }, [cadColumnsData, selectedGroupBy, selectedSumCols, addToast, t]);

  const toggleGroupByCol = useCallback((col: string) => {
    setSelectedGroupBy((prev) =>
      prev.includes(col) ? prev.filter((c) => c !== col) : [...prev, col],
    );
  }, []);

  const toggleSumCol = useCallback((col: string) => {
    setSelectedSumCols((prev) =>
      prev.includes(col) ? prev.filter((c) => c !== col) : [...prev, col],
    );
  }, []);

  const handlePasteSubmit = useCallback(() => {
    if (!pasteText.trim()) return;

    const request: QuickEstimateRequest = {
      description: `Parse the following BOQ/cost data and generate a structured estimate:\n\n${pasteText.trim()}`,
    };
    if (location.trim()) request.location = location.trim();
    if (currency) request.currency = currency;
    if (standard) request.standard = standard;

    setResult(null);
    textEstimateMutation.mutate(request);
  }, [pasteText, location, currency, standard, textEstimateMutation]);

  // ── Unified submit ────────────────────────────────────────────────────

  const handleSubmit = useCallback(
    (e?: FormEvent) => {
      if (e) e.preventDefault();
      switch (activeTab) {
        case 'text':
          handleTextSubmit(e ?? ({ preventDefault: () => {} } as FormEvent));
          break;
        case 'photo':
          handlePhotoSubmit();
          break;
        case 'pdf':
        case 'excel':
          handleFileSubmit();
          break;
        case 'cad':
          handleCadSubmit();
          break;
        case 'paste':
          handlePasteSubmit();
          break;
      }
    },
    [activeTab, handleTextSubmit, handlePhotoSubmit, handleFileSubmit, handleCadSubmit, handlePasteSubmit],
  );

  // ── Can submit check ──────────────────────────────────────────────────

  const canSubmit = (() => {
    if (isPending) return false;
    switch (activeTab) {
      case 'text':
        return !!description.trim();
      case 'photo':
      case 'pdf':
      case 'excel':
      case 'cad':
        return !!selectedFile;
      case 'paste':
        return !!pasteText.trim();
      default:
        return false;
    }
  })();

  // ── Submit button label ───────────────────────────────────────────────

  const submitLabel = (() => {
    if (isPending) return t('ai.generating', { defaultValue: 'Generating...' });
    switch (activeTab) {
      case 'text':
        return t('ai.generate', { defaultValue: 'Generate Estimate' });
      case 'photo':
        return t('ai.analyze_photo', { defaultValue: 'Analyze Photo' });
      case 'pdf':
        return t('ai.extract_estimate', { defaultValue: 'Extract & Estimate' });
      case 'excel':
        return t('ai.import_parse', { defaultValue: 'Import & Parse' });
      case 'cad':
        return t('ai.extract_quantities', { defaultValue: 'Extract Quantities' });
      case 'paste':
        return t('ai.parse_import', { defaultValue: 'Parse & Import' });
      default:
        return t('ai.generate', { defaultValue: 'Generate Estimate' });
    }
  })();

  // ── Reset ─────────────────────────────────────────────────────────────

  const handleReset = useCallback(() => {
    setResult(null);
    setCadResult(null);
    setEnrichResult(null);
    setCadColumnsData(null);
    setCadGroupResult(null);
    setSelectedGroupBy([]);
    setSelectedSumCols([]);
    setDeletedGroupKeys(new Set());
    setHideEmptyGroups(true);
    setDescription('');
    setLocation('');
    setCurrency('');
    setStandard('');
    setBuildingType('');
    setAreaM2('');
    setPasteText('');
    handleRemoveFile();
    textEstimateMutation.reset();
    photoEstimateMutation.reset();
    fileEstimateMutation.reset();
    cadExtractMutation.reset();
    cadColumnsMutation.reset();
  }, [handleRemoveFile, textEstimateMutation, photoEstimateMutation, fileEstimateMutation, cadExtractMutation, cadColumnsMutation]);

  const resetMutationErrors = useCallback(() => {
    textEstimateMutation.reset();
    photoEstimateMutation.reset();
    fileEstimateMutation.reset();
    cadExtractMutation.reset();
    cadColumnsMutation.reset();
  }, [textEstimateMutation, photoEstimateMutation, fileEstimateMutation, cadExtractMutation, cadColumnsMutation]);

  // ── Filtered groups for CAD QTO ──────────────────────────────────────
  const filteredGroups = useMemo(() => {
    if (!cadGroupResult?.groups) return [];
    let groups = cadGroupResult.groups.filter(g => !deletedGroupKeys.has(g.key));
    if (hideEmptyGroups) {
      groups = groups.filter(g => {
        const sumValues = Object.values(g.sums || {});
        return g.count > 0 && sumValues.some(v => v > 0);
      });
    }
    return groups;
  }, [cadGroupResult?.groups, hideEmptyGroups, deletedGroupKeys]);

  const computedTotals = useMemo(() => {
    let count = 0;
    const sums: Record<string, number> = {};
    for (const g of filteredGroups) {
      count += g.count;
      for (const [k, v] of Object.entries(g.sums || {})) {
        sums[k] = (sums[k] || 0) + v;
      }
    }
    return { count, sums };
  }, [filteredGroups]);

  const handleSaveQtoAsBOQ = useCallback(async () => {
    if (!filteredGroups.length) return;
    const sumCols = cadGroupResult?.sum_columns || [];
    const unitLabels = cadColumnsData?.unit_labels || {};

    // Build meaningful BOQ positions from grouped data
    const items = filteredGroups
      .filter(g => Object.values(g.sums || {}).some(v => v > 0))
      .map((g, i) => {
        // Clean description: remove OST_ prefix, join group parts
        const parts = Object.entries(g.key_parts || {}).map(([col, val]) =>
          col === 'category' ? (val || '').replace(/^OST_/, '') : val || '',
        );
        const description = parts.filter(Boolean).join(' — ');

        // Find primary quantity (volume > area > length > count)
        let unit = 'pcs';
        let quantity = g.count;
        for (const col of ['volume', 'area', 'length']) {
          if (sumCols.includes(col) && (g.sums[col] || 0) > 0) {
            unit = unitLabels[col] || col;
            quantity = Math.round((g.sums[col] ?? 0) * 100) / 100;
            break;
          }
        }

        return {
          ordinal: String(i + 1).padStart(3, '0'),
          description,
          unit,
          quantity,
          unit_rate: 0,
          metadata: { source: 'cad_qto', cad_category: g.key_parts?.category, count: g.count, sums: g.sums },
        };
      });

    sessionStorage.setItem('oe_qto_import', JSON.stringify({
      filename: cadColumnsData?.filename,
      items,
      groups: filteredGroups,
      group_by: cadGroupResult?.group_by,
      sum_columns: cadGroupResult?.sum_columns,
    }));
    addToast({
      type: 'success',
      title: t('ai.qto_saved', { defaultValue: 'QTO ready' }),
      message: t('ai.qto_saved_msg', { defaultValue: '{{count}} positions prepared for BOQ import', count: items.length }),
    });
  }, [filteredGroups, cadColumnsData, cadGroupResult, addToast, t]);

  // ── Render ────────────────────────────────────────────────────────────

  return (
    <div className="max-w-content mx-auto space-y-6">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-xs text-content-tertiary">
        <a href="/" className="hover:text-content-primary transition-colors">{t('nav.dashboard', { defaultValue: 'Dashboard' })}</a>
        <span className="text-content-quaternary">/</span>
        <span className="text-content-primary font-medium">
          {isCadRoute
            ? t('nav.cad_takeoff', { defaultValue: 'CAD/BIM Takeoff' })
            : t('nav.ai_estimate', { defaultValue: 'AI Estimate' })
          }
        </span>
      </nav>

      {/* Header */}
      <div className="animate-card-in" style={{ animationDelay: '0ms' }}>
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-oe-blue to-[#7c3aed] shadow-lg shadow-oe-blue/20">
            <Sparkles size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-content-primary">
              {isCadRoute
                ? t('ai.cad_takeoff_title', { defaultValue: 'CAD/BIM Takeoff' })
                : t('ai.estimate_title', { defaultValue: 'AI Estimate' })
              }
            </h1>
            <p className="text-sm text-content-secondary">
              {isCadRoute
                ? t('ai.cad_takeoff_subtitle', { defaultValue: 'Extract quantities from 3D models and drawings' })
                : t('ai.estimate_subtitle', { defaultValue: 'Create an estimate from any source' })
              }
            </p>
          </div>
        </div>
      </div>

      {/* AI Status Banner */}
      {aiSettings && !isConfigured ? (
        /* ── NOT CONFIGURED — prominent setup card ─── */
        <div
          className="animate-card-in rounded-2xl border-2 border-dashed border-oe-blue/30 bg-gradient-to-br from-oe-blue-subtle/60 to-surface-elevated p-6 text-center"
          style={{ animationDelay: '50ms' }}
        >
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-oe-blue/10">
            <Sparkles size={28} className="text-oe-blue" />
          </div>
          <h3 className="text-lg font-bold text-content-primary">
            {t('ai.setup_required_title', { defaultValue: 'Connect your AI to get started' })}
          </h3>
          <p className="mt-2 text-sm text-content-secondary max-w-md mx-auto">
            {t('ai.setup_required_desc', {
              defaultValue: 'Add your API key for Anthropic Claude, OpenAI, or Google Gemini to generate estimates from text, photos, PDFs, and CAD files.',
            })}
          </p>
          <div className="mt-5 flex items-center justify-center gap-3">
            <Button
              variant="primary"
              size="lg"
              onClick={() => navigate('/settings')}
              icon={<ArrowRight size={16} />}
              iconPosition="right"
              className="btn-shimmer"
            >
              {t('ai.configure_ai', { defaultValue: 'Configure AI Provider' })}
            </Button>
          </div>
          <div className="mt-4 flex items-center justify-center gap-4 text-xs text-content-tertiary">
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-content-tertiary" />
              Anthropic Claude
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-content-tertiary" />
              OpenAI GPT-4
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-content-tertiary" />
              Google Gemini
            </span>
          </div>
        </div>
      ) : aiSettings && isConfigured ? (
        /* ── CONFIGURED — green status bar ─── */
        <div
          className="animate-card-in flex items-center gap-3 rounded-xl bg-semantic-success-bg/60 border border-semantic-success/20 px-4 py-2.5"
          style={{ animationDelay: '50ms' }}
        >
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-semantic-success/20">
            <div className="h-2.5 w-2.5 rounded-full bg-semantic-success animate-pulse" />
          </div>
          <div className="flex-1 flex items-center gap-3">
            <span className="text-sm font-medium text-[#15803d]">
              {t('ai.connected', { defaultValue: 'AI Connected' })}
            </span>
            <span className="text-xs text-[#15803d]/70">
              {aiSettings.preferred_model || 'Claude'}
            </span>
          </div>
          <div className="flex items-center gap-2 text-2xs text-[#15803d]/60">
            <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-semantic-success" /> Text</span>
            <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-semantic-success" /> Photo</span>
            <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-semantic-success" /> PDF</span>
            <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-semantic-success" /> Excel</span>
          </div>
        </div>
      ) : null}

      {/* Source type selector (hidden on /cad-takeoff) */}
      {!isCadRoute && (
      <div className="animate-card-in" style={{ animationDelay: '100ms' }}>
        {/* Horizontal tab pills — single row */}
        <div className="grid grid-cols-5 gap-2">
          {TABS.map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => handleTabChange(tab.id)}
                disabled={isPending}
                className={`
                  flex flex-col items-center gap-1.5 rounded-xl px-2 py-3 text-center transition-all border
                  ${isActive
                    ? 'border-oe-blue bg-oe-blue-subtle/70 shadow-sm ring-1 ring-oe-blue/20'
                    : 'border-border-light bg-surface-elevated hover:border-border hover:bg-surface-secondary active:scale-[0.98]'
                  }
                  ${isPending ? 'opacity-50 pointer-events-none' : ''}
                `}
              >
                <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors ${isActive ? 'bg-oe-blue text-white' : 'bg-surface-secondary text-content-tertiary'}`}>
                  {tab.icon}
                </div>
                <div>
                  <div className={`text-xs font-semibold ${isActive ? 'text-oe-blue' : 'text-content-primary'}`}>
                    {t(tab.labelKey, { defaultValue: tab.label })}
                  </div>
                  <div className="text-2xs text-content-tertiary leading-tight mt-0.5">
                    {t(tab.descKey, { defaultValue: tab.descFallback })}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>
      )}

      {/* Input area for selected source */}
      <Card className="animate-card-in" style={{ animationDelay: '200ms' }} padding="none">

        {/* Tab content */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSubmit();
          }}
        >
          <div className="px-6 py-5">
            {/* ── Tab 1: Text Description ─────────────────────────── */}
            {activeTab === 'text' && (
              <div className="space-y-4">
                <div className="relative">
                  <textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder={t('ai.describe_placeholder', {
                      defaultValue:
                        'Describe your project...\n\nExample: "3-story residential building, 1200 m\u00b2 total area, reinforced concrete frame with brick facade, flat roof, standard MEP installations. Location: Berlin, Germany."',
                    })}
                    rows={5}
                    className="w-full rounded-xl border border-border bg-surface-primary px-4 py-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue focus:shadow-[0_0_0_4px_rgba(0,113,227,0.08)] transition-all duration-normal ease-oe hover:border-content-tertiary resize-none leading-relaxed"
                    disabled={isPending}
                  />
                  <div className="absolute bottom-3 right-3 text-xs text-content-tertiary">
                    {description.length > 0 && `${description.length} chars`}
                  </div>
                </div>

                {/* Full options row for text tab */}
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                      {t('ai.location', { defaultValue: 'Location' })}
                    </label>
                    <input
                      type="text"
                      value={location}
                      onChange={(e) => setLocation(e.target.value)}
                      placeholder={t('ai.location_placeholder', { defaultValue: 'e.g. Berlin' })}
                      className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all duration-fast ease-oe hover:border-content-tertiary"
                      disabled={isPending}
                    />
                  </div>

                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                      {t('ai.currency_label', { defaultValue: 'Currency' })}
                    </label>
                    <select
                      value={currency}
                      onChange={(e) => setCurrency(e.target.value)}
                      className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue hover:border-content-tertiary cursor-pointer appearance-none"
                      disabled={isPending}
                    >
                      {CURRENCIES.map((c) => (
                        <option key={c.value} value={c.value}>
                          {c.labelKey ? t(c.labelKey, { defaultValue: c.fallback ?? '' }) : c.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                      {t('ai.standard_label', { defaultValue: 'Standard' })}
                    </label>
                    <select
                      value={standard}
                      onChange={(e) => setStandard(e.target.value)}
                      className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue hover:border-content-tertiary cursor-pointer appearance-none"
                      disabled={isPending}
                    >
                      {STANDARDS.map((s) => (
                        <option key={s.value} value={s.value}>
                          {s.labelKey ? t(s.labelKey, { defaultValue: s.fallback ?? '' }) : s.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                      {t('ai.building_type', { defaultValue: 'Building Type' })}
                    </label>
                    <select
                      value={buildingType}
                      onChange={(e) => setBuildingType(e.target.value)}
                      className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue hover:border-content-tertiary cursor-pointer appearance-none"
                      disabled={isPending}
                    >
                      {BUILDING_TYPES.map((bt) => (
                        <option key={bt.value} value={bt.value}>
                          {t(bt.labelKey, { defaultValue: bt.fallback })}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="flex flex-col gap-1">
                    <label className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                      {t('ai.area', { defaultValue: 'Area (m\u00b2)' })}
                    </label>
                    <input
                      type="number"
                      min="0"
                      step="1"
                      value={areaM2}
                      onChange={(e) => setAreaM2(e.target.value)}
                      placeholder="1200"
                      className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all duration-fast ease-oe hover:border-content-tertiary"
                      disabled={isPending}
                    />
                  </div>
                </div>
              </div>
            )}

            {/* ── Tab 2: Photo / Scan ─────────────────────────────── */}
            {activeTab === 'photo' && (
              <div>
                {!selectedFile ? (
                  <FileDropZone
                    accept={ACCEPT_MAP.photo as string}
                    formatLabel={FORMAT_LABELS.photo as string}
                    onFileSelect={handleFileSelect}
                    disabled={isPending}
                  />
                ) : (
                  <FilePreview
                    file={selectedFile}
                    imagePreviewUrl={imagePreviewUrl}
                    onRemove={handleRemoveFile}
                    disabled={isPending}
                  />
                )}
                <CompactOptions
                  location={location}
                  setLocation={setLocation}
                  currency={currency}
                  setCurrency={setCurrency}
                  standard={standard}
                  setStandard={setStandard}
                  disabled={isPending}
                />
              </div>
            )}

            {/* ── Tab 3: PDF Document ─────────────────────────────── */}
            {activeTab === 'pdf' && (
              <div>
                {!selectedFile ? (
                  <FileDropZone
                    accept={ACCEPT_MAP.pdf as string}
                    formatLabel={FORMAT_LABELS.pdf as string}
                    onFileSelect={handleFileSelect}
                    disabled={isPending}
                    hint={t('ai.pdf_hint', {
                      defaultValue:
                        'Upload BOQ documents, specifications, or drawings in PDF format.',
                    })}
                  />
                ) : (
                  <FilePreview
                    file={selectedFile}
                    imagePreviewUrl={null}
                    onRemove={handleRemoveFile}
                    disabled={isPending}
                  />
                )}
                <CompactOptions
                  location={location}
                  setLocation={setLocation}
                  currency={currency}
                  setCurrency={setCurrency}
                  standard={standard}
                  setStandard={setStandard}
                  disabled={isPending}
                />
              </div>
            )}

            {/* ── Tab 4: Excel / CSV ──────────────────────────────── */}
            {activeTab === 'excel' && (
              <div>
                {!selectedFile ? (
                  <FileDropZone
                    accept={ACCEPT_MAP.excel as string}
                    formatLabel={FORMAT_LABELS.excel as string}
                    onFileSelect={handleFileSelect}
                    disabled={isPending}
                    hint={t('ai.excel_hint', {
                      defaultValue:
                        'Works best with columns: Description, Unit, Quantity, Rate/Price.',
                    })}
                  />
                ) : (
                  <FilePreview
                    file={selectedFile}
                    imagePreviewUrl={null}
                    onRemove={handleRemoveFile}
                    disabled={isPending}
                  />
                )}
                <CompactOptions
                  location={location}
                  setLocation={setLocation}
                  currency={currency}
                  setCurrency={setCurrency}
                  standard={standard}
                  setStandard={setStandard}
                  disabled={isPending}
                />
              </div>
            )}

            {/* ── Tab 5: CAD / BIM (direct extraction, no AI) ────── */}
            {activeTab === 'cad' && (
              <div>
                {!selectedFile ? (
                  <FileDropZone
                    accept={ACCEPT_MAP.cad as string}
                    formatLabel={FORMAT_LABELS.cad as string}
                    onFileSelect={handleFileSelect}
                    disabled={isPending}
                    hint={t('ai.cad_extract_hint', {
                      defaultValue: 'File will be converted and quantities extracted automatically — no AI key needed.',
                    })}
                  />
                ) : (
                  <FilePreview
                    file={selectedFile}
                    imagePreviewUrl={null}
                    onRemove={handleRemoveFile}
                    disabled={isPending}
                  />
                )}
                {/* ── DDC Converter Modules ─────────────────────── */}
                {isCadRoute ? (
                  /* Full converter management UI on /cad-takeoff */
                  <CadConverterSection
                    converters={convertersData?.converters ?? []}
                    installedCount={convertersData?.installed_count ?? 0}
                    totalCount={convertersData?.total_count ?? 4}
                    installingId={installingId}
                    installElapsed={installElapsed}
                    installResult={installResult}
                    installError={installError}
                    onInstall={handleConverterInstall}
                    onUninstall={handleConverterUninstall}
                    onDismissProgress={() => { setInstallResult(null); setInstallError(null); }}
                    t={t}
                  />
                ) : (
                  /* Compact status panel on /ai-estimate?tab=cad */
                  <div className="mt-3 rounded-xl border border-border bg-surface-secondary/50 p-3">
                    <div className="flex items-center justify-between mb-2.5">
                      <h4 className="text-xs font-semibold text-content-primary flex items-center gap-1.5">
                        <HardHat size={13} />
                        {t('ai.cad_converters_title', { defaultValue: 'DDC Converter Modules' })}
                      </h4>
                      {convertersData && (
                        <Badge variant={convertersData.installed_count > 0 ? 'success' : 'warning'} size="sm">
                          {convertersData.installed_count}/{convertersData.total_count}{' '}
                          {t('ai.cad_installed', { defaultValue: 'installed' })}
                        </Badge>
                      )}
                    </div>
                    <div className="grid grid-cols-2 gap-1.5">
                      {(convertersData?.converters ?? []).map((c) => (
                        <div
                          key={c.id}
                          className={`flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs ${
                            c.installed
                              ? 'bg-green-50 dark:bg-green-950/30 text-green-700 dark:text-green-400'
                              : 'bg-surface-primary text-content-tertiary'
                          }`}
                        >
                          {c.installed ? (
                            <CheckCircle2 size={13} className="shrink-0 text-green-500" />
                          ) : (
                            <XCircle size={13} className="shrink-0 text-content-quaternary" />
                          )}
                          <span className="font-medium truncate">{c.name}</span>
                          <span className="ml-auto text-[10px] opacity-60">{c.extensions.join(', ')}</span>
                        </div>
                      ))}
                    </div>
                    <div className="mt-2.5 flex items-start gap-2 rounded-lg bg-oe-blue-subtle/50 px-2.5 py-2">
                      <Info size={13} className="shrink-0 mt-0.5 text-oe-blue" />
                      <div className="text-[11px] text-oe-blue leading-relaxed">
                        <p>
                          {t('ai.cad_module_info_extract', {
                            defaultValue:
                              'CAD/BIM files are converted using DDC converters and quantities are extracted directly — no AI API key required.',
                          })}
                        </p>
                        <Link
                          to="/cad-takeoff"
                          className="mt-1 inline-flex items-center gap-1 font-medium text-oe-blue hover:underline"
                        >
                          {t('ai.cad_manage_converters', { defaultValue: 'Manage Converters' })}
                          <ExternalLink size={11} />
                        </Link>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ── Tab 6: Paste from Clipboard ─────────────────────── */}
            {activeTab === 'paste' && (
              <div>
                <div className="relative">
                  <textarea
                    value={pasteText}
                    onChange={(e) => setPasteText(e.target.value)}
                    placeholder={t('ai.paste_placeholder', {
                      defaultValue:
                        'Paste your BOQ data here (from Excel, Word, or any table)...\n\nExample:\nPos\tDescription\tUnit\tQty\tRate\n01.01\tExcavation\tm3\t250\t18.50\n01.02\tConcrete C30/37\tm3\t120\t145.00\n01.03\tReinforcement BSt 500\tkg\t12000\t1.85',
                    })}
                    rows={8}
                    className="w-full rounded-xl border border-border bg-surface-primary px-4 py-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue focus:shadow-[0_0_0_4px_rgba(0,113,227,0.08)] transition-all duration-normal ease-oe hover:border-content-tertiary resize-none leading-relaxed font-mono"
                    disabled={isPending}
                  />
                  <div className="absolute bottom-3 right-3 text-xs text-content-tertiary">
                    {pasteText.length > 0 && `${pasteText.length} chars`}
                  </div>
                </div>
                <p className="mt-2 text-xs text-content-tertiary">
                  {t('ai.paste_info', {
                    defaultValue:
                      'Auto-detects tab-separated, semicolon, or comma-delimited data. AI will parse and structure your data into estimate items.',
                  })}
                </p>
                <CompactOptions
                  location={location}
                  setLocation={setLocation}
                  currency={currency}
                  setCurrency={setCurrency}
                  standard={standard}
                  setStandard={setStandard}
                  disabled={isPending}
                />
              </div>
            )}

            {/* Submit button */}
            <div className="mt-5 flex items-center justify-between">
              <div className="text-xs text-content-tertiary">
                {isConfigured && aiSettings?.preferred_model && (
                  <span className="flex items-center gap-1.5">
                    <Zap size={12} />
                    {t('ai.powered_by', {
                      defaultValue: 'Powered by {{model}}',
                      model: aiSettings.preferred_model,
                    })}
                  </span>
                )}
              </div>
              <div className="flex flex-col items-end gap-1">
                <Button
                  type="submit"
                  variant="primary"
                  size="lg"
                  loading={isPending}
                  disabled={!canSubmit}
                  icon={activeTab === 'cad' ? <Layers size={18} /> : <Sparkles size={18} />}
                >
                  {submitLabel}
                </Button>
                {!canSubmit && !isPending && (
                  <span className="text-2xs text-content-tertiary">
                    {activeTab === 'text'
                      ? t('ai.hint_enter_description', { defaultValue: 'Enter a project description to continue' })
                      : t('ai.hint_select_file', { defaultValue: 'Select a file to continue' })
                    }
                  </span>
                )}
              </div>
            </div>
          </div>
        </form>
      </Card>

      {/* Loading state */}
      {isPending && <LoadingState />}

      {/* Error state */}
      {isError && (
        <div className="animate-card-in">
          <Card className="border-semantic-error/20">
            <CardContent className="!mt-0">
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-semantic-error-bg">
                  <AlertCircle size={18} className="text-semantic-error" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-semantic-error">
                    {t('ai.generation_failed', { defaultValue: 'Estimate generation failed' })}
                  </p>
                  <p className="mt-1 text-sm text-content-secondary">
                    {mutationError?.message ||
                      t('ai.try_again', {
                        defaultValue: 'Please try again or check your AI settings.',
                      })}
                  </p>
                  <Button
                    variant="secondary"
                    size="sm"
                    className="mt-3"
                    onClick={resetMutationErrors}
                    icon={<RotateCcw size={14} />}
                  >
                    {t('ai.dismiss', { defaultValue: 'Dismiss' })}
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* CAD Interactive Column Selection (step 1 of interactive grouping) */}
      {cadColumnsData && !cadGroupResult && !isPending && (
        <div className="rounded-xl border border-border-light bg-surface-primary p-5 space-y-4 animate-fade-in">
          {/* Header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Layers size={16} className="text-oe-blue" />
              <h3 className="text-sm font-semibold text-content-primary">
                {cadColumnsData.filename}
              </h3>
              <Badge variant="blue" size="sm">{cadColumnsData.total_elements.toLocaleString()} elements</Badge>
              <Badge variant="neutral" size="sm">{cadColumnsData.format.toUpperCase()}</Badge>
            </div>
            <span className="text-2xs text-content-quaternary">
              Extracted in {(cadColumnsData.duration_ms / 1000).toFixed(1)}s
            </span>
          </div>

          {/* Preset Buttons */}
          <div>
            <label className="text-xs font-medium text-content-secondary mb-2 block">
              QTO Grouping
            </label>
            <div className="flex flex-wrap gap-2">
              {Object.entries(cadColumnsData.presets || {}).map(([key, preset]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => {
                    setActivePreset(key);
                    setSelectedGroupBy(preset.group_by);
                    setSelectedSumCols(preset.sum_columns);
                    setShowCustom(false);
                  }}
                  className={clsx(
                    'rounded-lg px-4 py-2 text-xs font-medium transition-all border',
                    activePreset === key && !showCustom
                      ? 'bg-oe-blue text-white border-oe-blue shadow-sm'
                      : 'border-border bg-surface-secondary text-content-secondary hover:border-oe-blue/40',
                  )}
                >
                  <div className="font-semibold">{preset.label}</div>
                  <div className="text-2xs opacity-70 mt-0.5">{preset.description}</div>
                </button>
              ))}
              <button
                type="button"
                onClick={() => setShowCustom(!showCustom)}
                className={clsx(
                  'rounded-lg px-4 py-2 text-xs font-medium transition-all border',
                  showCustom
                    ? 'bg-oe-blue text-white border-oe-blue shadow-sm'
                    : 'border-border bg-surface-secondary text-content-secondary hover:border-oe-blue/40',
                )}
              >
                <div className="font-semibold">Custom</div>
                <div className="text-2xs opacity-70 mt-0.5">Advanced column selection</div>
              </button>
            </div>
          </div>

          {/* Selected columns summary (always visible) */}
          <div className="flex flex-wrap gap-4 text-xs text-content-secondary bg-surface-secondary/50 rounded-lg px-4 py-2.5">
            <div>
              <span className="font-medium text-content-primary">Group by: </span>
              {(selectedGroupBy || []).join(', ') || 'none'}
            </div>
            <div>
              <span className="font-medium text-content-primary">Sum: </span>
              {(selectedSumCols || []).map(col => {
                const unit = cadColumnsData.unit_labels?.[col];
                return unit ? `${col} (${unit})` : col;
              }).join(', ') || 'none'}
            </div>
          </div>

          {/* Custom column selection (collapsible) */}
          {showCustom && (
            <div className="space-y-3 border-t border-border-light pt-3">
              <div>
                <label className="text-xs font-medium text-content-secondary mb-2 block">Group by columns</label>
                <div className="flex flex-wrap gap-1.5">
                  {(cadColumnsData.columns?.grouping || []).map(col => {
                    const isSelected = (selectedGroupBy || []).includes(col);
                    return (
                      <button key={col} type="button" onClick={() => toggleGroupByCol(col)}
                        className={clsx('rounded-md px-2.5 py-1 text-2xs font-medium transition-colors',
                          isSelected ? 'bg-oe-blue text-white' : 'border border-border-light bg-surface-secondary text-content-tertiary hover:text-content-primary'
                        )}>
                        {col}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div>
                <label className="text-xs font-medium text-content-secondary mb-2 block">Sum quantities</label>
                <div className="flex flex-wrap gap-1.5">
                  {(cadColumnsData.columns?.quantity || []).map(col => {
                    const isSelected = (selectedSumCols || []).includes(col);
                    const unit = cadColumnsData.unit_labels?.[col];
                    return (
                      <button key={col} type="button" onClick={() => toggleSumCol(col)}
                        className={clsx('rounded-md px-2.5 py-1 text-2xs font-medium transition-colors',
                          isSelected ? 'bg-emerald-500 text-white' : 'border border-border-light bg-surface-secondary text-content-tertiary hover:text-content-primary'
                        )}>
                        {col}{unit ? ` (${unit})` : ''}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {/* Preview table — show only selected columns */}
          {(cadColumnsData.preview || []).length > 0 && (
            <div>
              <label className="text-xs font-medium text-content-secondary mb-2 block">
                {t('ai.cad_preview', { defaultValue: 'Preview (first 10 elements)' })}
              </label>
              <div className="overflow-x-auto rounded-lg border border-border-light">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border-light bg-surface-secondary/50">
                      {(() => {
                        const previewKeys = new Set(Object.keys(cadColumnsData.preview[0] ?? {}));
                        const visibleCols = (selectedGroupBy.length || selectedSumCols.length)
                          ? [...(selectedGroupBy || []), ...(selectedSumCols || [])].filter(c => c !== 'count' && previewKeys.has(c))
                          : Object.keys(cadColumnsData.preview[0] ?? {}).slice(0, 8);
                        return visibleCols.map((key) => {
                          const unit = cadColumnsData.unit_labels?.[key];
                          return (
                            <th
                              key={key}
                              className="px-3 py-1.5 text-left font-semibold text-content-tertiary uppercase tracking-wide whitespace-nowrap text-oe-blue"
                            >
                              {key}{unit ? ` (${unit})` : ''}
                            </th>
                          );
                        });
                      })()}
                    </tr>
                  </thead>
                  <tbody>
                    {cadColumnsData.preview.map((row, idx) => {
                      const previewKeys = new Set(Object.keys(cadColumnsData.preview[0] ?? {}));
                      const visibleCols = (selectedGroupBy.length || selectedSumCols.length)
                        ? [...(selectedGroupBy || []), ...(selectedSumCols || [])].filter(c => c !== 'count' && previewKeys.has(c))
                        : Object.keys(row).slice(0, 8);
                      return (
                        <tr key={idx} className="border-b border-border-light/30 hover:bg-surface-secondary/20">
                          {visibleCols.map((key) => {
                            const val = row[key];
                            return (
                              <td
                                key={key}
                                className={clsx(
                                  'px-3 py-1 whitespace-nowrap',
                                  typeof val === 'number' ? 'text-right font-mono text-content-primary' : 'text-content-secondary',
                                )}
                              >
                                {val === null || val === undefined || val === 'None' || val === ''
                                  ? '-'
                                  : typeof val === 'number'
                                    ? val.toLocaleString(getIntlLocale(), { maximumFractionDigits: 2 })
                                    : String(val)}
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Action buttons */}
          <div className="flex items-center gap-3 pt-2 border-t border-border-light">
            <Button variant="ghost" size="sm" onClick={() => { setCadColumnsData(null); setCadGroupResult(null); }}>
              {t('ai.cad_reset', { defaultValue: 'Reset' })}
            </Button>
            <div className="flex-1" />
            <Button
              variant="primary"
              size="sm"
              onClick={handleApplyGrouping}
              disabled={!selectedGroupBy?.length || cadGrouping}
              loading={cadGrouping}
            >
              {t('ai.cad_apply_grouping', { defaultValue: 'Apply Grouping' })}
            </Button>
          </div>
        </div>
      )}

      {/* CAD Dynamic Group Result (step 2 of interactive grouping) */}
      {cadGroupResult && !isPending && (
        <div className="space-y-4 animate-card-in" style={{ animationDelay: '50ms' }}>
          {/* Header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-content-primary">
                {t('ai.cad_grouped_results', { defaultValue: 'Grouped Results' })}
              </h2>
              <Badge variant="success" size="sm">
                {filteredGroups.length} {t('ai.cad_groups', { defaultValue: 'groups' })}
              </Badge>
              <Badge variant="neutral" size="sm">
                {computedTotals.count} {t('ai.cad_elements', { defaultValue: 'elements' })}
              </Badge>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => { setCadGroupResult(null); setDeletedGroupKeys(new Set()); }}
              icon={<RotateCcw size={14} />}
            >
              {t('ai.cad_change_grouping', { defaultValue: 'Change Grouping' })}
            </Button>
          </div>

          {/* Filter & sort controls */}
          <div className="flex flex-wrap items-center gap-3 rounded-lg bg-surface-secondary/30 border border-border-light/40 px-3 py-2">
            <label className="flex items-center gap-1.5 text-xs text-content-secondary cursor-pointer">
              <input type="checkbox" checked={hideEmptyGroups} onChange={e => setHideEmptyGroups(e.target.checked)} className="rounded accent-oe-blue" />
              {t('ai.cad_hide_empty', { defaultValue: 'Hide empty groups' })}
            </label>
            <span className="text-border">|</span>
            <span className="text-xs text-content-quaternary">
              {filteredGroups.length} / {(cadGroupResult.groups || []).length} {t('ai.cad_groups_label', { defaultValue: 'groups' })}
            </span>
            {deletedGroupKeys.size > 0 && (
              <>
                <span className="text-border">|</span>
                <button onClick={() => setDeletedGroupKeys(new Set())} className="text-xs text-oe-blue hover:underline">
                  {t('ai.cad_restore_removed', { defaultValue: 'Restore {{count}} removed', count: deletedGroupKeys.size })}
                </button>
              </>
            )}
          </div>

          {/* Grouped results table */}
          <Card padding="none">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-light bg-surface-secondary/50 text-left">
                    <th className="px-2 py-2.5 w-8" />
                    {(cadGroupResult.group_by || []).map((col) => (
                      <th key={col} className="px-4 py-2.5 text-xs font-semibold text-content-tertiary uppercase tracking-wide">
                        {col}
                      </th>
                    ))}
                    {(cadGroupResult.sum_columns || []).map((col) => {
                      const unit = cadColumnsData?.unit_labels?.[col];
                      return (
                        <th key={col} className="px-4 py-2.5 text-xs font-semibold text-content-tertiary uppercase tracking-wide text-right">
                          {col}{unit ? ` (${unit})` : ''}
                        </th>
                      );
                    })}
                    <th className="px-4 py-2.5 text-xs font-semibold text-content-tertiary uppercase tracking-wide text-right w-20">
                      {t('ai.cad_col_count', { defaultValue: 'Count' })}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {filteredGroups
                    .sort((a, b) => {
                      // Sort by first sum column descending (volume first)
                      const firstSumCol = (cadGroupResult.sum_columns || []).find(c => c !== 'count') || 'count';
                      return (b.sums[firstSumCol] || 0) - (a.sums[firstSumCol] || 0);
                    })
                    .map((g) => {
                      const hasQty = Object.values(g.sums || {}).some(v => v > 0);
                      // Clean category names: remove OST_ prefix
                      const cleanValue = (col: string, val: string) => {
                        if (!val || val === '(empty)') return '-';
                        if (col === 'category') return val.replace(/^OST_/, '');
                        return val;
                      };
                      return (
                        <tr key={g.key} className={clsx(
                          'border-b border-border-light/30 hover:bg-surface-secondary/20 transition-colors',
                          !hasQty && 'opacity-40',
                        )}>
                          <td className="px-2 py-1.5">
                            <button onClick={() => setDeletedGroupKeys(prev => new Set(prev).add(g.key))}
                              className="text-content-quaternary hover:text-red-500 transition-colors" title={t('ai.cad_remove_group', { defaultValue: 'Remove' })}>
                              <X size={12} />
                            </button>
                          </td>
                          {(cadGroupResult.group_by || []).map((col) => (
                            <td key={col} className="px-4 py-1.5 text-sm text-content-primary font-medium">
                              {cleanValue(col, g.key_parts[col] || '')}
                            </td>
                          ))}
                          {(cadGroupResult.sum_columns || []).map((col) => (
                            <td key={col} className={clsx(
                              'px-4 py-1.5 text-right font-mono text-sm',
                              (g.sums[col] ?? 0) > 0 ? 'text-content-primary font-medium' : 'text-content-quaternary',
                            )}>
                              {g.sums[col] != null && g.sums[col] > 0
                                ? g.sums[col].toLocaleString(getIntlLocale(), { minimumFractionDigits: 0, maximumFractionDigits: 2 })
                                : '-'}
                            </td>
                          ))}
                          <td className="px-4 py-1.5 text-right font-mono text-sm font-medium text-content-primary">{g.count}</td>
                        </tr>
                      );
                    })}
                </tbody>
                <tfoot>
                  <tr className="border-t-2 border-oe-blue/20 bg-oe-blue-subtle/30">
                    <td />
                    <td
                      colSpan={(cadGroupResult.group_by || []).length}
                      className="px-4 py-2.5 text-xs font-bold text-content-primary uppercase"
                    >
                      {t('ai.cad_grand_total', { defaultValue: 'Grand Total' })}
                    </td>
                    {(cadGroupResult.sum_columns || []).map((col) => (
                      <td key={col} className="px-4 py-2.5 text-right font-mono font-bold text-oe-blue">
                        {computedTotals.sums[col] != null
                          ? (computedTotals.sums[col] ?? 0).toLocaleString(getIntlLocale(), { minimumFractionDigits: 0, maximumFractionDigits: 2 })
                          : '-'}
                      </td>
                    ))}
                    <td className="px-4 py-2.5 text-right font-mono font-bold text-oe-blue">
                      {computedTotals.count}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </Card>

          {/* Save as BOQ + Action buttons */}
          <div className="flex items-center gap-3 pt-3 border-t border-border-light">
            <Button variant="primary" size="sm" onClick={handleSaveQtoAsBOQ} disabled={!filteredGroups.length} icon={<Save size={14} />}>
              {t('ai.cad_save_boq', { defaultValue: 'Save as BOQ ({{count}} positions)', count: filteredGroups.length })}
            </Button>
            <span className="text-xs text-content-tertiary">
              {t('ai.cad_save_boq_hint', { defaultValue: 'Creates BOQ positions from grouped quantities' })}
            </span>
            <div className="flex-1" />
            <Button
              variant="ghost"
              size="sm"
              onClick={handleReset}
              icon={<RotateCcw size={14} />}
            >
              {t('ai.new_extract', { defaultValue: 'New Extraction' })}
            </Button>
          </div>
        </div>
      )}

      {/* CAD Quantity Tables Result */}
      {cadResult && !isPending && (
        <div className="space-y-4 animate-card-in" style={{ animationDelay: '50ms' }}>
          {/* Header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-content-primary">
                {t('ai.cad_quantity_tables', { defaultValue: 'Quantity Tables' })}
              </h2>
              <Badge variant="success" size="sm">
                {cadResult.total_elements} {t('ai.cad_elements', { defaultValue: 'elements' })}
              </Badge>
              <Badge variant="neutral" size="sm">
                {cadResult.groups.length} {t('ai.cad_categories', { defaultValue: 'categories' })}
              </Badge>
            </div>
            <div className="flex items-center gap-3 text-xs text-content-tertiary">
              <Badge variant="neutral" size="sm">.{cadResult.format}</Badge>
              <span>
                {t('ai.cad_extracted_in', {
                  defaultValue: 'Extracted in {{duration}}s',
                  duration: (cadResult.duration_ms / 1000).toFixed(1),
                })}
              </span>
            </div>
          </div>

          {/* Quantity tables */}
          <Card padding="none">
            <div className="p-4">
              <QuantityTablesResult data={cadResult} />
            </div>
          </Card>

          {/* Action buttons */}
          <div className="flex items-center justify-between">
            <Button
              variant="ghost"
              size="sm"
              onClick={handleReset}
              icon={<RotateCcw size={14} />}
            >
              {t('ai.new_extract', { defaultValue: 'New Extraction' })}
            </Button>
          </div>
        </div>
      )}

      {/* AI Estimate Results — failed status */}
      {result && !isPending && result.status === 'failed' && result.error_message && (
        <div className="animate-card-in" style={{ animationDelay: '50ms' }}>
          <Card>
            <CardContent>
              <div className="flex items-start gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-red-50 dark:bg-red-500/10">
                  <AlertCircle size={16} className="text-red-500" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-content-primary">
                    {t('ai.estimate_failed', { defaultValue: 'Estimation failed' })}
                  </p>
                  <p className="mt-1 text-sm text-content-secondary">
                    {result.error_message}
                  </p>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="mt-3"
                    onClick={handleReset}
                    icon={<RotateCcw size={14} />}
                  >
                    {t('ai.try_again', { defaultValue: 'Try again' })}
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* AI Estimate Results — success */}
      {result && !isPending && result.status === 'completed' && result.items.length > 0 && (
        <div className="space-y-4 animate-card-in" style={{ animationDelay: '50ms' }}>
          {/* Results header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-content-primary">
                {t('ai.results', { defaultValue: 'Estimate Results' })}
              </h2>
              <Badge variant="success" size="sm">
                {result.items.length} {t('ai.items', { defaultValue: 'items' })}
              </Badge>
              {(result.confidence ?? 0) > 0 && (
                <Badge
                  variant={
                    (result.confidence ?? 0) >= 0.7
                      ? 'success'
                      : (result.confidence ?? 0) >= 0.4
                        ? 'warning'
                        : 'error'
                  }
                  size="sm"
                >
                  {Math.round((result.confidence ?? 0) * 100)}%{' '}
                  {t('ai.confidence', { defaultValue: 'confidence' })}
                </Badge>
              )}
            </div>
            <div className="text-xs text-content-tertiary">
              {t('ai.generated_in', {
                defaultValue: 'Generated in {{duration}}s using {{model}}',
                duration: (result.duration_ms / 1000).toFixed(1),
                model: result.model_used,
              })}
            </div>
          </div>

          {/* Results table */}
          <Card padding="none">
            <ResultsTable result={result} selectedCurrency={currency || undefined} enrichResult={enrichResult} />
          </Card>

          {/* Cost Database Matching */}
          <div className="rounded-xl border border-border-light bg-surface-secondary/30 p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Database size={16} className="text-emerald-600" />
                <span className="text-sm font-semibold text-content-primary">
                  {t('ai.cost_db_matching', { defaultValue: 'Cost Database Matching' })}
                </span>
                {enrichResult && (
                  <Badge variant={enrichResult.total_matched > 0 ? 'success' : 'neutral'} size="sm">
                    {enrichResult.total_matched}/{enrichResult.total_items} {t('ai.matched', { defaultValue: 'matched' })}
                  </Badge>
                )}
              </div>
              <div className="flex items-center gap-3">
                <select
                  value={enrichRegion}
                  onChange={(e) => setEnrichRegion(e.target.value)}
                  className="h-8 rounded-lg border border-border bg-surface-primary px-2 text-xs text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue hover:border-content-tertiary cursor-pointer appearance-none"
                  disabled={enriching}
                >
                  <option value="DE_BERLIN">{t('ai.region_de_berlin', { defaultValue: 'Germany (Berlin)' })}</option>
                  <option value="DE_MUNICH">{t('ai.region_de_munich', { defaultValue: 'Germany (Munich)' })}</option>
                  <option value="DE_HAMBURG">{t('ai.region_de_hamburg', { defaultValue: 'Germany (Hamburg)' })}</option>
                  <option value="DE_FRANKFURT">{t('ai.region_de_frankfurt', { defaultValue: 'Germany (Frankfurt)' })}</option>
                  <option value="AT_VIENNA">{t('ai.region_at_vienna', { defaultValue: 'Austria (Vienna)' })}</option>
                  <option value="CH_ZURICH">{t('ai.region_ch_zurich', { defaultValue: 'Switzerland (Zurich)' })}</option>
                  <option value="UK_LONDON">{t('ai.region_uk_london', { defaultValue: 'UK (London)' })}</option>
                  <option value="UK_MANCHESTER">{t('ai.region_uk_manchester', { defaultValue: 'UK (Manchester)' })}</option>
                  <option value="US_NEW_YORK">{t('ai.region_us_new_york', { defaultValue: 'USA (New York)' })}</option>
                  <option value="US_LOS_ANGELES">{t('ai.region_us_la', { defaultValue: 'USA (Los Angeles)' })}</option>
                  <option value="US_CHICAGO">{t('ai.region_us_chicago', { defaultValue: 'USA (Chicago)' })}</option>
                  <option value="AE_DUBAI">{t('ai.region_ae_dubai', { defaultValue: 'UAE (Dubai)' })}</option>
                </select>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleEnrich}
                  loading={enriching}
                  disabled={enriching}
                  icon={<Database size={14} />}
                >
                  {t('ai.match_cost_db', { defaultValue: 'Match with Cost DB' })}
                </Button>
              </div>
            </div>
            {!enrichResult && (
              <p className="text-xs text-content-tertiary">
                {t('ai.cost_db_matching_desc', {
                  defaultValue: 'Match AI-estimated rates against the CWICR cost database for your region. Matched rates will replace AI estimates in the table above.',
                })}
              </p>
            )}
            {enrichResult && enrichResult.total_matched > 0 && (
              <div className="flex items-center gap-2 text-xs text-emerald-600">
                <CheckCircle2 size={13} />
                <span>
                  {t('ai.enrich_summary', {
                    defaultValue: '{{matched}} of {{total}} items matched with regional cost data ({{region}})',
                    matched: enrichResult.total_matched,
                    total: enrichResult.total_items,
                    region: enrichResult.region,
                  })}
                </span>
              </div>
            )}
          </div>

          {/* Action buttons */}
          <div className="flex items-center justify-between">
            <Button
              variant="ghost"
              size="sm"
              onClick={handleReset}
              icon={<RotateCcw size={14} />}
            >
              {t('ai.new_estimate', { defaultValue: 'New Estimate' })}
            </Button>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                icon={<Download size={14} />}
                onClick={() => {
                  // Generate a simple CSV download from results
                  if (!result?.items?.length) return;
                  const header = 'Pos,Description,Unit,Quantity,Unit Rate,Total\n';
                  const rows = result.items.map((item, i) =>
                    `${item.ordinal || i + 1},"${(item.description || '').replace(/"/g, '""')}",${item.unit},${item.quantity},${item.unit_rate},${item.quantity * item.unit_rate}`
                  ).join('\n');
                  const blob = new Blob([header + rows], { type: 'text/csv' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `ai-estimate-${new Date().toISOString().slice(0, 10)}.csv`;
                  a.click();
                  URL.revokeObjectURL(url);
                  addToast({ type: 'success', title: t('ai.exported', { defaultValue: 'Estimate exported as CSV' }) });
                }}
              >
                {t('ai.export_csv', { defaultValue: 'Export CSV' })}
              </Button>
              <Button
                variant="primary"
                size="sm"
                icon={<Save size={14} />}
                onClick={() => setSaveDialogOpen(true)}
              >
                {t('ai.save_as_boq', { defaultValue: 'Save as BOQ' })}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Save dialog */}
      <SaveToBOQDialog
        open={saveDialogOpen}
        onClose={() => setSaveDialogOpen(false)}
        onSave={(projectId, boqName) => saveMutation.mutate({ projectId, boqName })}
        saving={saveMutation.isPending}
      />
    </div>
  );
}
