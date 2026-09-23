// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  PenTool,
  Search,
  Download,
  GitCompare,
  ChevronDown,
  ChevronLeft,
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
  ExternalLink,
  Flag,
  CalendarClock,
  AlertTriangle,
  ClipboardCheck,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb, ConfirmDialog, RecoveryCard, SkeletonTable, ModuleGuideButton } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DismissibleInfo, IntroRichText } from '@/shared/ui/DismissibleInfo';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { apiGet, type Page } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { fetchUsers, type User as AssigneeUser } from '@/features/users/api';
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
import { UnifiedMarkupsList } from './UnifiedMarkupsList';
import { EditMarkupModal } from './EditMarkupModal';
import { markupsGuide } from './markupsGuide';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import { buildMarkupsInsights } from './markupsInsights';
import {
  MARKUP_PRIORITIES,
  PRIORITY_LABELS,
  PRIORITY_CHIP_CLASSES,
  getMarkupPriority,
  getMarkupDueDate,
  getMarkupPunchId,
  isMarkupOverdue,
  computeGeometryCentroid01,
  type MarkupPriority,
} from './issueTracking';
import { ApprovalInstanceCard } from '@/features/approval-routes';
// Read-only cross-module import: promoting a markup into a tracked site issue
// reuses the punch-list create endpoint. We never mutate punch-list files.
import { createPunchItem, type CreatePunchPayload, type PunchPriority } from '@/features/punchlist/api';
import { getIntlLocale } from '@/shared/lib/formatters';
import { IssueHubLink } from '@/features/issues/IssueHubLink';

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

// Pagination: matches the backend's default page size (offset/limit, max
// 200). The list grows by this increment each time the user clicks
// "Load more" so projects with thousands of markups don't all load at once.
const MARKUPS_PAGE_SIZE = 50;

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

/* ── Assignee filter sentinels ────────────────────────────────────────── */
// "" = no filter, "__unassigned__" = NULL assignee, otherwise user UUID.
const ASSIGNEE_UNASSIGNED = '__unassigned__';

/* ── Assignee chip ────────────────────────────────────────────────────── */

function AssigneeChip({
  assigneeId,
  userMap,
}: {
  assigneeId: string | null | undefined;
  userMap: Map<string, AssigneeUser>;
}) {
  const { t } = useTranslation();
  if (!assigneeId) {
    return (
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-surface-secondary text-2xs text-content-tertiary border border-border-light"
        title={t('markups.unassigned', { defaultValue: 'Unassigned' })}
      >
        {t('markups.unassigned', { defaultValue: 'Unassigned' })}
      </span>
    );
  }
  const user = userMap.get(assigneeId);
  const display = user?.full_name?.trim() || user?.email || assigneeId.slice(0, 8);
  const initials = (user?.full_name || user?.email || '?')
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase() ?? '')
    .join('') || '?';
  return (
    <span
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-oe-blue-subtle text-2xs text-oe-blue-text border border-oe-blue/30 max-w-[150px]"
      title={display}
    >
      <span className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full bg-oe-blue text-content-inverse text-[8px] font-semibold shrink-0">
        {initials}
      </span>
      <span className="truncate">{display}</span>
    </span>
  );
}

/* ── Priority chip ────────────────────────────────────────────────────── */

function PriorityChip({ priority }: { priority: MarkupPriority }) {
  const { t } = useTranslation();
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-2xs font-medium border',
        PRIORITY_CHIP_CLASSES[priority],
      )}
      title={t('markups.priority', { defaultValue: 'Priority' })}
    >
      <Flag size={9} />
      {t(`markups.priority_${priority}`, { defaultValue: PRIORITY_LABELS[priority] })}
    </span>
  );
}

/* ── Due-date chip ────────────────────────────────────────────────────── */
// Renders the due date with overdue styling. ``overdue`` is passed in rather
// than recomputed so the caller can key it off the markup's live status.
function DueChip({ due, overdue }: { due: string; overdue: boolean }) {
  const { t } = useTranslation();
  const formatted = useMemo(() => {
    const ms = Date.parse(`${due}T00:00:00`);
    if (!Number.isFinite(ms)) return due;
    return new Date(ms).toLocaleDateString(getIntlLocale(), {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  }, [due]);
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 text-2xs',
        overdue ? 'text-semantic-error font-semibold' : 'text-content-tertiary',
      )}
      title={
        overdue
          ? t('markups.overdue_since', { defaultValue: 'Overdue since {{date}}', date: formatted })
          : t('markups.due_date', { defaultValue: 'Due date' })
      }
    >
      {overdue ? <AlertTriangle size={10} /> : <CalendarClock size={10} />}
      {formatted}
    </span>
  );
}

/* ── Add Markup Modal ─────────────────────────────────────────────────── */

