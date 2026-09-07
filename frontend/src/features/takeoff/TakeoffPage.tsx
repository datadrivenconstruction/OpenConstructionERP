// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useCallback, useRef, useMemo, useEffect, useId, lazy, Suspense } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  FileSearch,
  Upload,
  FileUp,
  FileText,
  Sparkles,
  Table2,
  Eye,
  Plus,
  CheckCircle2,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Loader2,
  X,
  Ruler,
  Box,
  Link2,
  ArrowRight,
  Layers,
  Pin,
  PinOff,
  GitCompare,
  BrainCircuit,
  FolderOpen,
} from 'lucide-react';

import { Button, Card, Badge, Input, Skeleton, DismissibleInfo, IntroRichText, Breadcrumb, ModuleGuideButton, ProjectFilePicker, type PickedProjectFile } from '@/shared/ui';
import { PDF_TAKEOFF_FORMATS } from '@/shared/lib/projectFileFormats';
import type { FileKind } from '@/features/file-manager/types';
import { PdfCompareDrawer } from './PdfCompareDrawer';
import { takeoffGuide } from './takeoffGuide';
import { apiGet, apiPost } from '@/shared/lib/api';
import { formatFileSize } from '@/shared/lib/formatters';
import { isTauri } from '@/shared/lib/desktop';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { takeoffApi, type TakeoffDocumentResponse } from './api';
import { canonicalizeUnit } from './lib/units';
import { aiApi } from '@/features/ai/api';
import { hasLlmKey } from '@/features/ai-estimator/useAiReadiness';
import { compareNames } from '@/shared/lib/collator';

const TakeoffViewerModule = lazy(() => import('@/modules/pdf-takeoff/TakeoffViewerModule'));

/** The module's own file store, listed in the picker beside the project's
 *  documents area. Module scope, so a stable reference the picker can key its
 *  query on rather than a fresh array every render. */
const TAKEOFF_PICKER_KINDS: readonly FileKind[] = ['takeoff'];

/* ── Types ─────────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
  description: string;
  classification_standard: string;
}

interface BOQ {
  id: string;
  project_id: string;
  name: string;
  description: string;
  status: string;
}

interface ExtractedElement {
  id: string;
  category: string;
  description: string;
  quantity: number;
  unit: string;
  confidence: number;
  selected: boolean;
}

interface AnalysisResult {
  elements: ExtractedElement[];
  summary: {
    total_elements: number;
    categories: Record<string, { count: number; total_quantity: number; unit: string }>;
  };
}

interface UploadedDocument {
  id: string;
  filename: string;
  pages: number;
  size_bytes: number;
  uploaded_at: string;
  analysis: AnalysisResult | null;
  analyzing: boolean;
  extractingTables: boolean;
  uploadError?: string;
  uploading?: boolean;
}

interface QuickMeasurement {
  description: string;
  value: string;
  unit: string;
}

type UnitOption =
  | 'm'
  | 'm2'
  | 'm3'
  | 'kg'
  | 'pcs'
  | 'lsum'
  | 't'
  | 'l'
  // US construction trade units (GitHub #320). A metric measurement links into
  // a position priced in one of these and is converted on link (GitHub #319).
  | 'ft'
  | 'ft2'
  | 'ft3'
  | 'yd'
  | 'cy'
  | 'bdft'
  | 'sq';

/* ── Constants ─────────────────────────────────────────────────────────── */

const UNIT_OPTIONS: UnitOption[] = [
  'm',
  'm2',
  'm3',
  'kg',
  'pcs',
  'lsum',
  't',
  'l',
  'ft',
  'ft2',
  'ft3',
  'yd',
  'cy',
  'bdft',
  'sq',
];

// No upload size cap — kept Number.POSITIVE_INFINITY as a sentinel so
// the existing filter expressions still type-check while allowing any
// payload through. Per product policy.
const MAX_FILE_SIZE_BYTES = Number.POSITIVE_INFINITY;

/* ── Helpers ───────────────────────────────────────────────────────────── */

// `formatFileSize` lives in `@/shared/lib/formatters` — same implementation,
// shared with the AI and Costs surfaces. Imported above.

function formatTimeAgo(isoDate: string, t: (key: string, fallback: string) => string): string {
  const diff = Date.now() - new Date(isoDate).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return t('takeoff.just_now', 'Just now');
  if (minutes < 60) {
    return t('takeoff.minutes_ago', '{{count}} min ago').replace('{{count}}', String(minutes));
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return t('takeoff.hours_ago', '{{count}}h ago').replace('{{count}}', String(hours));
  }
  const days = Math.floor(hours / 24);
  return t('takeoff.days_ago', '{{count}}d ago').replace('{{count}}', String(days));
}

function getConfidenceVariant(confidence: number): 'success' | 'warning' | 'error' {
  if (confidence >= 0.8) return 'success';
  if (confidence >= 0.5) return 'warning';
  return 'error';
}

/* ── Sub-components ────────────────────────────────────────────────────── */

function SelectDropdown({
  label,
  value,
  onChange,
  options,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  placeholder: string;
}) {
  // Stable, label-derived id so axe can match the <label> to the <select>.
  const selectId = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label
        htmlFor={selectId}
        className="text-sm font-medium text-content-primary"
      >
        {label}
      </label>
      <select
        id={selectId}
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={clsx(
          'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm',
          'transition-all duration-normal ease-oe',
          'focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue',
          'hover:border-content-tertiary',
          !value ? 'text-content-tertiary' : 'text-content-primary',
        )}
      >
        <option value="">{placeholder}</option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function DropZone({
  onFilesSelected,
  disabled,
}: {
  onFilesSelected: (files: File[]) => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);
      if (disabled) return;

      const files = Array.from(e.dataTransfer.files).filter(
        (f) =>
          (f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf')) &&
          f.size <= MAX_FILE_SIZE_BYTES,
      );
      if (files.length > 0) {
        onFilesSelected(files);
      }
    },
    [disabled, onFilesSelected],
  );

  const handleClick = useCallback(() => {
    if (!disabled) {
      fileInputRef.current?.click();
    }
  }, [disabled]);

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []).filter(
        (f) =>
          (f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf')) &&
          f.size <= MAX_FILE_SIZE_BYTES,
      );
      if (files.length > 0) {
        onFilesSelected(files);
      }
      // Reset so the same file can be selected again
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    },
    [onFilesSelected],
  );

  return (
    <div className="rounded-2xl bg-surface-primary border border-border-light shadow-lg shadow-black/5 dark:shadow-black/20 p-6">
      <div
        role="button"
        tabIndex={0}
        aria-label={t('takeoff.upload_aria', { defaultValue: 'Upload PDF takeoff file' })}
        onClick={handleClick}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') handleClick();
        }}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={clsx(
          'relative flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-10',
          'transition-all duration-normal ease-oe cursor-pointer min-h-[200px]',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2',
          disabled && 'opacity-40 pointer-events-none',
          isDragOver
            ? 'border-oe-blue bg-oe-blue/5 scale-[1.01]'
            : 'border-border-medium hover:border-oe-blue hover:bg-blue-50/50 dark:hover:bg-blue-950/20',
        )}
      >
        <div
          className={clsx(
            'flex h-14 w-14 items-center justify-center rounded-xl border transition-colors duration-fast',
            isDragOver
              ? 'bg-oe-blue/10 border-oe-blue/30 text-oe-blue'
              : 'bg-gradient-to-br from-blue-50 to-blue-100 dark:from-blue-950/30 dark:to-blue-900/20 border-blue-200/50 dark:border-blue-800/30 text-oe-blue',
          )}
        >
          <FileUp size={26} strokeWidth={1.5} />
        </div>
        <p className="text-sm font-semibold text-content-primary">
          {t('takeoff.drop_file_here', 'Drop your PDF here')}
        </p>
        <p className="text-[11px] text-content-quaternary">
          {t('takeoff.file_limit', 'PDF')}
        </p>
        <div className="flex items-center gap-2 mt-1">
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-950/30 text-blue-600 dark:text-blue-400 border border-blue-200/50 dark:border-blue-800/30">.pdf</span>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          onChange={handleFileChange}
          className="hidden"
          aria-label={t('takeoff.upload_pdf', 'Upload PDF')}
        />
      </div>
      <p className="text-[11px] text-content-tertiary mt-3">
        {t('takeoff.formats_detailed', {
          defaultValue: 'PDF construction drawings \u2014 vector floor plans, sections and scans. AI will extract walls, slabs, doors, and other elements with quantities.',
        })}
      </p>
    </div>
  );
}

function ElementRow({
  element,
  onToggleSelect,
}: {
  element: ExtractedElement;
  onToggleSelect: (id: string) => void;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg px-3 py-2 hover:bg-surface-secondary/50 transition-colors duration-fast">
      <input
        type="checkbox"
        checked={element.selected}
        onChange={() => onToggleSelect(element.id)}
        className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30 cursor-pointer"
      />
      <div className="min-w-0 flex-1">
        <span className="text-sm text-content-primary">{element.description}</span>
      </div>
      <span className="text-sm font-medium tabular-nums text-content-primary">
        {element.quantity}
      </span>
      <Badge variant="neutral" size="sm">
        {element.unit}
      </Badge>
      <Badge variant={getConfidenceVariant(element.confidence)} size="sm">
        {Math.round(element.confidence * 100)}%
      </Badge>
    </div>
  );
}

