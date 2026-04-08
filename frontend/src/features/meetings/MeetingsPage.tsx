import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
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
  type Meeting,
  type MeetingType,
  type MeetingStatus,
  type CreateMeetingPayload,
  type AttendeeStatus,
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

const MEETING_STATUSES: MeetingStatus[] = ['scheduled', 'in_progress', 'completed', 'cancelled'];

/* -- Create Meeting Modal -------------------------------------------------- */

interface MeetingFormData {
  title: string;
  meeting_type: MeetingType;
  date: string;
  location: string;
  chairperson: string;
}

const EMPTY_FORM: MeetingFormData = {
  title: '',
  meeting_type: 'progress',
  date: '',
  location: '',
  chairperson: '',
};

function CreateMeetingModal({
  onClose,
  onSubmit,
  isPending,
}: {
  onClose: () => void;
  onSubmit: (data: MeetingFormData) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<MeetingFormData>(EMPTY_FORM);
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
          <h2 className="text-lg font-semibold text-content-primary">
            {t('meetings.new_meeting', { defaultValue: 'New Meeting' })}
          </h2>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Form */}
        <div className="px-6 py-4 space-y-4">
          {/* Title */}
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
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

          {/* Two-column: Type + Date */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('meetings.field_type', { defaultValue: 'Meeting Type' })}
              </label>
              <div className="relative">
                <select
                  value={form.meeting_type}
                  onChange={(e) => set('meeting_type', e.target.value as MeetingType)}
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
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('meetings.field_date', { defaultValue: 'Date' })}{' '}
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
          </div>

          {/* Two-column: Location + Chairperson */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('meetings.field_location', { defaultValue: 'Location' })}
              </label>
              <input
                value={form.location}
                onChange={(e) => set('location', e.target.value)}
                className={inputCls}
                placeholder={t('meetings.location_placeholder', {
                  defaultValue: 'e.g. Site Office, Room 201',
                })}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('meetings.field_chairperson', { defaultValue: 'Chairperson' })}
              </label>
              <input
                value={form.chairperson}
                onChange={(e) => set('chairperson', e.target.value)}
                className={inputCls}
                placeholder={t('meetings.chairperson_placeholder', {
                  defaultValue: 'Person chairing the meeting',
                })}
              />
            </div>
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

function ImportSummaryModal({
  onClose,
  onImport,
  isPending,
}: {
  onClose: () => void;
  onImport: (file: File) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);

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
    if (lower.includes('teams') || lower.includes('microsoft')) return 'Teams';
    if (lower.includes('meet') || lower.includes('google')) return 'Google Meet';
    if (lower.includes('zoom')) return 'Zoom';
    return 'Other';
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
      <div className="w-full max-w-lg bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('meetings.import_summary', { defaultValue: 'Import Meeting Summary' })}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('meetings.import_summary', { defaultValue: 'Import Meeting Summary' })}
          </h2>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Content */}
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
                <Badge variant="blue" size="sm">
                  {detectSource(selectedFile.name)}
                </Badge>
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

          {/* Format hints */}
          <div className="rounded-lg bg-surface-secondary p-3">
            <p className="text-xs text-content-tertiary font-medium uppercase tracking-wide mb-2">
              {t('meetings.supported_sources', { defaultValue: 'Supported Sources' })}
            </p>
            <div className="flex flex-wrap gap-2">
              {[
                { label: 'Microsoft Teams', cls: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400' },
                { label: 'Google Meet', cls: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' },
                { label: 'Zoom', cls: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400' },
                { label: 'Other', cls: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
              ].map((s) => (
                <Badge key={s.label} variant="neutral" size="sm" className={s.cls}>
                  {s.label}
                </Badge>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
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
              <FileUp size={16} className="mr-1.5 shrink-0" />
            )}
            <span>{t('meetings.import_btn', { defaultValue: 'Import & Extract' })}</span>
          </Button>
        </div>
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
}: {
  meeting: Meeting;
  onComplete: (id: string) => void;
  onExportPdf: (id: string) => void;
  isExporting: boolean;
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
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('meetings.completed', { defaultValue: 'Meeting completed' }),
      });
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
      createMut.mutate({
        project_id: projectId,
        title: formData.title,
        meeting_type: formData.meeting_type,
        date: formData.date,
        location: formData.location || undefined,
        chairperson: formData.chairperson || undefined,
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
          {t('common.select_project_first', { defaultValue: 'Please select a project to continue.' })}
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <Card className="p-4 animate-card-in">
          <p className="text-2xs text-content-tertiary uppercase tracking-wide">
            {t('meetings.stat_total', { defaultValue: 'Total Meetings' })}
          </p>
          <p className="text-xl font-bold mt-1 tabular-nums text-content-primary">{stats.total}</p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs text-content-tertiary uppercase tracking-wide">
            {t('meetings.stat_scheduled', { defaultValue: 'Scheduled' })}
          </p>
          <p className="text-xl font-bold mt-1 tabular-nums text-oe-blue">{stats.scheduled}</p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs text-content-tertiary uppercase tracking-wide">
            {t('meetings.stat_in_progress', { defaultValue: 'In Progress' })}
          </p>
          <p className="text-xl font-bold mt-1 tabular-nums text-amber-500">{stats.inProgress}</p>
        </Card>
        <Card className="p-4 animate-card-in">
          <p className="text-2xs text-content-tertiary uppercase tracking-wide">
            {t('meetings.stat_completed', { defaultValue: 'Completed' })}
          </p>
          <p className="text-xl font-bold mt-1 tabular-nums text-semantic-success">
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
            icon={<CalendarDays size={24} strokeWidth={1.5} />}
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
              <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border bg-surface-secondary/50 text-xs font-medium text-content-tertiary uppercase tracking-wide min-w-[640px]">
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
        />
      )}

      {/* Import Summary Modal */}
      {showImportModal && (
        <ImportSummaryModal
          onClose={() => setShowImportModal(false)}
          onImport={handleImport}
          isPending={importMut.isPending}
        />
      )}

      {/* Confirm Dialog */}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