function AddMarkupModal({
  open,
  onClose,
  projectId,
  documents,
  users,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  documents: DocItem[];
  users: AssigneeUser[];
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
  const [assigneeId, setAssigneeId] = useState('');
  const [priority, setPriority] = useState<MarkupPriority | ''>('');
  const [dueDate, setDueDate] = useState('');

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
      setAssigneeId('');
      setPriority('');
      setDueDate('');
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
      ...(assigneeId && { assignee_id: assigneeId }),
      ...(MEASUREMENT_TYPES.includes(selectedType) &&
        measurementValue && {
          measurement_value: parseFloat(measurementValue),
          measurement_unit: measurementUnit,
        }),
      // Priority / due date ride in metadata (no dedicated column). Only
      // included when set, so a plain markup stores an empty metadata dict.
      ...((priority || dueDate) && {
        metadata: {
          ...(priority && { priority }),
          ...(dueDate && { due_date: dueDate }),
        },
      }),
    };
    createMut.mutate(payload);
  };

  if (!open) return null;

  const isMeasurementType = MEASUREMENT_TYPES.includes(selectedType);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in" />
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
            aria-label={t('common.close', { defaultValue: 'Close' })}
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
                        ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text ring-1 ring-oe-blue/30'
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

          {/* Assignee dropdown */}
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1.5">
              {t('markups.assignee', { defaultValue: 'Assignee' })}
            </label>
            <select
              value={assigneeId}
              onChange={(e) => setAssigneeId(e.target.value)}
              className={selectCls + ' w-full'}
              data-testid="markup-form-assignee"
            >
              <option value="">{t('markups.unassigned', { defaultValue: 'Unassigned' })}</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name?.trim() || u.email}
                </option>
              ))}
            </select>
          </div>

          {/* Priority + Due date - optional issue-tracking fields. */}
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="flex items-center gap-1 text-xs font-medium text-content-secondary mb-1.5">
                <Flag size={12} />
                {t('markups.priority', { defaultValue: 'Priority' })}
              </label>
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value as MarkupPriority | '')}
                className={selectCls + ' w-full'}
                data-testid="markup-form-priority"
              >
                <option value="">{t('markups.no_priority', { defaultValue: 'None' })}</option>
                {MARKUP_PRIORITIES.map((p) => (
                  <option key={p} value={p}>
                    {t(`markups.priority_${p}`, { defaultValue: PRIORITY_LABELS[p] })}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex-1">
              <label className="flex items-center gap-1 text-xs font-medium text-content-secondary mb-1.5">
                <CalendarClock size={12} />
                {t('markups.due_date', { defaultValue: 'Due date' })}
              </label>
              <input
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                className={inputCls + ' w-full'}
                data-testid="markup-form-due"
              />
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

function MarkupDetail({
  markup,
  documentName,
  onEdit,
  siblings,
  onNavigate,
  onOpenInDocument,
  onOpenBoqPosition,
  onUseAsQuantity,
  onConvertToIssue,
  onOpenIssue,
  isConverting,
}: {
  markup: Markup;
  documentName?: string;
  onEdit?: () => void;
  /**
   * Other markups on the same document, sorted by created_at ASC.
   * Used to compute prev/next for chevron navigation. When the current
   * markup has no document, only itself is provided so chevrons are
   * disabled at both ends.
   */
  siblings?: Markup[];
  onNavigate?: (id: string) => void;
  /**
   * Opens the source document in the inline PDF annotator and pulses a
   * glow ring around this markup. Disabled / hidden when the markup has
   * no ``document_id`` (project-level annotation).
   */
  onOpenInDocument?: (markup: Markup) => void;
  /**
   * Jumps to the BOQ that this markup is linked to. Only rendered when
   * ``linked_boq_position_id`` is set, so the previously-dead "Linked to a
   * BOQ position" text becomes a live navigation control.
   */
  onOpenBoqPosition?: (positionId: string) => void;
  /**
   * Sends a measurement markup's value into PDF Takeoff so a clouded
   * distance / area / count can become a takeoff quantity instead of being
   * re-keyed by hand (CONN-67). Only rendered for measurement-type markups
   * that carry a value.
   */
  onUseAsQuantity?: (markup: Markup) => void;
  /**
   * Promotes this markup into a tracked punch-list issue (document + page +
   * geometry centroid + label/text + assignee + priority + due). Rendered
   * until the markup already links to an issue, at which point ``onOpenIssue``
   * takes over.
   */
  onConvertToIssue?: (markup: Markup) => void;
  /** Deep-links to the punch-list issue this markup was promoted into. */
  onOpenIssue?: (punchId: string) => void;
  /** True while this markup's conversion request is in flight. */
  isConverting?: boolean;
}) {
  const { t } = useTranslation();
  const idx = siblings ? siblings.findIndex((m) => m.id === markup.id) : -1;
  const total = siblings?.length ?? 0;
  const prevId = idx > 0 ? siblings![idx - 1]!.id : null;
  const nextId = idx >= 0 && idx < total - 1 ? siblings![idx + 1]!.id : null;
  const showNav = !!siblings && total > 1 && idx >= 0;

  // A measurement markup (distance / area / count) carrying a numeric value
  // can be pushed straight into PDF Takeoff as a quantity (CONN-67).
  const canUseAsQuantity =
    MEASUREMENT_TYPES.includes(markup.type) &&
    markup.measurement_value != null &&
    !!onUseAsQuantity;

  // Issue-tracking state for this markup.
  const priority = getMarkupPriority(markup);
  const due = getMarkupDueDate(markup);
  const overdue = isMarkupOverdue(markup);
  const punchId = getMarkupPunchId(markup);

  return (
    <div className="px-6 py-3 bg-surface-secondary/40 border-t border-border-light">
      {/* Deep-link CTAs — primary actions for the detail row. Sit above the
          metadata grid so reviewers see them first when expanding a row. */}
      {((markup.document_id && onOpenInDocument) ||
        canUseAsQuantity ||
        (punchId ? onOpenIssue : onConvertToIssue)) && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {markup.document_id && onOpenInDocument && (
            <button
              type="button"
              onClick={() => onOpenInDocument(markup)}
              title={t('markups.openInDocumentHint', {
                defaultValue: 'Jump to this markup on the source document',
              })}
              data-testid="markup-open-in-document"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-oe-blue text-white hover:bg-oe-blue-hover transition-colors shadow-sm"
            >
              <FileText size={13} />
              {t('markups.openInDocument', { defaultValue: 'Open in document' })}
              <ExternalLink size={11} className="opacity-80" />
            </button>
          )}
          {/* Convert to issue, or open the linked issue once promoted. This is
              what upgrades a bare annotation into a tracked site issue. */}
          {punchId
            ? onOpenIssue && (
                <button
                  type="button"
                  onClick={() => onOpenIssue(punchId)}
                  title={t('markups.openIssueHint', {
                    defaultValue: 'Open the tracked issue raised from this markup',
                  })}
                  data-testid="markup-open-issue"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-green-700 bg-green-50 border border-green-300 hover:bg-green-100 transition-colors dark:text-green-300 dark:bg-green-900/20 dark:border-green-700"
                >
                  <ClipboardCheck size={13} />
                  {t('markups.openIssue', { defaultValue: 'Open issue' })}
                  <ExternalLink size={11} className="opacity-80" />
                </button>
              )
            : onConvertToIssue && (
                <button
                  type="button"
                  onClick={() => onConvertToIssue(markup)}
                  disabled={isConverting}
                  title={t('markups.convertToIssueHint', {
                    defaultValue:
                      'Raise a tracked punch-list issue from this markup, keeping its drawing location, priority and due date',
                  })}
                  data-testid="markup-convert-to-issue"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-oe-blue bg-oe-blue-subtle border border-oe-blue/30 hover:bg-oe-blue/10 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  <ClipboardCheck size={13} />
                  {isConverting
                    ? t('markups.converting', { defaultValue: 'Converting...' })
                    : t('markups.convertToIssue', { defaultValue: 'Convert to issue' })}
                </button>
              )}
          {canUseAsQuantity && (
            <button
              type="button"
              onClick={() => onUseAsQuantity!(markup)}
              title={t('markups.useAsQuantityHint', {
                defaultValue:
                  'Send this measurement into PDF Takeoff as a quantity instead of re-keying it',
              })}
              data-testid="markup-use-as-quantity"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-oe-blue bg-oe-blue-subtle border border-oe-blue/30 hover:bg-oe-blue/10 transition-colors"
            >
              <Ruler size={13} />
              {t('markups.useAsQuantity', { defaultValue: 'Use as takeoff quantity' })}
              <ExternalLink size={11} className="opacity-80" />
            </button>
          )}
        </div>
      )}
      {showNav && (
        <div className="flex items-center justify-between mb-3 pb-2 border-b border-border-light/60">
          <button
            type="button"
            onClick={() => prevId && onNavigate?.(prevId)}
            disabled={!prevId}
            data-testid="markup-prev"
            aria-label={t('markups.previous', { defaultValue: 'Previous markup' })}
            title={t('markups.previous', { defaultValue: 'Previous' }) + ' (←)'}
            className={clsx(
              'inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium transition-colors',
              prevId
                ? 'text-content-primary hover:bg-surface-primary'
                : 'text-content-tertiary opacity-50 cursor-not-allowed',
            )}
          >
            <ChevronLeft size={14} />
            {t('markups.previous', { defaultValue: 'Prev' })}
          </button>
          <span
            className="text-xs text-content-tertiary tabular-nums"
            data-testid="markup-position"
          >
            {t('markups.position_n_of_m', {
              defaultValue: '{{n}} of {{total}}',
              n: idx + 1,
              total,
            })}
          </span>
          <button
            type="button"
            onClick={() => nextId && onNavigate?.(nextId)}
            disabled={!nextId}
            data-testid="markup-next"
            aria-label={t('markups.next', { defaultValue: 'Next markup' })}
            title={t('markups.next', { defaultValue: 'Next' }) + ' (→)'}
            className={clsx(
              'inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium transition-colors',
              nextId
                ? 'text-content-primary hover:bg-surface-primary'
                : 'text-content-tertiary opacity-50 cursor-not-allowed',
            )}
          >
            {t('markups.next', { defaultValue: 'Next' })}
            <ChevronRight size={14} />
          </button>
        </div>
      )}
      {onEdit && (
        <div className="flex items-center justify-end mb-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={onEdit}
            icon={<Edit3 size={13} />}
          >
            {t('markups.edit', { defaultValue: 'Edit' })}
          </Button>
        </div>
      )}
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
            {t('markups.document', { defaultValue: 'Document' })}
          </p>
          <p className="text-sm text-content-secondary">
            {markup.document_id
              ? documentName || t('markups.unknown_document', { defaultValue: 'Document' })
              : t('markups.no_document_link', {
                  defaultValue: 'Project-level annotation (no document)',
                })}
            {markup.document_id && (
              <>
                {' · '}
                <span className="text-content-tertiary">
                  {t('markups.page_n', { defaultValue: 'page {{n}}', n: markup.page })}
                </span>
              </>
            )}
          </p>
        </div>
        <div>
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide mb-0.5">
            {t('markups.linked_boq', { defaultValue: 'Linked BOQ Position' })}
          </p>
          {markup.linked_boq_position_id ? (
            <button
              type="button"
              onClick={() =>
                onOpenBoqPosition?.(markup.linked_boq_position_id as string)
              }
              data-testid="markup-open-boq-position"
              title={t('markups.open_linked_boq_hint', {
                defaultValue: 'Open the linked BOQ position',
              })}
              className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs font-medium text-oe-blue bg-oe-blue-subtle border border-oe-blue/30 hover:bg-oe-blue/10 transition-colors"
            >
              <ExternalLink size={11} />
              {t('markups.open_linked_boq', { defaultValue: 'Open BOQ position' })}
            </button>
          ) : (
            <p className="text-sm text-content-secondary">
              {t('markups.not_linked', { defaultValue: 'Not linked' })}
            </p>
          )}
        </div>
        <div>
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide mb-0.5">
            {t('markups.issue_tracking', { defaultValue: 'Priority / Due' })}
          </p>
          {priority || due ? (
            <div className="flex items-center gap-2 flex-wrap">
              {priority && <PriorityChip priority={priority} />}
              {due && <DueChip due={due} overdue={overdue} />}
            </div>
          ) : (
            <p className="text-sm text-content-secondary">
              {t('markups.no_priority_or_due', { defaultValue: 'None set' })}
            </p>
          )}
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
      {/* Wave-2 Epic A — approval workflow drop-in. The card no-ops
          gracefully when no instance exists and no route is configured. */}
      <div className="mt-3">
        <ApprovalInstanceCard
          targetKind="markup"
          targetId={markup.id}
          projectId={markup.project_id}
        />
      </div>
    </div>
  );
}

/* ── Grid Card ───────────────────────────────────────────────────────── */

function MarkupGridCard({
  markup,
  onChangeStatus,
  onDelete,
  onEdit,
  userMap,
  onConvertToIssue,
  onOpenIssue,
  isConverting,
}: {
  markup: Markup;
  onChangeStatus: (status: MarkupStatus) => void;
  onDelete: () => void;
  onEdit: () => void;
  userMap: Map<string, AssigneeUser>;
  onConvertToIssue?: (markup: Markup) => void;
  onOpenIssue?: (punchId: string) => void;
  isConverting?: boolean;
}) {
  const { t } = useTranslation();
  const Icon = TYPE_ICONS[markup.type] ?? PenTool;
  const color = TYPE_COLORS[markup.type] ?? 'text-content-secondary';
  const bgColor = TYPE_BG_COLORS[markup.type] ?? '';

  const priority = getMarkupPriority(markup);
  const due = getMarkupDueDate(markup);
  const overdue = isMarkupOverdue(markup);
  const punchId = getMarkupPunchId(markup);

  const formattedDate = useMemo(() => {
    try {
      return new Date(markup.created_at).toLocaleDateString(getIntlLocale(), {
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

      {/* Assignee + priority + due chips */}
      <div className="mt-2 flex items-center gap-1.5 flex-wrap">
        <AssigneeChip assigneeId={markup.assignee_id} userMap={userMap} />
        {priority && <PriorityChip priority={priority} />}
        {due && <DueChip due={due} overdue={overdue} />}
      </div>

      {/* Footer: date + actions */}
      <div className="flex items-center justify-between mt-2.5 pt-2 border-t border-border-light/50">
        <span className="text-2xs text-content-tertiary">{formattedDate}</span>
        <div className="flex items-center gap-0.5">
          {/* Convert to issue / open linked issue */}
          {punchId
            ? onOpenIssue && (
                <button
                  onClick={() => onOpenIssue(punchId)}
                  title={t('markups.openIssue', { defaultValue: 'Open issue' })}
                  data-testid="markup-grid-open-issue"
                  className="p-1 rounded hover:bg-surface-secondary text-green-600 transition-colors"
                >
                  <ClipboardCheck size={13} />
                </button>
              )
            : onConvertToIssue && (
                <button
                  onClick={() => onConvertToIssue(markup)}
                  disabled={isConverting}
                  title={t('markups.convertToIssue', { defaultValue: 'Convert to issue' })}
                  data-testid="markup-grid-convert-to-issue"
                  className="p-1 rounded hover:bg-surface-secondary text-content-tertiary hover:text-oe-blue transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  <ClipboardCheck size={13} />
                </button>
              )}
          <button
            onClick={onEdit}
            title={t('markups.edit', { defaultValue: 'Edit' })}
            className="p-1 rounded hover:bg-surface-secondary text-content-tertiary hover:text-oe-blue transition-colors"
          >
            <Edit3 size={13} />
          </button>
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
  onEdit,
  documentName,
  siblings,
  onNavigate,
  userMap,
  onOpenInDocument,
  onOpenBoqPosition,
  onUseAsQuantity,
  onConvertToIssue,
  onOpenIssue,
  isConverting,
}: {
  markup: Markup;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onChangeStatus: (status: MarkupStatus) => void;
  onDelete: () => void;
  onEdit: () => void;
  documentName?: string;
  siblings?: Markup[];
  onNavigate?: (id: string) => void;
  userMap: Map<string, AssigneeUser>;
  onOpenInDocument?: (markup: Markup) => void;
  onOpenBoqPosition?: (positionId: string) => void;
  onUseAsQuantity?: (markup: Markup) => void;
  onConvertToIssue?: (markup: Markup) => void;
  onOpenIssue?: (punchId: string) => void;
  isConverting?: boolean;
}) {
  const { t } = useTranslation();
  const TypeIcon = TYPE_ICONS[markup.type] ?? PenTool;
  const iconColor = TYPE_COLORS[markup.type] ?? 'text-content-secondary';

  const priority = getMarkupPriority(markup);
  const due = getMarkupDueDate(markup);
  const overdue = isMarkupOverdue(markup);

  const formattedDate = useMemo(() => {
    try {
      return new Date(markup.created_at).toLocaleDateString(getIntlLocale(), {
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
            <span
              className="text-xs text-content-secondary truncate max-w-[130px] block"
              title={documentName || markup.document_id || undefined}
            >
              {markup.document_id
                ? documentName || t('markups.unknown_document', { defaultValue: 'Document' })
                : t('markups.hub_only', { defaultValue: 'Hub' })}
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
        {/* Priority / Due */}
        <td className="px-3 py-2.5">
          {priority || due ? (
            <div className="flex flex-col gap-0.5 items-start">
              {priority && <PriorityChip priority={priority} />}
              {due && <DueChip due={due} overdue={overdue} />}
            </div>
          ) : (
            <span className="text-2xs text-content-tertiary">
              {t('markups.dash', { defaultValue: '-' })}
            </span>
          )}
        </td>
        {/* Assignee */}
        <td className="px-3 py-2.5">
          <AssigneeChip assigneeId={markup.assignee_id} userMap={userMap} />
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
            <button
              onClick={onEdit}
              title={t('markups.edit', { defaultValue: 'Edit' })}
              className="p-1 rounded hover:bg-surface-secondary text-content-tertiary hover:text-oe-blue transition-colors"
            >
              <Edit3 size={14} />
            </button>
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
                <Check size={14} />
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
          <td colSpan={10}>
            <MarkupDetail
              markup={markup}
              documentName={documentName}
              onEdit={onEdit}
              siblings={siblings}
              onNavigate={onNavigate}
              onOpenInDocument={onOpenInDocument}
              onOpenBoqPosition={onOpenBoqPosition}
              onUseAsQuantity={onUseAsQuantity}
              onConvertToIssue={onConvertToIssue}
              onOpenIssue={onOpenIssue}
              isConverting={isConverting}
            />
          </td>
        </tr>
      )}
    </>
  );
}

/* ── Main Page ────────────────────────────────────────────────────────── */

export function MarkupsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // State
  const [searchQuery, setSearchQuery] = useState('');
  const [filterType, setFilterType] = useState<MarkupType | ''>('');
  const [filterStatus, setFilterStatus] = useState<MarkupStatus | ''>('');
  const [filterDocumentId, setFilterDocumentId] = useState('');
  // M3 — assignee filter: "" = no filter, "__unassigned__" = NULL,
  // anything else = user id.
  const [filterAssignee, setFilterAssignee] = useState('');
  // Issue-tracking filters. Priority + overdue live in metadata (not a
  // server-side column), so these are applied client-side over the loaded
  // page window - the same scope as the text search below. "" = no priority
  // filter; ``overdueOnly`` narrows to markups past their due date.
  const [filterPriority, setFilterPriority] = useState<MarkupPriority | ''>('');
  const [overdueOnly, setOverdueOnly] = useState(false);
  // Pagination: how many markups to request. Grows by MARKUPS_PAGE_SIZE
  // each "Load more". Reset back to one page whenever the active filters
  // change so a narrower filter doesn't keep an over-large limit.
  const [limit, setLimit] = useState(MARKUPS_PAGE_SIZE);
  const [showFilters, setShowFilters] = useState(false);
  const [expandedRowId, setExpandedRowId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'list' | 'grid'>('list');
  const [showAddModal, setShowAddModal] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<Markup | null>(null);
  const [annotateDocId, setAnnotateDocId] = useState<string | null>(null);
  const [annotateStamp, setAnnotateStamp] = useState<string | undefined>(undefined);
  // Deep-link target — when set, the annotator pulses a glow ring on
  // this markup id and scrolls it into view. Cleared either by the
  // annotator (after the 2s pulse) or when the user closes it.
  const [highlightMarkupId, setHighlightMarkupId] = useState<string | undefined>(undefined);
  const [annotateInitialPage, setAnnotateInitialPage] = useState<number | undefined>(undefined);
  const [showCustomStampForm, setShowCustomStampForm] = useState(false);
  const [customStampName, setCustomStampName] = useState('');
  const [customStampColor, setCustomStampColor] = useState('#3B82F6');
  // Unified vs hub-only tab. "unified" is the default because the user's
  // primary complaint was that the three modules were disconnected —
  // opening this page and seeing only hub markups reinforced that.
  const [scopeTab, setScopeTab] = useState<'unified' | 'hub'>('unified');
  const onScopeTabKeyDown = useTabKeyboardNav<'unified' | 'hub'>({
    ids: ['unified', 'hub'] as const,
    activeId: scopeTab,
    onChange: setScopeTab,
    orientation: 'horizontal',
  });

  // Deep-link reader — supports both calling conventions:
  //   /markups?openDoc=<id>&page=<n>&markup=<id>   (from the file manager)
  //   /markups?markup=<id>                         (from anywhere with just
  //                                                 the markup id; we'll
  //                                                 fetch the markup, then
  //                                                 derive document + page)
  // Runs once on mount and whenever the params change.
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    const openDoc = searchParams.get('openDoc');
    const markupParam = searchParams.get('markup');
    const pageParam = searchParams.get('page');
    if (!markupParam && !openDoc) return;
    if (openDoc) {
      setFilterDocumentId(openDoc);
      setAnnotateDocId(openDoc);
    }
    if (pageParam) {
      const n = parseInt(pageParam, 10);
      if (Number.isFinite(n) && n > 0) setAnnotateInitialPage(n);
    }
    if (markupParam) {
      setHighlightMarkupId(markupParam);
    }
    // Strip the params from the URL once consumed so a back-button reload
    // doesn't re-trigger the highlight (which would be confusing if the
    // user already dismissed it).
    const next = new URLSearchParams(searchParams);
    next.delete('openDoc');
    next.delete('markup');
    next.delete('page');
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  // Data queries
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Project[]>(),
    staleTime: 5 * 60_000,
  });

  const projectId = activeProjectId || projects[0]?.id || '';

  // M3 — fetch users for the assignee dropdown + row chip.
  // Failures degrade silently to an empty list (the chip falls back to
  // showing the raw user-id slice) so the page still works without
  // /v1/users/ read access (e.g. project viewers without users.read).
  const { data: users = [] } = useQuery({
    queryKey: ['markups', 'users'],
    queryFn: () => fetchUsers({ is_active: true, limit: 200 }).catch(() => [] as AssigneeUser[]),
    staleTime: 5 * 60_000,
  });
  const userMap = useMemo(() => {
    const m = new Map<string, AssigneeUser>();
    for (const u of users) m.set(u.id, u);
    return m;
  }, [users]);

  const { data: documentPage } = useQuery({
    // Share the queryKey with ``useUnifiedMarkups`` (mounted by the
    // ``UnifiedMarkupsList`` tab on this same page) so React Query dedupes
    // the GET /v1/documents/ request — without this both queries fire
    // their own copy. ``staleTime`` matches the hook so the cache window
    // covers re-mounts cleanly.
    queryKey: ['unified-markups', projectId, 'documents'],
    queryFn: () => apiGet<Page<DocItem>>(`/v1/documents/?project_id=${projectId}`),
    enabled: !!projectId,
    staleTime: 60_000,
  });
  const documents = useMemo(() => documentPage?.items ?? [], [documentPage]);

  // When no filters are set the request body is identical to the
  // ``useUnifiedMarkups`` hub query (mounted by the sibling Unified tab).
  // Share the queryKey in that case so React Query dedupes the fetch —
  // otherwise both queries fire their own copy of GET /v1/markups/ on
  // every page open.
  const noFilters = !filterType && !filterStatus && !filterDocumentId && !filterAssignee;
  const isUnassignedFilter = filterAssignee === ASSIGNEE_UNASSIGNED;
  const assigneeIdFilter =
    filterAssignee && !isUnassignedFilter ? filterAssignee : undefined;
  // Only share the deduped hub key on the *first* page with no filters: in
  // that exact case the request is byte-for-byte identical to the sibling
  // ``useUnifiedMarkups`` hub query (no filters, backend default limit), so
  // React Query collapses the two GETs into one. As soon as the user loads
  // more (limit grows) or applies a filter, we switch to a dedicated key so
  // the larger / filtered request can't clobber the shared hub cache.
  const isFirstHubPage = noFilters && limit === MARKUPS_PAGE_SIZE;
  const { data: markups = [], isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: isFirstHubPage
      ? ['unified-markups', projectId, 'hub']
      : ['markups', projectId, filterType, filterStatus, filterDocumentId, filterAssignee, limit],
    queryFn: () =>
      fetchMarkups(projectId, {
        type: filterType || undefined,
        status: filterStatus || undefined,
        document_id: filterDocumentId || undefined,
        assignee_id: assigneeIdFilter,
        unassigned: isUnassignedFilter,
        // Omit the limit param on the shared first-page hub query so the
        // request matches the unified hook exactly (it relies on the
        // backend default). Otherwise request the accumulated page window.
        ...(isFirstHubPage ? {} : { limit }),
      }),
    enabled: !!projectId,
    staleTime: noFilters ? 30_000 : 0,
    // Keep the current rows on-screen while a "Load more" (larger limit)
    // request resolves, instead of flashing the skeleton and losing scroll.
    placeholderData: (prev) => prev,
  });

  // A full page came back, so the server may have more rows beyond what we
  // asked for. ``MARKUPS_PAGE_SIZE`` is the backend default, so an exact
  // multiple is the signal that another page might exist.
  const hasMore = markups.length >= limit;
  const loadMore = useCallback(() => {
    setLimit((prev) => prev + MARKUPS_PAGE_SIZE);
  }, []);

  // Reset the page window whenever the server-side filters change so a
  // narrower filter doesn't carry an over-large limit (and the deduped
  // first-page hub key can re-engage).
  useEffect(() => {
    setLimit(MARKUPS_PAGE_SIZE);
  }, [filterType, filterStatus, filterDocumentId, filterAssignee]);

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

  // Resolve document_id → human name so the table/detail show the
  // filename instead of an opaque UUID slice (was "ab12cd34...").
  const docNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const d of documents) map.set(d.id, d.name);
    return map;
  }, [documents]);

  // Siblings of the currently-expanded markup (same document_id),
  // sorted oldest-first by created_at. Used for ‹ / › chevron nav and
  // ArrowLeft / ArrowRight keyboard shortcuts. Project-level markups
  // (no document_id) share a sibling group keyed on `null`.
  const expandedMarkup = useMemo(
    () => markups.find((m) => m.id === expandedRowId) ?? null,
    [markups, expandedRowId],
  );
  const siblingsForExpanded = useMemo(() => {
    if (!expandedMarkup) return [] as Markup[];
    const docKey = expandedMarkup.document_id ?? null;
    return markups
      .filter((m) => (m.document_id ?? null) === docKey)
      .slice()
      .sort((a, b) => {
        const da = new Date(a.created_at).getTime();
        const db = new Date(b.created_at).getTime();
        return da - db;
      });
  }, [markups, expandedMarkup]);

  // Navigate prev/next inside the expanded detail. We swap
  // ``expandedRowId`` rather than ``navigate('/markups/{id}')`` because
  // this page is single-route — the "detail" is the expanded row pane.
  // Keeps the surrounding scroll position because we never unmount the
  // row.
  const goToMarkup = useCallback(
    (id: string) => {
      setExpandedRowId(id);
    },
    [],
  );

  // Keyboard shortcuts: ← / → step through siblings while a row is
  // expanded. Suppressed when an input/textarea/select/contenteditable
  // owns the focus so typing in the search box keeps working.
  useEffect(() => {
    if (!expandedRowId || siblingsForExpanded.length < 2) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      const ae = document.activeElement as HTMLElement | null;
      const tag = ae?.tagName;
      if (
        tag === 'INPUT' ||
        tag === 'TEXTAREA' ||
        tag === 'SELECT' ||
        ae?.isContentEditable
      ) {
        return;
      }
      const idx = siblingsForExpanded.findIndex((m) => m.id === expandedRowId);
      if (idx < 0) return;
      if (e.key === 'ArrowLeft' && idx > 0) {
        e.preventDefault();
        goToMarkup(siblingsForExpanded[idx - 1]!.id);
      } else if (e.key === 'ArrowRight' && idx < siblingsForExpanded.length - 1) {
        e.preventDefault();
        goToMarkup(siblingsForExpanded[idx + 1]!.id);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [expandedRowId, siblingsForExpanded, goToMarkup]);

  // Client-side filters: text search + priority + overdue. Priority and
  // overdue are metadata-backed (no server column), so they are applied here
  // over whatever page window is loaded, exactly like the text search.
  const filteredMarkups = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q && !filterPriority && !overdueOnly) return markups;
    return markups.filter((m) => {
      if (q) {
        const matchesText =
          (m.label ?? '').toLowerCase().includes(q) ||
          (m.text ?? '').toLowerCase().includes(q) ||
          m.type.toLowerCase().includes(q);
        if (!matchesText) return false;
      }
      if (filterPriority && getMarkupPriority(m) !== filterPriority) return false;
      if (overdueOnly && !isMarkupOverdue(m)) return false;
      return true;
    });
  }, [markups, searchQuery, filterPriority, overdueOnly]);

  // Opens the inline PDF annotator for a markup's source document and
  // tells the annotator to pulse-highlight the markup itself. Falls back
  // to a toast when the markup is project-level (no document_id) so the
  // user doesn't silently click a dead button.
  const handleOpenInDocument = useCallback((markup: Markup) => {
    if (!markup.document_id) {
      addToast({
        type: 'info',
        title: t('markups.no_document_to_open', {
          defaultValue: 'This markup has no source document',
        }),
      });
      return;
    }
    // Auto-pick the document in the top filter so the toolbar reflects
    // what the annotator is showing — small UX nicety, prevents the
    // dropdown from disagreeing with the open document.
    setFilterDocumentId(markup.document_id);
    setAnnotateDocId(markup.document_id);
    setAnnotateInitialPage(markup.page || 1);
    setHighlightMarkupId(markup.id);
    // Scroll the annotator into view — the markups list can be long,
    // and the annotator mounts further down the page.
    requestAnimationFrame(() => {
      const el = document.querySelector('[data-inline-annotator-mount]');
      el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }, [addToast, t]);

  // Deep-link to the BOQ position a markup is linked to. Closes the
  // loop the "Linked BOQ Position" detail used to only describe in text.
  const handleOpenBoqPosition = useCallback(
    (positionId: string) => {
      navigate(`/boq?positionId=${encodeURIComponent(positionId)}`);
    },
    [navigate],
  );

  // Push a measurement markup into PDF Takeoff as a quantity (CONN-67).
  // Takeoff matches its document by filename, which is exactly the document
  // name we already resolve for the row, so we hand it ``docId=<name>`` and
  // open straight on the Measurements tab. The measured value and unit ride
  // along as ``mv`` / ``mu`` so the takeoff "Add measurement" form can
  // pre-fill them (that consumer lands with the takeoff batch); the
  // navigation itself is already useful without it.
  const handleUseAsQuantity = useCallback(
    (markup: Markup) => {
      const params = new URLSearchParams();
      params.set('tab', 'measurements');
      const docName = markup.document_id
        ? docNameById.get(markup.document_id)
        : undefined;
      if (docName) params.set('docId', docName);
      if (markup.measurement_value != null) {
        params.set('mv', String(markup.measurement_value));
      }
      if (markup.measurement_unit) params.set('mu', markup.measurement_unit);
      if (markup.label || markup.text) {
        params.set('mdesc', (markup.label || markup.text) as string);
      }
      navigate(`/takeoff?${params.toString()}`);
    },
    [navigate, docNameById],
  );

  // Invalidation. Includes the unified feed so hub-scope mutations appear
  // in the "All annotations" tab without a manual reload.
  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['markups'] });
    qc.invalidateQueries({ queryKey: ['markups-summary'] });
    qc.invalidateQueries({ queryKey: ['unified-markups'] });
  }, [qc]);

  // Deep-link to a tracked issue on the punch list. Used by the toast CTA
  // after a conversion and by rows whose markup already links to an issue.
  const handleOpenIssue = useCallback(
    (punchId: string) => {
      navigate(`/punchlist?highlight=${encodeURIComponent(punchId)}`);
    },
    [navigate],
  );

  // "Convert to issue" promotes a bare markup into a tracked punch-list
  // item, carrying its drawing location (document + page + 0..1 centroid),
  // label/text, assignee, priority and due date across. Priority uses the
  // same vocabulary on both sides, so it maps 1:1. After the issue is
  // created we stash its id back on the markup's metadata so the row flips
  // to "Open issue" and a duplicate conversion is blocked.
  const convertMut = useMutation({
    mutationFn: async (markup: Markup) => {
      const centroid = computeGeometryCentroid01(markup.geometry);
      const priority = getMarkupPriority(markup);
      const due = getMarkupDueDate(markup);
      const typeLabel = t(`markups.type_${markup.type}`, {
        defaultValue: TYPE_LABELS[markup.type] ?? markup.type,
      });
      const title = (
        markup.label?.trim() ||
        markup.text?.trim() ||
        t('markups.issue_default_title', {
          defaultValue: '{{type}} markup',
          type: typeLabel,
        })
      ).slice(0, 255);
      const payload: CreatePunchPayload = {
        project_id: projectId,
        title,
        ...(markup.text?.trim() ? { description: markup.text.trim() } : {}),
        // Markup priority uses the same vocabulary as PunchPriority, so it
        // maps across 1:1 with no translation.
        ...(priority ? { priority: priority as PunchPriority } : {}),
        ...(markup.assignee_id ? { assigned_to: markup.assignee_id } : {}),
        ...(due ? { due_date: due } : {}),
        ...(markup.document_id ? { document_id: markup.document_id } : {}),
        ...(markup.page ? { page: markup.page } : {}),
        ...(centroid ? { location_x: centroid.x, location_y: centroid.y } : {}),
      };
      const punch = await createPunchItem(payload);
      // Link-back is best-effort: the issue already exists, so a failed
      // metadata patch must not surface as a conversion failure.
      try {
        await updateMarkup(markup.id, { metadata: { punch_item_id: punch.id } });
      } catch {
        /* non-fatal: punch created; link-back can be retried on next edit */
      }
      return punch;
    },
    onSuccess: (punch) => {
      invalidateAll();
      addToast(
        {
          type: 'success',
          title: t('markups.issue_created', {
            defaultValue: 'Issue created from markup',
          }),
          message: punch.title,
          action: {
            label: t('markups.openIssue', { defaultValue: 'Open issue' }),
            onClick: () => handleOpenIssue(punch.id),
          },
        },
        { duration: 8000 },
      );
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const handleConvertToIssue = useCallback(
    (markup: Markup) => {
      if (!projectId || getMarkupPunchId(markup)) return;
      convertMut.mutate(markup);
    },
    [projectId, convertMut],
  );

  // Id of the markup whose conversion is currently in flight (for per-row
  // spinner / disabled state). ``variables`` is the markup passed to mutate.
  const convertingId = convertMut.isPending ? convertMut.variables?.id ?? null : null;

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

  // Module Insights - the toggleable visualization panel for this module. Its
  // charts are built client-side from the markups already loaded; when there
  // are none the panel draws nothing rather than inventing rows to fill it.
  // Open state and any user-built charts persist per module via
  // useModuleInsights. Declared among the top hooks so the hook order stays
  // stable.
  const insights = useModuleInsights('markups', { defaultOpen: true });
  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildMarkupsInsights(markups, '', t),
    [markups, t],
  );

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          ...(activeProjectId
            ? (() => {
                const name = projects.find((p) => p.id === activeProjectId)?.name;
                return name ? [{ label: name, to: `/projects/${activeProjectId}` }] : [];
              })()
            : []),
          { label: t('nav.markups', { defaultValue: 'Markups' }) },
        ]}
      />

      {/* ── Header (canonical top block) ─────────────────────────────────── */}
      <PageHeader
        srTitle={t('nav.markups', { defaultValue: 'Markups' })}
        subtitle={t('markups.subtitle', {
          defaultValue:
            'Review annotations - clouds, arrows, stamps and measurements placed on project documents.',
        })}
        actions={
          <>
            {/* Insights toggle - shows or hides this module's visualization
                panel. Leads the cluster so charts are one obvious click away. */}
            <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
            <ModuleGuideButton content={markupsGuide} />
            <IssueHubLink />

            {/* Document selector — a within-project entity picker, stays. */}
            {projectId && (
              <select
                value={filterDocumentId}
                onChange={(e) => setFilterDocumentId(e.target.value)}
                className={selectCls + ' max-w-[140px]'}
                aria-label={t('markups.document', { defaultValue: 'Document' })}
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

            {/* Compare revisions — opens the PDF overlay / visual-diff view */}
            {projectId && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  const params = new URLSearchParams();
                  if (filterDocumentId) params.set('docA', filterDocumentId);
                  navigate(`/markups/compare${params.toString() ? `?${params.toString()}` : ''}`);
                }}
                className="shrink-0 whitespace-nowrap"
                title={t('markups.compare_revisions', { defaultValue: 'Compare revisions' })}
              >
                <GitCompare size={14} />
                <span className="hidden lg:inline ml-1">
                  {t('markups.compare_revisions', { defaultValue: 'Compare' })}
                </span>
              </Button>
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
          </>
        }
      />

      {/* The document filter above, and the document names on the rows below,
          both come from one page of the register. Past that page a markup
          shows a bare id and its document cannot be selected in the filter,
          so the page says how much of the register it holds. */}
      {documentPage ? <TruncationNotice page={documentPage} className="mb-2" /> : null}

      {/* Module Insights panel - toggled by the header button. Placed high,
          outside the project gate, so its charts are visible the moment the
          page opens. */}
      <InsightsPanel
        open={insights.open}
        title={t('markups.insights.title', { defaultValue: 'Markup insights' })}
        datasets={insightDatasets}
        builtins={insightBuiltins}
        custom={insights.custom}
        onAdd={insights.addCustom}
        onUpdate={insights.updateCustom}
        onRemove={insights.removeCustom}
        onCollapse={() => insights.setOpen(false)}
      />

      {/* Project gate */}
      {!projectId ? (
        <div className="mt-10">
          <RequiresProject
            emptyHint={t('markups.no_project_desc', {
              defaultValue:
                'Select a project from the dropdown to view markups and annotations. You can create markups on document pages, add measurements, and track review status.',
            })}
          >{null}</RequiresProject>
        </div>
      ) : (
        <>
          {/* ── Purpose intro (canonical DismissibleInfo) ─────────────────── */}
          <DismissibleInfo
            storageKey="markups"
            title={t('markups.intro_title', {
              defaultValue: 'Drawing comments that do not get lost',
            })}
            more={t('markups.intro_more', { defaultValue: '' }) ? <IntroRichText text={t('markups.intro_more')} /> : undefined}
            links={[
              {
                label: t('markups.compare_revisions', { defaultValue: 'Compare' }),
                onClick: () => navigate('/markups/compare'),
              },
            ]}
          >
            {t('markups.intro_body', {
              defaultValue:
                'Add clouds, arrows, text, stamps and distance, area or count measurements onto project PDFs, assign them to a person and track each one through active, resolved and archived. Open a markup straight on its source drawing in the inline annotator, or push it through an approval route. Export the lot to CSV, and jump to Compare to check two revisions side by side.',
            })}
          </DismissibleInfo>

          {/* ── Stats Bar ──────────────────────────────────────────────────── */}
          <div>
            <StatsBar summary={summary} />
          </div>

          {/* ── Scope Tabs (Unified / Hub only) ───────────────────────────── */}
          <div
            className="inline-flex items-center rounded-lg border border-border-light bg-surface-primary p-0.5"
            role="tablist"
            aria-label={t('markups.scope_tabs', { defaultValue: 'Annotation scope' })}
            onKeyDown={onScopeTabKeyDown}
          >
            <button
              type="button"
              role="tab"
              id="markups-scope-tab-unified"
              aria-selected={scopeTab === 'unified'}
              aria-controls="markups-scope-panel-unified"
              tabIndex={scopeTab === 'unified' ? 0 : -1}
              onClick={() => setScopeTab('unified')}
              data-testid="markups-tab-unified"
              className={clsx(
                'px-3 py-1.5 text-xs font-medium rounded-md transition-colors',
                scopeTab === 'unified'
                  ? 'bg-oe-blue text-content-inverse'
                  : 'text-content-secondary hover:bg-surface-secondary',
              )}
            >
              {t('markups.scope_unified', { defaultValue: 'All annotations' })}
            </button>
            <button
              type="button"
              role="tab"
              id="markups-scope-tab-hub"
              aria-selected={scopeTab === 'hub'}
              aria-controls="markups-scope-panel-hub"
              tabIndex={scopeTab === 'hub' ? 0 : -1}
              onClick={() => setScopeTab('hub')}
              data-testid="markups-tab-hub"
              className={clsx(
                'px-3 py-1.5 text-xs font-medium rounded-md transition-colors',
                scopeTab === 'hub'
                  ? 'bg-oe-blue text-content-inverse'
                  : 'text-content-secondary hover:bg-surface-secondary',
              )}
            >
              {t('markups.scope_hub_only', { defaultValue: 'Hub only' })}
            </button>
          </div>

          {/* ── Inline PDF Annotator ──────────────────────────────────────── */}
          {annotateDocId && (
            <div data-inline-annotator-mount>
              <InlinePdfAnnotator
                documentId={annotateDocId}
                documentName={documents.find((d) => d.id === annotateDocId)?.name || 'Document'}
                projectId={projectId}
                onClose={() => {
                  setAnnotateDocId(null);
                  setAnnotateStamp(undefined);
                  setHighlightMarkupId(undefined);
                  setAnnotateInitialPage(undefined);
                }}
                onMarkupCreated={invalidateAll}
                activeStamp={annotateStamp}
                highlightMarkupId={highlightMarkupId}
                initialPage={annotateInitialPage}
              />
            </div>
          )}

          {/* ── Unified Feed (all three sources) ──────────────────────────── */}
          {scopeTab === 'unified' && (
            <div>
              <UnifiedMarkupsList projectId={projectId} />
            </div>
          )}

          {/* ── Filter / Search / View Toggle (hub-only view) ─────────────── */}
          {scopeTab === 'hub' && (
          <>
          <div className="flex items-center gap-2 flex-wrap">
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

              {/* M3: assignee filter */}
              <select
                value={filterAssignee}
                onChange={(e) => setFilterAssignee(e.target.value)}
                className={selectCls + ' max-w-[180px]'}
                aria-label={t('markups.filterByAssignee', { defaultValue: 'Filter by assignee' })}
                data-testid="markups-filter-assignee"
              >
                <option value="">
                  {t('markups.all_assignees', { defaultValue: 'All Assignees' })}
                </option>
                <option value={ASSIGNEE_UNASSIGNED}>
                  {t('markups.unassigned', { defaultValue: 'Unassigned' })}
                </option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.full_name?.trim() || u.email}
                  </option>
                ))}
              </select>

              {/* Priority filter (client-side, metadata-backed) */}
              <select
                value={filterPriority}
                onChange={(e) => setFilterPriority(e.target.value as MarkupPriority | '')}
                className={selectCls + ' max-w-[150px]'}
                aria-label={t('markups.filterByPriority', { defaultValue: 'Filter by priority' })}
                data-testid="markups-filter-priority"
              >
                <option value="">
                  {t('markups.all_priorities', { defaultValue: 'All Priorities' })}
                </option>
                {MARKUP_PRIORITIES.map((p) => (
                  <option key={p} value={p}>
                    {t(`markups.priority_${p}`, { defaultValue: PRIORITY_LABELS[p] })}
                  </option>
                ))}
              </select>

              {/* Overdue toggle (client-side, metadata-backed) */}
              <button
                type="button"
                onClick={() => setOverdueOnly((v) => !v)}
                aria-pressed={overdueOnly}
                data-testid="markups-filter-overdue"
                className={clsx(
                  'inline-flex items-center gap-1 h-8 px-2.5 rounded-lg border text-xs font-medium transition-colors',
                  overdueOnly
                    ? 'border-semantic-error/40 bg-semantic-error/10 text-semantic-error'
                    : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary',
                )}
                title={t('markups.overdueOnlyHint', {
                  defaultValue: 'Show only markups past their due date',
                })}
              >
                <AlertTriangle size={13} />
                {t('markups.overdue_only', { defaultValue: 'Overdue' })}
              </button>

              {(filterType || filterStatus || filterAssignee || filterPriority || overdueOnly) && (
                <button
                  onClick={() => {
                    setFilterType('');
                    setFilterStatus('');
                    setFilterAssignee('');
                    setFilterPriority('');
                    setOverdueOnly(false);
                  }}
                  className="text-xs text-oe-blue hover:underline"
                >
                  {t('markups.clear_filters', { defaultValue: 'Clear' })}
                </button>
              )}
            </div>
          )}

          {/* ── Main Content ───────────────────────────────────────────────── */}
          <div>
            {isLoading ? (
              <SkeletonTable rows={6} columns={4} />
            ) : isError ? (
              <RecoveryCard error={error} onRetry={() => refetch()} />
            ) : filteredMarkups.length === 0 ? (
              (() => {
                // "No match" (a filter is narrowing the result) vs "empty"
                // (nothing exists yet). Includes the client-side priority /
                // overdue filters so a narrowed-to-zero view offers "adjust
                // your criteria" rather than "add your first markup".
                const narrowed = !!(
                  searchQuery ||
                  filterType ||
                  filterStatus ||
                  filterAssignee ||
                  filterPriority ||
                  overdueOnly
                );
                return (
                  <EmptyState
                    icon={<PenTool size={28} strokeWidth={1.5} />}
                    title={
                      narrowed
                        ? t('markups.no_match_title', { defaultValue: 'No matching markups' })
                        : t('markups.empty_title', { defaultValue: 'No markups yet' })
                    }
                    description={
                      narrowed
                        ? t('markups.no_match_desc', {
                            defaultValue: 'Try adjusting your search or filter criteria.',
                          })
                        : t('markups.empty_desc', {
                            defaultValue:
                              'Create your first markup to start annotating documents. Use clouds, arrows, text, and measurement tools to collaborate with your team.',
                          })
                    }
                    action={
                      narrowed
                        ? undefined
                        : {
                            label: t('markups.add_first', { defaultValue: 'Add First Markup' }),
                            onClick: () => setShowAddModal(true),
                          }
                    }
                  />
                );
              })()
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
                        <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[120px]">
                          {t('markups.col_priority', { defaultValue: 'Priority' })}
                        </th>
                        <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[140px]">
                          {t('markups.col_assignee', { defaultValue: 'Assignee' })}
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
                          documentName={
                            markup.document_id
                              ? docNameById.get(markup.document_id)
                              : undefined
                          }
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
                          onEdit={() => setEditTarget(markup)}
                          siblings={
                            expandedRowId === markup.id
                              ? siblingsForExpanded
                              : undefined
                          }
                          onNavigate={goToMarkup}
                          userMap={userMap}
                          onOpenInDocument={handleOpenInDocument}
                          onOpenBoqPosition={handleOpenBoqPosition}
                          onUseAsQuantity={handleUseAsQuantity}
                          onConvertToIssue={handleConvertToIssue}
                          onOpenIssue={handleOpenIssue}
                          isConverting={convertingId === markup.id}
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
                    onEdit={() => setEditTarget(markup)}
                    userMap={userMap}
                    onConvertToIssue={handleConvertToIssue}
                    onOpenIssue={handleOpenIssue}
                    isConverting={convertingId === markup.id}
                  />
                ))}
              </div>
            )}

            {/* ── Load more ──────────────────────────────────────────────── */}
            {!isLoading && !isError && hasMore && filteredMarkups.length > 0 && (
              <div className="mt-3 flex flex-col items-center gap-1">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={loadMore}
                  loading={isFetching}
                >
                  {t('markups.load_more', { defaultValue: 'Load more' })}
                </Button>
                <span className="text-2xs text-content-tertiary">
                  {t('markups.showing_count', {
                    defaultValue: 'Showing {{count}} markups',
                    count: markups.length,
                  })}
                </span>
              </div>
            )}
          </div>
          </>
          )}

          {/* ── Stamps (inline badges row) ─────────────────────────────────── */}
          {displayStamps.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
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
        users={users}
        onCreated={invalidateAll}
      />

      {/* ── Edit Markup Modal ──────────────────────────────────────────── */}
      <EditMarkupModal
        open={editTarget !== null}
        markup={editTarget}
        projectId={projectId}
        onClose={() => setEditTarget(null)}
        onUpdated={invalidateAll}
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
