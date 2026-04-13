import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  PenTool,
  Search,
  Download,
  ChevronDown,
  ChevronRight,
  Trash2,
  Cloud,
  ArrowRight,
  Type,
  Stamp,
  Ruler,
  Highlighter,
  Square,
  Hash,
  Pentagon,
  Plus,
  Filter,
  Edit3,
  Check,
  X,
  LayoutList,
  LayoutGrid,
  FileText,
  TriangleRight,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb, ConfirmDialog } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchMarkups,
  fetchMarkupsSummary,
  fetchStampTemplates,
  createMarkup,
  updateMarkup,
  deleteMarkup,
  exportMarkupsCSV,
} from './api';
import type {
  Markup,
  MarkupType,
  MarkupStatus,
  MarkupsSummary,
  CreateMarkupPayload,
} from './api';
import { InlinePdfAnnotator } from './InlinePdfAnnotator';

/* ── Constants ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
  currency: string;
}

interface DocItem {
  id: string;
  name: string;
}

const ALL_MARKUP_TYPES: MarkupType[] = [
  'cloud',
  'arrow',
  'text',
  'rectangle',
  'highlight',
  'distance',
  'area',
  'count',
  'stamp',
  'polygon',
];

const MARKUP_STATUSES: MarkupStatus[] = ['active', 'resolved', 'archived'];

const TYPE_ICONS: Record<MarkupType, React.ElementType> = {
  cloud: Cloud,
  arrow: ArrowRight,
  text: Type,
  rectangle: Square,
  highlight: Highlighter,
  distance: Ruler,
  area: TriangleRight,
  count: Hash,
  stamp: Stamp,
  polygon: Pentagon,
};

const TYPE_LABELS: Record<MarkupType, string> = {
  cloud: 'Cloud',
  arrow: 'Arrow',
  text: 'Text',
  rectangle: 'Rectangle',
  highlight: 'Highlight',
  distance: 'Distance',
  area: 'Area',
  count: 'Count',
  stamp: 'Stamp',
  polygon: 'Polygon',
};

const TYPE_COLORS: Record<MarkupType, string> = {
  cloud: 'text-blue-500',
  arrow: 'text-orange-500',
  text: 'text-gray-500',
  rectangle: 'text-indigo-500',
  highlight: 'text-yellow-500',
  distance: 'text-purple-500',
  area: 'text-teal-500',
  count: 'text-rose-500',
  stamp: 'text-green-500',
  polygon: 'text-cyan-500',
};

const TYPE_BG_COLORS: Record<MarkupType, string> = {
  cloud: 'bg-blue-50 border-blue-200 dark:bg-blue-900/20 dark:border-blue-800',
  arrow: 'bg-orange-50 border-orange-200 dark:bg-orange-900/20 dark:border-orange-800',
  text: 'bg-gray-50 border-gray-200 dark:bg-gray-900/20 dark:border-gray-700',
  rectangle: 'bg-indigo-50 border-indigo-200 dark:bg-indigo-900/20 dark:border-indigo-800',
  highlight: 'bg-yellow-50 border-yellow-200 dark:bg-yellow-900/20 dark:border-yellow-800',
  distance: 'bg-purple-50 border-purple-200 dark:bg-purple-900/20 dark:border-purple-800',
  area: 'bg-teal-50 border-teal-200 dark:bg-teal-900/20 dark:border-teal-800',
  count: 'bg-rose-50 border-rose-200 dark:bg-rose-900/20 dark:border-rose-800',
  stamp: 'bg-green-50 border-green-200 dark:bg-green-900/20 dark:border-green-800',
  polygon: 'bg-cyan-50 border-cyan-200 dark:bg-cyan-900/20 dark:border-cyan-800',
};

const STATUS_BADGE_VARIANT: Record<MarkupStatus, 'blue' | 'success' | 'neutral'> = {
  active: 'blue',
  resolved: 'success',
  archived: 'neutral',
};

const MEASUREMENT_TYPES: MarkupType[] = ['distance', 'area', 'count'];

const PRESET_COLORS = [
  { name: 'Red', value: '#EF4444' },
  { name: 'Blue', value: '#3B82F6' },
  { name: 'Green', value: '#22C55E' },
  { name: 'Orange', value: '#F97316' },
  { name: 'Purple', value: '#A855F7' },
  { name: 'Gray', value: '#6B7280' },
];

const DEFAULT_STAMPS = [
  { name: 'approved', label: 'Approved', color: 'green' },
  { name: 'rejected', label: 'Rejected', color: 'red' },
  { name: 'for_review', label: 'For Review', color: 'blue' },
  { name: 'revised', label: 'Revised', color: 'purple' },
  { name: 'final', label: 'Final', color: 'amber' },
];

const STAMP_BADGE_COLORS: Record<string, string> = {
  green:
    'bg-green-100 text-green-800 border-green-300 dark:bg-green-900/30 dark:text-green-400 dark:border-green-700',
  red: 'bg-red-100 text-red-800 border-red-300 dark:bg-red-900/30 dark:text-red-400 dark:border-red-700',
  blue: 'bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-700',
  purple:
    'bg-purple-100 text-purple-800 border-purple-300 dark:bg-purple-900/30 dark:text-purple-400 dark:border-purple-700',
  amber:
    'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-900/30 dark:text-amber-400 dark:border-amber-700',
};

const inputCls =
  'h-8 rounded-lg border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-colors';

const selectCls = inputCls + ' pr-7 appearance-none cursor-pointer';

/* ── Add Markup Modal ─────────────────────────────────────────────────── */

