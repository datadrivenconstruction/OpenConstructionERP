import { useState, useCallback, useRef, useMemo, useEffect, lazy, Suspense } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
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
} from 'lucide-react';

import { Button, Card, Badge, Input, Skeleton } from '@/shared/ui';
import { apiGet, apiPost } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { takeoffApi, type TakeoffDocumentResponse } from './api';

const TakeoffViewerModule = lazy(() => import('@/modules/pdf-takeoff/TakeoffViewerModule'));

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

type UnitOption = 'm' | 'm2' | 'm3' | 'kg' | 'pcs' | 'lsum' | 't' | 'l';

/* ── Constants ─────────────────────────────────────────────────────────── */

const UNIT_OPTIONS: UnitOption[] = ['m', 'm2', 'm3', 'kg', 'pcs', 'lsum', 't', 'l'];

const MAX_FILE_SIZE_MB = 50;
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

/* ── Helpers ───────────────────────────────────────────────────────────── */

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

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
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-sm font-medium text-content-primary">{label}</label>
      <select
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
        (f) => (f.type === 'application/pdf' || f.type.startsWith('image/')) && f.size <= MAX_FILE_SIZE_BYTES,
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
        (f) => (f.type === 'application/pdf' || f.type.startsWith('image/')) && f.size <= MAX_FILE_SIZE_BYTES,
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
          {t('takeoff.drop_file_here', 'Drop your PDF or image here')}
        </p>
        <p className="text-[11px] text-content-quaternary">
          {t('takeoff.file_limit', 'PDF, JPG, PNG up to {{size}}MB').replace(
            '{{size}}',
            String(MAX_FILE_SIZE_MB),
          )}
        </p>
        <div className="flex items-center gap-2 mt-1">
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-950/30 text-blue-600 dark:text-blue-400 border border-blue-200/50 dark:border-blue-800/30">.pdf</span>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-950/30 text-blue-600 dark:text-blue-400 border border-blue-200/50 dark:border-blue-800/30">.jpg</span>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface-secondary text-content-quaternary border border-border-light">.png</span>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface-secondary text-content-quaternary border border-border-light">.tiff</span>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/pdf,.pdf,image/*,.jpg,.jpeg,.png,.tiff"
          multiple
          onChange={handleFileChange}
          className="hidden"
          aria-label={t('takeoff.upload_pdf', 'Upload PDF')}
        />
      </div>
      <p className="text-[11px] text-content-tertiary mt-3">
        {t('takeoff.formats_detailed', {
          defaultValue: 'PDF construction drawings \u00B7 JPG / PNG photos \u00B7 TIFF scans. AI will extract walls, slabs, doors, and other elements with quantities.',
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
  boqSelected,
}: {
  doc: UploadedDocument;
  onAnalyze: (id: string) => void;
  onExtractTables: (id: string) => void;
  onRemove: (id: string) => void;
  onToggleElement: (docId: string, elementId: string) => void;
  onSelectAll: (docId: string) => void;
  onDeselectAll: (docId: string) => void;
  onAddToBOQ: (docId: string) => void;
  boqSelected: boolean;
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
              ? 'bg-oe-blue-subtle text-oe-blue'
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
          onClick={() => window.open(`/api/v1/takeoff/documents/${doc.id}/download`, '_blank')}
        >
          {t('takeoff.view', 'View')}
        </Button>
      </div>

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
                    className="flex items-center gap-1.5 rounded-lg border border-border-light px-3 py-1.5 text-xs text-content-secondary transition-colors hover:bg-oe-blue-subtle hover:text-oe-blue hover:border-oe-blue/30"
                  >
                    <Box size={13} />
                    {t('takeoff.open_in_bim', 'Open in BIM Viewer')}
                    <ArrowRight size={11} className="text-content-quaternary" />
                  </a>
                  <a
                    href="/boq"
                    className="flex items-center gap-1.5 rounded-lg border border-border-light px-3 py-1.5 text-xs text-content-secondary transition-colors hover:bg-oe-blue-subtle hover:text-oe-blue hover:border-oe-blue/30"
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
          <label className="text-sm font-medium text-content-primary">
            {t('takeoff.unit', 'Unit')}
          </label>
          <select
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

  return (
    <div className="shrink-0 bg-surface-primary border border-border-light rounded-xl mt-6 overflow-hidden">
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
          {isLoading && documents.length === 0 ? (
            <Loader2 size={14} className="animate-spin text-content-tertiary" />
          ) : documents.length > 0 ? (
            documents.map((doc) => {
              const isActive = doc.id === activeDocId;
              const hasError = !!doc.uploadError;
              const isUploading = !!doc.uploading;
              return (
                <button
                  key={doc.id}
                  type="button"
                  onClick={() => onSelectDoc(doc.id)}
                  disabled={isUploading || hasError}
                  className={clsx(
                    'group relative shrink-0 w-44 text-start rounded-lg border transition-all duration-200 overflow-hidden',
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
                  {/* Delete button on hover */}
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