function DocumentCard({
  doc,
  onAnalyze,
  onExtractTables,
  onRemove,
  onToggleElement,
  onSelectAll,
  onDeselectAll,
  onAddToBOQ,
  onView,
  boqSelected,
  aiConnected,
}: {
  doc: UploadedDocument;
  onAnalyze: (id: string) => void;
  onExtractTables: (id: string) => void;
  onRemove: (id: string) => void;
  onToggleElement: (docId: string, elementId: string) => void;
  onSelectAll: (docId: string) => void;
  onDeselectAll: (docId: string) => void;
  onAddToBOQ: (docId: string) => void;
  onView: (docId: string) => void;
  boqSelected: boolean;
  aiConnected: boolean;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(true);

  const selectedCount = doc.analysis
    ? doc.analysis.elements.filter((el) => el.selected).length
    : 0;
  const totalCount = doc.analysis ? doc.analysis.elements.length : 0;

  const hasError = !!doc.uploadError;
  const isUploading = !!doc.uploading;

  return (
    <Card className={clsx('overflow-hidden', hasError && 'border-semantic-error/40')}>
      {/* Document header */}
      <div className="flex items-start gap-3">
        <div className={clsx(
          'flex h-10 w-10 shrink-0 items-center justify-center rounded-lg',
          hasError
            ? 'bg-semantic-error-bg text-semantic-error'
            : isUploading
              ? 'bg-oe-blue-subtle text-oe-blue-text'
              : doc.analysis
                ? 'bg-semantic-success-bg text-semantic-success'
                : 'bg-surface-secondary text-content-tertiary',
        )}>
          {isUploading ? (
            <Loader2 size={20} strokeWidth={1.5} className="animate-spin" />
          ) : (
            <FileText size={20} strokeWidth={1.5} />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-content-primary truncate">
              {doc.filename}
            </h3>
            {hasError && (
              <Badge variant="error" size="sm">
                {t('takeoff.upload_failed', 'Upload failed')}
              </Badge>
            )}
            {isUploading && (
              <Badge variant="blue" size="sm">
                {t('takeoff.uploading', 'Uploading...')}
              </Badge>
            )}
            <button
              onClick={() => onRemove(doc.id)}
              className="shrink-0 rounded-md p-1 text-content-tertiary hover:text-semantic-error hover:bg-semantic-error-bg transition-colors duration-fast"
              title={t('common.delete', 'Delete')}
            >
              <X size={14} />
            </button>
          </div>
          <p className="mt-0.5 text-xs text-content-tertiary">
            {doc.pages > 0 ? `${doc.pages} ${t('takeoff.pages', 'pages')} \u2022 ` : ''}
            {formatFileSize(doc.size_bytes)}{' '}
            &bull; {t('takeoff.uploaded', 'Uploaded')}{' '}
            {formatTimeAgo(doc.uploaded_at, t)}
          </p>
          {hasError && (
            <p className="mt-1 text-xs text-semantic-error">
              {doc.uploadError}
            </p>
          )}
        </div>
      </div>

      {/* Action buttons */}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          size="sm"
          icon={
            doc.analyzing ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Sparkles size={14} />
            )
          }
          disabled={doc.analyzing || doc.extractingTables || isUploading || hasError}
          onClick={() => onAnalyze(doc.id)}
        >
          {doc.analyzing
            ? t('takeoff.analyzing', 'Analyzing...')
            : t('takeoff.analyze_with_ai', 'Analyze with AI')}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          icon={
            doc.extractingTables ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Table2 size={14} />
            )
          }
          disabled={doc.analyzing || doc.extractingTables || isUploading || hasError}
          onClick={() => onExtractTables(doc.id)}
        >
          {doc.extractingTables
            ? t('takeoff.extracting', 'Extracting...')
            : t('takeoff.extract_tables', 'Extract Tables')}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          icon={<Eye size={14} />}
          disabled={isUploading || hasError}
          aria-label={t('takeoff.view_aria', {
            defaultValue: 'View {{name}}',
            name: doc.filename,
          })}
          onClick={() => onView(doc.id)}
        >
          {t('takeoff.view', 'View')}
        </Button>
      </div>

      {/* AI-not-connected hint — the Analyze / Extract Tables buttons call an
          LLM provider, so guide the user to settings when none is connected.
          Suppressed once an analysis already exists. */}
      {!aiConnected && !doc.analysis && !hasError && (
        <p className="mt-2.5 flex flex-wrap items-center gap-1 text-xs text-content-tertiary">
          <BrainCircuit size={13} className="shrink-0 text-oe-blue" />
          {t('takeoff.ai_not_connected_hint', {
            defaultValue: 'Analyze with AI needs an AI provider connected.',
          })}
          <Link
            to="/settings?tab=ai"
            className="font-semibold text-oe-blue hover:underline"
          >
            {t('takeoff.ai_setup.connect_cta', { defaultValue: 'Connect an AI provider' })}
          </Link>
        </p>
      )}

      {/* Analysis results */}
      {doc.analysis && (
        <div className="mt-4 border-t border-border-light pt-4 animate-fade-in">
          <button
            onClick={() => setExpanded((prev) => !prev)}
            className="flex w-full items-center gap-2 text-left"
          >
            <span className="text-content-tertiary">
              {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </span>
            <CheckCircle2 size={16} className="text-semantic-success" />
            <span className="text-sm font-medium text-content-primary">
              {t('takeoff.ai_analysis_results', 'AI Analysis Results')}
            </span>
            <Badge variant="blue" size="sm">
              {t('takeoff.found_elements', '{{count}} elements found').replace(
                '{{count}}',
                String(doc.analysis.summary.total_elements),
              )}
            </Badge>
          </button>

          {expanded && (
            <div className="mt-3 space-y-3 animate-fade-in">
              {/* Category summary */}
              <div className="rounded-lg bg-surface-secondary/50 px-4 py-3 space-y-1.5">
                <p className="text-xs font-medium text-content-secondary uppercase tracking-wider">
                  {t('takeoff.summary', 'Summary')}
                </p>
                {Object.entries(doc.analysis.summary.categories).map(([cat, info]) => (
                  <div key={cat} className="flex items-center gap-2 text-sm">
                    <span className="text-content-tertiary">&bull;</span>
                    <span className="text-content-secondary">
                      {info.count} {cat}
                    </span>
                    <span className="text-content-tertiary">
                      ({t('takeoff.total_quantity', 'total')}: {info.total_quantity} {info.unit})
                    </span>
                  </div>
                ))}
              </div>

              {/* Element list */}
              <div className="space-y-1">
                <div className="flex items-center justify-between px-3 py-1">
                  <span className="text-xs text-content-tertiary">
                    {selectedCount}/{totalCount} {t('takeoff.selected', 'selected')}
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => onSelectAll(doc.id)}
                      className="text-xs text-oe-blue hover:underline"
                    >
                      {t('takeoff.select_all', 'Select all')}
                    </button>
                    <span className="text-content-tertiary">|</span>
                    <button
                      onClick={() => onDeselectAll(doc.id)}
                      className="text-xs text-content-tertiary hover:text-content-secondary hover:underline"
                    >
                      {t('takeoff.deselect_all', 'Deselect all')}
                    </button>
                  </div>
                </div>
                {doc.analysis.elements.map((el) => (
                  <ElementRow
                    key={el.id}
                    element={el}
                    onToggleSelect={(elId) => onToggleElement(doc.id, elId)}
                  />
                ))}
              </div>

              {/* Add to BOQ button */}
              <div className="pt-3 border-t border-border-light mt-2 space-y-2">
                <div className="flex items-center gap-3">
                  <Button
                    variant="primary"
                    size="sm"
                    icon={<Plus size={14} />}
                    disabled={selectedCount === 0}
                    onClick={() => onAddToBOQ(doc.id)}
                  >
                    {t('takeoff.add_selected_to_boq', 'Add {{count}} to BOQ').replace(
                      '{{count}}',
                      String(selectedCount),
                    )}
                  </Button>
                </div>
                {!boqSelected && (
                  <div className="flex items-center gap-2 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/40 px-3 py-2">
                    <AlertTriangle size={14} className="text-amber-600 shrink-0" />
                    <span className="text-xs text-amber-700 dark:text-amber-400 font-medium">
                      {t('takeoff.select_boq_warning', 'Select a project & BOQ above to add items')}
                    </span>
                  </div>
                )}
              </div>

              {/* Next steps */}
              <div className="pt-3 border-t border-border-light mt-2">
                <p className="text-2xs font-semibold text-content-tertiary uppercase tracking-wider mb-2">
                  {t('takeoff.next_steps', 'Next Steps')}
                </p>
                <div className="flex flex-wrap gap-2">
                  <a
                    href="/bim"
                    className="flex items-center gap-1.5 rounded-lg border border-border-light px-3 py-1.5 text-xs text-content-secondary transition-colors hover:bg-oe-blue-subtle hover:text-oe-blue-text hover:border-oe-blue/30"
                  >
                    <Box size={13} />
                    {t('takeoff.open_in_bim', 'Open in BIM Viewer')}
                    <ArrowRight size={11} className="text-content-quaternary" />
                  </a>
                  <a
                    href="/boq"
                    className="flex items-center gap-1.5 rounded-lg border border-border-light px-3 py-1.5 text-xs text-content-secondary transition-colors hover:bg-oe-blue-subtle hover:text-oe-blue-text hover:border-oe-blue/30"
                  >
                    <Link2 size={13} />
                    {t('takeoff.link_to_boq', 'Link to BOQ')}
                    <ArrowRight size={11} className="text-content-quaternary" />
                  </a>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Analyzing skeleton */}
      {doc.analyzing && !doc.analysis && (
        <div className="mt-4 border-t border-border-light pt-4 space-y-3">
          <div className="flex items-center gap-2">
            <Loader2 size={16} className="animate-spin text-oe-blue" />
            <span className="text-sm text-content-secondary">
              {t('takeoff.analyzing_document', 'Analyzing document with AI...')}
            </span>
          </div>
          <div className="space-y-2">
            <Skeleton height={16} className="w-3/4" rounded="md" />
            <Skeleton height={16} className="w-1/2" rounded="md" />
            <Skeleton height={16} className="w-2/3" rounded="md" />
          </div>
        </div>
      )}
    </Card>
  );
}

function QuickMeasurementForm({
  onAdd,
  disabled,
}: {
  onAdd: (measurement: QuickMeasurement) => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  const [description, setDescription] = useState('');
  const [value, setValue] = useState('');
  const [unit, setUnit] = useState<string>('m2');
  const unitSelectId = useId();

  const handleSubmit = useCallback(() => {
    if (!description.trim() || !value.trim()) return;
    onAdd({ description: description.trim(), value: value.trim(), unit });
    setDescription('');
    setValue('');
  }, [description, value, unit, onAdd]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit],
  );

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
      <div className="flex-1">
        <Input
          label={t('takeoff.description', 'Description')}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t('takeoff.description_placeholder', 'e.g., External wall area')}
          disabled={disabled}
        />
      </div>
      <div className="w-32">
        <Input
          label={t('takeoff.value', 'Value')}
          type="number"
          step="any"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="0.00"
          disabled={disabled}
        />
      </div>
      <div className="w-28">
        <div className="flex flex-col gap-1.5">
          <label
            htmlFor={unitSelectId}
            className="text-sm font-medium text-content-primary"
          >
            {t('takeoff.unit', 'Unit')}
          </label>
          <select
            id={unitSelectId}
            aria-label={t('a11y.takeoff.unit_select', { defaultValue: 'Unit' })}
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            disabled={disabled}
            className={clsx(
              'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm',
              'transition-all duration-normal ease-oe text-content-primary',
              'focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue',
              'hover:border-content-tertiary',
              disabled && 'opacity-40 cursor-not-allowed',
            )}
          >
            {UNIT_OPTIONS.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="shrink-0">
        <Button
          variant="primary"
          size="md"
          icon={<Plus size={16} />}
          disabled={disabled || !description.trim() || !value.trim()}
          onClick={handleSubmit}
        >
          {t('takeoff.add_to_boq', 'Add to BOQ')}
        </Button>
      </div>
    </div>
  );
}

/* ── Document Filmstrip ─────────────────────────────────────────────── */

type FilmstripSort = 'recent' | 'name' | 'size';

const PINNED_LS_KEY = 'oe-takeoff-pinned-docs';

function readPinned(): Set<string> {
  try {
    const raw = window.localStorage.getItem(PINNED_LS_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw) as string[];
    return new Set(Array.isArray(parsed) ? parsed : []);
  } catch {
    return new Set();
  }
}

function writePinned(ids: Set<string>): void {
  try {
    window.localStorage.setItem(PINNED_LS_KEY, JSON.stringify(Array.from(ids)));
  } catch {
    /* localStorage may be unavailable (private mode); silently ignore. */
  }
}

/** Bottom panel showing uploaded takeoff PDFs — light-themed, styled like BIM model filmstrip. */
function TakeoffDocFilmstrip({
  documents,
  activeDocId,
  isLoading,
  onSelectDoc,
  onDeleteDoc,
  onUploadNew,
}: {
  documents: UploadedDocument[];
  activeDocId: string | null;
  isLoading?: boolean;
  onSelectDoc: (id: string) => void;
  onDeleteDoc: (id: string) => void;
  onUploadNew: () => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(true);
  const [sortBy, setSortBy] = useState<FilmstripSort>('recent');
  const [pinned, setPinned] = useState<Set<string>>(() => readPinned());

  const togglePin = useCallback((id: string) => {
    setPinned((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      writePinned(next);
      return next;
    });
  }, []);

  const sortedDocs = useMemo(() => {
    const arr = [...documents];
    arr.sort((a, b) => {
      // Pinned docs always come first.
      const aPin = pinned.has(a.id) ? 1 : 0;
      const bPin = pinned.has(b.id) ? 1 : 0;
      if (aPin !== bPin) return bPin - aPin;
      if (sortBy === 'name') return compareNames(a.filename, b.filename);
      if (sortBy === 'size') return b.size_bytes - a.size_bytes;
      // 'recent' — newest uploaded_at first.
      const at = new Date(a.uploaded_at || 0).getTime();
      const bt = new Date(b.uploaded_at || 0).getTime();
      return bt - at;
    });
    return arr;
  }, [documents, sortBy, pinned]);

  return (
    <div className="shrink-0 bg-surface-primary border border-border-light rounded-xl mt-3 overflow-hidden">
      {/* Header — always visible */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center w-full px-4 py-2 cursor-pointer group hover:bg-surface-secondary/40 transition-colors"
      >
        <Layers size={14} className="text-content-tertiary mr-2 shrink-0" />
        <span className="text-xs font-semibold text-content-primary">
          {t('takeoff.documents_panel', { defaultValue: 'Documents' })}
        </span>
        <span className="text-[11px] text-content-quaternary ml-1.5">
          ({documents.length})
        </span>
        <ChevronDown
          size={14}
          className={clsx(
            'ml-auto text-content-tertiary transition-transform duration-200',
            expanded ? '' : '-rotate-90',
          )}
        />
      </button>

      {/* Collapsible document cards */}
      <div
        className="overflow-hidden transition-all duration-300 ease-in-out"
        style={{ maxHeight: expanded ? '120px' : '0px', opacity: expanded ? 1 : 0 }}
      >
        <div className="flex items-center gap-2 px-4 pb-2.5 overflow-x-auto">
          {/* Sort selector — sticky-left so it stays visible while the
              filmstrip scrolls horizontally on small viewports. */}
          {documents.length > 1 && (
            <label className="shrink-0 flex items-center gap-1 text-[10px] text-content-tertiary">
              <span className="sr-only">
                {t('takeoff.sort_by', { defaultValue: 'Sort by' })}
              </span>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as FilmstripSort)}
                aria-label={t('takeoff.sort_by', { defaultValue: 'Sort by' })}
                className="h-6 rounded border border-border-light bg-surface-primary px-1 text-[10px] text-content-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                data-testid="takeoff-filmstrip-sort"
              >
                <option value="recent">
                  {t('takeoff.sort_recent', { defaultValue: 'Recent' })}
                </option>
                <option value="name">
                  {t('takeoff.sort_name', { defaultValue: 'Name' })}
                </option>
                <option value="size">
                  {t('takeoff.sort_size', { defaultValue: 'Size' })}
                </option>
              </select>
            </label>
          )}
          {isLoading && documents.length === 0 ? (
            <Loader2 size={14} className="animate-spin text-content-tertiary" />
          ) : documents.length > 0 ? (
            sortedDocs.map((doc) => {
              const isActive = doc.id === activeDocId;
              const hasError = !!doc.uploadError;
              const isUploading = !!doc.uploading;
              const isPinned = pinned.has(doc.id);
              return (
                <button
                  key={doc.id}
                  type="button"
                  onClick={() => onSelectDoc(doc.id)}
                  disabled={isUploading || hasError}
                  aria-label={t('takeoff.open_doc_aria', {
                    defaultValue: 'Open {{name}}',
                    name: doc.filename,
                  })}
                  className={clsx(
                    'group relative shrink-0 w-44 text-start rounded-lg border transition-all duration-200 overflow-hidden',
                    'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
                    hasError
                      ? 'border-semantic-error/40 bg-semantic-error-bg/40'
                      : isActive
                        ? 'border-oe-blue bg-oe-blue-subtle/40 shadow-sm'
                        : 'border-border-light bg-surface-secondary/40 hover:bg-surface-secondary hover:border-oe-blue/30',
                    (isUploading || hasError) && 'cursor-not-allowed',
                  )}
                >
                  <div className="px-2.5 py-2">
                    <div className="flex items-center gap-1.5 mb-1">
                      {isUploading ? (
                        <Loader2 size={12} className="shrink-0 text-oe-blue animate-spin" />
                      ) : (
                        <FileText
                          size={12}
                          className={clsx(
                            'shrink-0',
                            isActive ? 'text-oe-blue' : 'text-content-tertiary',
                          )}
                        />
                      )}
                      <span
                        className={clsx(
                          'text-[11px] font-semibold truncate',
                          isActive ? 'text-oe-blue' : 'text-content-primary',
                        )}
                      >
                        {doc.filename}
                      </span>
                      {isPinned && (
                        <Pin
                          size={10}
                          className="shrink-0 text-oe-blue"
                          aria-label={t('takeoff.pinned', { defaultValue: 'Pinned' })}
                        />
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 text-[10px] text-content-quaternary">
                      {doc.pages > 0 && (
                        <>
                          <span>
                            {doc.pages} {t('takeoff.pages_short', { defaultValue: 'p' })}
                          </span>
                          <span>&middot;</span>
                        </>
                      )}
                      <span>{formatFileSize(doc.size_bytes)}</span>
                      {doc.uploaded_at && (
                        <>
                          <span>&middot;</span>
                          <span>{formatTimeAgo(doc.uploaded_at, t)}</span>
                        </>
                      )}
                    </div>
                  </div>
                  {/* Pin + delete buttons on hover */}
                  <span
                    role="button"
                    tabIndex={0}
                    onClick={(e) => {
                      e.stopPropagation();
                      togglePin(doc.id);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        e.stopPropagation();
                        togglePin(doc.id);
                      }
                    }}
                    className={clsx(
                      'absolute top-1 right-6 p-1 rounded transition-all',
                      isPinned
                        ? 'text-oe-blue opacity-100'
                        : 'text-content-quaternary hover:text-oe-blue-text hover:bg-oe-blue-subtle opacity-0 group-hover:opacity-100',
                    )}
                    title={
                      isPinned
                        ? t('takeoff.unpin', { defaultValue: 'Unpin' })
                        : t('takeoff.pin', { defaultValue: 'Pin to top' })
                    }
                    aria-label={
                      isPinned
                        ? t('takeoff.unpin', { defaultValue: 'Unpin' })
                        : t('takeoff.pin', { defaultValue: 'Pin to top' })
                    }
                  >
                    {isPinned ? <PinOff size={11} /> : <Pin size={11} />}
                  </span>
                  <span
                    role="button"
                    tabIndex={0}
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteDoc(doc.id);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.stopPropagation();
                        onDeleteDoc(doc.id);
                      }
                    }}
                    className="absolute top-1 right-1 p-1 rounded text-content-quaternary hover:text-semantic-error hover:bg-semantic-error-bg opacity-0 group-hover:opacity-100 transition-all"
                    title={t('common.delete', 'Delete')}
                    aria-label={t('common.delete', 'Delete')}
                  >
                    <X size={11} />
                  </span>
                </button>
              );
            })
          ) : (
            <span className="text-[11px] text-content-quaternary">
              {t('takeoff.no_documents_filmstrip', {
                defaultValue: 'No documents uploaded yet',
              })}
            </span>
          )}
          {/* Upload new doc button */}
          <button
            type="button"
            onClick={onUploadNew}
            className="flex items-center justify-center shrink-0 w-14 h-14 rounded-lg border-2 border-dashed border-border-medium hover:border-oe-blue/50 hover:bg-oe-blue/5 transition-all group"
            title={t('takeoff.upload_pdf', 'Upload PDF')}
          >
            <Plus
              size={18}
              className="text-content-quaternary group-hover:text-oe-blue transition-colors"
            />
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

type TakeoffTab = 'documents' | 'measurements';

/* ── AI setup notice ───────────────────────────────────────────────────── */

/**
 * Shown at the top of the Documents & AI tab. When no AI provider is
 * connected it explains, in plain language, that AI takeoff needs a provider
 * and links to the AI settings tab where the key is entered. Once a provider
 * is connected it collapses to a slim "ready" confirmation so the working UI
 * is never blocked. The numbered steps stay visible either way so a new user
 * always sees how the feature works.
 */
function AiTakeoffNotice({ connected }: { connected: boolean }) {
  const { t } = useTranslation();

  const steps = [
    t('takeoff.ai_setup.step_connect', {
      defaultValue: 'Connect an AI provider in settings (use any supported provider and your own API key).',
    }),
    t('takeoff.ai_setup.step_upload', {
      defaultValue: 'Upload a PDF drawing below.',
    }),
    t('takeoff.ai_setup.step_review', {
      defaultValue: 'Review the AI suggestions, confirm the ones you want, and send them to your BOQ.',
    }),
  ];

  return (
    <div
      data-testid="takeoff-ai-setup-notice"
      className={clsx(
        'mb-6 rounded-xl border px-5 py-4',
        connected
          ? 'border-emerald-200 bg-emerald-50/60 dark:border-emerald-900/50 dark:bg-emerald-900/15'
          : 'border-oe-blue/25 bg-oe-blue-subtle/50',
      )}
    >
      <div className="flex items-start gap-3">
        <div
          className={clsx(
            'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg',
            connected
              ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-200'
              : 'bg-oe-blue/10 text-oe-blue',
          )}
        >
          {connected ? <CheckCircle2 size={18} /> : <BrainCircuit size={18} />}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-content-primary">
            {connected
              ? t('takeoff.ai_setup.ready_title', { defaultValue: 'AI provider connected' })
              : t('takeoff.ai_setup.title', { defaultValue: 'Connect an AI provider to use AI takeoff' })}
          </h3>
          <p className="mt-0.5 text-xs text-content-tertiary">
            {connected
              ? t('takeoff.ai_setup.ready_body', {
                  defaultValue:
                    'Upload a PDF below and AI will extract elements with quantities for you to review.',
                })
              : t('takeoff.ai_setup.body', {
                  defaultValue:
                    'AI takeoff reads your drawings and suggests elements with quantities. It needs an AI provider connected first. You can still measure by hand and use Quick Measurements without it.',
                })}
          </p>

          {/* Numbered how-it-works steps */}
          <ol className="mt-3 space-y-1.5">
            {steps.map((step, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-content-secondary">
                <span
                  className={clsx(
                    'mt-px flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-2xs font-bold',
                    connected
                      ? 'bg-emerald-200/70 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200'
                      : 'bg-oe-blue/15 text-oe-blue',
                  )}
                >
                  {i + 1}
                </span>
                <span>{step}</span>
              </li>
            ))}
          </ol>

          {!connected && (
            <Link
              to="/settings?tab=ai"
              data-testid="takeoff-connect-ai"
              className="mt-3.5 inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3.5 py-2 text-xs font-semibold text-content-inverse transition-colors hover:bg-oe-blue/90"
            >
              {t('takeoff.ai_setup.connect_cta', { defaultValue: 'Connect an AI provider' })}
              <ArrowRight size={13} />
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

export function TakeoffPage() {
  const { t } = useTranslation();

  /* ── Tab state (synced with ?tab= query parameter from sidebar) ──── */

  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const tabFromUrl = searchParams.get('tab');
  const initialTab: TakeoffTab =
    tabFromUrl === 'measurements' || tabFromUrl === 'documents' ? tabFromUrl : 'documents';
  const [activeTab, setActiveTab] = useState<TakeoffTab>(initialTab);

  // Keep tab in sync when navigating via sidebar links
  useEffect(() => {
    if (tabFromUrl === 'measurements' || tabFromUrl === 'documents') {
      setActiveTab(tabFromUrl);
    }
  }, [tabFromUrl]);

  /* ── State ──────────────────────────────────────────────────────────── */

  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const selectedProjectId = activeProjectId ?? '';
  const [selectedBoqId, setSelectedBoqId] = useState('');
  const [documents, setDocuments] = useState<UploadedDocument[]>([]);
  const [activeDocId, setActiveDocId] = useState<string | null>(null);
  const [addToBOQSuccess, setAddToBOQSuccess] = useState<string | null>(null);
  const [uploadErrorToast, setUploadErrorToast] = useState<string | null>(null);
  const filmstripUploadRef = useRef<HTMLInputElement>(null);

  /** Currently opened document in the Measurements viewer. ``id`` is the
   *  stable document UUID (takeoff doc PK or Project Files doc PK); it keys
   *  measurement identity instead of the filename (issue #238). */
  const [viewerDoc, setViewerDoc] = useState<{ url: string; name: string; id: string } | null>(
    null,
  );

  /** Revision compare drawer (Item 17) — diffs two takeoff PDFs. */
  const [showCompare, setShowCompare] = useState(false);

  /** Set when a deep-link references a measurement so the viewer can
   *  select + scroll-to it after the document and measurement list load. */
  const [initialMeasurementId, setInitialMeasurementId] = useState<string | null>(
    () => searchParams.get('measurementId'),
  );

  /** Set when the URL carries a `?page=` deep-link so the viewer can restore
   *  it after the document loads, instead of always landing on page 1
   *  (issue #386). Read once from the initial URL, mirroring
   *  `initialMeasurementId` above. */
  const [initialPage] = useState<number | null>(() => {
    const raw = searchParams.get('page');
    const parsed = raw ? parseInt(raw, 10) : NaN;
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  });

  /** The document id deep-linked at mount (`?doc=` or `?docId=`), if any.
   *  `initialPage` only makes sense for THIS document - the viewer is keyed
   *  by document id and remounts on document switch, so an unscoped
   *  `initialPage` would leak onto the next document opened in the same
   *  session. Captured once via a ref (mirrors `deepLinkConsumedRef` in the
   *  viewer). The only later write is the `?source=document` branch below,
   *  which swaps in the takeoff id that find-or-create resolved the deep-link
   *  to - still the same deep link, just under the id the viewer is keyed by. */
  const deepLinkedDocIdRef = useRef<string | null>(
    searchParams.get('doc') || searchParams.get('docId') || null,
  );

  /** True when a `?docId=` deep-link couldn't be resolved against either
   *  the takeoff documents catalogue or the project documents module —
   *  drives a friendly empty-state with a "back to /markups" link instead
   *  of a blank viewer. Reset every time the docId param changes. */
  const [deepLinkNotFound, setDeepLinkNotFound] = useState(false);

  /* ── AI provider readiness ─────────────────────────────────────────────
   * AI takeoff (Analyze with AI / Extract Tables) calls an LLM provider, so
   * the Documents & AI tab tells the user up front whether one is connected
   * and links to the AI settings tab when it is not. Errors degrade to
   * "not connected" so the guidance shows instead of an error. */
  const aiSettingsQuery = useQuery({
    queryKey: ['ai-settings'],
    queryFn: aiApi.getSettings,
    staleTime: 60_000,
    retry: false,
  });
  const aiConnected = hasLlmKey(aiSettingsQuery.data);

  /* ── Handle ?doc= / ?name= deep link from Documents / BOQ link icon ─ */

  useEffect(() => {
    const docId = searchParams.get('doc');
    const docName = searchParams.get('name');
    const tab = searchParams.get('tab');
    if (!docId) return;
    // Track the doc as active regardless of which tab the user landed on.
    setActiveDocId(docId);
    // On Measurements tab, rely on filmstripDocuments (hydrated from the
    // server) — inserting a placeholder here would duplicate the entry until
    // refetch and confuses the filmstrip. On Documents tab we need a
    // placeholder so the user sees a card immediately.
    if (tab !== 'measurements') {
      setDocuments((prev) => {
        if (prev.some((d) => d.id === docId)) return prev;
        return [
          ...prev,
          {
            id: docId,
            filename: docName
              ? decodeURIComponent(docName)
              : t('takeoff.document_placeholder', { defaultValue: 'Document' }),
            pages: 0,
            size_bytes: 0,
            uploaded_at: new Date().toISOString(),
            analysis: null,
            analyzing: false,
            extractingTables: false,
          },
        ];
      });
      setActiveTab('documents');
    }
  }, [searchParams]);

  /* ── Open linked PDF by filename — moved below serverDocuments query */

  /* ── Queries ────────────────────────────────────────────────────────── */

  const { data: projects, isLoading: projectsLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const { data: boqs, isLoading: boqsLoading } = useQuery({
    queryKey: ['boqs', selectedProjectId],
    queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${selectedProjectId}`),
    enabled: !!selectedProjectId,
  });

  /** Server-side list of previously uploaded takeoff documents for the active project. */
  const {
    data: serverDocuments,
    isLoading: serverDocumentsLoading,
    refetch: refetchServerDocuments,
  } = useQuery({
    queryKey: ['takeoff-documents', selectedProjectId],
    queryFn: () => takeoffApi.listDocuments(selectedProjectId || undefined),
    staleTime: 30_000,
  });

  /* ── Open linked PDF by filename (from BOQ link icon) ─────────────── */
  useEffect(() => {
    const docName = searchParams.get('name');
    const tab = searchParams.get('tab');
    if (!docName || tab !== 'measurements' || searchParams.get('doc')) return;
    if (!serverDocuments || serverDocuments.length === 0) return;
    const target = decodeURIComponent(docName).toLowerCase();
    const match = serverDocuments.find(
      (d) =>
        d.filename.toLowerCase() === target ||
        d.filename.toLowerCase() === target.replace(/\.[^.]+$/, ''),
    );
    if (!match) return;
    setActiveDocId(match.id);
    setViewerDoc({
      url: `/api/v1/takeoff/documents/${match.id}/download/`,
      name: match.filename,
      id: match.id,
    });
    setActiveTab('measurements');
    const next = new URLSearchParams(searchParams);
    next.delete('name');
    next.delete('page');
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, serverDocuments]);

  /* ── Restore viewer on reload when ?doc=X&tab=measurements ────────── */
  useEffect(() => {
    const docId = searchParams.get('doc');
    const tab = searchParams.get('tab');
    if (!docId || tab !== 'measurements') return;
    if (viewerDoc) return; // already open
    if (!serverDocuments || serverDocuments.length === 0) return;
    const match = serverDocuments.find((d) => d.id === docId);
    if (!match) return;
    setViewerDoc({
      url: `/api/v1/takeoff/documents/${docId}/download/`,
      name: match.filename,
      id: docId,
    });
    setActiveTab('measurements');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverDocuments, searchParams]);

  /* ── Cross-module open: ?doc=X&source=document ─────────────────────────
   * The unified /files page links a documents-module PDF here so the user
   * can start measuring without re-uploading. The `doc` id is the documents
   * table PK, NOT a takeoff_document id - so the viewer's own calls
   * (detect-scale, page-scales, measurements) used to 404 against it and
   * measurements got filed under the wrong id. We now ask the backend to
   * find-or-create a REAL takeoff_document for this source (idempotent, so a
   * second open reuses the same row) and drive the viewer entirely off THAT
   * takeoff id. The fallback display name is read from the optional `?name=`
   * param so the header isn't empty during the fetch.                    */
  useEffect(() => {
    const docId = searchParams.get('doc');
    const source = searchParams.get('source');
    if (!docId || source !== 'document') return;
    if (viewerDoc) return;
    let cancelled = false;
    (async () => {
      try {
        const takeoff = await apiPost<{ id: string; filename?: string; status?: string }>(
          `/v1/takeoff/documents/from-source/${encodeURIComponent(docId)}`,
        );
        if (cancelled) return;
        const displayName =
          takeoff.filename ||
          searchParams.get('name') ||
          t('takeoff.document_placeholder', { defaultValue: 'Document' });
        // Use the takeoff_document id everywhere from here on so scale-detect,
        // page-scales and measurements all resolve against takeoff_documents.
        setActiveDocId(takeoff.id);
        // Re-point the deep-link ref at the id the viewer will actually be
        // keyed by. `initialPage` is gated on `viewerDoc.id === ref`, and the
        // ref was captured at mount from `?doc=`, which on this path is the
        // documents-module id, not the takeoff id we just resolved. Without
        // this the two never match and a `?page=` alongside `?source=document`
        // is silently dropped, landing the user on page 1 of the right set -
        // which is what the sheet register's "measure this sheet" link needs.
        deepLinkedDocIdRef.current = takeoff.id;
        setViewerDoc({
          url: `/api/v1/takeoff/documents/${encodeURIComponent(takeoff.id)}/download/`,
          name: displayName,
          id: takeoff.id,
        });
        setActiveTab('measurements');
      } catch {
        if (cancelled) return;
        // The find-or-create failed (e.g. access denied, the source blob is
        // missing, or the file is not a PDF). Surface it instead of leaving a
        // silently empty page.
        useToastStore.getState().addToast({
          type: 'error',
          title: t('takeoff.open_failed_title', { defaultValue: 'Could not open file' }),
          message: t('takeoff.open_failed_msg', {
            defaultValue:
              'This file could not be opened in the takeoff viewer. It may have been moved, or you may not have access to it.',
          }),
        });
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  /* ── /markups deep-link: ?docId=<uuid|filename>&measurementId=<uuid> ───
   *
   * The unified Markups hub builds deep-links from `measurement.document_id`.
   * Since issue #238 a measurement's document_id is the stable document UUID,
   * so `docId` is usually a UUID; legacy rows written by older builds still
   * carry a filename. We handle both: a UUID id match against the takeoff
   * docs catalogue first, then a filename match as the legacy fallback.
   *
   * On hit: open the PDF in the Measurements viewer (passing the resolved
   * document UUID) and stash the measurementId so TakeoffViewerModule can
   * select + scroll-to it once the persistence hook has loaded the list.
   *
   * On miss: surface a "document not found" empty state with a back link
   * to /markups — far less confusing than the previous silent blank page.
   */
  useEffect(() => {
    const docId = searchParams.get('docId');
    const measurementId = searchParams.get('measurementId');
    const tab = searchParams.get('tab');
    // Track the measurementId param so the viewer can act on it once the
    // measurement list lands (the viewer fetches its own measurement list
    // keyed by the document UUID).
    setInitialMeasurementId(measurementId);

    if (!docId) {
      setDeepLinkNotFound(false);
      return;
    }
    if (tab === 'measurements') {
      setActiveTab('measurements');
    }
    if (viewerDoc) return; // already opened from a prior effect
    if (!serverDocuments) return; // wait for the catalogue to load

    const decodedDocId = decodeURIComponent(docId);
    const lowered = decodedDocId.toLowerCase();
    // Try UUID id match first (the hub now stores the document UUID), then
    // fall back to a filename match for legacy filename-keyed deeplinks.
    const match =
      serverDocuments.find((d) => d.id === decodedDocId) ??
      serverDocuments.find(
        (d) =>
          d.filename.toLowerCase() === lowered ||
          d.filename.toLowerCase() === lowered.replace(/\.[^.]+$/, ''),
      );

    if (match) {
      setDeepLinkNotFound(false);
      setActiveDocId(match.id);
      setViewerDoc({
        url: `/api/v1/takeoff/documents/${match.id}/download/`,
        name: match.filename,
        id: match.id,
      });
      setActiveTab('measurements');
    } else if (serverDocuments.length >= 0) {
      // Catalogue is loaded but no row matches — surface a friendly miss.
      setDeepLinkNotFound(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, serverDocuments]);

  /* ── Mutations ──────────────────────────────────────────────────────── */

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append('file', file);

      const token = useAuthStore.getState().accessToken;
      const headers: HeadersInit = {};
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      // Attach the active project so the document is stored under it (#242).
      // Without this the row saved with project_id=NULL and the
      // project-filtered reload (listDocuments(selectedProjectId)) dropped it,
      // so an uploaded PDF vanished on refresh. The backend verifies access to
      // the project before any write.
      const uploadUrl = selectedProjectId
        ? `/api/v1/takeoff/documents/upload/?project_id=${encodeURIComponent(selectedProjectId)}`
        : `/api/v1/takeoff/documents/upload/`;
      const response = await fetch(uploadUrl, {
        method: 'POST',
        headers,
        body: formData,
      });

      if (!response.ok) {
        // Surface the server's structured error message (FastAPI returns
        // {"detail": "..."}) instead of the generic HTTP status text so the
        // user sees the real reason (e.g. "File does not appear to be a valid
        // PDF", "This PDF is password-protected", "Too many uploads"). Falls
        // back to statusText when the response body is not JSON or has no
        // detail field (D-TKC-UP01).
        let detail = response.statusText;
        try {
          const body = await response.json() as { detail?: string };
          if (typeof body?.detail === 'string' && body.detail) {
            detail = body.detail;
          }
        } catch {
          // non-JSON body — keep statusText
        }
        throw new Error(detail);
      }

      return (await response.json()) as {
        id: string;
        filename: string;
        pages: number;
        size_bytes: number;
      };
    },
    // NOTE: onSuccess/onError handled per-call in handleFilesSelected
  });

  const analyzeMutation = useMutation({
    mutationFn: async (docId: string) => {
      return apiPost<AnalysisResult>(`/v1/takeoff/documents/${docId}/analyze/`);
    },
    onMutate: (docId) => {
      setDocuments((prev) =>
        prev.map((d) => (d.id === docId ? { ...d, analyzing: true } : d)),
      );
    },
    onSuccess: (data, docId) => {
      const elements = data.elements.map((el) => ({ ...el, selected: true }));
      setDocuments((prev) =>
        prev.map((d) =>
          d.id === docId
            ? {
                ...d,
                analyzing: false,
                analysis: { ...data, elements },
              }
            : d,
        ),
      );
    },
    onError: (_err, docId) => {
      setDocuments((prev) =>
        prev.map((d) => (d.id === docId ? { ...d, analyzing: false } : d)),
      );
    },
  });

  const extractTablesMutation = useMutation({
    mutationFn: async (docId: string) => {
      return apiPost<AnalysisResult>(`/v1/takeoff/documents/${docId}/extract-tables/`);
    },
    onMutate: (docId) => {
      setDocuments((prev) =>
        prev.map((d) => (d.id === docId ? { ...d, extractingTables: true } : d)),
      );
    },
    onSuccess: (data, docId) => {
      const elements = data.elements.map((el) => ({ ...el, selected: true }));
      setDocuments((prev) =>
        prev.map((d) =>
          d.id === docId
            ? {
                ...d,
                extractingTables: false,
                analysis: { ...data, elements },
              }
            : d,
        ),
      );
    },
    onError: (_err, docId) => {
      setDocuments((prev) =>
        prev.map((d) => (d.id === docId ? { ...d, extractingTables: false } : d)),
      );
    },
  });

  const addToBOQMutation = useMutation({
    mutationFn: async (
      items: {
        description: string;
        quantity: number;
        unit: string;
        source?: string;
        metadata?: Record<string, unknown>;
      }[],
    ) => {
      if (!selectedBoqId) {
        throw new Error(t('takeoff.no_boq_selected', 'Please select a project and BOQ first'));
      }
      return apiPost(`/v1/boq/boqs/${selectedBoqId}/positions/bulk/`, { items });
    },
    onSuccess: (_data, variables) => {
      const msg = t('takeoff.added_to_boq_success_count', '{{count}} items added to BOQ successfully').replace(
        '{{count}}',
        String(variables.length),
      );
      setAddToBOQSuccess(msg);
      useToastStore.getState().addToast({ type: 'success', title: t('takeoff.added_title', 'Added to BOQ'), message: msg });
      setTimeout(() => setAddToBOQSuccess(null), 5000);
    },
    onError: (err: Error) => {
      const msg = err.message || t('takeoff.add_to_boq_failed', 'Failed to add items to BOQ');
      setUploadErrorToast(msg);
      useToastStore.getState().addToast({ type: 'error', title: t('takeoff.error_title', 'Error'), message: msg });
      setTimeout(() => setUploadErrorToast(null), 5000);
    },
  });

  /* ── Callbacks ──────────────────────────────────────────────────────── */

  const handleProjectChange = useCallback(
    (projectId: string) => {
      const name = (projects || []).find((p) => p.id === projectId)?.name ?? '';
      if (projectId) {
        useProjectContextStore.getState().setActiveProject(projectId, name);
      } else {
        useProjectContextStore.getState().clearProject();
      }
      setSelectedBoqId('');
    },
    [projects],
  );

  const handleBoqChange = useCallback((boqId: string) => {
    setSelectedBoqId(boqId);
  }, []);

  // BUG-DUAL-UPLOAD-PDF — the takeoff upload mutation already persists
  // the PDF on the server.  An earlier helper (``createDocumentRecord``)
  // re-uploaded the same file to ``/api/v1/documents/upload`` for
  // "cross-referencing", which doubled the bytes-on-disk and showed two
  // identical entries in the Documents module.  Removed.  If a takeoff
  // doc needs to surface in the Documents module, do it backend-side at
  // upload time via FK, not by sending the file twice.

  const handleFilesSelected = useCallback(
    (files: File[]) => {
      // Clear any previous upload error toast so stale errors don't linger on retry
      setUploadErrorToast(null);
      for (const file of files) {
        // Create an optimistic local entry immediately
        const tempId = `temp-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
        const localDoc: UploadedDocument = {
          id: tempId,
          filename: file.name,
          pages: 0,
          size_bytes: file.size,
          uploaded_at: new Date().toISOString(),
          analysis: null,
          analyzing: false,
          extractingTables: false,
          uploading: true,
        };
        setDocuments((prev) => [...prev, localDoc]);

        // Attempt to upload; on success replace the temp entry
        uploadMutation.mutate(file, {
          onSuccess: (data) => {
            setDocuments((prev) =>
              prev.map((d) =>
                d.id === tempId
                  ? {
                      ...d,
                      id: data.id,
                      pages: data.pages || d.pages,
                      size_bytes: data.size_bytes || d.size_bytes,
                      filename: data.filename || d.filename,
                      uploading: false,
                    }
                  : d,
              ),
            );
            setActiveDocId(data.id);
            // Persist the newly-opened document in the URL so reload keeps
            // it mounted (prevents the "uploaded project disappears on
            // refresh" bug — backend persistence was already fine).
            setSearchParams(
              (prev) => {
                const next = new URLSearchParams(prev);
                next.set('doc', data.id);
                return next;
              },
              { replace: true },
            );
            // Refresh server-side document list (fire-and-forget).
            // The dual ``createDocumentRecord`` upload that used to live
            // here was removed — see BUG-DUAL-UPLOAD-PDF comment above.
            refetchServerDocuments();
          },
          onError: (err) => {
            // Keep the entry visible with error state instead of removing it
            const msg = err instanceof Error ? err.message : 'Upload failed';
            setDocuments((prev) =>
              prev.map((d) =>
                d.id === tempId ? { ...d, uploading: false, uploadError: msg } : d,
              ),
            );
            setUploadErrorToast(msg);
          },
        });
      }
    },
    [uploadMutation, refetchServerDocuments],
  );

  const [showProjectFilePicker, setShowProjectFilePicker] = useState(false);
  const [pickingFileId, setPickingFileId] = useState<string | null>(null);

  // Open a PDF that is already in the project instead of asking the user to
  // find it on their own disk again.
  //
  // The picker federates two stores, so a pick arrives in one of three states.
  //
  //  * A takeoff document (kind `takeoff`): it already exists with its
  //    measurements and page scales, so it just opens. No request at all.
  //  * A project file the module has already been given (`takeoff_document_id`
  //    set): same thing - open the takeoff document that exists rather than
  //    asking for another one.
  //  * A project file seen for the first time: ask the backend to
  //    find-or-create the takeoff_document behind it, exactly like the
  //    `?doc=X&source=document` deep-link above.
  //
  // This never re-uploads the bytes. Downloading the blob and pushing it back
  // through the upload path would leave a second copy of the same drawing
  // under a new id every time the user picked it. And a takeoff document owns
  // the page rasters, annotations and AI recognition state that scale-detect,
  // recognize and table-extract are keyed by, so the viewer needs a real
  // takeoff id - handing it the CDE document id would render the sheet and
  // then 404 every AI call on it.
  //
  // The endpoint is idempotent, so picking the same file twice reopens the
  // same takeoff document with its measurements intact.
  const openTakeoffDocument = useCallback(
    (id: string, name: string) => {
      setShowProjectFilePicker(false);
      setActiveDocId(id);
      setViewerDoc({
        url: `/api/v1/takeoff/documents/${encodeURIComponent(id)}/download/`,
        name,
        id,
      });
      setActiveTab('measurements');
    },
    [],
  );

  const handlePickProjectFile = useCallback(
    async (file: PickedProjectFile) => {
      if (file.kind === 'takeoff') {
        openTakeoffDocument(file.id, file.name);
        return;
      }
      if (file.takeoff_document_id) {
        openTakeoffDocument(file.takeoff_document_id, file.name);
        void refetchServerDocuments();
        return;
      }
      setPickingFileId(file.id);
      try {
        const takeoff = await apiPost<{ id: string; filename?: string; status?: string }>(
          `/v1/takeoff/documents/from-source/${encodeURIComponent(file.id)}`,
        );
        openTakeoffDocument(takeoff.id, takeoff.filename || file.name);
        // The catalogue now holds one more takeoff document, so refresh it or
        // the sidebar list stays a step behind what the viewer is showing.
        void refetchServerDocuments();
      } catch (err) {
        useToastStore.getState().addToast({
          type: 'error',
          title: t('project_files.pick_failed_title', {
            defaultValue: 'Could not open that file',
          }),
          message:
            err instanceof Error
              ? err.message
              : t('project_files.pick_failed_msg', {
                  defaultValue: 'The file could not be read from the project. Try again.',
                }),
        });
      } finally {
        setPickingFileId(null);
      }
    },
    [openTakeoffDocument, refetchServerDocuments, t],
  );

  const handleRemoveDocument = useCallback(
    (docId: string) => {
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
      setActiveDocId((prev) => (prev === docId ? null : prev));
      // Close the viewer if it was showing the deleted doc. Match on the
      // stable document id (issue #238) rather than a URL substring, which
      // could false-match a docId that is a substring of another.
      setViewerDoc((prev) => (prev && prev.id === docId ? null : prev));
      // Drop the doc param if it matched, so a reload doesn't revive the
      // deleted entry as a placeholder via the initial-read effect.
      setSearchParams(
        (prev) => {
          if (prev.get('doc') !== docId) return prev;
          const next = new URLSearchParams(prev);
          next.delete('doc');
          return next;
        },
        { replace: true },
      );
      // Best-effort server delete; silently ignore errors for legacy temp ids
      takeoffApi
        .deleteDocument(docId)
        .then(() => refetchServerDocuments())
        .catch(() => {
          /* ignore — document may be local-only */
        });
    },
    [refetchServerDocuments],
  );

  const handleAnalyze = useCallback(
    (docId: string) => {
      analyzeMutation.mutate(docId);
    },
    [analyzeMutation],
  );

  const handleExtractTables = useCallback(
    (docId: string) => {
      extractTablesMutation.mutate(docId);
    },
    [extractTablesMutation],
  );

  const handleToggleElement = useCallback((docId: string, elementId: string) => {
    setDocuments((prev) =>
      prev.map((d) => {
        if (d.id !== docId || !d.analysis) return d;
        return {
          ...d,
          analysis: {
            ...d.analysis,
            elements: d.analysis.elements.map((el) =>
              el.id === elementId ? { ...el, selected: !el.selected } : el,
            ),
          },
        };
      }),
    );
  }, []);

  const handleSelectAll = useCallback((docId: string) => {
    setDocuments((prev) =>
      prev.map((d) => {
        if (d.id !== docId || !d.analysis) return d;
        return {
          ...d,
          analysis: {
            ...d.analysis,
            elements: d.analysis.elements.map((el) => ({ ...el, selected: true })),
          },
        };
      }),
    );
  }, []);

  const handleDeselectAll = useCallback((docId: string) => {
    setDocuments((prev) =>
      prev.map((d) => {
        if (d.id !== docId || !d.analysis) return d;
        return {
          ...d,
          analysis: {
            ...d.analysis,
            elements: d.analysis.elements.map((el) => ({ ...el, selected: false })),
          },
        };
      }),
    );
  }, []);

  const handleAddToBOQ = useCallback(
    (docId: string) => {
      if (!selectedBoqId) {
        setUploadErrorToast(t('takeoff.no_boq_selected', 'Please select a project and BOQ first'));
        setTimeout(() => setUploadErrorToast(null), 5000);
        return;
      }
      // Analysis state lives only on the local `documents` list — server
      // docs are plain metadata until the user clicks Analyze.
      const doc = documents.find((d) => d.id === docId);
      if (!doc?.analysis) return;

      const selectedItems = doc.analysis.elements
        .filter((el) => el.selected)
        .map((el) => ({
          description: el.description,
          quantity: el.quantity,
          // Canonicalize the (often German / raw-OCR) extracted unit so
          // BOQ validation + cost matching can see the row (D-TKC-021).
          unit: canonicalizeUnit(el.unit),
          source: 'takeoff',
          metadata: { takeoff_raw_unit: el.unit },
        }));

      if (selectedItems.length > 0) {
        addToBOQMutation.mutate(selectedItems);
      }
    },
    [selectedBoqId, documents, addToBOQMutation, t],
  );

  const handleQuickMeasurement = useCallback(
    (measurement: QuickMeasurement) => {
      if (!selectedBoqId) {
        setUploadErrorToast(t('takeoff.no_boq_selected', 'Please select a project and BOQ first'));
        setTimeout(() => setUploadErrorToast(null), 5000);
        return;
      }
      addToBOQMutation.mutate([
        {
          description: measurement.description,
          quantity: parseFloat(measurement.value) || 0,
          unit: canonicalizeUnit(measurement.unit),
          source: 'takeoff',
          metadata: { takeoff_raw_unit: measurement.unit },
        },
      ]);
    },
    [selectedBoqId, addToBOQMutation, t],
  );

  /* ── Derived ────────────────────────────────────────────────────────── */

  const projectOptions = useMemo(
    () => (projects || []).map((p) => ({ value: p.id, label: p.name })),
    [projects],
  );

  const boqOptions = useMemo(
    () => (boqs || []).map((b) => ({ value: b.id, label: b.name })),
    [boqs],
  );

  const hasBoqSelected = !!selectedBoqId;

  /**
   * Merged list of documents for the filmstrip: server-side uploads (from /v1/takeoff/documents/)
   * unioned with locally-tracked ones (in-progress uploads, errors, fresh uploads not yet refetched).
   * Local entries take precedence when IDs collide (they have upload/analysis state).
   */
  const filmstripDocuments: UploadedDocument[] = useMemo(() => {
    const byId = new Map<string, UploadedDocument>();
    (serverDocuments ?? []).forEach((d: TakeoffDocumentResponse) => {
      byId.set(d.id, {
        id: d.id,
        filename: d.filename,
        pages: d.pages,
        size_bytes: d.size_bytes,
        uploaded_at: d.uploaded_at ?? new Date().toISOString(),
        analysis: null,
        analyzing: false,
        extractingTables: false,
      });
    });
    documents.forEach((d) => byId.set(d.id, d));
    return Array.from(byId.values());
  }, [serverDocuments, documents]);

  /** Open a server-side document in the Measurements viewer. */
  const handleOpenDocInViewer = useCallback(
    (docId: string) => {
      const doc = filmstripDocuments.find((d) => d.id === docId);
      if (!doc) return;
      // Local-only (not yet uploaded or failed) docs can't be opened via URL
      if (doc.uploading || doc.uploadError || docId.startsWith('temp-')) {
        setUploadErrorToast(
          t(
            'takeoff.doc_not_ready',
            { defaultValue: 'Document is not ready to open yet.' },
          ),
        );
        setTimeout(() => setUploadErrorToast(null), 4000);
        return;
      }
      setActiveDocId(docId);
      setViewerDoc({
        url: `/api/v1/takeoff/documents/${docId}/download/`,
        name: doc.filename,
        id: docId,
      });
      setActiveTab('measurements');
      // Pin the current doc to the URL so reload restores the viewer.
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set('doc', docId);
          next.set('tab', 'measurements');
          return next;
        },
        { replace: true },
      );
    },
    [filmstripDocuments, t, setSearchParams],
  );

  /** Mirror the viewer's current page into the URL (issue #386) so a sheet
   *  can be bookmarked/shared and reopening the document restores it. Page 1
   *  keeps a clean URL (param dropped); any other page is written in. */
  const handleViewerPageChange = useCallback(
    (page: number) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (page > 1) {
            next.set('page', String(page));
          } else {
            next.delete('page');
          }
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  /* ── Render ─────────────────────────────────────────────────────────── */

  return (
    <div
      className={clsx(
        'relative flex min-h-0 w-full flex-col overflow-x-hidden animate-fade-in',
        // Definite-height column so each tab panel fills the space with flex
        // instead of a hardcoded height (#341). Budget = viewport minus the
        // sticky app header (--oe-header-height) and the <main> vertical
        // padding (pt-6 + pb-4 = 2.5rem). In the desktop (Tauri) shell a 36px
        // DesktopToolbar (h-9) sits above the header, so subtract it there too.
        isTauri
          ? 'h-[calc(100vh-2.25rem-var(--oe-header-height,52px)-2.5rem)]'
          : 'h-[calc(100vh-var(--oe-header-height,52px)-2.5rem)]',
      )}
    >
      {/* Barely-visible field-surveyor geometry — rectangles, irregular
          polygons, distance dimension lines, vertex pins — the kind of
          marks an estimator drags across a drawing to measure area or
          perimeter.  Fixed to viewport so both tabs share the same
          background; pointer-events disabled and opacity tiny so it
          never interferes with foreground controls. */}
      <svg
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10 w-full h-full text-slate-500 dark:text-slate-300"
        preserveAspectRatio="xMidYMid slice"
        viewBox="0 0 1600 1000"
      >
        <defs>
          <linearGradient id="tkoPageFade" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="white" stopOpacity="0.25" />
            <stop offset="45%" stopColor="white" stopOpacity="1" />
            <stop offset="100%" stopColor="white" stopOpacity="0.15" />
          </linearGradient>
          <mask id="tkoPageMask">
            <rect width="1600" height="1000" fill="url(#tkoPageFade)" />
          </mask>
        </defs>
        <g mask="url(#tkoPageMask)" opacity="0.06" fill="none" stroke="currentColor" strokeWidth="1.1">
          <rect x="110" y="90" width="280" height="170" strokeDasharray="8 6" />
          <circle cx="110" cy="90" r="4" fill="currentColor" />
          <circle cx="390" cy="90" r="4" fill="currentColor" />
          <circle cx="390" cy="260" r="4" fill="currentColor" />
          <circle cx="110" cy="260" r="4" fill="currentColor" />
          <text x="250" y="180" textAnchor="middle" fill="currentColor" stroke="none" fontSize="14" fontFamily="ui-monospace,monospace" opacity="0.55">47.6 m²</text>

          <polygon points="820,120 1080,140 1180,260 1140,390 940,430 820,340 760,230" strokeDasharray="6 4" />
          {([[820, 120], [1080, 140], [1180, 260], [1140, 390], [940, 430], [820, 340], [760, 230]] as [number, number][]).map(([x, y], i) => (
            <circle key={`pA${i}`} cx={x} cy={y} r="3.5" fill="currentColor" />
          ))}
          <text x="960" y="290" textAnchor="middle" fill="currentColor" stroke="none" fontSize="13" fontFamily="ui-monospace,monospace" opacity="0.5">83.2 m²</text>

          <g strokeDasharray="3 3">
            <line x1="1280" y1="130" x2="1540" y2="200" />
            <line x1="1275" y1="120" x2="1285" y2="140" strokeDasharray="0" strokeWidth="2" />
            <line x1="1535" y1="190" x2="1545" y2="210" strokeDasharray="0" strokeWidth="2" />
          </g>
          <text x="1410" y="155" textAnchor="middle" fill="currentColor" stroke="none" fontSize="12" fontFamily="ui-monospace,monospace" opacity="0.5">12.43 m</text>

          <polyline points="140,620 260,560 380,620 520,560 640,640" />
          {([[140, 620], [260, 560], [380, 620], [520, 560], [640, 640]] as [number, number][]).map(([x, y], i) => (
            <rect key={`pB${i}`} x={x - 3} y={y - 3} width="6" height="6" fill="currentColor" />
          ))}

          <rect x="1080" y="620" width="360" height="220" strokeDasharray="8 6" />
          {([[1080, 620], [1440, 620], [1440, 840], [1080, 840]] as [number, number][]).map(([x, y], i) => (
            <circle key={`pC${i}`} cx={x} cy={y} r="4" fill="currentColor" />
          ))}
          <text x="1260" y="740" textAnchor="middle" fill="currentColor" stroke="none" fontSize="14" fontFamily="ui-monospace,monospace" opacity="0.5">79.2 m²</text>

          <polygon points="60,440 270,460 320,640 90,630" strokeDasharray="4 4" />
          {([[60, 440], [270, 460], [320, 640], [90, 630]] as [number, number][]).map(([x, y], i) => (
            <circle key={`pD${i}`} cx={x} cy={y} r="3" fill="currentColor" />
          ))}

          <g>
            <line x1="660" y1="920" x2="940" y2="920" strokeWidth="1" />
            {Array.from({ length: 11 }).map((_, i) => (
              <line key={`tick${i}`} x1={660 + i * 28} y1="916" x2={660 + i * 28} y2="924" strokeWidth="1" />
            ))}
            <text x="800" y="950" textAnchor="middle" fill="currentColor" stroke="none" fontSize="10" fontFamily="ui-monospace,monospace" opacity="0.5">0   1   2   3   4   5 m</text>
          </g>
        </g>
      </svg>
      {/* Header zone — full-bleed viewer keeps its own SVG chrome on the root,
          so the canonical breadcrumb > header > info > tabs block carries its
          own space-y-5 rhythm here (style guide §1 viewer exception). */}
      <div className="shrink-0 space-y-5">
      {/* Breadcrumb and the "How it works" guide button share one row so the
          guide action sits level with the project / page trail and the blocks
          below move up (founder layout request). The module name + icon still
          come from the global top app bar; the sr-only h1 keeps the accessible
          page heading, and the "what this page does" copy lives in the
          dismissible info card just below. */}
      <div className="flex min-h-7 flex-wrap items-center gap-x-4 gap-y-2">
        <Breadcrumb
          items={[
            ...(() => {
              const sel = projects?.find((p) => p.id === selectedProjectId);
              return sel ? [{ label: sel.name, to: `/projects/${sel.id}` }] : [];
            })(),
            { label: t('nav.pdf_measurements', 'PDF Measurements') },
          ]}
        />
        <h1 className="sr-only">{t('nav.pdf_measurements', 'PDF Measurements')}</h1>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <ModuleGuideButton
            content={takeoffGuide}
            onCta={() => setActiveTab('documents')}
          />
        </div>
      </div>

      <DismissibleInfo
        storageKey="takeoff"
        title={t('takeoff.intro_title', { defaultValue: 'Measure straight off the drawing' })}
        more={
          t('takeoff.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('takeoff.intro_more')} />
            : undefined
        }
        links={[
          { label: t('nav.boq', { defaultValue: 'Bill of Quantities' }), onClick: () => navigate('/boq') },
          { label: t('nav.quantities', { defaultValue: 'Quantity Takeoff' }), onClick: () => navigate('/quantities') },
        ]}
      >
        {t('takeoff.intro_body', {
          defaultValue:
            'Upload PDF drawings to measure areas, lengths and counts by hand, or let AI extract elements with quantities. Selected measurements flow straight into your BOQ and stay linked to the project cost and schedule.',
        })}
      </DismissibleInfo>

      {/* Tabs — Measurements primary (first), AI second. Lower radius
          for a sharper, more "tool-like" feel; no ring-halo. The Compare
          button sits to the right so revision-diffing is reachable from
          either tab without stealing the tablist's full width. */}
      <div className="flex items-stretch gap-2">
      <div
        className="flex flex-1 gap-1 rounded-md border border-border-light/80 bg-surface-secondary/40 p-1"
        role="tablist"
        aria-label={t('takeoff.tabs_aria', { defaultValue: 'Takeoff sections' })}
      >
        <button
          id="takeoff-tab-measurements"
          role="tab"
          aria-selected={activeTab === 'measurements'}
          aria-controls="takeoff-tabpanel-measurements"
          tabIndex={activeTab === 'measurements' ? 0 : -1}
          onClick={() => setActiveTab('measurements')}
          onKeyDown={(e) => {
            if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
              e.preventDefault();
              setActiveTab('documents');
            }
          }}
          className={clsx(
            'flex flex-1 items-center justify-center gap-2 rounded-sm px-4 py-2 text-sm font-semibold transition-colors',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
            activeTab === 'measurements'
              ? 'bg-surface-primary text-oe-blue shadow-sm'
              : 'text-content-tertiary hover:text-content-primary hover:bg-surface-primary/60',
          )}
        >
          <Ruler size={15} strokeWidth={2.1} aria-hidden />
          {t('takeoff.tab_measurements', 'Measurements')}
        </button>
        <button
          id="takeoff-tab-documents"
          role="tab"
          aria-selected={activeTab === 'documents'}
          aria-controls="takeoff-tabpanel-documents"
          tabIndex={activeTab === 'documents' ? 0 : -1}
          onClick={() => setActiveTab('documents')}
          onKeyDown={(e) => {
            if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
              e.preventDefault();
              setActiveTab('measurements');
            }
          }}
          className={clsx(
            'flex flex-1 items-center justify-center gap-2 rounded-sm px-4 py-2 text-sm font-semibold transition-colors',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
            activeTab === 'documents'
              ? 'bg-surface-primary text-oe-blue shadow-sm'
              : 'text-content-tertiary hover:text-content-primary hover:bg-surface-primary/60',
          )}
        >
          <Sparkles size={15} strokeWidth={2.1} aria-hidden />
          {t('takeoff.tab_documents', 'Documents & AI')}
          {documents.length > 0 && (
            <Badge variant={activeTab === 'documents' ? 'blue' : 'neutral'} size="sm">
              {documents.length}
            </Badge>
          )}
        </button>
      </div>
      <button
        type="button"
        onClick={() => setShowCompare(true)}
        disabled={(serverDocuments?.length ?? 0) < 2}
        data-testid="takeoff-compare-button"
        title={t('takeoff_compare.compare_revisions', {
          defaultValue: 'Compare two takeoff PDFs with cost delta',
        })}
        className={clsx(
          'inline-flex items-center gap-1.5 rounded-md border border-border-light/80 px-3 text-sm font-semibold transition-colors',
          (serverDocuments?.length ?? 0) >= 2
            ? 'bg-surface-secondary/40 text-content-secondary hover:text-oe-blue hover:bg-surface-primary/60'
            : 'cursor-not-allowed text-content-quaternary',
        )}
      >
        <GitCompare size={15} strokeWidth={2.1} aria-hidden />
        <span className="hidden sm:inline">
          {t('takeoff_compare.compare_short', { defaultValue: 'Compare' })}
        </span>
      </button>
      </div>
      </div>

      {/* Tab content */}
      {activeTab === 'documents' ? (
        <div
          role="tabpanel"
          id="takeoff-tabpanel-documents"
          aria-labelledby="takeoff-tab-documents"
          className="mt-5 flex-1 min-h-0 overflow-y-auto overflow-x-hidden"
        >
          {/* AI provider setup notice — explains that AI takeoff needs a
              provider connected and links to AI settings. Hidden while the
              settings query is still loading so it doesn't flash the
              "connect" prompt for users who already have a key. */}
          {!aiSettingsQuery.isLoading && <AiTakeoffNotice connected={aiConnected} />}

          {/* Workflow steps */}
          <div className="mb-6 grid grid-cols-1 sm:grid-cols-4 gap-3">
            {[
              { num: '1', label: t('takeoff.step_upload', 'Upload PDF'), icon: Upload, done: documents.length > 0 },
              { num: '2', label: t('takeoff.step_analyze', 'AI Analysis'), icon: Sparkles, done: documents.some(d => d.analysis) },
              { num: '3', label: t('takeoff.step_review', 'Review & Select'), icon: CheckCircle2, done: documents.some(d => d.analysis?.elements.some(e => e.selected)) },
              { num: '4', label: t('takeoff.step_add', 'Add to BOQ'), icon: Plus, done: !!addToBOQSuccess },
            ].map((step) => (
              <div key={step.num} className={clsx(
                'flex items-center gap-2.5 rounded-xl px-4 py-2.5 border transition-colors',
                step.done
                  ? 'border-semantic-success/30 bg-semantic-success-bg/50 text-semantic-success'
                  : 'border-border-light bg-surface-secondary/30 text-content-tertiary',
              )}>
                <div className={clsx(
                  'flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold',
                  step.done ? 'bg-semantic-success text-white' : 'bg-content-tertiary/20 text-content-tertiary',
                )}>
                  {step.done ? <CheckCircle2 size={14} /> : step.num}
                </div>
                <span className="text-xs font-medium">{step.label}</span>
              </div>
            ))}
          </div>

          {/* Project + BOQ selector — collapsed in a subtle bar */}
          <div className="mb-6 rounded-xl border border-border-light bg-surface-secondary/30 px-4 py-3">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="flex-1">
                {projectsLoading ? (
                  <Skeleton height={36} className="w-full" rounded="md" />
                ) : (
                  <SelectDropdown
                    label={t('takeoff.select_project', 'Project')}
                    value={selectedProjectId}
                    onChange={handleProjectChange}
                    options={projectOptions}
                    placeholder={t('takeoff.select_project_placeholder', 'Choose a project...')}
                  />
                )}
              </div>
              <div className="flex-1">
                {boqsLoading ? (
                  <Skeleton height={36} className="w-full" rounded="md" />
                ) : (
                  <SelectDropdown
                    label={t('takeoff.select_boq', 'Bill of Quantities')}
                    value={selectedBoqId}
                    onChange={handleBoqChange}
                    options={boqOptions}
                    placeholder={
                      selectedProjectId
                        ? t('takeoff.select_boq_placeholder', 'Choose a BOQ...')
                        : t('takeoff.select_project_first', 'Select a project first')
                    }
                  />
                )}
              </div>
              {!hasBoqSelected && (
                <p className="text-2xs text-content-quaternary sm:pb-1.5">
                  {t('takeoff.boq_hint', 'Select to add items to BOQ')}
                </p>
              )}
            </div>
          </div>

          {/* Success toast */}
          {addToBOQSuccess && (
            <div className="mb-4 flex items-center gap-3 rounded-xl bg-semantic-success-bg px-5 py-3 animate-fade-in">
              <CheckCircle2 size={18} className="shrink-0 text-semantic-success" />
              <p className="text-sm font-medium text-semantic-success">{addToBOQSuccess}</p>
            </div>
          )}

          {/* Upload error toast */}
          {uploadErrorToast && (
            <div className="mb-4 flex items-center gap-3 rounded-xl bg-semantic-error-bg px-5 py-3 animate-fade-in">
              <AlertTriangle size={18} className="shrink-0 text-semantic-error" />
              <p className="text-sm font-medium text-semantic-error flex-1">{uploadErrorToast}</p>
              <button aria-label={t('common.dismiss', { defaultValue: 'Dismiss' })}
                onClick={() => setUploadErrorToast(null)}
                className="shrink-0 rounded-md p-1 text-semantic-error transition-colors"
              >
                <X size={14} />
              </button>
            </div>
          )}

          {/* Upload Area */}
          <div className="mb-6" data-guide="takeoff-upload">
            <DropZone onFilesSelected={handleFilesSelected} disabled={false} />
            {selectedProjectId && (
              <div className="mt-3 flex justify-center">
                <button
                  type="button"
                  onClick={() => setShowProjectFilePicker(true)}
                  data-testid="takeoff-open-from-project-files"
                  className="inline-flex items-center gap-2 rounded-lg border border-border-medium bg-surface-primary px-3 py-2 text-sm font-semibold text-content-secondary transition-colors hover:border-oe-blue/40 hover:text-oe-blue focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                >
                  <FolderOpen size={14} />
                  {t('project_files.open_from_project', {
                    defaultValue: 'Open from project files',
                  })}
                </button>
              </div>
            )}
          </div>

          <ProjectFilePicker
            open={showProjectFilePicker}
            onClose={() => setShowProjectFilePicker(false)}
            projectId={selectedProjectId}
            accepted={PDF_TAKEOFF_FORMATS}
            // Takeoff keeps its own sheets, so "project files" has to mean both
            // stores here or the dialog cannot find the plan this very module
            // has open.
            moduleKinds={TAKEOFF_PICKER_KINDS}
            onPick={handlePickProjectFile}
            busyId={pickingFileId}
          />

          {/* Uploaded Documents — merged list (server + local) so uploads
              survive page reload. */}
          {filmstripDocuments.length > 0 && (
            <div className="mb-8">
              <h2 className="mb-4 text-lg font-semibold text-content-primary">
                {t('takeoff.uploaded_documents', 'Uploaded Documents')}
              </h2>
              <div className="space-y-4">
                {filmstripDocuments.map((doc) => (
                  <DocumentCard
                    key={doc.id}
                    doc={doc}
                    onAnalyze={handleAnalyze}
                    onExtractTables={handleExtractTables}
                    onRemove={handleRemoveDocument}
                    onToggleElement={handleToggleElement}
                    onSelectAll={handleSelectAll}
                    onDeselectAll={handleDeselectAll}
                    onAddToBOQ={handleAddToBOQ}
                    onView={handleOpenDocInViewer}
                    boqSelected={hasBoqSelected}
                    aiConnected={aiConnected}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Empty state when no documents */}
          {filmstripDocuments.length === 0 && !serverDocumentsLoading && (
            <div className="mb-8 rounded-xl border border-border-light/60 bg-surface-secondary/20 px-6 py-8 text-center">
              <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-oe-blue-subtle">
                <FileSearch size={24} strokeWidth={1.5} className="text-oe-blue" />
              </div>
              <h3 className="text-sm font-semibold text-content-primary mb-1">
                {t('takeoff.no_documents', 'No documents uploaded')}
              </h3>
              <p className="text-xs text-content-tertiary max-w-md mx-auto">
                {t('takeoff.no_documents_description', 'Upload PDF construction drawings above. AI will extract walls, slabs, doors, and other elements with quantities.')}
              </p>
            </div>
          )}

          {/* Quick Measurements */}
          <Card className="mt-6">
            <div className="flex items-center gap-2 mb-4">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-amber-500/10">
                <Ruler size={14} className="text-amber-600" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-content-primary">
                  {t('takeoff.quick_measurements', 'Quick Measurements')}
                </h2>
                <p className="text-2xs text-content-tertiary">
                  {t('takeoff.quick_measurements_desc', 'Add quantities manually without PDF')}
                </p>
              </div>
            </div>
            <QuickMeasurementForm onAdd={handleQuickMeasurement} disabled={!hasBoqSelected} />
            {!hasBoqSelected && (
              <p className="mt-3 flex items-center gap-1.5 text-xs text-content-tertiary">
                <AlertTriangle size={12} />
                {t(
                  'takeoff.select_boq_to_add',
                  'Select a project and BOQ above to add measurements.',
                )}
              </p>
            )}
          </Card>

        </div>
      ) : (
        // Measurements tab panel. The page root is already a definite-height
        // flex column, so this panel just claims the leftover height with
        // `flex-1 min-h-0` and lays its own children out as a flex column: the
        // viewer fills and scrolls internally, and the Documents filmstrip is a
        // shrink-0 footer pinned in view, no hardcoded viewport math (#341).
        <div
          className="mt-5 flex flex-1 min-h-0 flex-col overflow-x-hidden"
          role="tabpanel"
          id="takeoff-tabpanel-measurements"
          aria-labelledby="takeoff-tab-measurements"
        >
          <div className="flex flex-1 min-h-0 flex-col overflow-y-auto overflow-x-hidden">
            {deepLinkNotFound && !viewerDoc ? (
              <div
                className="mx-auto my-8 max-w-md rounded-xl border border-amber-200 dark:border-amber-800/40 bg-amber-50 dark:bg-amber-900/20 px-6 py-8 text-center"
                data-testid="takeoff-deeplink-not-found"
              >
                <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-amber-100 dark:bg-amber-900/30">
                  <AlertTriangle size={24} className="text-amber-600" strokeWidth={1.5} />
                </div>
                <h3 className="text-sm font-semibold text-content-primary mb-1">
                  {t('takeoff.deeplink_not_found_title', { defaultValue: 'Document not found' })}
                </h3>
                <p className="text-xs text-content-tertiary mb-4">
                  {t('takeoff.deeplink_not_found_desc', {
                    defaultValue:
                      "The annotation references a document that isn't in this project's takeoff library. It may have been deleted or belong to a different project.",
                  })}
                </p>
                <a
                  href="/markups"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-oe-blue-text hover:bg-oe-blue-subtle transition-colors"
                >
                  <ArrowRight size={12} className="rotate-180" />
                  {t('takeoff.back_to_markups', { defaultValue: 'Back to Markups' })}
                </a>
              </div>
            ) : (
              <Suspense
                fallback={
                  <div className="flex items-center justify-center py-20">
                    <Loader2 size={24} className="animate-spin text-oe-blue" />
                  </div>
                }
              >
                <TakeoffViewerModule
                  // Key by the open document id so switching documents via the
                  // filmstrip REMOUNTS the viewer (issue #281). Without this the
                  // component instance is reused and the previous document's
                  // in-memory measurements bleed onto the newly opened one. The
                  // unmount runs the persistence hook's teardown flush, so the
                  // document being left is saved before the new one loads.
                  key={viewerDoc?.id ?? 'no-doc'}
                  initialPdfUrl={viewerDoc?.url}
                  initialPdfName={viewerDoc?.name}
                  initialDocumentId={viewerDoc?.id}
                  initialMeasurementId={initialMeasurementId}
                  // Scoped to the document deep-linked at mount only - the
                  // viewer remounts (new `key`) on document switch, so an
                  // unscoped page would otherwise leak onto the next
                  // document opened in this session (issue #386).
                  initialPage={
                    viewerDoc && viewerDoc.id === deepLinkedDocIdRef.current
                      ? (initialPage ?? undefined)
                      : undefined
                  }
                  onPageChange={handleViewerPageChange}
                  recentDocuments={serverDocuments}
                  onOpenRecentDocument={handleOpenDocInViewer}
                />
              </Suspense>
            )}
          </div>

          {/* Bottom filmstrip — list previously uploaded takeoff documents. */}
          <TakeoffDocFilmstrip
            documents={filmstripDocuments}
            activeDocId={activeDocId}
            isLoading={serverDocumentsLoading}
            onSelectDoc={handleOpenDocInViewer}
            onDeleteDoc={handleRemoveDocument}
            onUploadNew={() => filmstripUploadRef.current?.click()}
          />
          {/* Hidden file input shared between Documents tab and Measurements filmstrip. */}
          <input
            ref={filmstripUploadRef}
            type="file"
            accept="application/pdf,.pdf"
            multiple
            className="hidden"
            onChange={(e) => {
              const files = Array.from(e.target.files || []).filter(
                (f) =>
                  (f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf')) &&
                  f.size <= MAX_FILE_SIZE_BYTES,
              );
              if (files.length > 0) handleFilesSelected(files);
              if (filmstripUploadRef.current) filmstripUploadRef.current.value = '';
            }}
          />
        </div>
      )}

      {/* Revision compare with cost delta (Item 17) */}
      {selectedProjectId && (
        <PdfCompareDrawer
          open={showCompare}
          onClose={() => setShowCompare(false)}
          projectId={selectedProjectId}
          documents={serverDocuments ?? []}
          currentDocumentId={activeDocId}
        />
      )}
    </div>
  );
}