function AddMarkupModal({
  open,
  onClose,
  projectId,
  documents,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  documents: DocItem[];
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const dialogRef = useRef<HTMLDivElement>(null);

  const [selectedType, setSelectedType] = useState<MarkupType>('cloud');
  const [documentId, setDocumentId] = useState('');
  const [page, setPage] = useState(1);
  const [label, setLabel] = useState('');
  const [text, setText] = useState('');
  const [color, setColor] = useState(PRESET_COLORS[1]!.value);
  const [measurementValue, setMeasurementValue] = useState('');
  const [measurementUnit, setMeasurementUnit] = useState('m');

  // Reset form on open
  useEffect(() => {
    if (open) {
      setSelectedType('cloud');
      setDocumentId(documents[0]?.id ?? '');
      setPage(1);
      setLabel('');
      setText('');
      setColor(PRESET_COLORS[1]!.value);
      setMeasurementValue('');
      setMeasurementUnit('m');
    }
  }, [open, documents]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', handler, { capture: true });
    return () => document.removeEventListener('keydown', handler, { capture: true });
  }, [open, onClose]);

  // Close on backdrop click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (dialogRef.current && !dialogRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open, onClose]);

  const createMut = useMutation({
    mutationFn: (data: CreateMarkupPayload) => createMarkup(data),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('markups.created', { defaultValue: 'Markup created' }),
      });
      onCreated();
      onClose();
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const handleSubmit = () => {
    const payload: CreateMarkupPayload = {
      project_id: projectId,
      type: selectedType,
      color,
      ...(documentId && { document_id: documentId }),
      ...(page > 0 && { page }),
      ...(label.trim() && { label: label.trim() }),
      ...(text.trim() && { text: text.trim() }),
      ...(MEASUREMENT_TYPES.includes(selectedType) &&
        measurementValue && {
          measurement_value: parseFloat(measurementValue),
          measurement_unit: measurementUnit,
        }),
    };
    createMut.mutate(payload);
  };

  if (!open) return null;

  const isMeasurementType = MEASUREMENT_TYPES.includes(selectedType);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm animate-fade-in" />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={t('markups.add_markup', { defaultValue: 'Add Markup' })}
        className="relative z-10 w-full max-w-lg mx-4 rounded-2xl border border-border-light bg-surface-elevated shadow-xl animate-scale-in"
      >
        {/* Modal Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border-light">
          <h2 className="text-base font-semibold text-content-primary flex items-center gap-2">
            <Plus size={16} className="text-oe-blue" />
            {t('markups.add_markup', { defaultValue: 'Add Markup' })}
          </h2>
          <button
            onClick={onClose}
            className="p-1 rounded-md hover:bg-surface-secondary text-content-tertiary transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {/* Type Selector: 2 rows of 5 */}
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1.5">
              {t('markups.markup_type', { defaultValue: 'Type' })}
            </label>
            <div className="grid grid-cols-5 gap-1.5">
              {ALL_MARKUP_TYPES.map((tp) => {
                const Icon = TYPE_ICONS[tp];
                const isSelected = selectedType === tp;
                return (
                  <button
                    key={tp}
                    onClick={() => setSelectedType(tp)}
                    className={clsx(
                      'flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-xs font-medium transition-all border',
                      isSelected
                        ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue ring-1 ring-oe-blue/30'
                        : 'border-border-light bg-surface-primary text-content-secondary hover:bg-surface-secondary',
                    )}
                  >
                    <Icon size={13} className={isSelected ? TYPE_COLORS[tp] : ''} />
                    <span className="truncate">
                      {t(`markups.type_${tp}`, { defaultValue: TYPE_LABELS[tp] })}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Document + Page row */}
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="block text-xs font-medium text-content-secondary mb-1.5">
                {t('markups.document', { defaultValue: 'Document' })}
              </label>
              <select
                value={documentId}
                onChange={(e) => setDocumentId(e.target.value)}
                className={selectCls + ' w-full'}
              >
                <option value="">
                  {t('markups.no_document', { defaultValue: '-- None --' })}
                </option>
                {documents.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="w-20">
              <label className="block text-xs font-medium text-content-secondary mb-1.5">
                {t('markups.page', { defaultValue: 'Page' })}
              </label>
              <input
                type="number"
                min={1}
                value={page}
                onChange={(e) => setPage(Math.max(1, parseInt(e.target.value) || 1))}
                className={inputCls + ' w-full text-center'}
              />
            </div>
          </div>

          {/* Label + Text */}
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="block text-xs font-medium text-content-secondary mb-1.5">
                {t('markups.label_field', { defaultValue: 'Label' })}
              </label>
              <input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={t('markups.label_placeholder', {
                  defaultValue: 'Short label...',
                })}
                className={inputCls + ' w-full'}
              />
            </div>
            <div className="flex-1">
              <label className="block text-xs font-medium text-content-secondary mb-1.5">
                {t('markups.text_field', { defaultValue: 'Text' })}
              </label>
              <input
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={t('markups.text_placeholder', {
                  defaultValue: 'Annotation text...',
                })}
                className={inputCls + ' w-full'}
              />
            </div>
          </div>

          {/* Color Picker */}
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1.5">
              {t('markups.color', { defaultValue: 'Color' })}
            </label>
            <div className="flex items-center gap-2">
              {PRESET_COLORS.map((c) => (
                <button
                  key={c.value}
                  onClick={() => setColor(c.value)}
                  title={c.name}
                  className={clsx(
                    'w-7 h-7 rounded-full border-2 transition-all',
                    color === c.value
                      ? 'border-content-primary scale-110 ring-2 ring-offset-1 ring-oe-blue/40'
                      : 'border-transparent hover:scale-105',
                  )}
                  style={{ backgroundColor: c.value }}
                />
              ))}
            </div>
          </div>

          {/* Measurement fields (only for distance/area/count) */}
          {isMeasurementType && (
            <div className="flex gap-3">
              <div className="flex-1">
                <label className="block text-xs font-medium text-content-secondary mb-1.5">
                  {t('markups.measurement_value', { defaultValue: 'Value' })}
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={measurementValue}
                  onChange={(e) => setMeasurementValue(e.target.value)}
                  placeholder="0.00"
                  className={inputCls + ' w-full'}
                />
              </div>
              <div className="w-24">
                <label className="block text-xs font-medium text-content-secondary mb-1.5">
                  {t('markups.measurement_unit', { defaultValue: 'Unit' })}
                </label>
                <select
                  value={measurementUnit}
                  onChange={(e) => setMeasurementUnit(e.target.value)}
                  className={selectCls + ' w-full'}
                >
                  <option value="m">m</option>
                  <option value="m2">m&sup2;</option>
                  <option value="m3">m&sup3;</option>
                  <option value="mm">mm</option>
                  <option value="ft">ft</option>
                  <option value="in">in</option>
                  <option value="pcs">pcs</option>
                </select>
              </div>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-border-light">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={createMut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleSubmit}
            loading={createMut.isPending}
            icon={<Plus size={14} />}
          >
            {t('markups.create', { defaultValue: 'Create' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Stats Bar (compact inline) ──────────────────────────────────────── */

function StatsBar({ summary }: { summary: MarkupsSummary | undefined }) {
  const { t } = useTranslation();

  const total = summary?.total ?? 0;
  const byType = summary?.by_type ?? {};
  const byStatus = summary?.by_status ?? {};
  const activeCount = byStatus['active'] ?? 0;
  const resolvedCount = byStatus['resolved'] ?? 0;

  // Only show types that have > 0 count
  const typeCounts = ALL_MARKUP_TYPES.filter((tp) => (byType[tp] ?? 0) > 0).map((tp) => ({
    type: tp,
    count: byType[tp] ?? 0,
    Icon: TYPE_ICONS[tp],
    color: TYPE_COLORS[tp],
  }));

  return (
    <div className="flex items-center gap-2 flex-wrap text-xs">
      {/* Total */}
      <span className="inline-flex items-center gap-1 font-semibold text-content-primary bg-surface-secondary px-2 py-1 rounded-md">
        {t('markups.stat_total_short', { defaultValue: 'Total' })}: {total}
      </span>

      {typeCounts.length > 0 && (
        <span className="text-border-light select-none">|</span>
      )}

      {/* By type */}
      {typeCounts.map(({ type, count, Icon, color }) => (
        <span
          key={type}
          className="inline-flex items-center gap-1 text-content-secondary bg-surface-secondary/60 px-1.5 py-0.5 rounded"
        >
          <Icon size={12} className={color} />
          <span className="capitalize">
            {t(`markups.type_${type}`, { defaultValue: TYPE_LABELS[type] })}
          </span>
          <span className="font-semibold text-content-primary">{count}</span>
        </span>
      ))}

      {(activeCount > 0 || resolvedCount > 0) && (
        <span className="text-border-light select-none">|</span>
      )}

      {/* Status counts */}
      {activeCount > 0 && (
        <Badge variant="blue" size="sm">
          {t('markups.active', { defaultValue: 'Active' })}: {activeCount}
        </Badge>
      )}
      {resolvedCount > 0 && (
        <Badge variant="success" size="sm">
          {t('markups.resolved', { defaultValue: 'Resolved' })}: {resolvedCount}
        </Badge>
      )}
    </div>
  );
}

/* ── Expanded Row Detail ─────────────────────────────────────────────── */

function MarkupDetail({ markup }: { markup: Markup }) {
  const { t } = useTranslation();
  return (
    <div className="px-6 py-3 bg-surface-secondary/40 border-t border-border-light">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div>
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide mb-0.5">
            {t('markups.full_text', { defaultValue: 'Text Content' })}
          </p>
          <p className="text-sm text-content-secondary">
            {markup.text || t('markups.no_text', { defaultValue: '(none)' })}
          </p>
        </div>
        <div>
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide mb-0.5">
            {t('markups.geometry_preview', { defaultValue: 'Geometry' })}
          </p>
          <p className="text-sm text-content-secondary">
            {markup.geometry && Object.keys(markup.geometry).length > 0
              ? t('markups.has_geometry', { defaultValue: 'Geometry data available' })
              : t('markups.no_geometry', { defaultValue: 'No geometry data' })}
          </p>
        </div>
        <div>
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide mb-0.5">
            {t('markups.linked_boq', { defaultValue: 'Linked BOQ Position' })}
          </p>
          <p className="text-sm text-content-secondary">
            {markup.linked_boq_position_id ||
              t('markups.not_linked', { defaultValue: 'Not linked' })}
          </p>
        </div>
      </div>
      {markup.metadata && Object.keys(markup.metadata).length > 0 && (
        <div className="mt-2">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide mb-0.5">
            {t('markups.metadata', { defaultValue: 'Metadata' })}
          </p>
          <pre className="text-xs text-content-tertiary bg-surface-primary rounded-lg p-2 overflow-x-auto">
            {JSON.stringify(markup.metadata, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

/* ── Grid Card ───────────────────────────────────────────────────────── */

function MarkupGridCard({
  markup,
  onChangeStatus,
  onDelete,
}: {
  markup: Markup;
  onChangeStatus: (status: MarkupStatus) => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const Icon = TYPE_ICONS[markup.type] ?? PenTool;
  const color = TYPE_COLORS[markup.type] ?? 'text-content-secondary';
  const bgColor = TYPE_BG_COLORS[markup.type] ?? '';

  const formattedDate = useMemo(() => {
    try {
      return new Date(markup.created_at).toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
      });
    } catch {
      return '';
    }
  }, [markup.created_at]);

  const measurementDisplay =
    markup.measurement_value && markup.measurement_unit
      ? `${markup.measurement_value} ${markup.measurement_unit}`
      : null;

  return (
    <div
      className={clsx(
        'rounded-lg border p-3 transition-all hover:shadow-md cursor-default',
        bgColor,
      )}
    >
      {/* Top row: icon+type and status */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <Icon size={14} className={color} />
          <span className="text-xs font-medium capitalize text-content-primary">
            {t(`markups.type_${markup.type}`, { defaultValue: TYPE_LABELS[markup.type] })}
          </span>
        </div>
        <Badge variant={STATUS_BADGE_VARIANT[markup.status] ?? 'neutral'} size="sm">
          {t(`markups.status_${markup.status}`, {
            defaultValue: markup.status.charAt(0).toUpperCase() + markup.status.slice(1),
          })}
        </Badge>
      </div>

      {/* Label / text excerpt */}
      <p className="text-sm text-content-primary font-medium truncate">
        {markup.label || markup.text || '-'}
      </p>
      {markup.text && markup.label && (
        <p className="text-xs text-content-tertiary truncate mt-0.5">{markup.text}</p>
      )}

      {/* Measurement */}
      {measurementDisplay && (
        <p className="text-xs font-semibold text-content-secondary mt-1.5 tabular-nums">
          {measurementDisplay}
        </p>
      )}

      {/* Footer: date + actions */}
      <div className="flex items-center justify-between mt-2.5 pt-2 border-t border-border-light/50">
        <span className="text-2xs text-content-tertiary">{formattedDate}</span>
        <div className="flex items-center gap-0.5">
          {markup.status === 'active' && (
            <button
              onClick={() => onChangeStatus('resolved')}
              title={t('markups.action_resolve', { defaultValue: 'Resolve' })}
              className="p-1 rounded hover:bg-surface-secondary text-green-600 transition-colors"
            >
              <Check size={13} />
            </button>
          )}
          {markup.status === 'resolved' && (
            <button
              onClick={() => onChangeStatus('archived')}
              title={t('markups.action_archive', { defaultValue: 'Archive' })}
              className="p-1 rounded hover:bg-surface-secondary text-content-tertiary transition-colors"
            >
              <Check size={13} />
            </button>
          )}
          <button
            onClick={onDelete}
            title={t('common.delete', { defaultValue: 'Delete' })}
            className="p-1 rounded hover:bg-surface-secondary text-semantic-error/70 hover:text-semantic-error transition-colors"
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Table Row ───────────────────────────────────────────────────────── */

function MarkupTableRow({
  markup,
  isExpanded,
  onToggleExpand,
  onChangeStatus,
  onDelete,
}: {
  markup: Markup;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onChangeStatus: (status: MarkupStatus) => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const TypeIcon = TYPE_ICONS[markup.type] ?? PenTool;
  const iconColor = TYPE_COLORS[markup.type] ?? 'text-content-secondary';

  const formattedDate = useMemo(() => {
    try {
      return new Date(markup.created_at).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      });
    } catch {
      return markup.created_at;
    }
  }, [markup.created_at]);

  const measurementDisplay =
    markup.measurement_value && markup.measurement_unit
      ? `${markup.measurement_value} ${markup.measurement_unit}`
      : '-';

  return (
    <>
      <tr
        onClick={onToggleExpand}
        className="cursor-pointer hover:bg-surface-secondary/50 transition-colors"
      >
        {/* Type */}
        <td className="px-3 py-2.5">
          <div className="flex items-center gap-1.5">
            {isExpanded ? (
              <ChevronDown size={12} className="text-content-tertiary shrink-0" />
            ) : (
              <ChevronRight size={12} className="text-content-tertiary shrink-0" />
            )}
            <TypeIcon size={14} className={clsx('shrink-0', iconColor)} />
            <span className="text-xs text-content-secondary capitalize">
              {t(`markups.type_${markup.type}`, {
                defaultValue: TYPE_LABELS[markup.type] ?? markup.type,
              })}
            </span>
          </div>
        </td>
        {/* Label / Text */}
        <td className="px-3 py-2.5">
          <span className="text-sm text-content-primary font-medium truncate max-w-[200px] block">
            {markup.label || markup.text?.slice(0, 40) || '-'}
          </span>
        </td>
        {/* Document */}
        <td className="px-3 py-2.5">
          <div className="flex items-center gap-1">
            <FileText size={12} className="text-content-tertiary shrink-0" />
            <span className="text-xs text-content-secondary truncate max-w-[130px] block">
              {markup.document_id ? markup.document_id.slice(0, 8) + '...' : '-'}
            </span>
          </div>
        </td>
        {/* Page */}
        <td className="px-3 py-2.5 text-xs text-content-secondary tabular-nums text-center">
          {markup.page}
        </td>
        {/* Status */}
        <td className="px-3 py-2.5">
          <Badge variant={STATUS_BADGE_VARIANT[markup.status] ?? 'neutral'} size="sm">
            {t(`markups.status_${markup.status}`, {
              defaultValue: markup.status.charAt(0).toUpperCase() + markup.status.slice(1),
            })}
          </Badge>
        </td>
        {/* Measurement */}
        <td className="px-3 py-2.5 text-xs text-content-secondary tabular-nums">
          {measurementDisplay}
        </td>
        {/* Date */}
        <td className="px-3 py-2.5 text-xs text-content-tertiary">{formattedDate}</td>
        {/* Actions */}
        <td className="px-3 py-2.5 text-right">
          <div
            className="flex items-center justify-end gap-0.5"
            onClick={(e) => e.stopPropagation()}
          >
            {markup.status === 'active' && (
              <button
                onClick={() => onChangeStatus('resolved')}
                title={t('markups.action_resolve', { defaultValue: 'Resolve' })}
                className="p-1 rounded hover:bg-surface-secondary text-green-600 transition-colors"
              >
                <Check size={14} />
              </button>
            )}
            {markup.status === 'resolved' && (
              <button
                onClick={() => onChangeStatus('archived')}
                title={t('markups.action_archive', { defaultValue: 'Archive' })}
                className="p-1 rounded hover:bg-surface-secondary text-content-tertiary transition-colors"
              >
                <Edit3 size={14} />
              </button>
            )}
            <button
              onClick={onDelete}
              title={t('common.delete', { defaultValue: 'Delete' })}
              className="p-1 rounded hover:bg-surface-secondary text-semantic-error/70 hover:text-semantic-error transition-colors"
            >
              <Trash2 size={14} />
            </button>
          </div>
        </td>
      </tr>
      {isExpanded && (
        <tr>
          <td colSpan={8}>
            <MarkupDetail markup={markup} />
          </td>
        </tr>
      )}
    </>
  );
}

/* ── Main Page ────────────────────────────────────────────────────────── */

export function MarkupsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // State
  const [searchQuery, setSearchQuery] = useState('');
  const [filterType, setFilterType] = useState<MarkupType | ''>('');
  const [filterStatus, setFilterStatus] = useState<MarkupStatus | ''>('');
  const [filterDocumentId, setFilterDocumentId] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [expandedRowId, setExpandedRowId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'list' | 'grid'>('list');
  const [showAddModal, setShowAddModal] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [annotateDocId, setAnnotateDocId] = useState<string | null>(null);
  const [annotateStamp, setAnnotateStamp] = useState<string | undefined>(undefined);
  const [showCustomStampForm, setShowCustomStampForm] = useState(false);
  const [customStampName, setCustomStampName] = useState('');
  const [customStampColor, setCustomStampColor] = useState('#3B82F6');

  // Data queries
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const projectId = activeProjectId || projects[0]?.id || '';

  const { data: documents = [] } = useQuery({
    queryKey: ['documents-list', projectId],
    queryFn: () => apiGet<DocItem[]>(`/v1/documents/?project_id=${projectId}`),
    enabled: !!projectId,
  });

  const { data: markups = [], isLoading } = useQuery({
    queryKey: ['markups', projectId, filterType, filterStatus, filterDocumentId],
    queryFn: () =>
      fetchMarkups(projectId, {
        type: filterType || undefined,
        status: filterStatus || undefined,
        document_id: filterDocumentId || undefined,
      }),
    enabled: !!projectId,
  });

  const { data: summary } = useQuery({
    queryKey: ['markups-summary', projectId],
    queryFn: () => fetchMarkupsSummary(projectId),
    enabled: !!projectId,
  });

  const { data: stamps = [] } = useQuery({
    queryKey: ['stamp-templates', projectId],
    queryFn: () => fetchStampTemplates(projectId),
    enabled: !!projectId,
  });

  // Client-side search filter
  const filteredMarkups = useMemo(() => {
    if (!searchQuery.trim()) return markups;
    const q = searchQuery.toLowerCase();
    return markups.filter(
      (m) =>
        (m.label ?? '').toLowerCase().includes(q) ||
        (m.text ?? '').toLowerCase().includes(q) ||
        m.type.toLowerCase().includes(q),
    );
  }, [markups, searchQuery]);

  // Invalidation
  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['markups'] });
    qc.invalidateQueries({ queryKey: ['markups-summary'] });
  }, [qc]);

  // Mutations
  const statusMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: MarkupStatus }) =>
      updateMarkup(id, { status }),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('markups.status_updated', { defaultValue: 'Markup status updated' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const delMut = useMutation({
    mutationFn: (id: string) => deleteMarkup(id),
    onSuccess: () => {
      invalidateAll();
      setDeleteTarget(null);
      addToast({
        type: 'success',
        title: t('markups.deleted', { defaultValue: 'Markup deleted' }),
      });
    },
    onError: (e: Error) => {
      setDeleteTarget(null);
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      });
    },
  });

  // CSV export
  const handleExportCSV = useCallback(async () => {
    if (!projectId) return;
    try {
      const blob = await exportMarkupsCSV(projectId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `markups-${projectId}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      addToast({
        type: 'success',
        title: t('markups.exported', { defaultValue: 'Markups exported to CSV' }),
      });
    } catch (e) {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e instanceof Error ? e.message : String(e),
      });
    }
  }, [projectId, addToast, t]);

  // Build stamp display list
  const displayStamps = useMemo(() => {
    const apiStampMap = new Map(stamps.map((s) => [s.name, s]));
    const result: Array<{ name: string; label: string; color: string }> = DEFAULT_STAMPS.map(
      (def) => {
        const apiStamp = apiStampMap.get(def.name);
        return apiStamp
          ? { name: apiStamp.name, label: apiStamp.text || apiStamp.name, color: apiStamp.color }
          : def;
      },
    );
    for (const s of stamps) {
      if (!DEFAULT_STAMPS.some((d) => d.name === s.name)) {
        result.push({ name: s.name, label: s.text || s.name, color: s.color });
      }
    }
    return result;
  }, [stamps]);

  return (
    <div className="mx-auto max-w-7xl px-4 py-4 animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          { label: t('markups.title', { defaultValue: 'Markups & Annotations' }) },
        ]}
      />

      {/* ── Header: single row ───────────────────────────────────────────── */}
      <div className="mt-3 flex items-center justify-between gap-3 flex-wrap">
        {/* Left: title */}
        <h1 className="text-lg font-bold text-content-primary flex items-center gap-2 shrink-0">
          <PenTool size={20} className="text-oe-blue" />
          {t('markups.title', { defaultValue: 'Markups & Annotations' })}
        </h1>

        {/* Right: controls — single row, no wrap */}
        <div className="flex items-center gap-1.5 shrink-0">
          {/* Project selector */}
          {projects.length > 0 && (
            <select
              value={projectId}
              onChange={(e) => {
                const p = projects.find((pr) => pr.id === e.target.value);
                if (p) {
                  useProjectContextStore.getState().setActiveProject(p.id, p.name);
                }
              }}
              className={selectCls + ' max-w-[150px]'}
            >
              <option value="" disabled>
                {t('markups.select_project', { defaultValue: 'Project...' })}
              </option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}

          {/* Document selector */}
          {projectId && (
            <select
              value={filterDocumentId}
              onChange={(e) => setFilterDocumentId(e.target.value)}
              className={selectCls + ' max-w-[140px]'}
            >
              <option value="">
                {documents.length > 0
                  ? t('markups.all_documents', { defaultValue: 'All Docs' })
                  : t('markups.no_documents', { defaultValue: 'No docs' })}
              </option>
              {documents.map((doc) => (
                <option key={doc.id} value={doc.id}>
                  {doc.name}
                </option>
              ))}
            </select>
          )}

          {/* Open inline PDF annotator — icon-only on small screens */}
          {documents.length > 0 && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setAnnotateDocId(filterDocumentId || documents[0]?.id || null)}
              disabled={!projectId || documents.length === 0}
              className="shrink-0 whitespace-nowrap"
              title={t('markups.annotate_pdf', { defaultValue: 'Annotate on PDF' })}
            >
              <PenTool size={14} />
              <span className="hidden lg:inline ml-1">{t('markups.annotate_pdf', { defaultValue: 'Annotate' })}</span>
            </Button>
          )}

          {/* Add Markup */}
          <Button
            variant="primary"
            size="sm"
            onClick={() => setShowAddModal(true)}
            disabled={!projectId}
            className="shrink-0 whitespace-nowrap"
            title={t('markups.add_markup', { defaultValue: 'Add Markup' })}
          >
            <Plus size={14} />
            <span className="hidden lg:inline ml-1">{t('markups.add_markup', { defaultValue: 'Add' })}</span>
          </Button>

          {/* Export — icon only */}
          <Button
            variant="ghost"
            size="sm"
            onClick={handleExportCSV}
            disabled={!projectId}
            icon={<Download size={14} />}
            title={t('markups.export', { defaultValue: 'Export' })}
          >
            <span className="hidden lg:inline">{t('markups.export', { defaultValue: 'Export' })}</span>
          </Button>
        </div>
      </div>

      {/* ── No project selected ──────────────────────────────────────────── */}
      {!projectId ? (
        <div className="mt-10">
          <EmptyState
            icon={<PenTool size={28} strokeWidth={1.5} />}
            title={t('markups.no_project_title', { defaultValue: 'No project selected' })}
            description={t('markups.no_project_desc', {
              defaultValue:
                'Select a project from the dropdown to view markups and annotations. You can create markups on document pages, add measurements, and track review status.',
            })}
            action={{
              label: t('markups.select_project_btn', { defaultValue: 'Select a Project' }),
              onClick: () => {
                /* Focus the project selector */
              },
            }}
          />
        </div>
      ) : (
        <>
          {/* ── Stats Bar ──────────────────────────────────────────────────── */}
          <div className="mt-3">
            <StatsBar summary={summary} />
          </div>

          {/* ── Inline PDF Annotator ──────────────────────────────────────── */}
          {annotateDocId && (
            <div className="mt-3">
              <InlinePdfAnnotator
                documentId={annotateDocId}
                documentName={documents.find((d) => d.id === annotateDocId)?.name || 'Document'}
                projectId={projectId}
                onClose={() => { setAnnotateDocId(null); setAnnotateStamp(undefined); }}
                onMarkupCreated={invalidateAll}
                activeStamp={annotateStamp}
              />
            </div>
          )}

          {/* ── Filter / Search / View Toggle ──────────────────────────────── */}
          <div className="mt-3 flex items-center gap-2 flex-wrap">
            {/* Search */}
            <div className="relative flex-1 min-w-[200px] max-w-xs">
              <Search
                size={14}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-content-tertiary"
              />
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t('markups.search', {
                  defaultValue: 'Search markups...',
                })}
                className={inputCls + ' w-full pl-8'}
              />
            </div>

            {/* Filters toggle */}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowFilters(!showFilters)}
              className={showFilters ? 'text-oe-blue' : ''}
              icon={<Filter size={14} />}
            >
              {t('common.filters', { defaultValue: 'Filters' })}
            </Button>

            {/* View toggle */}
            <div className="flex items-center border border-border rounded-lg overflow-hidden ml-auto">
              <button
                onClick={() => setViewMode('list')}
                className={clsx(
                  'p-1.5 transition-colors',
                  viewMode === 'list'
                    ? 'bg-oe-blue text-content-inverse'
                    : 'bg-surface-primary text-content-tertiary hover:bg-surface-secondary',
                )}
                title={t('markups.view_list', { defaultValue: 'List view' })}
              >
                <LayoutList size={14} />
              </button>
              <button
                onClick={() => setViewMode('grid')}
                className={clsx(
                  'p-1.5 transition-colors',
                  viewMode === 'grid'
                    ? 'bg-oe-blue text-content-inverse'
                    : 'bg-surface-primary text-content-tertiary hover:bg-surface-secondary',
                )}
                title={t('markups.view_grid', { defaultValue: 'Grid view' })}
              >
                <LayoutGrid size={14} />
              </button>
            </div>
          </div>

          {/* Collapsible filters */}
          {showFilters && (
            <div className="mt-2 flex items-center gap-2 flex-wrap animate-fade-in">
              <select
                value={filterType}
                onChange={(e) => setFilterType(e.target.value as MarkupType | '')}
                className={selectCls + ' max-w-[140px]'}
              >
                <option value="">
                  {t('markups.all_types', { defaultValue: 'All Types' })}
                </option>
                {ALL_MARKUP_TYPES.map((tp) => (
                  <option key={tp} value={tp}>
                    {t(`markups.type_${tp}`, { defaultValue: TYPE_LABELS[tp] })}
                  </option>
                ))}
              </select>

              <select
                value={filterStatus}
                onChange={(e) => setFilterStatus(e.target.value as MarkupStatus | '')}
                className={selectCls + ' max-w-[140px]'}
              >
                <option value="">
                  {t('markups.all_statuses', { defaultValue: 'All Statuses' })}
                </option>
                {MARKUP_STATUSES.map((st) => (
                  <option key={st} value={st}>
                    {t(`markups.status_${st}`, {
                      defaultValue: st.charAt(0).toUpperCase() + st.slice(1),
                    })}
                  </option>
                ))}
              </select>

              {(filterType || filterStatus) && (
                <button
                  onClick={() => {
                    setFilterType('');
                    setFilterStatus('');
                  }}
                  className="text-xs text-oe-blue hover:underline"
                >
                  {t('markups.clear_filters', { defaultValue: 'Clear' })}
                </button>
              )}
            </div>
          )}

          {/* ── Main Content ───────────────────────────────────────────────── */}
          <div className="mt-3">
            {isLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" />
              </div>
            ) : filteredMarkups.length === 0 ? (
              <EmptyState
                icon={<PenTool size={28} strokeWidth={1.5} />}
                title={
                  searchQuery || filterType || filterStatus
                    ? t('markups.no_match_title', { defaultValue: 'No matching markups' })
                    : t('markups.empty_title', { defaultValue: 'No markups yet' })
                }
                description={
                  searchQuery || filterType || filterStatus
                    ? t('markups.no_match_desc', {
                        defaultValue: 'Try adjusting your search or filter criteria.',
                      })
                    : t('markups.empty_desc', {
                        defaultValue:
                          'Create your first markup to start annotating documents. Use clouds, arrows, text, and measurement tools to collaborate with your team.',
                      })
                }
                action={
                  searchQuery || filterType || filterStatus
                    ? undefined
                    : {
                        label: t('markups.add_first', { defaultValue: 'Add First Markup' }),
                        onClick: () => setShowAddModal(true),
                      }
                }
              />
            ) : viewMode === 'list' ? (
              /* ── List View (Table) ─────────────────────────────────────── */
              <Card padding="none" className="overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border-light bg-surface-secondary/50">
                        <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[120px]">
                          {t('markups.col_type', { defaultValue: 'Type' })}
                        </th>
                        <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                          {t('markups.col_label', { defaultValue: 'Label / Text' })}
                        </th>
                        <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[130px]">
                          {t('markups.col_document', { defaultValue: 'Document' })}
                        </th>
                        <th className="px-3 py-2 text-center text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[50px]">
                          {t('markups.col_page', { defaultValue: 'Pg' })}
                        </th>
                        <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[90px]">
                          {t('markups.col_status', { defaultValue: 'Status' })}
                        </th>
                        <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[100px]">
                          {t('markups.col_measurement', { defaultValue: 'Measure' })}
                        </th>
                        <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[100px]">
                          {t('markups.col_date', { defaultValue: 'Date' })}
                        </th>
                        <th className="px-3 py-2 text-right text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[80px]">
                          {t('common.actions', { defaultValue: 'Actions' })}
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-light">
                      {filteredMarkups.map((markup) => (
                        <MarkupTableRow
                          key={markup.id}
                          markup={markup}
                          isExpanded={expandedRowId === markup.id}
                          onToggleExpand={() =>
                            setExpandedRowId(
                              expandedRowId === markup.id ? null : markup.id,
                            )
                          }
                          onChangeStatus={(status) =>
                            statusMut.mutate({ id: markup.id, status })
                          }
                          onDelete={() => setDeleteTarget(markup.id)}
                        />
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            ) : (
              /* ── Grid View ─────────────────────────────────────────────── */
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2.5">
                {filteredMarkups.map((markup) => (
                  <MarkupGridCard
                    key={markup.id}
                    markup={markup}
                    onChangeStatus={(status) =>
                      statusMut.mutate({ id: markup.id, status })
                    }
                    onDelete={() => setDeleteTarget(markup.id)}
                  />
                ))}
              </div>
            )}
          </div>

          {/* ── Stamps (inline badges row) ─────────────────────────────────── */}
          {displayStamps.length > 0 && (
            <div className="mt-4 flex items-center gap-2 flex-wrap">
              <span className="text-xs font-semibold text-content-tertiary uppercase tracking-wide">
                {t('markups.stamps', { defaultValue: 'Stamps' })}:
              </span>
              {displayStamps.map((stamp) => {
                const colorCls =
                  STAMP_BADGE_COLORS[stamp.color] ??
                  'bg-gray-100 text-gray-700 border-gray-300 dark:bg-gray-900/30 dark:text-gray-400 dark:border-gray-600';
                return (
                  <button
                    key={stamp.name}
                    onClick={() => {
                      if (documents.length > 0) {
                        setAnnotateStamp(stamp.name);
                        setAnnotateDocId(filterDocumentId || documents[0]?.id || null);
                      } else {
                        addToast({
                          type: 'info',
                          title: t('markups.upload_doc_first', { defaultValue: 'Upload a document first to place stamps on it.' }),
                        });
                      }
                    }}
                    className={clsx(
                      'inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-xs font-medium cursor-pointer hover:opacity-80 hover:scale-105 transition-all',
                      colorCls,
                    )}
                    title={t('markups.click_to_place_stamp', { defaultValue: 'Click to place this stamp on a document' })}
                  >
                    <Stamp size={11} />
                    {t(`markups.stamp_${stamp.name}`, { defaultValue: stamp.label })}
                  </button>
                );
              })}
              <button
                className="text-xs text-oe-blue hover:underline ml-1"
                onClick={() => setShowCustomStampForm(true)}
                disabled={!projectId}
              >
                + {t('markups.custom_stamp', { defaultValue: 'Custom' })}
              </button>
            </div>
          )}
        </>
      )}

      {/* ── Add Markup Modal ───────────────────────────────────────────── */}
      <AddMarkupModal
        open={showAddModal}
        onClose={() => setShowAddModal(false)}
        projectId={projectId}
        documents={documents}
        onCreated={invalidateAll}
      />

      {/* ── Custom Stamp Form ──────────────────────────────────────────── */}
      {showCustomStampForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setShowCustomStampForm(false)}>
          <div className="w-full max-w-sm mx-4 rounded-xl bg-surface-elevated shadow-xl border border-border-light p-5" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-semibold text-content-primary mb-4">
              {t('markups.create_custom_stamp', { defaultValue: 'Create Custom Stamp' })}
            </h3>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-content-secondary mb-1">
                  {t('markups.stamp_text', { defaultValue: 'Stamp Text' })}
                </label>
                <input
                  value={customStampName}
                  onChange={(e) => setCustomStampName(e.target.value)}
                  placeholder={t('markups.stamp_text_placeholder', { defaultValue: 'e.g. CHECKED, HOLD, RFI...' })}
                  className="h-8 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-content-secondary mb-1">
                  {t('markups.stamp_color', { defaultValue: 'Color' })}
                </label>
                <div className="flex gap-2">
                  {PRESET_COLORS.map((c) => (
                    <button
                      key={c.value}
                      onClick={() => setCustomStampColor(c.value)}
                      className={clsx(
                        'w-7 h-7 rounded-full border-2 transition-all',
                        customStampColor === c.value ? 'border-content-primary scale-110 ring-2 ring-offset-1 ring-oe-blue/40' : 'border-transparent hover:scale-105',
                      )}
                      style={{ backgroundColor: c.value }}
                    />
                  ))}
                </div>
              </div>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setShowCustomStampForm(false)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                size="sm"
                disabled={!customStampName.trim()}
                onClick={async () => {
                  if (!customStampName.trim()) return;
                  try {
                    const { createStampTemplate } = await import('./api');
                    await createStampTemplate({
                      name: customStampName.trim().toLowerCase().replace(/\s+/g, '_'),
                      text: customStampName.trim().toUpperCase(),
                      color: customStampColor,
                      project_id: projectId || undefined,
                    });
                    addToast({
                      type: 'success',
                      title: t('markups.stamp_created', { defaultValue: 'Stamp created' }),
                    });
                    qc.invalidateQueries({ queryKey: ['stamp-templates'] });
                    setShowCustomStampForm(false);
                    setCustomStampName('');
                  } catch (err) {
                    addToast({
                      type: 'error',
                      title: t('common.error', { defaultValue: 'Error' }),
                      message: err instanceof Error ? err.message : '',
                    });
                  }
                }}
              >
                {t('common.create', { defaultValue: 'Create' })}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── Delete Confirm Dialog ──────────────────────────────────────── */}
      <ConfirmDialog
        open={deleteTarget !== null}
        onConfirm={() => deleteTarget && delMut.mutate(deleteTarget)}
        onCancel={() => setDeleteTarget(null)}
        title={t('markups.delete_title', { defaultValue: 'Delete Markup' })}
        message={t('markups.delete_message', {
          defaultValue:
            'This markup will be permanently removed. This action cannot be undone.',
        })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        cancelLabel={t('common.cancel', { defaultValue: 'Cancel' })}
        variant="danger"
        loading={delMut.isPending}
      />
    </div>
  );
}
