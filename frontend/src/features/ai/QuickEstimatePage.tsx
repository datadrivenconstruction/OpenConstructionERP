// OpenConstructionERP — DataDrivenConstruction (DDC)
// CWICR AI Estimation Engine
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// DDC-CWICR-OE-2026
import React, { useState, useCallback, useRef, useEffect, useId, useMemo, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams, useLocation, Link } from 'react-router-dom';
import { useFocusTrap } from '@/shared/hooks/useFocusTrap';
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
  Plus,
  Search,
  BrainCircuit,
  Wand2,
} from 'lucide-react';
import clsx from 'clsx';
import { Card, CardContent, Button, Badge, AIDisclaimerBanner } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { aiApi, type QuickEstimateRequest, type EstimateJobResponse, type EstimateItem, type CadExtractResponse, type EnrichResult, type EnrichedItem, type CadColumnsResponse, type CadGroupResponse, type CadDynamicGroup, type CadGroupElementsResponse } from './api';
import { apiGet, apiPost } from '@/shared/lib/api';
import {
  formatFileSize,
  formatNumber,
  getFileExtension,
  getIntlLocale,
} from '@/shared/lib/formatters';
import { useLLMRun } from './hooks/useLLMRun';

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
  { value: 'BRL', label: 'BRL' },
  { value: 'MXN', label: 'MXN' },
  { value: 'ZAR', label: 'ZAR' },
  { value: 'RUB', label: 'RUB' },
  { value: 'TRY', label: 'TRY' },
  { value: 'SEK', label: 'SEK' },
  { value: 'NOK', label: 'NOK' },
  { value: 'DKK', label: 'DKK' },
  { value: 'PLN', label: 'PLN' },
  { value: 'CZK', label: 'CZK' },
  { value: 'AED', label: 'AED' },
  { value: 'SAR', label: 'SAR' },
  { value: 'SGD', label: 'SGD' },
  { value: 'HKD', label: 'HKD' },
  { value: 'KRW', label: 'KRW' },
  { value: 'NZD', label: 'NZD' },
  { value: 'ILS', label: 'ILS' },
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
// formatNumber / formatFileSize / getFileExtension live in
// `@/shared/lib/formatters` — they were lifted out of this file once it
// became clear they were not AI-specific.

// ── Shimmer loading rows ─────────────────────────────────────────────────────

function ShimmerRow() {
  return (
    <tr className="animate-pulse">
      <td className="px-4 py-3">
        <div className="h-4 w-12 rounded bg-slate-200/70 dark:bg-slate-700/40" />
      </td>
      <td className="px-4 py-3">
        <div className="h-4 w-48 rounded bg-slate-200/70 dark:bg-slate-700/40" />
      </td>
      <td className="px-4 py-3">
        <div className="h-4 w-8 rounded bg-slate-200/70 dark:bg-slate-700/40" />
      </td>
      <td className="px-4 py-3 text-right">
        <div className="ml-auto h-4 w-14 rounded bg-slate-200/70 dark:bg-slate-700/40" />
      </td>
      <td className="px-4 py-3 text-right">
        <div className="ml-auto h-4 w-16 rounded bg-slate-200/70 dark:bg-slate-700/40" />
      </td>
      <td className="px-4 py-3 text-right">
        <div className="ml-auto h-4 w-20 rounded bg-slate-200/70 dark:bg-slate-700/40" />
      </td>
    </tr>
  );
}