export function TakeoffPage() {
  const { t } = useTranslation();

  /* ── Tab state (synced with ?tab= query parameter from sidebar) ──── */

  const [searchParams] = useSearchParams();
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

  /** Currently opened document in the Measurements viewer. */
  const [viewerDoc, setViewerDoc] = useState<{ url: string; name: string } | null>(null);

  /* ── Handle ?doc= deep link from Documents page ─────────────────── */

  useEffect(() => {
    const docId = searchParams.get('doc');
    const docName = searchParams.get('name');
    if (docId) {
      // Create a placeholder document entry for the deep-linked document
      setDocuments((prev) => {
        if (prev.some((d) => d.id === docId)) return prev;
        return [
          ...prev,
          {
            id: docId,
            filename: docName ? decodeURIComponent(docName) : 'Document',
            pages: 0,
            size_bytes: 0,
            uploaded_at: new Date().toISOString(),
            analysis: null,
            analyzing: false,
            extractingTables: false,
          },
        ];
      });
      setActiveDocId(docId);
      setActiveTab('documents');
    }
  }, [searchParams]);

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

      const response = await fetch(`/api/v1/takeoff/documents/upload/`, {
        method: 'POST',
        headers,
        body: formData,
      });

      if (!response.ok) {
        throw new Error(`Upload failed: ${response.statusText}`);
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
    mutationFn: async (items: { description: string; quantity: number; unit: string }[]) => {
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

  /** Also create a Document record in the Documents module for cross-referencing. */
  const createDocumentRecord = useCallback(
    async (file: File) => {
      if (!selectedProjectId) return;
      try {
        const token = useAuthStore.getState().accessToken;
        const formData = new FormData();
        formData.append('file', file);
        const headers: HeadersInit = { 'X-DDC-Client': 'OE/1.0' };
        if (token) headers['Authorization'] = `Bearer ${token}`;
        await fetch(
          `/api/v1/documents/upload?project_id=${selectedProjectId}&category=drawing`,
          { method: 'POST', headers, body: formData },
        );
      } catch {
        // Non-critical: the takeoff upload already succeeded
      }
    },
    [selectedProjectId],
  );

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
            // Also save to Documents module (fire-and-forget)
            createDocumentRecord(file);
            // Refresh server-side document list (fire-and-forget)
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
    [uploadMutation, createDocumentRecord, refetchServerDocuments],
  );

  const handleRemoveDocument = useCallback(
    (docId: string) => {
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
      setActiveDocId((prev) => (prev === docId ? null : prev));
      setViewerDoc((prev) => (prev && prev.url.includes(`/${docId}/`) ? null : prev));
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
      const doc = documents.find((d) => d.id === docId);
      if (!doc?.analysis) return;

      const selectedItems = doc.analysis.elements
        .filter((el) => el.selected)
        .map((el) => ({
          description: el.description,
          quantity: el.quantity,
          unit: el.unit,
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
          unit: measurement.unit,
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
      });
      setActiveTab('measurements');
    },
    [filmstripDocuments, t],
  );

  /* ── Render ─────────────────────────────────────────────────────────── */

  return (
    <div className="relative w-full animate-fade-in">
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
      {/* Header removed — the page title is already in the left sidebar
          nav, and the subtitle was purely decorative. Saves ~80px of
          vertical space so the main workspace fits in one viewport. */}

      {/* Tabs — Measurements primary (first), AI second. Lower radius
          for a sharper, more "tool-like" feel; no ring-halo. */}
      <div className="mb-6 flex gap-1 rounded-md border border-border-light/80 bg-surface-secondary/40 p-1">
        <button
          onClick={() => setActiveTab('measurements')}
          className={clsx(
            'flex flex-1 items-center justify-center gap-2 rounded-sm px-4 py-2.5 text-sm font-semibold transition-colors',
            activeTab === 'measurements'
              ? 'bg-surface-primary text-oe-blue shadow-sm'
              : 'text-content-tertiary hover:text-content-primary hover:bg-surface-primary/60',
          )}
        >
          <Ruler size={15} strokeWidth={2.1} />
          {t('takeoff.tab_measurements', 'Measurements')}
        </button>
        <button
          onClick={() => setActiveTab('documents')}
          className={clsx(
            'flex flex-1 items-center justify-center gap-2 rounded-sm px-4 py-2.5 text-sm font-semibold transition-colors',
            activeTab === 'documents'
              ? 'bg-surface-primary text-oe-blue shadow-sm'
              : 'text-content-tertiary hover:text-content-primary hover:bg-surface-primary/60',
          )}
        >
          <Sparkles size={15} strokeWidth={2.1} />
          {t('takeoff.tab_documents', 'Documents & AI')}
          {documents.length > 0 && (
            <Badge variant={activeTab === 'documents' ? 'blue' : 'neutral'} size="sm">
              {documents.length}
            </Badge>
          )}
        </button>
      </div>

      {/* Tab content */}
      {activeTab === 'documents' ? (
        <>
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
              <button
                onClick={() => setUploadErrorToast(null)}
                className="shrink-0 rounded-md p-1 text-semantic-error/60 hover:text-semantic-error transition-colors"
              >
                <X size={14} />
              </button>
            </div>
          )}

          {/* Upload Area */}
          <div className="mb-6">
            <DropZone onFilesSelected={handleFilesSelected} disabled={false} />
          </div>

          {/* Uploaded Documents */}
          {documents.length > 0 && (
            <div className="mb-8">
              <h2 className="mb-4 text-lg font-semibold text-content-primary">
                {t('takeoff.uploaded_documents', 'Uploaded Documents')}
              </h2>
              <div className="space-y-4">
                {documents.map((doc) => (
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
                    boqSelected={hasBoqSelected}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Empty state when no documents */}
          {documents.length === 0 && (
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

        </>
      ) : (
        <>
          <Suspense
            fallback={
              <div className="flex items-center justify-center py-20">
                <Loader2 size={24} className="animate-spin text-oe-blue" />
              </div>
            }
          >
            <TakeoffViewerModule
              initialPdfUrl={viewerDoc?.url}
              initialPdfName={viewerDoc?.name}
            />
          </Suspense>

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
            accept="application/pdf,.pdf,image/*,.jpg,.jpeg,.png,.tiff"
            multiple
            className="hidden"
            onChange={(e) => {
              const files = Array.from(e.target.files || []).filter(
                (f) =>
                  (f.type === 'application/pdf' || f.type.startsWith('image/')) &&
                  f.size <= MAX_FILE_SIZE_BYTES,
              );
              if (files.length > 0) handleFilesSelected(files);
              if (filmstripUploadRef.current) filmstripUploadRef.current.value = '';
            }}
          />
        </>
      )}
    </div>
  );
}
