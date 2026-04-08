import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, Link } from 'react-router-dom';
import clsx from 'clsx';
import {
  CalendarDays,
  Search,
  Plus,
  X,
  ChevronDown,
  ChevronRight,
  Users,
  CheckCircle2,
  Circle,
  XCircle,
  Clock,
  FileDown,
  FileUp,
  Loader2,
  Upload,
  ListChecks,
  Edit3,
  Trash2,
  ArrowLeft,
  Sparkles,
  AlertCircle,
  BarChart3,
  PenTool,
  HardHat,
  Rocket,
  MapPin,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb, ConfirmDialog, SkeletonTable } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { apiGet, triggerDownload } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  fetchMeetings,
  createMeeting,
  completeMeeting,
  importMeetingSummary,
  importMeetingSummaryPreview,
  type Meeting,
  type MeetingType,
  type MeetingStatus,
  type CreateMeetingPayload,
  type AttendeeStatus,
  type ImportPreviewResponse,
  type ImportPreviewAttendee,
  type ImportPreviewActionItem,
} from './api';

/* -- Constants ------------------------------------------------------------- */

interface Project {
  id: string;
  name: string;
}

const MEETING_TYPE_COLORS: Record<
  MeetingType,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  progress: 'blue',
  design: 'neutral',
  safety: 'error',
  subcontractor: 'warning',
  kickoff: 'success',
  closeout: 'neutral',
};

const STATUS_CONFIG: Record<
  MeetingStatus,
  { variant: 'neutral' | 'blue' | 'success' | 'error' | 'warning'; cls: string }
> = {
  scheduled: { variant: 'blue', cls: '' },
  in_progress: { variant: 'warning', cls: '' },
  completed: { variant: 'success', cls: '' },
  cancelled: {
    variant: 'neutral',
    cls: 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
  },
};

const ATTENDEE_STATUS_ICON: Record<AttendeeStatus, React.ReactNode> = {
  present: <CheckCircle2 size={14} className="text-semantic-success" />,
  absent: <XCircle size={14} className="text-semantic-error" />,
  excused: <Circle size={14} className="text-content-tertiary" />,
};

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const MEETING_TYPES: MeetingType[] = [
  'progress',
  'design',
  'safety',
  'subcontractor',
  'kickoff',
  'closeout',
];

const MEETING_TYPE_CARD_CONFIG: Record<
  MeetingType,
  { icon: React.ElementType; color: string; description: string }
> = {
  progress: {
    icon: BarChart3,
    color:
      'text-blue-600 bg-blue-50 border-blue-200 dark:text-blue-400 dark:bg-blue-950/30 dark:border-blue-800',
    description: 'Regular project progress review',
  },
  design: {
    icon: PenTool,
    color:
      'text-purple-600 bg-purple-50 border-purple-200 dark:text-purple-400 dark:bg-purple-950/30 dark:border-purple-800',
    description: 'Design coordination meeting',
  },
  safety: {
    icon: HardHat,
    color:
      'text-red-600 bg-red-50 border-red-200 dark:text-red-400 dark:bg-red-950/30 dark:border-red-800',
    description: 'Safety toolbox talk / review',
  },
  subcontractor: {
    icon: Users,
    color:
      'text-amber-600 bg-amber-50 border-amber-200 dark:text-amber-400 dark:bg-amber-950/30 dark:border-amber-800',
    description: 'Subcontractor coordination',
  },
  kickoff: {
    icon: Rocket,
    color:
      'text-green-600 bg-green-50 border-green-200 dark:text-green-400 dark:bg-green-950/30 dark:border-green-800',
    description: 'Project kickoff',
  },
  closeout: {
    icon: CheckCircle2,
    color:
      'text-gray-600 bg-gray-50 border-gray-200 dark:text-gray-400 dark:bg-gray-800/50 dark:border-gray-700',
    description: 'Project closeout / handover',
  },
};

const MEETING_STATUSES: MeetingStatus[] = ['scheduled', 'in_progress', 'completed', 'cancelled'];

/* -- Create Meeting Modal -------------------------------------------------- */

interface MeetingFormData {
  title: string;
  meeting_type: MeetingType;
  date: string;
  location: string;
  chairperson: string;
  attendees: string;
}

const todayStr = () => {
  const now = new Date();
  // Format as YYYY-MM-DDTHH:mm for datetime-local
  const pad = (n: number) => n.toString().padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
};

const EMPTY_FORM: MeetingFormData = {
  title: '',
  meeting_type: 'progress',
  date: '',
  location: '',
  chairperson: '',
  attendees: '',
};