function LoadingState({ isCad, fileName, fileSizeMB }: { isCad?: boolean; fileName?: string; fileSizeMB?: number }) {
  const { t } = useTranslation();
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(timer);
  }, []);

  // Estimated progress for CAD: ~1 min per 50 MB, minimum 30s
  const estimatedTotal = isCad && fileSizeMB ? Math.max(30, (fileSizeMB / 50) * 60) : 0;
  const progressPct = estimatedTotal > 0 ? Math.min(95, (elapsed / estimatedTotal) * 100) : 0;
  const remaining = estimatedTotal > 0 ? Math.max(0, Math.round(estimatedTotal - elapsed)) : 0;

  const title = isCad
    ? t('ai.converting_cad', { defaultValue: 'Converting CAD file...' })
    : t('ai.analyzing', { defaultValue: 'AI is analyzing your input...' });
  const subtitle = isCad && estimatedTotal > 0
    ? remaining > 0
      ? t('ai.cad_progress_hint', { defaultValue: '~{{remaining}}s remaining — extracting elements and detecting columns', remaining })
      : t('ai.cad_finalizing', { defaultValue: 'Finalizing extraction...' })
    : isCad
      ? t('ai.cad_processing_hint', { defaultValue: 'Extracting elements, detecting columns. This may take 30-60 seconds for large files.' })
      : t('ai.generating', { defaultValue: 'Generating cost breakdown and quantities' });

  // a11y: aria-live="polite" so SR users hear the loading transition
  // without interrupting the user; aria-busy reinforces "in progress" for
  // assistive tech; the decorative gradient + sparkle icon stay hidden
  // from screen readers.
  return (
    <div className="animate-card-in" style={{ animationDelay: '100ms' }}>
      <section
        role="status"
        aria-live="polite"
        aria-busy="true"
        aria-label={title}
        className="relative overflow-hidden rounded-2xl border border-white/40 bg-white/60 backdrop-blur-xl shadow-lg shadow-slate-900/[0.04] dark:border-white/5 dark:bg-slate-900/40 dark:shadow-slate-950/30"
      >
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -top-20 -right-20 h-48 w-48 rounded-full bg-gradient-radial from-sky-500/20 to-transparent blur-3xl"
        />
        <div className="relative px-6 pt-6 pb-2">
          <div className="flex items-center gap-3 mb-4">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500 to-blue-600 text-white shadow-md shadow-sky-500/25">
              <Sparkles size={18} className="animate-pulse" aria-hidden="true" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-content-primary">{title}</p>
              <p className="text-xs text-content-tertiary">{subtitle}</p>
            </div>
            <div className="text-xs text-content-quaternary tabular-nums shrink-0">
              {isCad && estimatedTotal > 0 && (
                <span className="font-semibold text-oe-blue mr-2">{Math.round(progressPct)}%</span>
              )}
              {elapsed > 0 && `${elapsed}s`}
              {fileName && <span className="ml-2 text-content-tertiary truncate max-w-[120px] inline-block align-bottom">{fileName}</span>}
            </div>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200/60 dark:bg-slate-700/40">
            {isCad && estimatedTotal > 0 ? (
              <div
                className="h-full rounded-full bg-gradient-to-r from-sky-500 to-blue-600 transition-all duration-1000 ease-linear"
                style={{ width: `${progressPct}%` }}
              />
            ) : (
              <div className="h-full w-1/3 animate-shimmer rounded-full bg-gradient-to-r from-sky-500 to-blue-600 opacity-70 bg-[length:200%_100%]" />
            )}
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
                  {t('common.quantity')}
                </th>
                <th className="px-4 py-3 text-xs font-semibold text-content-tertiary uppercase tracking-wide text-right">
                  {t('common.rate')}
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
      </section>
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

  // a11y: stable ids let <label htmlFor> wire to inputs; useFocusTrap +
  // Escape handler + body-scroll-lock complete the modal contract
  // (matches WideModal). Initial focus goes to the first focusable input.
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const projectSelectId = useId();
  const boqNameId = useId();

  const { data: projects } = useQuery({
    queryKey: ['projects-list-simple'],
    queryFn: () => apiGet<ProjectSummary[]>('/v1/projects/?page_size=100'),
    enabled: open,
    staleTime: 5 * 60_000,
  });

  useFocusTrap(panelRef, open);

  // Escape closes the dialog unless a save is in flight.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !saving) {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', handler, { capture: true });
    return () => document.removeEventListener('keydown', handler, { capture: true });
  }, [open, onClose, saving]);

  // Body-scroll lock while the dialog is open.
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  // Move initial focus into the first focusable form control on open.
  useEffect(() => {
    if (!open) return;
    const node = panelRef.current;
    if (!node) return;
    const first = node.querySelector<HTMLElement>(
      'input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])',
    );
    first?.focus();
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-lg"
        aria-hidden="true"
        onClick={() => !saving && onClose()}
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative w-full max-w-md animate-card-in rounded-2xl border border-border-light bg-surface-elevated p-6 shadow-xl"
      >
        <h3 id={titleId} className="text-lg font-semibold text-content-primary mb-4">
          {t('ai.save_to_boq', { defaultValue: 'Save as BOQ' })}
        </h3>

        <div className="space-y-4">
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor={projectSelectId}
              className="text-sm font-medium text-content-primary"
            >
              {t('ai.select_project', { defaultValue: 'Select Project' })}
            </label>
            <select
              id={projectSelectId}
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
            <label
              htmlFor={boqNameId}
              className="text-sm font-medium text-content-primary"
            >
              {t('ai.boq_name', { defaultValue: 'BOQ Name' })}
            </label>
            <input
              id={boqNameId}
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
              {t('common.quantity')}
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
              <React.Fragment key={`${item.ordinal}-${idx}`}>
                {showCategory && (
                  <tr className="bg-surface-secondary/50">
                    <td
                      colSpan={6}
                      className="px-4 py-2 text-xs font-semibold text-content-secondary uppercase tracking-wider"
                    >
                      {item.category}
                    </td>
                  </tr>
                )}
                <tr
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
              </React.Fragment>
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
                        {t('common.type')}
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
                        key={`${item.type}-${item.material || ''}-${idx}`}
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
  // a11y: useId per field so labels wire to controls via htmlFor.
  // Multiple instances of CompactOptions render across tabs — hard-coded
  // ids would collide and break SR / form associations.
  const locationId = useId();
  const currencyId = useId();
  const standardId = useId();
  const selectClass =
    'h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue hover:border-content-tertiary cursor-pointer appearance-none';
  const inputClass =
    'h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all duration-fast ease-oe hover:border-content-tertiary';

  return (
    <div className="mt-4 grid grid-cols-3 gap-3">
      <div className="flex flex-col gap-1">
        <label
          htmlFor={locationId}
          className="text-xs font-medium text-content-tertiary uppercase tracking-wide"
        >
          {t('ai.location', { defaultValue: 'Location' })}
        </label>
        <input
          id={locationId}
          type="text"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          placeholder={t('ai.location_placeholder', { defaultValue: 'e.g. Berlin' })}
          className={inputClass}
          disabled={disabled}
        />
      </div>
      <div className="flex flex-col gap-1">
        <label
          htmlFor={currencyId}
          className="text-xs font-medium text-content-tertiary uppercase tracking-wide"
        >
          {t('common.currency')}
        </label>
        <select
          id={currencyId}
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
        <label
          htmlFor={standardId}
          className="text-xs font-medium text-content-tertiary uppercase tracking-wide"
        >
          {t('ai.standard_label', { defaultValue: 'Standard' })}
        </label>
        <select
          id={standardId}
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

// ── Full Converter Section (for /data-explorer) ──────────────────────────────

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
  const isCadRoute = routeLocation.pathname === '/data-explorer';
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
  const [treeViewMode, setTreeViewMode] = useState(false);
  const [expandedTreeNodes, setExpandedTreeNodes] = useState<Set<string>>(new Set());
  const [elementDetailGroup, setElementDetailGroup] = useState<CadDynamicGroup | null>(null);
  const [elementDetailData, setElementDetailData] = useState<CadGroupElementsResponse | null>(null);
  const [elementDetailLoading, setElementDetailLoading] = useState(false);

  // Cost DB enrichment state
  const [enrichRegion, setEnrichRegion] = useState('DE_BERLIN');
  const [enrichResult, setEnrichResult] = useState<EnrichResult | null>(null);
  const [enriching, setEnriching] = useState(false);

  // a11y refs / ids — used by the textarea label, the disabled-submit
  // hint (aria-describedby), the tablist (role=tab + aria-controls), and
  // the post-submit focus target so SR users land on the result region.
  const descriptionId = useId();
  const pasteTextId = useId();
  const buildingTypeId = useId();
  const areaM2Id = useId();
  const submitHelpId = useId();
  const tablistId = useId();
  const resultRegionRef = useRef<HTMLDivElement>(null);

  // CAD BOQ creation state
  const globalProjectId = useProjectContextStore((s) => s.activeProjectId);
  const [cadBOQProjectId, setCadBOQProjectId] = useState(globalProjectId || '');
  const [cadBOQName, setCadBOQName] = useState('CAD Import');
  const [cadBOQCreating, setCadBOQCreating] = useState(false);
  const [cadExporting, setCadExporting] = useState(false);

  // Check if AI is configured
  const { data: aiSettings } = useQuery({
    queryKey: ['ai-settings'],
    queryFn: aiApi.getSettings,
    retry: false,
    staleTime: 5 * 60_000,
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
    queryFn: () => apiGet('/v1/takeoff/converters/'),
    staleTime: 60_000,
    enabled: activeTab === 'cad' || isCadRoute,
  });

  // ── Converter install/uninstall state (for /data-explorer route) ──────
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
      // 120 s explicit timeout — converter install (RVT especially) can
      // run 60-90 s; the user error log for v4.3.2 caught AbortErrors
      // on this exact path.
      const signal: AbortSignal | undefined =
        typeof AbortSignal !== 'undefined' &&
        typeof (AbortSignal as { timeout?: (ms: number) => AbortSignal }).timeout ===
          'function'
          ? (AbortSignal as unknown as { timeout: (ms: number) => AbortSignal }).timeout(
              120_000,
            )
          : undefined;
      const data = await apiPost<{ message: string }>(
        `/v1/takeoff/converters/${c.id}/install/`,
        undefined,
        signal ? { signal } : undefined,
      );
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
      await apiPost(`/v1/takeoff/converters/${c.id}/uninstall/`);
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

  // ── AI runs — all five operations now share `useLLMRun` so they get
  //    AbortController cancellation, post-run focus-restore (a11y P1
  //    finding #4), and a consistent error-normalisation contract.
  //    The toast call sites are identical to the pre-refactor versions;
  //    only the plumbing changed.

  const textEstimateRun = useLLMRun<QuickEstimateRequest, EstimateJobResponse>({
    mutationFn: (data, { signal }) => aiApi.quickEstimate(data, { signal }),
    focusRestoreRef: resultRegionRef,
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
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('ai.estimate_failed', { defaultValue: 'Estimation failed' }),
        message: err.message,
      });
    },
  });

  const photoEstimateRun = useLLMRun<Parameters<typeof aiApi.photoEstimate>[0], EstimateJobResponse>({
    mutationFn: (params, { signal }) => aiApi.photoEstimate({ ...params, signal }),
    focusRestoreRef: resultRegionRef,
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
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('ai.estimate_failed', { defaultValue: 'Estimation failed' }),
        message: err.message,
      });
    },
  });

  const fileEstimateRun = useLLMRun<Parameters<typeof aiApi.fileEstimate>[0], EstimateJobResponse>({
    mutationFn: (params, { signal }) => aiApi.fileEstimate({ ...params, signal }),
    focusRestoreRef: resultRegionRef,
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
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('ai.estimate_failed', { defaultValue: 'Estimation failed' }),
        message: err.message,
      });
    },
  });

  const cadExtractRun = useLLMRun<File, CadExtractResponse>({
    // `cadExtract` is a no-AI deterministic path; we still funnel it
    // through useLLMRun for the shared cancel/focus contract.
    mutationFn: (file) => aiApi.cadExtract(file),
    focusRestoreRef: resultRegionRef,
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
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('ai.cad_extract_failed', { defaultValue: 'CAD extraction failed' }),
        message: err.message,
      });
    },
  });

  const cadColumnsRun = useLLMRun<File, CadColumnsResponse>({
    mutationFn: (file) => aiApi.cadColumns(file),
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
    onError: (err) => {
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

  // a11y — focus the result region as soon as new content arrives so
  // keyboard / SR users land on the freshly generated estimate rather
  // than having to Tab past the form to find it. tabIndex={-1} on the
  // wrapper makes the div focusable programmatically only.
  useEffect(() => {
    if (!result && !cadResult && !cadGroupResult) return;
    const id = requestAnimationFrame(() => {
      resultRegionRef.current?.focus();
    });
    return () => cancelAnimationFrame(id);
  }, [result, cadResult, cadGroupResult]);

  // ── Determine if any mutation is pending ──────────────────────────────

  const isPending =
    textEstimateRun.isPending || photoEstimateRun.isPending || fileEstimateRun.isPending || cadExtractRun.isPending || cadColumnsRun.isPending || cadGrouping;
  const isError =
    (textEstimateRun.isError && !textEstimateRun.isPending) ||
    (photoEstimateRun.isError && !photoEstimateRun.isPending) ||
    (fileEstimateRun.isError && !fileEstimateRun.isPending) ||
    (cadExtractRun.isError && !cadExtractRun.isPending) ||
    (cadColumnsRun.isError && !cadColumnsRun.isPending);
  const mutationError =
    textEstimateRun.error ||
    photoEstimateRun.error ||
    fileEstimateRun.error ||
    cadExtractRun.error ||
    cadColumnsRun.error;

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
      textEstimateRun.run(request);
    },
    [description, location, currency, standard, buildingType, areaM2, textEstimateRun],
  );

  const handlePhotoSubmit = useCallback(() => {
    if (!selectedFile) return;
    setResult(null);
    photoEstimateRun.run({
      file: selectedFile,
      location: location.trim() || undefined,
      currency: currency || undefined,
      standard: standard || undefined,
    });
  }, [selectedFile, location, currency, standard, photoEstimateRun]);

  const handleFileSubmit = useCallback(() => {
    if (!selectedFile) return;
    setResult(null);
    fileEstimateRun.run({
      file: selectedFile,
      location: location.trim() || undefined,
      currency: currency || undefined,
      standard: standard || undefined,
    });
  }, [selectedFile, location, currency, standard, fileEstimateRun]);

  const handleCadSubmit = useCallback(() => {
    if (!selectedFile) return;
    setResult(null);
    setCadResult(null);
    setCadColumnsData(null);
    setCadGroupResult(null);
    if (isCadRoute) {
      cadColumnsRun.run(selectedFile);
    } else {
      cadExtractRun.run(selectedFile);
    }
  }, [selectedFile, cadExtractRun, cadColumnsRun, isCadRoute]);

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

  // ── Fetch element detail when a group row is clicked ──────────────────
  useEffect(() => {
    if (!elementDetailGroup || !cadColumnsData?.session_id) {
      setElementDetailData(null);
      return;
    }
    let cancelled = false;
    setElementDetailLoading(true);
    setElementDetailData(null);
    aiApi.cadGroupElements({
      session_id: cadColumnsData.session_id,
      group_key: elementDetailGroup.key_parts,
    }).then((data) => {
      if (!cancelled) setElementDetailData(data);
    }).catch((err) => {
      if (!cancelled) {
        addToast({
          type: 'error',
          title: t('ai.cad_elements_failed', { defaultValue: 'Failed to load elements' }),
          message: err instanceof Error ? err.message : 'Unknown error',
        });
      }
    }).finally(() => {
      if (!cancelled) setElementDetailLoading(false);
    });
    return () => { cancelled = true; };
  }, [elementDetailGroup, cadColumnsData?.session_id, addToast, t]);

  const handlePasteSubmit = useCallback(() => {
    if (!pasteText.trim()) return;

    const request: QuickEstimateRequest = {
      description: `Parse the following BOQ/cost data and generate a structured estimate:\n\n${pasteText.trim()}`,
    };
    if (location.trim()) request.location = location.trim();
    if (currency) request.currency = currency;
    if (standard) request.standard = standard;

    setResult(null);
    textEstimateRun.run(request);
  }, [pasteText, location, currency, standard, textEstimateRun]);

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
    setTreeViewMode(false);
    setExpandedTreeNodes(new Set());
    setElementDetailGroup(null);
    setDescription('');
    setLocation('');
    setCurrency('');
    setStandard('');
    setBuildingType('');
    setAreaM2('');
    setPasteText('');
    handleRemoveFile();
    textEstimateRun.reset();
    photoEstimateRun.reset();
    fileEstimateRun.reset();
    cadExtractRun.reset();
    cadColumnsRun.reset();
  }, [handleRemoveFile, textEstimateRun, photoEstimateRun, fileEstimateRun, cadExtractRun, cadColumnsRun]);

  const resetMutationErrors = useCallback(() => {
    textEstimateRun.reset();
    photoEstimateRun.reset();
    fileEstimateRun.reset();
    cadExtractRun.reset();
    cadColumnsRun.reset();
  }, [textEstimateRun, photoEstimateRun, fileEstimateRun, cadExtractRun, cadColumnsRun]);

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

  // ── Tree view data (hierarchical grouping by first group_by column) ──
  interface TreeNode {
    parentKey: string;
    parentLabel: string;
    children: CadDynamicGroup[];
    count: number;
    sums: Record<string, number>;
  }

  const treeData = useMemo((): TreeNode[] => {
    if (!cadGroupResult || (cadGroupResult.group_by || []).length < 2) return [];
    const firstCol = cadGroupResult.group_by[0]!;
    const nodeMap = new Map<string, TreeNode>();

    for (const g of filteredGroups) {
      const parentVal = g.key_parts[firstCol] || '(empty)';
      if (!nodeMap.has(parentVal)) {
        nodeMap.set(parentVal, {
          parentKey: parentVal,
          parentLabel: firstCol === 'category' ? parentVal.replace(/^OST_/, '') : parentVal,
          children: [],
          count: 0,
          sums: {},
        });
      }
      const node = nodeMap.get(parentVal)!;
      node.children.push(g);
      node.count += g.count;
      for (const [k, v] of Object.entries(g.sums || {})) {
        node.sums[k] = (node.sums[k] || 0) + v;
      }
    }
    return Array.from(nodeMap.values());
  }, [filteredGroups, cadGroupResult]);

  const canShowTreeView = (cadGroupResult?.group_by || []).length >= 2;

  const toggleTreeNode = useCallback((key: string) => {
    setExpandedTreeNodes((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

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
      message: t('ai.qto_saved_msg', {
        defaultValue:
          '{{count}} positions prepared. Open a project BOQ and use Import to bring them in.',
        count: items.length,
      }),
      action: {
        label: t('ai.qto_open_boq', { defaultValue: 'Go to BOQ' }),
        onClick: () => navigate('/boq'),
      },
    });
  }, [filteredGroups, cadColumnsData, cadGroupResult, addToast, t, navigate]);

  // ── Create BOQ from CAD QTO (server-side) ───────────────────────────

  const handleCreateBOQ = useCallback(async () => {
    if (!cadColumnsData?.session_id || !cadBOQProjectId || !filteredGroups.length) return;
    setCadBOQCreating(true);
    try {
      const result = await aiApi.createBOQFromCadQTO({
        session_id: cadColumnsData.session_id,
        project_id: cadBOQProjectId,
        boq_name: cadBOQName || 'CAD Import',
        group_by: cadGroupResult?.group_by || [],
        sum_columns: cadGroupResult?.sum_columns || [],
      });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      queryClient.invalidateQueries({ queryKey: ['boqs'] });
      addToast({
        type: 'success',
        title: t('ai.boq_created', { defaultValue: 'BOQ created successfully' }),
        message: t('ai.boq_created_msg', {
          defaultValue: '{{count}} positions added',
          count: result.position_count,
        }),
      });
      navigate(`/boq/${result.boq_id}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to create BOQ';
      // Handle session expiry
      if (msg.includes('expired') || msg.includes('not found')) {
        addToast({
          type: 'error',
          title: t('ai.session_expired', { defaultValue: 'Session expired' }),
          message: t('ai.session_expired_msg', { defaultValue: 'Please re-upload the CAD file and try again.' }),
        });
      } else {
        addToast({
          type: 'error',
          title: t('ai.boq_create_failed', { defaultValue: 'Failed to create BOQ' }),
          message: msg,
        });
      }
    } finally {
      setCadBOQCreating(false);
    }
  }, [cadColumnsData?.session_id, cadBOQProjectId, cadBOQName, cadGroupResult, filteredGroups, addToast, t, navigate, queryClient]);

  // ── Export CAD QTO as Excel ────────────────────────────────────────────

  const handleExportExcel = useCallback(async () => {
    if (!cadColumnsData?.session_id) return;
    setCadExporting(true);
    try {
      await aiApi.exportCadGroupExcel({
        session_id: cadColumnsData.session_id,
        group_by: cadGroupResult?.group_by || [],
        sum_columns: cadGroupResult?.sum_columns || [],
      });
      addToast({
        type: 'success',
        title: t('ai.excel_exported', { defaultValue: 'Excel exported' }),
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Export failed';
      if (msg.includes('expired') || msg.includes('not found')) {
        addToast({
          type: 'error',
          title: t('ai.session_expired', { defaultValue: 'Session expired' }),
          message: t('ai.session_expired_msg', { defaultValue: 'Please re-upload the CAD file and try again.' }),
        });
      } else {
        addToast({
          type: 'error',
          title: t('ai.export_failed', { defaultValue: 'Export failed' }),
          message: msg,
        });
      }
    } finally {
      setCadExporting(false);
    }
  }, [cadColumnsData?.session_id, cadGroupResult, addToast, t]);

  // ── Project list for BOQ creation ─────────────────────────────────────

  const { data: cadProjectsList } = useQuery({
    queryKey: ['projects-list-simple-cad'],
    queryFn: () => apiGet<ProjectSummary[]>('/v1/projects/?page_size=100'),
    enabled: !!cadGroupResult,
    staleTime: 5 * 60_000,
  });

  // ── Render ────────────────────────────────────────────────────────────

  return (
    <div
      data-testid="ai-quick-estimate-page"
      className="relative min-h-full w-full overflow-hidden animate-fade-in"
    >
      {/* Page-level gradient backdrop (sky → white → emerald) */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10 bg-gradient-to-br from-sky-50 via-white to-emerald-50/40 dark:from-slate-950 dark:via-slate-900 dark:to-slate-950"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-40 -left-40 -z-10 h-96 w-96 rounded-full bg-gradient-radial from-sky-400/15 to-transparent blur-3xl"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-40 -right-40 -z-10 h-96 w-96 rounded-full bg-gradient-radial from-emerald-400/15 to-transparent blur-3xl"
      />

      <div className="space-y-6 px-4 py-5 lg:px-6 lg:py-6">
      {/* Hero header — glass pill with title, subtitle, model pill */}
      <header
        className="animate-card-in relative overflow-hidden rounded-2xl border border-white/40 bg-white/60 px-5 py-4 backdrop-blur-xl shadow-lg shadow-slate-900/[0.04] dark:border-white/5 dark:bg-slate-900/40"
        style={{ animationDelay: '0ms' }}
      >
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -top-16 right-1/4 h-40 w-40 rounded-full bg-gradient-radial from-violet-400/20 to-transparent blur-3xl"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -bottom-16 -left-10 h-40 w-40 rounded-full bg-gradient-radial from-sky-400/15 to-transparent blur-3xl"
        />
        <div className="relative flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div
              aria-hidden="true"
              className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 via-blue-500 to-sky-500 text-white shadow-md shadow-violet-500/25"
            >
              <BrainCircuit size={22} />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight text-content-primary">
                {isCadRoute
                  ? t('ai.cad_takeoff_title', { defaultValue: 'CAD/BIM Takeoff' })
                  : t('ai.estimate_title', { defaultValue: 'AI Estimate' })
                }
              </h1>
              <p className="mt-0.5 text-sm text-content-secondary">
                {isCadRoute
                  ? t('ai.cad_takeoff_subtitle', { defaultValue: 'Extract quantities from 3D models and drawings' })
                  : t('ai.estimate_subtitle', { defaultValue: 'Create an estimate from any source' })
                }
              </p>
            </div>
          </div>
          {!isCadRoute && isConfigured && aiSettings?.preferred_model && (
            <div className="flex items-center gap-2">
              <span
                data-testid="ai-quick-estimate-model-pill"
                className="inline-flex items-center gap-1.5 rounded-full border border-white/50 bg-white/70 px-3 py-1 text-xs font-medium text-content-secondary backdrop-blur dark:border-white/10 dark:bg-slate-800/60"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                <Zap size={11} className="text-violet-500" />
                {t('ai.model_pill', {
                  defaultValue: 'model: {{model}}',
                  model: aiSettings.preferred_model,
                })}
              </span>
            </div>
          )}
        </div>
      </header>

      {!isCadRoute && <AIDisclaimerBanner />}

      {/* AI Status Banner */}
      {aiSettings && !isConfigured ? (
        isCadRoute ? (
          /* ── CAD route: compact AI info (AI is optional here) ─── */
          <div
            className="animate-card-in flex items-center gap-3 rounded-xl border border-border-light bg-surface-secondary/50 px-4 py-2.5"
            style={{ animationDelay: '50ms' }}
          >
            <Sparkles size={16} className="text-content-tertiary shrink-0" />
            <p className="text-xs text-content-secondary flex-1">
              {t('ai.cad_ai_optional', {
                defaultValue: 'AI is optional for CAD/BIM takeoff. Quantity extraction works without AI. Connect an AI provider in Settings for automatic cost enrichment.',
              })}
            </p>
            <Button variant="ghost" size="sm" onClick={() => navigate('/settings')} className="shrink-0 whitespace-nowrap text-2xs">
              {t('ai.setup_ai', { defaultValue: 'Setup AI' })}
            </Button>
          </div>
        ) : (
          /* ── AI Estimate route: prominent setup card ─── */
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
        )
      ) : aiSettings && isConfigured ? (
        /* ── CONFIGURED — green status bar. Status icon + explicit
            "Status:" sr-only prefix so meaning does not rely on green
            colour alone (WCAG 1.4.1). */
        <div
          className="animate-card-in flex items-center gap-3 rounded-xl bg-semantic-success-bg/60 border border-semantic-success/20 px-4 py-2.5"
          style={{ animationDelay: '50ms' }}
          role="status"
        >
          <div
            aria-hidden="true"
            className="flex h-7 w-7 items-center justify-center rounded-full bg-semantic-success/20"
          >
            <CheckCircle2 size={14} className="text-semantic-success" />
          </div>
          <div className="flex-1 flex items-center gap-3">
            <span className="text-sm font-medium text-semantic-success">
              <span className="sr-only">
                {t('ai.status_prefix', { defaultValue: 'Status: ' })}
              </span>
              {t('ai.connected', { defaultValue: 'AI Connected' })}
            </span>
            <span className="text-xs text-semantic-success/70">
              {aiSettings.preferred_model || 'Claude'}
            </span>
          </div>
          <div className="flex items-center gap-2 text-2xs text-semantic-success/60">
            <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-semantic-success" /> Text</span>
            <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-semantic-success" /> Photo</span>
            <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-semantic-success" /> PDF</span>
            <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-semantic-success" /> Excel</span>
          </div>
        </div>
      ) : null}

      {/* How it works — concise workflow context (AI Estimate route only,
          before any result is generated). Tells construction specialists
          exactly what the tool produces and where it fits in the pipeline. */}
      {!isCadRoute && !result && !cadResult && !cadGroupResult && (
        <div
          className="animate-card-in rounded-xl border border-border-light bg-surface-secondary/40 px-4 py-3"
          style={{ animationDelay: '80ms' }}
        >
          <div className="flex items-start gap-3">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10">
              <Info size={15} className="text-oe-blue" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold text-content-primary mb-1">
                {t('ai.estimate_intro_title', {
                  defaultValue: 'A first-pass estimate in seconds — then you refine it',
                })}
              </p>
              <p className="text-xs text-content-secondary leading-relaxed">
                {t('ai.estimate_intro_desc', {
                  defaultValue:
                    'Pick a source below. The AI returns a structured BOQ with quantities and indicative unit rates. Match those rates against the real CWICR cost database, save it as a project BOQ, then validate it. Treat AI numbers as a starting point — always review before pricing a tender.',
                })}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-2xs text-content-tertiary">
                {[
                  t('ai.estimate_step_1', { defaultValue: 'Describe / upload' }),
                  t('ai.estimate_step_2', { defaultValue: 'AI drafts BOQ' }),
                  t('ai.estimate_step_3', { defaultValue: 'Match Cost DB' }),
                  t('ai.estimate_step_4', { defaultValue: 'Save & validate' }),
                ].map((step, i, arr) => (
                  <span key={step} className="flex items-center gap-1.5">
                    <span className="inline-flex items-center gap-1 rounded-full bg-surface-primary border border-border-light px-2 py-0.5">
                      <span className="inline-flex h-3.5 w-3.5 items-center justify-center rounded-full bg-oe-blue/10 text-[9px] font-bold text-oe-blue">
                        {i + 1}
                      </span>
                      {step}
                    </span>
                    {i < arr.length - 1 && (
                      <ArrowRight size={10} className="text-content-quaternary" />
                    )}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Source type selector (hidden on /data-explorer) — proper
          WAI-ARIA tablist semantics so AT users understand the grid of
          buttons is a single-select tab control. */}
      {!isCadRoute && (
      <div className="animate-card-in" style={{ animationDelay: '100ms' }}>
        {/* Horizontal tab pills — single row, glass treatment */}
        <div
          role="tablist"
          id={tablistId}
          aria-label={t('ai.input_source_label', { defaultValue: 'Input source' })}
          className="grid grid-cols-5 gap-2"
        >
          {TABS.map((tab) => {
            const isActive = activeTab === tab.id;
            const tabPanelId = `${tablistId}-panel-${tab.id}`;
            const tabId = `${tablistId}-tab-${tab.id}`;
            return (
              <button
                key={tab.id}
                id={tabId}
                role="tab"
                type="button"
                aria-selected={isActive}
                aria-controls={tabPanelId}
                tabIndex={isActive ? 0 : -1}
                onClick={() => handleTabChange(tab.id)}
                disabled={isPending}
                className={clsx(
                  'group relative flex flex-col items-center gap-1.5 overflow-hidden rounded-xl px-2 py-3 text-center transition-all border backdrop-blur-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400',
                  isActive
                    ? 'border-violet-300/60 bg-gradient-to-br from-violet-50/90 via-white/80 to-sky-50/70 shadow-md shadow-violet-500/10 ring-1 ring-violet-400/20 dark:border-violet-400/30 dark:from-violet-500/10 dark:via-slate-900/40 dark:to-sky-500/10'
                    : 'border-white/40 bg-white/50 hover:-translate-y-0.5 hover:border-violet-300/40 hover:bg-white/80 hover:shadow-lg dark:border-white/5 dark:bg-slate-900/40 dark:hover:bg-slate-800/60',
                  isPending && 'opacity-50 pointer-events-none',
                )}
              >
                <div
                  aria-hidden="true"
                  className={clsx(
                    'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-all',
                    isActive
                      ? 'bg-gradient-to-br from-violet-500 to-sky-500 text-white shadow-sm shadow-violet-500/30'
                      : 'bg-slate-100 text-content-tertiary group-hover:bg-violet-100 group-hover:text-violet-600 dark:bg-slate-800 dark:group-hover:bg-violet-500/20',
                  )}
                >
                  {tab.icon}
                </div>
                <div>
                  <div className={clsx('text-xs font-semibold', isActive ? 'text-violet-700 dark:text-violet-300' : 'text-content-primary')}>
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

      {/* Input area for selected source — glass panel */}
      <section
        data-testid="ai-quick-estimate-input"
        {...(!isCadRoute && {
          role: 'tabpanel',
          id: `${tablistId}-panel-${activeTab}`,
          'aria-labelledby': `${tablistId}-tab-${activeTab}`,
        })}
        className="animate-card-in relative overflow-hidden rounded-2xl border border-white/40 bg-white/60 backdrop-blur-xl shadow-lg shadow-slate-900/[0.04] dark:border-white/5 dark:bg-slate-900/40 dark:shadow-slate-950/30"
        style={{ animationDelay: '200ms' }}
      >
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -top-24 -right-24 h-56 w-56 rounded-full bg-gradient-radial from-sky-500/15 to-transparent blur-3xl"
        />
        {/* Coloured section accent bar */}
        <div className="relative flex items-center gap-3 border-b border-white/40 px-5 py-3 dark:border-white/5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-sky-500 to-blue-600 text-white shadow-sm shadow-sky-500/25">
            <Wand2 size={15} />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold text-content-primary">
              {isCadRoute
                ? t('ai.input_cad_title', { defaultValue: 'Upload a CAD or BIM file' })
                : activeTab === 'text'
                  ? t('ai.input_text_title', { defaultValue: 'Describe your project' })
                  : activeTab === 'paste'
                    ? t('ai.input_paste_title', { defaultValue: 'Paste BOQ or table data' })
                    : t('ai.input_file_title', { defaultValue: 'Upload a source file' })}
            </h2>
            <p className="text-xs text-content-tertiary">
              {t('ai.input_subtitle', {
                defaultValue: 'The AI returns a structured BOQ with quantities and indicative rates.',
              })}
            </p>
          </div>
        </div>

        {/* Tab content */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSubmit();
          }}
        >
          <div className="relative px-6 py-5">
            {/* ── Tab 1: Text Description ─────────────────────────── */}
            {activeTab === 'text' && (
              <div className="space-y-4">
                <div className="relative">
                  {/* a11y: visually-hidden label associates the textarea
                      with a programmatic name. Placeholder text alone
                      is not a label (it disappears once typing starts). */}
                  <label htmlFor={descriptionId} className="sr-only">
                    {t('ai.describe_label', { defaultValue: 'Project description' })}
                  </label>
                  <textarea
                    id={descriptionId}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder={t('ai.describe_placeholder', {
                      defaultValue:
                        'Describe your project...\n\nExample: "3-story residential building, 1200 m\u00b2 total area, reinforced concrete frame with brick facade, flat roof, standard MEP installations. Location: Berlin, Germany."',
                    })}
                    rows={6}
                    className="w-full rounded-xl border border-white/50 bg-white/70 px-5 py-4 text-base text-content-primary placeholder:text-content-tertiary shadow-inner shadow-slate-900/[0.03] backdrop-blur-sm transition-all duration-normal ease-oe hover:border-violet-300/60 focus:border-violet-400 focus:bg-white/90 focus:outline-none focus:ring-2 focus:ring-violet-400/40 focus:shadow-[0_0_0_6px_rgba(139,92,246,0.08)] resize-none leading-relaxed dark:border-white/10 dark:bg-slate-900/50 dark:focus:bg-slate-900/70"
                    disabled={isPending}
                  />
                  <div className="absolute bottom-3 right-3 text-xs text-content-tertiary tabular-nums">
                    {description.length > 0 && `${description.length} chars`}
                  </div>
                </div>

                {/* Example chips — auto-fill the prompt */}
                {!description && !isPending && (
                  <div
                    data-testid="ai-quick-estimate-examples"
                    className="flex flex-wrap items-center gap-2"
                  >
                    <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                      {t('ai.examples_label', { defaultValue: 'Try' })}
                    </span>
                    {[
                      {
                        key: 'apartment_berlin',
                        label: t('ai.example_apartment_berlin', {
                          defaultValue: 'Apartment building 1200 m² Berlin',
                        }),
                        prompt: t('ai.example_apartment_berlin_prompt', {
                          defaultValue:
                            '4-story residential apartment building, 1200 m² total area, reinforced concrete frame with brick facade, flat roof, standard MEP installations. Location: Berlin, Germany.',
                        }),
                      },
                      {
                        key: 'office_nyc',
                        label: t('ai.example_office_nyc', {
                          defaultValue: 'Office fit-out NYC 800 m²',
                        }),
                        prompt: t('ai.example_office_nyc_prompt', {
                          defaultValue:
                            'Class A office tenant fit-out, 800 m², open-plan layout with 12 private offices, 4 meeting rooms, breakroom, full MEP upgrade. Location: New York, USA.',
                        }),
                      },
                      {
                        key: 'warehouse_rotterdam',
                        label: t('ai.example_warehouse_rotterdam', {
                          defaultValue: 'Warehouse 4500 m² Rotterdam',
                        }),
                        prompt: t('ai.example_warehouse_rotterdam_prompt', {
                          defaultValue:
                            'Single-story logistics warehouse, 4500 m², steel portal frame, insulated metal panel cladding, 8 loading docks, sprinkler system. Location: Rotterdam, Netherlands.',
                        }),
                      },
                      {
                        key: 'school_london',
                        label: t('ai.example_school_london', {
                          defaultValue: 'School 2000 m² London',
                        }),
                        prompt: t('ai.example_school_london_prompt', {
                          defaultValue:
                            'Two-story primary school extension, 2000 m², CLT structure with brick facade, 12 classrooms, assembly hall, kitchen, full MEP and AV. Location: London, UK.',
                        }),
                      },
                    ].map((ex) => (
                      <button
                        key={ex.key}
                        type="button"
                        onClick={() => setDescription(ex.prompt)}
                        disabled={isPending}
                        className="group inline-flex items-center gap-1.5 rounded-full border border-white/50 bg-white/60 px-3 py-1 text-xs font-medium text-content-secondary backdrop-blur transition hover:-translate-y-0.5 hover:border-violet-300/60 hover:bg-white/90 hover:text-violet-700 hover:shadow-sm dark:border-white/10 dark:bg-slate-800/50 dark:hover:bg-slate-700/60 dark:hover:text-violet-300"
                      >
                        <Sparkles size={11} className="text-violet-500 opacity-70 group-hover:opacity-100" />
                        {ex.label}
                      </button>
                    ))}
                  </div>
                )}

                {/* Full options row for text tab — every input wired to
                    its label via htmlFor so SR users can name them. */}
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
                  <div className="flex flex-col gap-1">
                    <label
                      htmlFor={`${descriptionId}-location`}
                      className="text-xs font-medium text-content-tertiary uppercase tracking-wide"
                    >
                      {t('ai.location', { defaultValue: 'Location' })}
                    </label>
                    <input
                      id={`${descriptionId}-location`}
                      type="text"
                      value={location}
                      onChange={(e) => setLocation(e.target.value)}
                      placeholder={t('ai.location_placeholder', { defaultValue: 'e.g. Berlin' })}
                      className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all duration-fast ease-oe hover:border-content-tertiary"
                      disabled={isPending}
                    />
                  </div>

                  <div className="flex flex-col gap-1">
                    <label
                      htmlFor={`${descriptionId}-currency`}
                      className="text-xs font-medium text-content-tertiary uppercase tracking-wide"
                    >
                      {t('common.currency')}
                    </label>
                    <select
                      id={`${descriptionId}-currency`}
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
                    <label
                      htmlFor={`${descriptionId}-standard`}
                      className="text-xs font-medium text-content-tertiary uppercase tracking-wide"
                    >
                      {t('ai.standard_label', { defaultValue: 'Standard' })}
                    </label>
                    <select
                      id={`${descriptionId}-standard`}
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
                    <label
                      htmlFor={buildingTypeId}
                      className="text-xs font-medium text-content-tertiary uppercase tracking-wide"
                    >
                      {t('ai.building_type', { defaultValue: 'Building Type' })}
                    </label>
                    <select
                      id={buildingTypeId}
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
                    <label
                      htmlFor={areaM2Id}
                      className="text-xs font-medium text-content-tertiary uppercase tracking-wide"
                    >
                      {t('ai.area', { defaultValue: 'Area (m\u00b2)' })}
                    </label>
                    <input
                      id={areaM2Id}
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
                {/* Converter status banner — always visible */}
                {isCadRoute && convertersData && (
                  <div className={clsx(
                    'mb-4 rounded-xl border p-4 flex items-center justify-between',
                    (convertersData.installed_count ?? 0) > 0
                      ? 'border-semantic-success/30 bg-semantic-success/5'
                      : 'border-amber-500/30 bg-amber-50 dark:bg-amber-900/10'
                  )}>
                    <div className="flex items-center gap-3">
                      <div className={clsx(
                        'flex h-10 w-10 items-center justify-center rounded-xl',
                        (convertersData.installed_count ?? 0) > 0 ? 'bg-semantic-success/10' : 'bg-amber-100 dark:bg-amber-900/20'
                      )}>
                        <HardDrive size={20} className={(convertersData.installed_count ?? 0) > 0 ? 'text-semantic-success' : 'text-amber-600'} />
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-content-primary">
                          {(convertersData.installed_count ?? 0) > 0
                            ? t('ai.converters_ready', { defaultValue: `${convertersData.installed_count} of ${convertersData.total_count} converters installed`, installed: convertersData.installed_count, total: convertersData.total_count })
                            : t('ai.converters_none', { defaultValue: 'No converters installed — install below to enable CAD/BIM import' })}
                        </p>
                        <p className="text-xs text-content-tertiary mt-0.5">
                          {(convertersData.converters ?? []).filter((c: ConverterFull) => c.installed).map((c: ConverterFull) => c.name).join(', ') || t('ai.converters_hint', { defaultValue: 'Scroll down to install DDC converters for RVT, IFC, DWG, DGN' })}
                        </p>
                      </div>
                    </div>
                  </div>
                )}
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
                  /* Full converter management UI on /data-explorer */
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
                          to="/data-explorer"
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
                  <label htmlFor={pasteTextId} className="sr-only">
                    {t('ai.paste_label', { defaultValue: 'Paste BOQ or table data' })}
                  </label>
                  <textarea
                    id={pasteTextId}
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
              <div className="flex flex-col items-end gap-2">
                {(() => {
                  // a11y: explain WHY the submit is disabled, both
                  // visually (text hint below the button) and to screen
                  // readers via aria-describedby. Without this, an SR
                  // user pressing the disabled button gets no feedback
                  // about the missing input.
                  const disabledReason = !canSubmit && !isPending
                    ? activeTab === 'text'
                      ? t('ai.hint_enter_description', { defaultValue: 'Enter a project description to continue' })
                      : activeTab === 'paste'
                        ? t('ai.hint_enter_paste', { defaultValue: 'Paste some BOQ or table data to continue' })
                        : t('ai.hint_select_file', { defaultValue: 'Select a file to continue' })
                    : '';
                  return (
                    <>
                      {isCadRoute ? (
                        /* CAD route: two prominent buttons */
                        <div className="flex items-center gap-2">
                          <Button
                            type="submit"
                            variant="primary"
                            size="lg"
                            loading={isPending}
                            disabled={!canSubmit}
                            icon={<Layers size={18} aria-hidden="true" />}
                            className="px-6"
                            aria-describedby={!canSubmit ? submitHelpId : undefined}
                          >
                            {submitLabel}
                          </Button>
                          <Button
                            type="button"
                            variant="secondary"
                            size="lg"
                            disabled={!canSubmit}
                            icon={<Database size={18} aria-hidden="true" />}
                            className="px-6"
                            onClick={() => {
                              if (selectedFile) {
                                // Upload via Data Explorer page
                                navigate('/data-explorer');
                              }
                            }}
                          >
                            {t('ai.open_explorer', { defaultValue: 'Data Explorer' })}
                          </Button>
                        </div>
                      ) : (
                        <Button
                          type="submit"
                          variant="primary"
                          size="lg"
                          loading={isPending}
                          disabled={!canSubmit}
                          icon={<Sparkles size={18} aria-hidden="true" />}
                          aria-describedby={!canSubmit ? submitHelpId : undefined}
                        >
                          {submitLabel}
                        </Button>
                      )}
                      {/* Always render the help span so the id stays
                          stable — hide it visually when nothing to say
                          so layout does not jump. */}
                      <span
                        id={submitHelpId}
                        className={clsx(
                          'text-2xs text-content-tertiary',
                          !disabledReason && 'sr-only',
                        )}
                      >
                        {disabledReason || t('ai.submit_ready', { defaultValue: 'Ready to submit' })}
                      </span>
                    </>
                  );
                })()}
              </div>
            </div>
          </div>
        </form>
      </section>

      {/* Loading state */}
      {isPending && <LoadingState isCad={isCadRoute} fileName={selectedFile?.name} fileSizeMB={selectedFile ? selectedFile.size / (1024 * 1024) : undefined} />}

      {/* Error state — role="alert" so AT announces it immediately;
          the AlertCircle icon + explicit "Error:" prefix avoid relying
          on colour alone (WCAG 1.4.1). */}
      {isError && (
        <div className="animate-card-in" role="alert">
          <Card className="border-semantic-error/20">
            <CardContent className="!mt-0">
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-semantic-error-bg">
                  <AlertCircle size={18} className="text-semantic-error" aria-hidden="true" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-semantic-error">
                    <span className="sr-only">
                      {t('ai.error_prefix', { defaultValue: 'Error: ' })}
                    </span>
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
                    icon={<RotateCcw size={14} aria-hidden="true" />}
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
            <div className="flex items-center gap-2">
              <span className="text-2xs text-content-quaternary">
                {t('ai.extracted_in', { defaultValue: 'Extracted in {{time}}s', time: (cadColumnsData.duration_ms / 1000).toFixed(1) })}
              </span>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => navigate(`/data-explorer?session=${cadColumnsData.session_id}`)}
                className="shrink-0 whitespace-nowrap"
              >
                <Database size={13} className="mr-1" />
                <span>{t('ai.open_data_explorer', { defaultValue: 'Data Explorer' })}</span>
              </Button>
            </div>
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
                    const conf = cadColumnsData.confidence?.[col];
                    return (
                      <button key={col} type="button" onClick={() => toggleGroupByCol(col)}
                        className={clsx('rounded-md px-2.5 py-1 text-2xs font-medium transition-colors inline-flex items-center gap-1',
                          isSelected ? 'bg-oe-blue text-white' : 'border border-border-light bg-surface-secondary text-content-tertiary hover:text-content-primary'
                        )}>
                        {col}
                        {conf != null && (
                          <span className={clsx('text-2xs', isSelected ? 'opacity-70' : 'text-content-quaternary')} title={t('ai.confidence_tooltip', { defaultValue: 'Column detection confidence — higher % = more reliable data' })}>
                            {Math.round(conf * 100)}%
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div>
                <label className="text-xs font-medium text-content-secondary mb-2 block">{t('ai.sum_quantities', { defaultValue: 'Sum quantities' })}</label>
                <div className="flex flex-wrap gap-1.5">
                  {(cadColumnsData.columns?.quantity || []).map(col => {
                    const isSelected = (selectedSumCols || []).includes(col);
                    const unit = cadColumnsData.unit_labels?.[col];
                    const conf = cadColumnsData.confidence?.[col];
                    return (
                      <button key={col} type="button" onClick={() => toggleSumCol(col)}
                        className={clsx('rounded-md px-2.5 py-1 text-2xs font-medium transition-colors inline-flex items-center gap-1',
                          isSelected ? 'bg-emerald-500 text-white' : 'border border-border-light bg-surface-secondary text-content-tertiary hover:text-content-primary'
                        )}>
                        {col}{unit ? ` (${unit})` : ''}
                        {conf != null && (
                          <span className={clsx('text-2xs', isSelected ? 'opacity-70' : 'text-content-quaternary')} title={t('ai.confidence_tooltip', { defaultValue: 'Column detection confidence — higher % = more reliable data' })}>
                            {Math.round(conf * 100)}%
                          </span>
                        )}
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
                        <tr key={`preview-${idx}-${Object.values(row).slice(0, 2).join('-')}`} className="border-b border-border-light/30 hover:bg-surface-secondary/20">
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

      {/* CAD Dynamic Group Result (step 2 of interactive grouping).
          Same focus-target pattern as AI results so SR users land here
          when the grouping completes. */}
      {cadGroupResult && !isPending && (
        <div
          ref={resultRegionRef}
          tabIndex={-1}
          role="region"
          aria-label={t('ai.cad_grouped_results', { defaultValue: 'Grouped Results' })}
          className="space-y-4 animate-card-in focus:outline-none"
          style={{ animationDelay: '50ms' }}
        >
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
              onClick={() => { setCadGroupResult(null); setDeletedGroupKeys(new Set()); setTreeViewMode(false); setExpandedTreeNodes(new Set()); setElementDetailGroup(null); }}
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
            {canShowTreeView && (
              <>
                <span className="text-border">|</span>
                <div className="inline-flex rounded-md border border-border-light overflow-hidden">
                  <button
                    onClick={() => setTreeViewMode(false)}
                    className={clsx(
                      'px-2.5 py-0.5 text-xs font-medium transition-colors',
                      !treeViewMode ? 'bg-oe-blue text-white' : 'bg-surface-secondary text-content-tertiary hover:text-content-primary',
                    )}
                  >
                    {t('ai.cad_view_flat', { defaultValue: 'Flat' })}
                  </button>
                  <button
                    onClick={() => { setTreeViewMode(true); setExpandedTreeNodes(new Set(treeData.map(n => n.parentKey))); }}
                    className={clsx(
                      'px-2.5 py-0.5 text-xs font-medium transition-colors',
                      treeViewMode ? 'bg-oe-blue text-white' : 'bg-surface-secondary text-content-tertiary hover:text-content-primary',
                    )}
                  >
                    {t('ai.cad_view_tree', { defaultValue: 'Tree' })}
                  </button>
                </div>
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
                  {(() => {
                    const cleanValue = (col: string, val: string) => {
                      if (!val || val === '(empty)') return '-';
                      if (col === 'category') return val.replace(/^OST_/, '');
                      return val;
                    };
                    const firstSumCol = (cadGroupResult.sum_columns || []).find(c => c !== 'count') || 'count';
                    const groupByCols = cadGroupResult.group_by || [];
                    const sumCols = cadGroupResult.sum_columns || [];

                    if (treeViewMode && canShowTreeView) {
                      // ── Tree view ──
                      const sortedTree = [...treeData].sort((a, b) => (b.sums[firstSumCol] || 0) - (a.sums[firstSumCol] || 0));
                      return sortedTree.map((node) => {
                        const isExpanded = expandedTreeNodes.has(node.parentKey);
                        const sortedChildren = [...node.children].sort((a, b) => (b.sums[firstSumCol] || 0) - (a.sums[firstSumCol] || 0));
                        return (
                          <React.Fragment key={`tree-${node.parentKey}`}>
                            {/* Parent row */}
                            <tr
                              className="border-b border-border-light/30 bg-surface-secondary/40 hover:bg-surface-secondary/60 cursor-pointer transition-colors"
                              onClick={() => toggleTreeNode(node.parentKey)}
                            >
                              <td className="px-2 py-2">
                                {isExpanded
                                  ? <ChevronDown size={14} className="text-content-tertiary" />
                                  : <ChevronRight size={14} className="text-content-tertiary" />
                                }
                              </td>
                              <td className="px-4 py-2 text-sm text-content-primary font-semibold">
                                {node.parentLabel}
                              </td>
                              {groupByCols.slice(1).map((col) => (
                                <td key={col} className="px-4 py-2 text-xs text-content-quaternary italic">
                                  {node.children.length} {t('ai.cad_sub_groups', { defaultValue: 'sub-groups' })}
                                </td>
                              ))}
                              {sumCols.map((col) => (
                                <td key={col} className="px-4 py-2 text-right font-mono text-sm font-semibold text-content-primary">
                                  {(node.sums[col] || 0) > 0
                                    ? (node.sums[col] || 0).toLocaleString(getIntlLocale(), { minimumFractionDigits: 0, maximumFractionDigits: 2 })
                                    : '-'}
                                </td>
                              ))}
                              <td className="px-4 py-2 text-right font-mono text-sm font-semibold text-content-primary">
                                {node.count}
                              </td>
                            </tr>
                            {/* Child rows */}
                            {isExpanded && sortedChildren.map((g) => {
                              const hasQty = Object.values(g.sums || {}).some(v => v > 0);
                              return (
                                <tr
                                  key={g.key}
                                  className={clsx(
                                    'border-b border-border-light/20 hover:bg-surface-secondary/20 cursor-pointer transition-colors',
                                    !hasQty && 'opacity-40',
                                  )}
                                  onClick={() => setElementDetailGroup(g)}
                                >
                                  <td className="px-2 py-1.5">
                                    <button
                                      onClick={(e) => { e.stopPropagation(); setDeletedGroupKeys(prev => new Set(prev).add(g.key)); }}
                                      className="text-content-quaternary hover:text-red-500 transition-colors"
                                      title={t('ai.cad_remove_group', { defaultValue: 'Remove' })}
                                    >
                                      <X size={12} />
                                    </button>
                                  </td>
                                  <td className="px-4 py-1.5 text-sm text-content-secondary pl-10">
                                    <span className="text-border mr-1.5">|--</span>
                                    {cleanValue(groupByCols[0]!, g.key_parts[groupByCols[0]!] || '')}
                                  </td>
                                  {groupByCols.slice(1).map((col) => (
                                    <td key={col} className="px-4 py-1.5 text-sm text-content-primary font-medium">
                                      {cleanValue(col, g.key_parts[col] || '')}
                                    </td>
                                  ))}
                                  {sumCols.map((col) => (
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
                          </React.Fragment>
                        );
                      });
                    }

                    // ── Flat view (default) ──
                    return filteredGroups
                      .sort((a, b) => (b.sums[firstSumCol] || 0) - (a.sums[firstSumCol] || 0))
                      .map((g) => {
                        const hasQty = Object.values(g.sums || {}).some(v => v > 0);
                        return (
                          <tr
                            key={g.key}
                            className={clsx(
                              'border-b border-border-light/30 hover:bg-surface-secondary/20 cursor-pointer transition-colors',
                              !hasQty && 'opacity-40',
                            )}
                            onClick={() => setElementDetailGroup(g)}
                          >
                            <td className="px-2 py-1.5">
                              <button
                                onClick={(e) => { e.stopPropagation(); setDeletedGroupKeys(prev => new Set(prev).add(g.key)); }}
                                className="text-content-quaternary hover:text-red-500 transition-colors"
                                title={t('ai.cad_remove_group', { defaultValue: 'Remove' })}
                              >
                                <X size={12} />
                              </button>
                            </td>
                            {groupByCols.map((col) => (
                              <td key={col} className="px-4 py-1.5 text-sm text-content-primary font-medium">
                                {cleanValue(col, g.key_parts[col] || '')}
                              </td>
                            ))}
                            {sumCols.map((col) => (
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
                      });
                  })()}
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
          <div className="space-y-3 pt-3 border-t border-border-light">
            {/* Project selector + BOQ name */}
            <div className="flex items-center gap-3 flex-wrap">
              <select
                value={cadBOQProjectId}
                onChange={(e) => setCadBOQProjectId(e.target.value)}
                className="h-8 rounded-md border border-border-light bg-surface-primary px-2 text-sm text-content-primary focus:border-oe-blue focus:ring-1 focus:ring-oe-blue"
              >
                <option value="">{t('ai.select_project', { defaultValue: '-- Select project --' })}</option>
                {(cadProjectsList || []).map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
              <input
                type="text"
                value={cadBOQName}
                onChange={(e) => setCadBOQName(e.target.value)}
                placeholder={t('ai.boq_name_placeholder', { defaultValue: 'BOQ name' })}
                className="h-8 w-48 rounded-md border border-border-light bg-surface-primary px-2 text-sm text-content-primary focus:border-oe-blue focus:ring-1 focus:ring-oe-blue"
              />
            </div>
            <div className="flex items-center gap-3">
              <Button variant="primary" size="sm" onClick={handleCreateBOQ} disabled={!filteredGroups.length || !cadBOQProjectId || cadBOQCreating} loading={cadBOQCreating} icon={<Plus size={14} />}>
                {t('ai.cad_create_boq', { defaultValue: 'Create BOQ' })}
              </Button>
              <Button variant="secondary" size="sm" onClick={handleExportExcel} disabled={!filteredGroups.length || cadExporting} loading={cadExporting} icon={<FileSpreadsheet size={14} />}>
                {t('ai.cad_export_excel', { defaultValue: 'Export Excel' })}
              </Button>
              <Button variant="ghost" size="sm" onClick={handleSaveQtoAsBOQ} disabled={!filteredGroups.length} icon={<Save size={14} />}>
                {t('ai.cad_save_boq', { defaultValue: 'Save as BOQ ({{count}} positions)', count: filteredGroups.length })}
              </Button>
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
        </div>
      )}

      {/* Element Detail Panel (slide-over) */}
      {elementDetailGroup && (
        <div className="fixed inset-0 z-50 flex justify-end" onClick={() => setElementDetailGroup(null)}>
          <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" />
          <div
            className="relative w-full max-w-3xl bg-surface-primary shadow-2xl border-l border-border-light overflow-hidden flex flex-col animate-slide-in-right"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-border-light bg-surface-secondary/30">
              <div>
                <h3 className="text-sm font-semibold text-content-primary">
                  {t('ai.cad_element_detail', { defaultValue: 'Element Detail' })}
                </h3>
                <p className="text-xs text-content-tertiary mt-0.5">
                  {Object.entries(elementDetailGroup.key_parts).map(([k, v]) =>
                    `${k}: ${v}`
                  ).join(' / ')}
                </p>
                <div className="flex items-center gap-2 mt-1">
                  <Badge variant="blue" size="sm">
                    {elementDetailGroup.count} {t('ai.cad_elements', { defaultValue: 'elements' })}
                  </Badge>
                  {elementDetailData?.truncated && (
                    <Badge variant="warning" size="sm">
                      {t('ai.cad_truncated', { defaultValue: 'Showing first 500' })}
                    </Badge>
                  )}
                </div>
              </div>
              <button
                onClick={() => setElementDetailGroup(null)}
                className="p-1.5 rounded-md text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
              >
                <X size={18} />
              </button>
            </div>
            {/* Content */}
            <div className="flex-1 overflow-auto">
              {elementDetailLoading && (
                <div className="flex items-center justify-center py-16">
                  <Loader2 size={24} className="animate-spin text-oe-blue" />
                  <span className="ml-2 text-sm text-content-secondary">
                    {t('ai.cad_loading_elements', { defaultValue: 'Loading elements...' })}
                  </span>
                </div>
              )}
              {elementDetailData && !elementDetailLoading && (
                <table className="w-full text-xs">
                  <thead className="sticky top-0 z-10">
                    <tr className="border-b border-border-light bg-surface-secondary/80 backdrop-blur">
                      <th className="px-3 py-2 text-left font-semibold text-content-tertiary uppercase tracking-wide w-10">#</th>
                      {elementDetailData.columns.map((col) => (
                        <th
                          key={col}
                          className={clsx(
                            'px-3 py-2 font-semibold text-content-tertiary uppercase tracking-wide whitespace-nowrap',
                            col in (elementDetailData.totals || {}) ? 'text-right' : 'text-left',
                          )}
                        >
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {elementDetailData.elements.map((el, idx) => (
                      <tr key={`el-${idx}-${Object.values(el).slice(0, 2).join('-')}`} className="border-b border-border-light/20 hover:bg-surface-secondary/20 transition-colors">
                        <td className="px-3 py-1.5 text-content-quaternary font-mono">{idx + 1}</td>
                        {elementDetailData.columns.map((col) => {
                          const val = el[col];
                          const isNumeric = col in (elementDetailData.totals || {});
                          return (
                            <td
                              key={col}
                              className={clsx(
                                'px-3 py-1.5 whitespace-nowrap max-w-[200px] truncate',
                                isNumeric ? 'text-right font-mono text-content-primary' : 'text-content-secondary',
                              )}
                              title={val != null ? String(val) : ''}
                            >
                              {val === null || val === undefined || val === 'None' || val === ''
                                ? '-'
                                : typeof val === 'number'
                                  ? val.toLocaleString(getIntlLocale(), { maximumFractionDigits: 4 })
                                  : String(val)}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="border-t-2 border-oe-blue/20 bg-oe-blue-subtle/30 sticky bottom-0">
                      <td className="px-3 py-2 font-bold text-xs text-content-primary uppercase">
                        {t('ai.cad_total', { defaultValue: 'Total' })}
                      </td>
                      {elementDetailData.columns.map((col) => {
                        const total = elementDetailData.totals?.[col];
                        return (
                          <td
                            key={col}
                            className={clsx(
                              'px-3 py-2',
                              total != null ? 'text-right font-mono font-bold text-oe-blue' : '',
                            )}
                          >
                            {total != null
                              ? total.toLocaleString(getIntlLocale(), { minimumFractionDigits: 0, maximumFractionDigits: 4 })
                              : ''}
                          </td>
                        );
                      })}
                    </tr>
                  </tfoot>
                </table>
              )}
            </div>
          </div>
        </div>
      )}

      {/* CAD Quantity Tables Result */}
      {cadResult && !isPending && (
        <div
          ref={resultRegionRef}
          tabIndex={-1}
          role="region"
          aria-label={t('ai.cad_quantity_tables', { defaultValue: 'Quantity Tables' })}
          className="space-y-4 animate-card-in focus:outline-none"
          style={{ animationDelay: '50ms' }}
        >
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

      {/* AI Estimate Results — failed status. role="alert" so SRs
          announce the failure immediately; "Error:" sr-only prefix +
          icon means the failure does not rely on red colour alone. */}
      {result && !isPending && result.status === 'failed' && result.error_message && (
        <div
          ref={resultRegionRef}
          tabIndex={-1}
          role="alert"
          className="animate-card-in focus:outline-none"
          style={{ animationDelay: '50ms' }}
        >
          <Card>
            <CardContent>
              <div className="flex items-start gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-red-50 dark:bg-red-500/10">
                  <AlertCircle size={16} className="text-red-500" aria-hidden="true" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-content-primary">
                    <span className="sr-only">
                      {t('ai.error_prefix', { defaultValue: 'Error: ' })}
                    </span>
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
                    icon={<RotateCcw size={14} aria-hidden="true" />}
                  >
                    {t('ai.try_again', { defaultValue: 'Try again' })}
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* AI Estimate Results — success. tabIndex={-1} + ref means the
          useEffect above can programmatically move focus here once the
          result lands, so SR users land on the new content. */}
      {result && !isPending && result.status === 'completed' && result.items.length > 0 && (
        <div
          ref={resultRegionRef}
          tabIndex={-1}
          role="region"
          aria-label={t('ai.results', { defaultValue: 'Estimate Results' })}
          className="space-y-4 animate-card-in focus:outline-none"
          style={{ animationDelay: '50ms' }}
        >
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

          {/* Next steps — make the AI→BOQ→validate→tender pipeline explicit.
              Without this, "Save as BOQ" feels like the end of the road. */}
          <div className="rounded-xl border border-oe-blue/15 bg-oe-blue-subtle/20 p-4">
            <p className="flex items-center gap-1.5 text-xs font-semibold text-content-primary mb-1.5">
              <Info size={13} className="text-oe-blue" />
              {t('ai.estimate_after_title', { defaultValue: 'Recommended next steps' })}
            </p>
            <ul className="space-y-1 text-xs text-content-secondary leading-relaxed list-none">
              <li className="flex gap-2">
                <span className="text-oe-blue font-bold shrink-0">1.</span>
                {t('ai.estimate_after_1', {
                  defaultValue:
                    'Match rates against the CWICR cost database above so prices reflect real regional data, not AI guesses.',
                })}
              </li>
              <li className="flex gap-2">
                <span className="text-oe-blue font-bold shrink-0">2.</span>
                {t('ai.estimate_after_2', {
                  defaultValue:
                    'Save as a project BOQ — then review every quantity and rate in the BOQ editor before relying on the total.',
                })}
              </li>
              <li className="flex gap-2">
                <span className="text-oe-blue font-bold shrink-0">3.</span>
                {t('ai.estimate_after_3', {
                  defaultValue:
                    'Run validation (DIN 276 / GAEB / quality rules) to catch missing scope, zero prices and classification gaps.',
                })}
              </li>
            </ul>
            <div className="mt-3 flex flex-wrap gap-2">
              <Link
                to="/match-elements"
                className="inline-flex items-center gap-1.5 rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-secondary hover:border-oe-blue/40 hover:text-oe-blue transition-colors"
              >
                <Database size={13} />
                {t('ai.estimate_link_match', { defaultValue: 'Match Elements' })}
              </Link>
              <Link
                to="/validation"
                className="inline-flex items-center gap-1.5 rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-secondary hover:border-oe-blue/40 hover:text-oe-blue transition-colors"
              >
                <CheckCircle2 size={13} />
                {t('ai.estimate_link_validation', { defaultValue: 'Validation' })}
              </Link>
              <Link
                to="/costs"
                className="inline-flex items-center gap-1.5 rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-secondary hover:border-oe-blue/40 hover:text-oe-blue transition-colors"
              >
                <Search size={13} />
                {t('ai.estimate_link_costs', { defaultValue: 'Cost Database' })}
              </Link>
            </div>
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
    </div>
  );
}