function CreateMeetingModal({
  onClose,
  onSubmit,
  isPending,
  projectName,
}: {
  onClose: () => void;
  onSubmit: (data: MeetingFormData) => void;
  isPending: boolean;
  projectName?: string;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<MeetingFormData>({ ...EMPTY_FORM, date: todayStr() });
  const [touched, setTouched] = useState(false);

  const set = <K extends keyof MeetingFormData>(key: K, value: MeetingFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const titleError = touched && form.title.trim().length === 0;
  const dateError = touched && form.date.trim().length === 0;
  const canSubmit = form.title.trim().length > 0 && form.date.trim().length > 0;

  const handleSubmit = () => {
    setTouched(true);
    if (canSubmit) onSubmit(form);
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-2xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('meetings.new_meeting', { defaultValue: 'New Meeting' })}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div>
            <h2 className="text-lg font-semibold text-content-primary">
              {t('meetings.new_meeting', { defaultValue: 'New Meeting' })}
            </h2>
            {projectName && (
              <p className="text-xs text-content-tertiary mt-0.5">
                {t('common.creating_in_project', {
                  defaultValue: 'In {{project}}',
                  project: projectName,
                })}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Form */}
        <div className="px-6 py-4 space-y-5">
          {/* ── Meeting Type ── */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-2">
              {t('meetings.field_type', { defaultValue: 'Meeting Type' })}
            </label>
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
              {MEETING_TYPES.map((mt) => {
                const cfg = MEETING_TYPE_CARD_CONFIG[mt];
                const TypeIcon = cfg.icon;
                const selected = form.meeting_type === mt;
                return (
                  <button
                    key={mt}
                    type="button"
                    onClick={() => set('meeting_type', mt)}
                    className={clsx(
                      'flex flex-col items-center gap-1.5 rounded-lg border-2 px-2 py-2.5 text-center transition-all',
                      selected
                        ? cfg.color + ' ring-2 ring-oe-blue/30'
                        : 'border-border bg-surface-primary text-content-tertiary hover:border-border-light hover:bg-surface-secondary',
                    )}
                  >
                    <TypeIcon size={18} />
                    <span className="text-2xs font-medium leading-tight">
                      {t(`meetings.type_${mt}`, {
                        defaultValue: mt.charAt(0).toUpperCase() + mt.slice(1),
                      })}
                    </span>
                  </button>
                );
              })}
            </div>
            <p className="mt-1.5 text-xs text-content-quaternary">
              {t(`meetings.type_${form.meeting_type}_desc`, {
                defaultValue: MEETING_TYPE_CARD_CONFIG[form.meeting_type].description,
              })}
            </p>
          </div>

          {/* ── Meeting Details Section ── */}
          <div className="flex items-center gap-2 pt-2 pb-1">
            <CalendarDays size={14} className="text-content-tertiary" />
            <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('meetings.section_details', { defaultValue: 'Meeting Details' })}
            </span>
            <div className="flex-1 h-px bg-border-light" />
          </div>

          {/* Title */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('meetings.field_title', { defaultValue: 'Title' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              value={form.title}
              onChange={(e) => {
                set('title', e.target.value);
                setTouched(true);
              }}
              placeholder={t('meetings.title_placeholder', {
                defaultValue: 'e.g. Weekly Progress Meeting #12',
              })}
              className={clsx(
                inputCls,
                titleError &&
                  'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
              )}
              autoFocus
            />
            {titleError && (
              <p className="mt-1 text-xs text-semantic-error">
                {t('meetings.title_required', { defaultValue: 'Title is required' })}
              </p>
            )}
          </div>

          {/* ── Schedule Section ── */}
          <div className="flex items-center gap-2 pt-2 pb-1">
            <Clock size={14} className="text-content-tertiary" />
            <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('meetings.section_schedule', { defaultValue: 'Schedule' })}
            </span>
            <div className="flex-1 h-px bg-border-light" />
          </div>

          {/* Date */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('meetings.field_date', { defaultValue: 'Date & Time' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              type="datetime-local"
              value={form.date}
              onChange={(e) => {
                set('date', e.target.value);
                setTouched(true);
              }}
              className={clsx(
                inputCls,
                dateError &&
                  'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
              )}
            />
            {dateError && (
              <p className="mt-1 text-xs text-semantic-error">
                {t('meetings.date_required', { defaultValue: 'Date is required' })}
              </p>
            )}
          </div>

          {/* ── Location Section ── */}
          <div className="flex items-center gap-2 pt-2 pb-1">
            <MapPin size={14} className="text-content-tertiary" />
            <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('meetings.section_location', { defaultValue: 'Location' })}
            </span>
            <div className="flex-1 h-px bg-border-light" />
          </div>

          {/* Location */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('meetings.field_location', { defaultValue: 'Location' })}
            </label>
            <input
              value={form.location}
              onChange={(e) => set('location', e.target.value)}
              className={inputCls}
              placeholder={t('meetings.location_placeholder', {
                defaultValue: 'e.g., Site office, Room 301, Online',
              })}
            />
          </div>

          {/* Chairperson */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('meetings.field_chairperson', { defaultValue: 'Chairperson' })}
            </label>
            <input
              value={form.chairperson}
              onChange={(e) => set('chairperson', e.target.value)}
              className={inputCls}
              placeholder={t('meetings.chairperson_placeholder', {
                defaultValue: 'Meeting organizer',
              })}
            />
          </div>

          {/* Attendees */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('meetings.field_attendees', { defaultValue: 'Attendees' })}
            </label>
            <textarea
              value={form.attendees}
              onChange={(e) => set('attendees', e.target.value)}
              rows={3}
              className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
              placeholder={t('meetings.attendees_placeholder', {
                defaultValue: 'One name per line',
              })}
            />
            <p className="mt-1 text-xs text-content-quaternary">
              {t('meetings.attendees_hint', {
                defaultValue: 'Enter each attendee on a separate line. They will be added to the meeting.',
              })}
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending}>
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : (
              <Plus size={16} className="mr-1.5 shrink-0" />
            )}
            <span>{t('meetings.create_meeting', { defaultValue: 'Create Meeting' })}</span>
          </Button>
        </div>
      </div>
    </div>
  );
}

/* -- Import Summary Modal -------------------------------------------------- */

const ACCEPTED_TRANSCRIPT_FORMATS = '.txt,.vtt,.srt,.docx,.pdf';

const SOURCE_LABELS: Record<string, { label: string; cls: string }> = {
  teams: {
    label: 'Microsoft Teams',
    cls: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  },
  google_meet: {
    label: 'Google Meet',
    cls: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  },
  zoom: {
    label: 'Zoom',
    cls: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400',
  },
  webex: {
    label: 'Cisco Webex',
    cls: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  },
  other: {
    label: 'Other',
    cls: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  },
};

type ImportStep = 'upload' | 'processing' | 'preview';

function ImportSummaryModal({
  onClose,
  onImport,
  isPending,
  projectId,
}: {
  onClose: () => void;
  onImport: (file: File) => void;
  isPending: boolean;
  projectId: string;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [step, setStep] = useState<ImportStep>('upload');
  const [processingStage, setProcessingStage] = useState('');
  const [previewData, setPreviewData] = useState<ImportPreviewResponse | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  // Editable preview state
  const [editTitle, setEditTitle] = useState('');
  const [editMeetingType, setEditMeetingType] = useState<MeetingType>('progress');
  const [editAttendees, setEditAttendees] = useState<(ImportPreviewAttendee & { included: boolean })[]>([]);
  const [editActionItems, setEditActionItems] = useState<(ImportPreviewActionItem & { included: boolean })[]>([]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) setSelectedFile(file);
    },
    [],
  );

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) setSelectedFile(file);
  }, []);

  const detectSource = (filename: string): string => {
    const lower = filename.toLowerCase();
    if (lower.includes('teams') || lower.includes('microsoft')) return 'teams';
    if (lower.includes('meet') || lower.includes('google')) return 'google_meet';
    if (lower.includes('zoom')) return 'zoom';
    if (lower.includes('webex') || lower.includes('cisco')) return 'webex';
    return 'other';
  };

  // Preview extraction
  const handleExtractPreview = useCallback(async () => {
    if (!selectedFile || !projectId) return;
    setStep('processing');
    setPreviewError(null);
    setProcessingStage(t('meetings.stage_parsing', { defaultValue: 'Parsing transcript...' }));
    try {
      // Short delay to show the "Parsing" stage visually
      await new Promise((r) => setTimeout(r, 300));
      setProcessingStage(t('meetings.stage_extracting', { defaultValue: 'Extracting with AI...' }));
      const data = await importMeetingSummaryPreview(projectId, selectedFile);
      setPreviewData(data);
      setEditTitle(data.title);
      setEditMeetingType(data.meeting_type as MeetingType);
      setEditAttendees(
        data.attendees.map((a) => ({ ...a, included: true })),
      );
      setEditActionItems(
        data.action_items.map((a) => ({ ...a, included: true })),
      );
      setProcessingStage(t('meetings.stage_done', { defaultValue: 'Done' }));
      setStep('preview');
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Preview extraction failed';
      setPreviewError(msg);
      setStep('upload');
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: msg });
    }
  }, [selectedFile, projectId, t, addToast]);

  const handleBackToUpload = useCallback(() => {
    setStep('upload');
    setPreviewData(null);
    setPreviewError(null);
  }, []);

  const handleRemoveActionItem = useCallback((idx: number) => {
    setEditActionItems((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const handleToggleAttendee = useCallback((idx: number) => {
    setEditAttendees((prev) =>
      prev.map((a, i) => (i === idx ? { ...a, included: !a.included } : a)),
    );
  }, []);

  const handleToggleActionItem = useCallback((idx: number) => {
    setEditActionItems((prev) =>
      prev.map((a, i) => (i === idx ? { ...a, included: !a.included } : a)),
    );
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const detectedSource = selectedFile ? detectSource(selectedFile.name) : null;
  const sourceCfg = detectedSource ? SOURCE_LABELS[detectedSource] || SOURCE_LABELS.other : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-2xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('meetings.import_summary', { defaultValue: 'Import Meeting Summary' })}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div className="flex items-center gap-3">
            {step === 'preview' && (
              <button
                onClick={handleBackToUpload}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
                aria-label={t('common.back', { defaultValue: 'Back' })}
              >
                <ArrowLeft size={18} />
              </button>
            )}
            <h2 className="text-lg font-semibold text-content-primary">
              {step === 'preview'
                ? t('meetings.review_import', { defaultValue: 'Review Extracted Data' })
                : t('meetings.import_summary', { defaultValue: 'Import Meeting Summary' })}
            </h2>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Step: Upload */}
        {step === 'upload' && (
          <>
            <div className="px-6 py-4 space-y-4">
              <p className="text-sm text-content-secondary">
                {t('meetings.import_description', {
                  defaultValue:
                    'Upload a meeting transcript from Microsoft Teams, Google Meet, Zoom, or any other source. AI will extract attendees, agenda, action items, and decisions.',
                })}
              </p>

              {/* Drop zone */}
              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                className={clsx(
                  'border-2 border-dashed rounded-xl p-8 text-center transition-colors cursor-pointer',
                  dragOver
                    ? 'border-oe-blue bg-oe-blue-subtle'
                    : selectedFile
                      ? 'border-semantic-success bg-green-50 dark:bg-green-950/20'
                      : 'border-border-light hover:border-oe-blue hover:bg-surface-secondary',
                )}
                onClick={() => document.getElementById('transcript-file-input')?.click()}
              >
                <input
                  id="transcript-file-input"
                  type="file"
                  accept={ACCEPTED_TRANSCRIPT_FORMATS}
                  className="hidden"
                  onChange={handleFileSelect}
                />

                {selectedFile ? (
                  <div className="space-y-2">
                    <CheckCircle2 size={32} className="mx-auto text-semantic-success" />
                    <p className="text-sm font-medium text-content-primary">{selectedFile.name}</p>
                    <p className="text-xs text-content-tertiary">
                      {(selectedFile.size / 1024).toFixed(1)} KB
                    </p>
                    {sourceCfg && (
                      <Badge variant="neutral" size="sm" className={sourceCfg.cls}>
                        {t('meetings.detected_source', { defaultValue: 'Detected: {{source}}', source: sourceCfg.label })}
                      </Badge>
                    )}
                  </div>
                ) : (
                  <div className="space-y-2">
                    <Upload size={32} className="mx-auto text-content-tertiary" />
                    <p className="text-sm font-medium text-content-secondary">
                      {t('meetings.drop_transcript', {
                        defaultValue: 'Drop transcript file here or click to browse',
                      })}
                    </p>
                    <p className="text-xs text-content-tertiary">
                      {t('meetings.accepted_formats', {
                        defaultValue: 'Accepted formats: .txt, .vtt, .srt, .docx, .pdf',
                      })}
                    </p>
                  </div>
                )}
              </div>

              {/* Error display */}
              {previewError && (
                <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-950/30 p-3">
                  <AlertCircle size={16} className="text-semantic-error mt-0.5 shrink-0" />
                  <p className="text-sm text-semantic-error">{previewError}</p>
                </div>
              )}

              {/* Format hints */}
              <div className="rounded-lg bg-surface-secondary p-3">
                <p className="text-xs text-content-tertiary font-medium uppercase tracking-wide mb-2">
                  {t('meetings.supported_sources', { defaultValue: 'Supported Sources' })}
                </p>
                <div className="flex flex-wrap gap-2">
                  {Object.values(SOURCE_LABELS).map((s) => (
                    <Badge key={s.label} variant="neutral" size="sm" className={s.cls}>
                      {s.label}
                    </Badge>
                  ))}
                </div>
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
              <Button variant="ghost" onClick={onClose}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                onClick={handleExtractPreview}
                disabled={!selectedFile}
              >
                <FileUp size={16} className="mr-1.5 shrink-0" />
                <span>{t('meetings.extract_preview', { defaultValue: 'Extract & Preview' })}</span>
              </Button>
            </div>
          </>
        )}

        {/* Step: Processing */}
        {step === 'processing' && (
          <div className="px-6 py-12 flex flex-col items-center gap-4">
            <Loader2 size={40} className="animate-spin text-oe-blue" />
            <div className="text-center space-y-1">
              <p className="text-sm font-medium text-content-primary">{processingStage}</p>
              <p className="text-xs text-content-tertiary">
                {t('meetings.processing_hint', { defaultValue: 'This may take a few seconds...' })}
              </p>
            </div>
            {/* Processing stages indicator */}
            <div className="flex items-center gap-2 mt-2">
              {[
                t('meetings.stage_parsing', { defaultValue: 'Parsing' }),
                t('meetings.stage_ai', { defaultValue: 'AI Extract' }),
                t('meetings.stage_done', { defaultValue: 'Done' }),
              ].map((label, idx) => {
                const currentIdx = processingStage.toLowerCase().includes('parsing')
                  ? 0
                  : processingStage.toLowerCase().includes('extract') || processingStage.toLowerCase().includes('ai')
                    ? 1
                    : 2;
                const isActive = idx <= currentIdx;
                return (
                  <React.Fragment key={label}>
                    {idx > 0 && (
                      <div className={clsx('h-0.5 w-6 rounded', isActive ? 'bg-oe-blue' : 'bg-border-light')} />
                    )}
                    <div className={clsx(
                      'text-2xs px-2 py-0.5 rounded-full font-medium',
                      isActive
                        ? 'bg-oe-blue/10 text-oe-blue'
                        : 'bg-surface-secondary text-content-tertiary',
                    )}>
                      {label}
                    </div>
                  </React.Fragment>
                );
              })}
            </div>
          </div>
        )}

        {/* Step: Preview */}
        {step === 'preview' && previewData && (
          <>
            <div className="px-6 py-4 space-y-4 max-h-[60vh] overflow-y-auto">
              {/* AI indicator */}
              {previewData.ai_enhanced && (
                <div className="flex items-center gap-2 rounded-lg bg-purple-50 dark:bg-purple-950/20 border border-purple-200 dark:border-purple-800 px-3 py-2">
                  <Sparkles size={14} className="text-purple-600 dark:text-purple-400" />
                  <span className="text-xs font-medium text-purple-700 dark:text-purple-300">
                    {t('meetings.ai_enhanced', { defaultValue: 'AI-enhanced extraction' })}
                  </span>
                </div>
              )}

              {/* Source badge */}
              {previewData.source && SOURCE_LABELS[previewData.source] && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-content-tertiary">
                    {t('meetings.label_source', { defaultValue: 'Source:' })}
                  </span>
                  <Badge
                    variant="neutral"
                    size="sm"
                    className={SOURCE_LABELS[previewData.source]?.cls || ''}
                  >
                    {SOURCE_LABELS[previewData.source]?.label || previewData.source}
                  </Badge>
                  <span className="text-xs text-content-tertiary ml-auto">
                    {t('meetings.segments_count', {
                      defaultValue: '{{count}} segments parsed',
                      count: previewData.segments_parsed,
                    })}
                  </span>
                </div>
              )}

              {/* Title (editable) */}
              <div>
                <label className="block text-xs font-medium text-content-tertiary mb-1 uppercase tracking-wide">
                  {t('meetings.field_title', { defaultValue: 'Title' })}
                </label>
                <div className="flex items-center gap-2">
                  <input
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    className={inputCls}
                  />
                  <Edit3 size={14} className="text-content-tertiary shrink-0" />
                </div>
              </div>

              {/* Meeting Type (editable) */}
              <div>
                <label className="block text-xs font-medium text-content-tertiary mb-1 uppercase tracking-wide">
                  {t('meetings.field_type', { defaultValue: 'Meeting Type' })}
                </label>
                <div className="relative">
                  <select
                    value={editMeetingType}
                    onChange={(e) => setEditMeetingType(e.target.value as MeetingType)}
                    className={inputCls + ' appearance-none pr-9'}
                  >
                    {MEETING_TYPES.map((mt) => (
                      <option key={mt} value={mt}>
                        {t(`meetings.type_${mt}`, {
                          defaultValue: mt.charAt(0).toUpperCase() + mt.slice(1),
                        })}
                      </option>
                    ))}
                  </select>
                  <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                    <ChevronDown size={14} />
                  </div>
                </div>
              </div>

              {/* Key Topics */}
              {previewData.key_topics.length > 0 && (
                <div>
                  <label className="block text-xs font-medium text-content-tertiary mb-1.5 uppercase tracking-wide">
                    {t('meetings.label_topics', { defaultValue: 'Key Topics' })}
                  </label>
                  <div className="flex flex-wrap gap-1.5">
                    {previewData.key_topics.map((topic, idx) => (
                      <Badge key={idx} variant="blue" size="sm">
                        {topic.length > 60 ? topic.slice(0, 60) + '...' : topic}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {/* Attendees (checkboxes) */}
              {editAttendees.length > 0 && (
                <div>
                  <label className="block text-xs font-medium text-content-tertiary mb-1.5 uppercase tracking-wide">
                    {t('meetings.label_attendees', { defaultValue: 'Attendees' })}
                    <span className="ml-1 text-content-tertiary font-normal">
                      ({editAttendees.filter((a) => a.included).length}/{editAttendees.length})
                    </span>
                  </label>
                  <div className="rounded-lg border border-border-light divide-y divide-border-light">
                    {editAttendees.map((att, idx) => (
                      <label
                        key={idx}
                        className="flex items-center gap-3 px-3 py-2 hover:bg-surface-secondary/50 cursor-pointer transition-colors"
                      >
                        <input
                          type="checkbox"
                          checked={att.included}
                          onChange={() => handleToggleAttendee(idx)}
                          className="rounded border-border text-oe-blue focus:ring-oe-blue/30"
                        />
                        <span className={clsx('text-sm flex-1', !att.included && 'text-content-tertiary line-through')}>
                          {att.name}
                        </span>
                        {att.company && (
                          <span className="text-xs text-content-tertiary">{att.company}</span>
                        )}
                        {att.role && (
                          <span className="text-xs text-content-tertiary">({att.role})</span>
                        )}
                      </label>
                    ))}
                  </div>
                </div>
              )}

              {/* Action Items (editable, removable) */}
              {editActionItems.length > 0 && (
                <div>
                  <label className="block text-xs font-medium text-content-tertiary mb-1.5 uppercase tracking-wide">
                    {t('meetings.label_actions', { defaultValue: 'Action Items' })}
                    <span className="ml-1 text-content-tertiary font-normal">
                      ({editActionItems.filter((a) => a.included).length}/{editActionItems.length})
                    </span>
                  </label>
                  <div className="rounded-lg border border-blue-200 dark:border-blue-800 divide-y divide-blue-100 dark:divide-blue-900">
                    {editActionItems.map((ai, idx) => (
                      <div
                        key={idx}
                        className={clsx(
                          'flex items-start gap-3 px-3 py-2.5 transition-colors',
                          !ai.included && 'opacity-50',
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={ai.included}
                          onChange={() => handleToggleActionItem(idx)}
                          className="rounded border-border text-oe-blue focus:ring-oe-blue/30 mt-0.5"
                        />
                        <div className="flex-1 min-w-0">
                          <p className={clsx('text-sm text-content-primary', !ai.included && 'line-through')}>
                            {ai.description}
                          </p>
                          <div className="flex items-center gap-3 mt-0.5 text-xs text-content-tertiary">
                            <span>
                              {t('meetings.action_owner', { defaultValue: 'Owner' })}: {ai.owner}
                            </span>
                            {ai.due_date && (
                              <span>
                                {t('meetings.action_due', { defaultValue: 'Due' })}: {ai.due_date}
                              </span>
                            )}
                          </div>
                        </div>
                        <button
                          onClick={() => handleRemoveActionItem(idx)}
                          className="flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:text-semantic-error hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors shrink-0 mt-0.5"
                          aria-label={t('common.remove', { defaultValue: 'Remove' })}
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Decisions (read-only) */}
              {previewData.decisions.length > 0 && (
                <div>
                  <label className="block text-xs font-medium text-content-tertiary mb-1.5 uppercase tracking-wide">
                    {t('meetings.label_decisions', { defaultValue: 'Decisions' })}
                  </label>
                  <div className="rounded-lg bg-green-50 dark:bg-green-950/20 border border-green-200 dark:border-green-800 p-3 space-y-1.5">
                    {previewData.decisions.map((d, idx) => (
                      <div key={idx} className="flex items-start gap-2 text-sm">
                        <CheckCircle2 size={14} className="text-semantic-success mt-0.5 shrink-0" />
                        <div className="flex-1 min-w-0">
                          <span className="text-content-primary">{d.decision}</span>
                          {d.made_by && (
                            <span className="text-xs text-content-tertiary ml-2">
                              ({d.made_by})
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Summary preview */}
              {previewData.summary && (
                <div>
                  <label className="block text-xs font-medium text-content-tertiary mb-1 uppercase tracking-wide">
                    {t('meetings.label_summary', { defaultValue: 'Summary' })}
                  </label>
                  <p className="text-sm text-content-secondary bg-surface-secondary rounded-lg p-3">
                    {previewData.summary.length > 500
                      ? previewData.summary.slice(0, 500) + '...'
                      : previewData.summary}
                  </p>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-border-light">
              <p className="text-xs text-content-tertiary">
                {t('meetings.review_hint', {
                  defaultValue: 'Review the extracted data above before creating the meeting.',
                })}
              </p>
              <div className="flex items-center gap-3 shrink-0">
                <Button variant="ghost" onClick={onClose} disabled={isPending}>
                  {t('common.cancel', { defaultValue: 'Cancel' })}
                </Button>
                <Button
                  variant="primary"
                  onClick={() => selectedFile && onImport(selectedFile)}
                  disabled={isPending || !selectedFile}
                >
                  {isPending ? (
                    <Loader2 size={16} className="mr-1.5 animate-spin shrink-0" />
                  ) : (
                    <Plus size={16} className="mr-1.5 shrink-0" />
                  )}
                  <span>{t('meetings.create_meeting', { defaultValue: 'Create Meeting' })}</span>
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* -- Export helper --------------------------------------------------------- */

async function downloadMeetingPdf(meetingId: string): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: 'application/pdf' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`/api/v1/meetings/${meetingId}/export/pdf`, {
    method: 'GET',
    headers,
  });
  if (!response.ok) {
    let detail = 'Export failed';
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition');
  const filename = disposition?.match(/filename="?(.+)"?/)?.[1] || `meeting_${meetingId}.pdf`;
  triggerDownload(blob, filename);
}

/* -- Meeting Row (expandable) ---------------------------------------------- */

const MeetingRow = React.memo(function MeetingRow({
  meeting,
  onComplete,
  onExportPdf,
  isExporting,
  projectId,
}: {
  meeting: Meeting;
  onComplete: (id: string) => void;
  onExportPdf: (id: string) => void;
  isExporting: boolean;
  projectId: string;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const statusCfg = STATUS_CONFIG[meeting.status] ?? STATUS_CONFIG.scheduled;
  const typeCfg = MEETING_TYPE_COLORS[meeting.meeting_type] ?? 'neutral';
  const attendeeCount = meeting.attendees?.length ?? 0;

  return (
    <div className="border-b border-border-light last:border-b-0">
      {/* Main row */}
      <div
        className={clsx(
          'flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-surface-secondary/50 transition-colors',
          expanded && 'bg-surface-secondary/30',
        )}
        onClick={() => setExpanded((prev) => !prev)}
      >
        <ChevronRight
          size={14}
          className={clsx(
            'text-content-tertiary transition-transform shrink-0',
            expanded && 'rotate-90',
          )}
        />

        {/* Meeting # */}
        <span className="text-sm font-mono font-semibold text-content-secondary w-20 shrink-0">
          MTG-{String(meeting.meeting_number).padStart(3, '0')}
        </span>

        {/* Title */}
        <span className="text-sm text-content-primary truncate flex-1 min-w-0">
          {meeting.title}
        </span>

        {/* Type badge */}
        <Badge variant={typeCfg} size="sm">
          {t(`meetings.type_${meeting.meeting_type}`, {
            defaultValue:
              meeting.meeting_type.charAt(0).toUpperCase() + meeting.meeting_type.slice(1),
          })}
        </Badge>

        {/* Date */}
        <span className="text-xs text-content-tertiary w-24 shrink-0 hidden md:block">
          <DateDisplay value={meeting.date} />
        </span>

        {/* Chairperson */}
        <span className="text-xs text-content-tertiary w-28 truncate shrink-0 hidden lg:block">
          {meeting.chairperson || '\u2014'}
        </span>

        {/* Status badge */}
        <Badge variant={statusCfg.variant} size="sm" className={statusCfg.cls}>
          {t(`meetings.status_${meeting.status}`, {
            defaultValue: meeting.status.replace(/_/g, ' '),
          })}
        </Badge>

        {/* Attendee count */}
        <span className="text-xs text-content-tertiary w-12 text-right shrink-0 flex items-center justify-end gap-1">
          <Users size={12} />
          {attendeeCount}
        </span>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-4 pl-12 space-y-3 animate-fade-in">
          {/* Attendees */}
          {meeting.attendees && meeting.attendees.length > 0 && (
            <div className="rounded-lg bg-surface-secondary p-3">
              <p className="text-xs text-content-tertiary mb-2 font-medium uppercase tracking-wide">
                {t('meetings.label_attendees', { defaultValue: 'Attendees' })}
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                {meeting.attendees.map((att) => (
                  <div key={att.id} className="flex items-center gap-2 text-sm">
                    {ATTENDEE_STATUS_ICON[att.status] ?? <Circle size={14} />}
                    <span className="text-content-primary">{att.name}</span>
                    {att.role && (
                      <span className="text-xs text-content-tertiary">({att.role})</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Agenda Items */}
          {meeting.agenda_items && meeting.agenda_items.length > 0 && (
            <div className="rounded-lg bg-surface-secondary p-3">
              <p className="text-xs text-content-tertiary mb-2 font-medium uppercase tracking-wide">
                {t('meetings.label_agenda', { defaultValue: 'Agenda' })}
              </p>
              <ol className="space-y-1.5">
                {meeting.agenda_items.map((item, idx) => (
                  <li key={item.id} className="flex items-start gap-2 text-sm">
                    <span className="text-xs text-content-tertiary font-mono w-5 shrink-0 pt-0.5">
                      {idx + 1}.
                    </span>
                    <div className="flex-1 min-w-0">
                      <span className="text-content-primary">{item.title}</span>
                      {item.presenter && (
                        <span className="text-xs text-content-tertiary ml-2">
                          ({item.presenter})
                        </span>
                      )}
                      {item.duration_minutes > 0 && (
                        <span className="text-xs text-content-tertiary ml-2 flex items-center gap-0.5 inline-flex">
                          <Clock size={10} />
                          {item.duration_minutes}m
                        </span>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Action Items */}
          {meeting.action_items && meeting.action_items.length > 0 && (
            <div className="rounded-lg bg-blue-50 dark:bg-blue-950/20 border border-blue-200 dark:border-blue-800 p-3">
              <p className="text-xs text-blue-700 dark:text-blue-400 mb-2 font-medium uppercase tracking-wide">
                {t('meetings.label_actions', { defaultValue: 'Action Items' })}
              </p>
              <div className="space-y-2">
                {meeting.action_items.map((ai) => (
                  <div key={ai.id} className="flex items-start gap-2 text-sm">
                    {ai.completed ? (
                      <CheckCircle2 size={14} className="text-semantic-success mt-0.5 shrink-0" />
                    ) : (
                      <Circle size={14} className="text-content-tertiary mt-0.5 shrink-0" />
                    )}
                    <div className="flex-1 min-w-0">
                      <span
                        className={clsx(
                          'text-content-primary',
                          ai.completed && 'line-through text-content-tertiary',
                        )}
                      >
                        {ai.description}
                      </span>
                      <div className="flex items-center gap-3 mt-0.5 text-xs text-content-tertiary">
                        <span>
                          {t('meetings.action_owner', { defaultValue: 'Owner' })}: {ai.owner}
                        </span>
                        {ai.due_date && (
                          <span>
                            {t('meetings.action_due', { defaultValue: 'Due' })}:{' '}
                            <DateDisplay value={ai.due_date} />
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Linked Tasks */}
          {meeting.action_items && meeting.action_items.length > 0 && meeting.status === 'completed' && (
            <div className="flex items-center gap-2">
              <ListChecks size={14} className="text-content-tertiary" />
              <span className="text-xs text-content-tertiary">
                {t('meetings.linked_tasks', {
                  defaultValue: '{{count}} tasks from action items',
                  count: meeting.action_items.length,
                })}
              </span>
              <Link
                to={`/projects/${projectId}/tasks?meeting_id=${meeting.id}`}
                className="text-xs font-medium text-oe-blue hover:underline"
                onClick={(e) => e.stopPropagation()}
              >
                {t('meetings.view_tasks', { defaultValue: 'View Tasks' })}
              </Link>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2 pt-1">
            {(meeting.status === 'scheduled' || meeting.status === 'in_progress') && (
              <Button
                variant="primary"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onComplete(meeting.id);
                }}
              >
                <CheckCircle2 size={14} className="mr-1.5" />
                {t('meetings.action_complete', { defaultValue: 'Complete Meeting' })}
              </Button>
            )}
            <Button
              variant="secondary"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                onExportPdf(meeting.id);
              }}
              disabled={isExporting}
            >
              {isExporting ? (
                <Loader2 size={14} className="mr-1.5 animate-spin" />
              ) : (
                <FileDown size={14} className="mr-1.5" />
              )}
              {t('meetings.export_pdf', { defaultValue: 'Export PDF' })}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
});

/* -- Main Page ------------------------------------------------------------- */

export function MeetingsPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // State
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState<MeetingType | ''>('');
  const [statusFilter, setStatusFilter] = useState<MeetingStatus | ''>('');

  // Data
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const projectName = projects.find((p) => p.id === projectId)?.name || '';

  const { data: meetings = [], isLoading } = useQuery({
    queryKey: ['meetings', projectId, typeFilter, statusFilter],
    queryFn: () =>
      fetchMeetings({
        project_id: projectId,
        meeting_type: typeFilter || undefined,
        status: statusFilter || undefined,
      }),
    enabled: !!projectId,
  });

  // Client-side search
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return meetings;
    const q = searchQuery.toLowerCase();
    return meetings.filter(
      (m) =>
        m.title.toLowerCase().includes(q) ||
        String(m.meeting_number).includes(q) ||
        (m.chairperson && m.chairperson.toLowerCase().includes(q)),
    );
  }, [meetings, searchQuery]);

  // Stats
  const stats = useMemo(() => {
    const total = meetings.length;
    const scheduled = meetings.filter((m) => m.status === 'scheduled').length;
    const completed = meetings.filter((m) => m.status === 'completed').length;
    const inProgress = meetings.filter((m) => m.status === 'in_progress').length;
    return { total, scheduled, completed, inProgress };
  }, [meetings]);

  // Invalidation
  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['meetings'] });
  }, [qc]);

  // Mutations
  const createMut = useMutation({
    mutationFn: (data: CreateMeetingPayload) => createMeeting(data),
    onSuccess: () => {
      invalidateAll();
      qc.invalidateQueries({ queryKey: ['tasks'] });
      setShowCreateModal(false);
      addToast({
        type: 'success',
        title: t('meetings.created', { defaultValue: 'Meeting created' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const completeMut = useMutation({
    mutationFn: (id: string) => completeMeeting(id),
    onSuccess: (data) => {
      invalidateAll();
      qc.invalidateQueries({ queryKey: ['tasks'] });
      const actionCount = data?.action_items?.length ?? 0;
      addToast(
        {
          type: 'success',
          title: t('meetings.completed', { defaultValue: 'Meeting completed' }),
          message: actionCount > 0
            ? t('meetings.tasks_created_count', {
                defaultValue: 'Meeting completed. {{count}} tasks created from action items.',
                count: actionCount,
              })
            : t('meetings.tasks_created', { defaultValue: 'Meeting completed. Action item tasks have been created.' }),
          action: actionCount > 0
            ? {
                label: t('meetings.view_tasks', { defaultValue: 'View Tasks' }),
                onClick: () => {
                  window.location.href = '/tasks';
                },
              }
            : undefined,
        },
        actionCount > 0 ? { duration: 8000 } : undefined,
      );
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const exportPdfMut = useMutation({
    mutationFn: (meetingId: string) => downloadMeetingPdf(meetingId),
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('meetings.export_success', { defaultValue: 'PDF exported' }),
      }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const importMut = useMutation({
    mutationFn: (file: File) => importMeetingSummary(projectId, file),
    onSuccess: () => {
      invalidateAll();
      qc.invalidateQueries({ queryKey: ['tasks'] });
      setShowImportModal(false);
      addToast({
        type: 'success',
        title: t('meetings.import_success', { defaultValue: 'Meeting imported from transcript' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const handleImport = useCallback(
    (file: File) => {
      importMut.mutate(file);
    },
    [importMut],
  );

  const handleCreateSubmit = useCallback(
    (formData: MeetingFormData) => {
      if (!projectId) {
        addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: t('common.select_project_first', { defaultValue: 'Please select a project first' }) });
        return;
      }
      const attendeesList = formData.attendees
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean);
      createMut.mutate({
        project_id: projectId,
        title: formData.title,
        meeting_type: formData.meeting_type,
        date: formData.date,
        location: formData.location || undefined,
        chairperson: formData.chairperson || undefined,
        attendees: attendeesList.length > 0 ? attendeesList : undefined,
      });
    },
    [createMut, projectId, addToast, t],
  );

  const { confirm, ...confirmProps } = useConfirm();

  const handleComplete = useCallback(
    async (id: string) => {
      const ok = await confirm({
        title: t('meetings.confirm_complete_title', { defaultValue: 'Complete meeting?' }),
        message: t('meetings.confirm_complete_msg', { defaultValue: 'This meeting will be marked as completed.' }),
        confirmLabel: t('meetings.mark_complete', { defaultValue: 'Complete' }),
        variant: 'warning',
      });
      if (ok) completeMut.mutate(id);
    },
    [completeMut, confirm, t],
  );

  const handleExportPdf = useCallback(
    (id: string) => {
      exportPdfMut.mutate(id);
    },
    [exportPdfMut],
  );

  return (
    <div className="max-w-content mx-auto animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          ...(projectName ? [{ label: projectName, to: `/projects/${projectId}` }] : []),
          { label: t('meetings.title', { defaultValue: 'Meetings' }) },
        ]}
        className="mb-4"
      />

      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-content-primary">
          {t('meetings.page_title', { defaultValue: 'Meetings' })}
        </h1>

        <div className="flex items-center gap-2 shrink-0">
          {!routeProjectId && projects.length > 0 && (
            <select
              value={projectId}
              onChange={(e) => {
                const p = projects.find((pr) => pr.id === e.target.value);
                if (p) {
                  useProjectContextStore.getState().setActiveProject(p.id, p.name);
                }
              }}
              className={inputCls + ' !h-8 !text-xs max-w-[180px]'}
            >
              <option value="" disabled>
                {t('meetings.select_project', { defaultValue: 'Project...' })}
              </option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
          <Button
            variant="secondary"
            onClick={() => setShowImportModal(true)}
            disabled={!projectId}
            icon={<FileUp size={16} />}
          >
            {t('meetings.import_summary', { defaultValue: 'Import Summary' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => setShowCreateModal(true)}
            disabled={!projectId}
            title={!projectId ? t('common.select_project_first', { defaultValue: 'Please select a project first' }) : undefined}
            icon={<Plus size={16} />}
          >
            {t('meetings.new_meeting', { defaultValue: 'New Meeting' })}
          </Button>
        </div>
      </div>

      {/* No-project warning */}
      {!projectId && (
        <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
          {t('common.select_project_hint', { defaultValue: 'Select a project from the header to get started.' })}
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('meetings.stat_total', { defaultValue: 'Total Meetings' })}
          </p>
          <p className="text-2xl font-bold mt-1 tabular-nums text-content-primary">{stats.total}</p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('meetings.stat_scheduled', { defaultValue: 'Scheduled' })}
          </p>
          <p className="text-2xl font-bold mt-1 tabular-nums text-oe-blue">{stats.scheduled}</p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('meetings.stat_in_progress', { defaultValue: 'In Progress' })}
          </p>
          <p className="text-2xl font-bold mt-1 tabular-nums text-amber-500">{stats.inProgress}</p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('meetings.stat_completed', { defaultValue: 'Completed' })}
          </p>
          <p className="text-2xl font-bold mt-1 tabular-nums text-semantic-success">
            {stats.completed}
          </p>
        </Card>
      </div>

      {/* Toolbar */}
      <div className="mb-6 flex flex-col sm:flex-row sm:items-center gap-3">
        {/* Search */}
        <div className="relative flex-1 max-w-sm">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('meetings.search_placeholder', {
              defaultValue: 'Search meetings...',
            })}
            className={inputCls + ' pl-9'}
          />
        </div>

        {/* Type filter */}
        <div className="relative">
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as MeetingType | '')}
            className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-44"
          >
            <option value="">
              {t('meetings.filter_all_types', { defaultValue: 'All Types' })}
            </option>
            {MEETING_TYPES.map((mt) => (
              <option key={mt} value={mt}>
                {t(`meetings.type_${mt}`, {
                  defaultValue: mt.charAt(0).toUpperCase() + mt.slice(1),
                })}
              </option>
            ))}
          </select>
          <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
            <ChevronDown size={14} />
          </div>
        </div>

        {/* Status filter */}
        <div className="relative">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as MeetingStatus | '')}
            className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-40"
          >
            <option value="">
              {t('meetings.filter_all_statuses', { defaultValue: 'All Statuses' })}
            </option>
            {MEETING_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`meetings.status_${s}`, {
                  defaultValue: s.replace(/_/g, ' '),
                })}
              </option>
            ))}
          </select>
          <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
            <ChevronDown size={14} />
          </div>
        </div>
      </div>

      {/* Table */}
      <div>
        {isLoading ? (
          <SkeletonTable rows={5} columns={6} />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<CalendarDays size={28} strokeWidth={1.5} />}
            title={
              searchQuery || typeFilter || statusFilter
                ? t('meetings.no_results', { defaultValue: 'No matching meetings' })
                : t('meetings.no_meetings', { defaultValue: 'No meetings yet' })
            }
            description={
              searchQuery || typeFilter || statusFilter
                ? t('meetings.no_results_hint', {
                    defaultValue: 'Try adjusting your search or filters',
                  })
                : t('meetings.no_meetings_hint', {
                    defaultValue: 'Schedule your first meeting',
                  })
            }
            action={
              !searchQuery && !typeFilter && !statusFilter
                ? {
                    label: t('meetings.new_meeting', { defaultValue: 'New Meeting' }),
                    onClick: () => setShowCreateModal(true),
                  }
                : undefined
            }
          />
        ) : (
          <>
            <p className="mb-3 text-sm text-content-tertiary">
              {t('meetings.showing_count', {
                defaultValue: '{{count}} meetings',
                count: filtered.length,
              })}
            </p>
            <Card padding="none" className="overflow-x-auto">
              {/* Table header */}
              <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border-light bg-surface-secondary/30 text-2xs font-medium text-content-tertiary uppercase tracking-wider min-w-[640px]">
                <span className="w-5" />
                <span className="w-20">#</span>
                <span className="flex-1">
                  {t('meetings.col_title', { defaultValue: 'Title' })}
                </span>
                <span className="w-24 text-center">
                  {t('meetings.col_type', { defaultValue: 'Type' })}
                </span>
                <span className="w-24 hidden md:block">
                  {t('meetings.col_date', { defaultValue: 'Date' })}
                </span>
                <span className="w-28 hidden lg:block">
                  {t('meetings.col_chair', { defaultValue: 'Chairperson' })}
                </span>
                <span className="w-24 text-center">
                  {t('meetings.col_status', { defaultValue: 'Status' })}
                </span>
                <span className="w-12 text-right">
                  <Users size={12} className="inline" />
                </span>
              </div>

              {/* Rows */}
              {filtered.map((meeting) => (
                <MeetingRow
                  key={meeting.id}
                  meeting={meeting}
                  onComplete={handleComplete}
                  onExportPdf={handleExportPdf}
                  isExporting={exportPdfMut.isPending && exportPdfMut.variables === meeting.id}
                  projectId={projectId}
                />
              ))}
            </Card>
          </>
        )}
      </div>

      {/* Create Modal */}
      {showCreateModal && (
        <CreateMeetingModal
          onClose={() => setShowCreateModal(false)}
          onSubmit={handleCreateSubmit}
          isPending={createMut.isPending}
          projectName={projectName}
        />
      )}

      {/* Import Summary Modal */}
      {showImportModal && (
        <ImportSummaryModal
          onClose={() => setShowImportModal(false)}
          onImport={handleImport}
          isPending={importMut.isPending}
          projectId={projectId}
        />
      )}

      {/* Confirm Dialog */}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
