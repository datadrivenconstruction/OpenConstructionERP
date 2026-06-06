import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import {
  Calendar,
  BookOpen,
  Archive,
  Plus,
  Lock,
  LockOpen,
  Cloud,
  CloudDownload,
  Camera,
  Plane,
  Scan,
  FileSignature,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  Trash2,
  Globe2,
  FileDown,
  Upload,
  Users,
  Package,
  CheckCircle2,
  Pencil,
  Wallet,
  ClipboardList,
  ExternalLink,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  SkeletonTable,
  WideModal,
  WideModalSection,
  WideModalField,
  ConfirmDialog,
  DismissibleInfo,
} from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { apiGet, getErrorMessage } from '@/shared/lib/api';
import { todayLocalISO, isoDateFromLocal, nowLocalISO } from '@/shared/lib/dates';
import { projectsApi } from '@/features/projects/api';
import {
  listDiaries,
  getDiary,
  createDiary,
  updateDiary,
  closeDiary,
  deleteDiary,
  signDiary,
  unlockDiary,
  archiveDiary,
  weatherToday,
  fetchWeather,
  createWeather,
  listEntries,
  createEntry,
  deleteEntry,
  listPhotos,
  createPhoto,
  listDroneSurveys,
  createDroneSurvey,
  listRealityCaptures,
  createRealityCapture,
  listArchiveSignatures,
  diaryCompleteness,
  diaryWorkforceSummary,
  exportSclBundle,
  downloadDiaryPdf,
  type DailyDiary,
  type WeatherRecord,
  type DiaryEntry,
  type DiaryPhoto,
  type DroneSurvey,
  type RealityCapture,
  type DiaryStatus,
  type SignerRole,
  type EntryType,
  type CaptureType,
  type DiaryCompleteness,
  type SclBundleManifest,
} from './api';

type Tab = 'diaries' | 'today' | 'archive';

const STATUS_VARIANT: Record<DiaryStatus, 'neutral' | 'blue' | 'success' | 'warning'> = {
  open: 'blue',
  closed: 'warning',
  signed: 'success',
  archived: 'neutral',
};

// Human, English-fallback labels for the diary status enum so badges read
// e.g. "Open" rather than the raw token "open". Audit ux_clarity fix.
const STATUS_LABEL_EN: Record<DiaryStatus, string> = {
  open: 'Open',
  closed: 'Closed',
  signed: 'Signed',
  archived: 'Archived',
};

// Human, English-fallback labels for the diary entry-type enum so the
// dropdown and timeline badges read e.g. "Delivery" rather than "delivery".
const ENTRY_TYPE_LABEL_EN: Record<EntryType, string> = {
  general: 'General',
  visitor: 'Visitor',
  event: 'Event',
  delivery: 'Delivery',
  completion: 'Completion',
  incident_summary: 'Incident summary',
  inspection_summary: 'Inspection summary',
  photo_note: 'Photo note',
};

type TFn = ReturnType<typeof useTranslation>['t'];

function statusLabel(t: TFn, status: DiaryStatus): string {
  return t(`daily_diary.status.${status}`, {
    defaultValue: STATUS_LABEL_EN[status] ?? status,
  });
}

function entryTypeLabel(t: TFn, type: EntryType): string {
  return t(`daily_diary.entry_type.${type}`, {
    defaultValue: ENTRY_TYPE_LABEL_EN[type] ?? type,
  });
}

const SIGNER_ROLE_LABEL_EN: Record<SignerRole, string> = {
  owner: 'Owner',
  supervisor: 'Site supervisor',
  inspector: 'Inspector',
  client: 'Client',
};

function signerRoleLabel(t: TFn, role: SignerRole): string {
  return t(`daily_diary.signer_role_label.${role}`, {
    defaultValue: SIGNER_ROLE_LABEL_EN[role] ?? role,
  });
}

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/* ── helpers ─────────────────────────────────────────────────────────── */

// Local-date helpers re-export — kept as local names for in-file readability,
// implementation lives in shared/lib/dates.ts and is shared with field-reports.
const todayIso = todayLocalISO;
const isoDate = isoDateFromLocal;

// The latest date a diary may be opened for. The backend allows today plus
// one day of slack (service.create_diary: now(UTC).date() + 1 day) so a site
// running ahead of UTC can still open "its" current day. Mirror that rule
// exactly in the UI so the calendar enables/disables the same cells the API
// would accept, instead of a stricter "today only" guess.
function maxDiaryIso(): string {
  const t = new Date();
  t.setDate(t.getDate() + 1);
  return todayLocalISO(t);
}

function monthBounds(year: number, month: number): { from: string; to: string } {
  // Built from the local calendar fields the grid itself uses, NOT a UTC
  // toISOString() slice — the latter shifts the first/last day by ±1 for
  // any viewer behind/ahead of UTC, so the range query would miss the
  // edge-of-month diaries the grid still renders cells for.
  const lastDay = new Date(year, month + 1, 0).getDate();
  return { from: isoDate(year, month, 1), to: isoDate(year, month, lastDay) };
}

function daysInMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate();
}

function fmtMonth(year: number, month: number, locale: string): string {
  try {
    return new Intl.DateTimeFormat(locale, { year: 'numeric', month: 'long' }).format(
      new Date(year, month, 1),
    );
  } catch {
    return `${year}-${String(month + 1).padStart(2, '0')}`;
  }
}

function formatSha(sha: string): string {
  if (!sha) return '';
  return `${sha.slice(0, 8)}…${sha.slice(-6)}`;
}

/* ── Page ────────────────────────────────────────────────────────────── */

export function DailyDiaryPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>('diaries');
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const [projectId, setProjectId] = useState<string>('');
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth());
  const [activeDiaryId, setActiveDiaryId] = useState<string>('');
  const [createOpen, setCreateOpen] = useState(false);
  // Date the create flow should be prefilled with. Set when a user clicks an
  // empty calendar day so the new diary defaults to THAT day rather than
  // today; empty string means "use today" (the header / FAB entry points).
  const [createDate, setCreateDate] = useState<string>('');
  const [signOpen, setSignOpen] = useState(false);

  const openCreate = (date?: string) => {
    setCreateDate(date ?? '');
    setCreateOpen(true);
  };

  const projectsQ = useQuery({
    queryKey: ['projects-list-for-diary'],
    queryFn: () => projectsApi.list(),
  });

  // Project selection lives in the global top bar. Follow the active project
  // from the shared context; only fall back to the first available project
  // when nothing is selected globally and nothing is picked here yet.
  useEffect(() => {
    if (activeProjectId) {
      if (activeProjectId !== projectId) {
        setProjectId(activeProjectId);
        setActiveDiaryId('');
      }
      return;
    }
    if (projectId) return;
    const seed = projectsQ.data?.[0]?.id;
    if (seed) setProjectId(seed);
  }, [activeProjectId, projectsQ.data, projectId]);

  const selectedProjectName = projectsQ.data?.find((p) => p.id === projectId)?.name ?? '';

  const bounds = useMemo(() => monthBounds(year, month), [year, month]);

  const diariesQ = useQuery({
    queryKey: ['daily-diary', 'list', projectId, bounds.from, bounds.to],
    queryFn: () =>
      listDiaries({
        project_id: projectId,
        date_from: bounds.from,
        date_to: bounds.to,
        limit: 200,
      }),
    enabled: !!projectId && tab === 'diaries',
  });

  // The "Today" tab shows the explicitly-selected diary when one is set
  // (e.g. a past day clicked in the calendar); otherwise it resolves the
  // project's diary for the current local day. Previously it ALWAYS queried
  // today's diary and ignored activeDiaryId, so clicking a historical day
  // in the calendar silently showed today (or an empty state) instead of
  // the clicked diary — the calendar's primary navigation was dead.
  const selectedDiaryQ = useQuery({
    queryKey: ['daily-diary', 'by-id', activeDiaryId],
    queryFn: () => getDiary(activeDiaryId),
    enabled: !!activeDiaryId && tab === 'today',
  });

  const todayDiariesQ = useQuery({
    queryKey: ['daily-diary', 'today', projectId],
    queryFn: () =>
      listDiaries({
        project_id: projectId,
        date_from: todayIso(),
        date_to: todayIso(),
        limit: 1,
      }),
    enabled: !!projectId && tab === 'today' && !activeDiaryId,
  });

  const activeDiary: DailyDiary | undefined = activeDiaryId
    ? selectedDiaryQ.data
    : todayDiariesQ.data?.[0];
  const activeLoading = activeDiaryId
    ? selectedDiaryQ.isLoading
    : todayDiariesQ.isLoading;
  const activeError = activeDiaryId
    ? selectedDiaryQ.isError
    : todayDiariesQ.isError;

  const archiveQ = useQuery({
    queryKey: ['daily-diary', 'archive', projectId],
    queryFn: () =>
      listDiaries({
        project_id: projectId,
        status: 'signed',
        limit: 500,
      }),
    enabled: !!projectId && tab === 'archive',
  });

  return (
    <div className="space-y-5">
      <Breadcrumb
        items={[
          ...(selectedProjectName
            ? [{ label: selectedProjectName, to: `/projects/${projectId}` }]
            : []),
          {
            label: t('nav.daily_diary', { defaultValue: 'Daily Site Diary' }),
          },
        ]}
      />

      <PageHeader
        srTitle={t('daily_diary.title', { defaultValue: 'Daily Site Diary' })}
        subtitle={t('daily_diary.subtitle', {
          defaultValue:
            'Weather, photos, drone surveys and signed daily records.',
        })}
        actions={
          <>
            <Button
              variant="secondary"
              size="sm"
              icon={<ClipboardList size={14} />}
              onClick={() => navigate('/field-reports')}
              title={t('daily_diary.open_field_report_hint', {
                defaultValue: 'Open the field-reports register for the daily field report.',
              })}
              data-testid="daily-diary-open-field-report"
            >
              {t('daily_diary.open_field_report', { defaultValue: "Today's field report" })}
            </Button>
            {projectId && (
              <Button
                variant="secondary"
                size="sm"
                icon={<Globe2 size={14} />}
                onClick={() => navigate(`/projects/${projectId}/geo`)}
                title={t('geo_hub.view_on_map', { defaultValue: 'View on map' })}
                data-testid="daily-diary-view-on-map"
              >
                {t('geo_hub.view_on_map', { defaultValue: 'View on map' })}
              </Button>
            )}
            <Button
              variant="primary"
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => openCreate()}
              disabled={!projectId}
            >
              {t('daily_diary.new_diary', { defaultValue: 'New Diary' })}
            </Button>
          </>
        }
      />

      <DismissibleInfo
        storageKey="daily-diary"
        title={t('daily_diary.intro_title', {
          defaultValue: 'Tamper-proof evidence when claims arrive',
        })}
        links={[
          {
            label: t('daily_diary.intro_link_schedule', { defaultValue: 'Schedule' }),
            onClick: () => navigate('/schedule'),
          },
          {
            label: t('daily_diary.intro_link_files', { defaultValue: 'Files' }),
            onClick: () => navigate('/files'),
          },
          {
            label: t('daily_diary.intro_link_payroll', { defaultValue: 'Payroll' }),
            onClick: () => navigate('/payroll'),
          },
          {
            label: t('daily_diary.intro_link_field_reports', { defaultValue: 'Field Reports' }),
            onClick: () => navigate('/field-reports'),
          },
        ]}
      >
        {t('daily_diary.intro_body', {
          defaultValue:
            'Each site day you open the diary, log weather, headcount, deliveries and events, attach photos and drone or reality-capture surveys, then close and sign it. A signed diary is sealed with a sha256 fingerprint so it stands as tamper-evident proof for delay claims and disputes, and it feeds schedule progress and the site photo library.',
        })}
      </DismissibleInfo>

      <div className="border-b border-border-light">
        <nav className="flex gap-1 -mb-px">
          {(
            [
              { id: 'diaries', label: t('daily_diary.tab_diaries', { defaultValue: 'Diaries' }), icon: Calendar },
              { id: 'today', label: t('daily_diary.tab_today', { defaultValue: 'Today' }), icon: BookOpen },
              { id: 'archive', label: t('daily_diary.tab_archive', { defaultValue: 'Archive' }), icon: Archive },
            ] as { id: Tab; label: string; icon: React.ElementType }[]
          ).map((it) => {
            const Icon = it.icon;
            return (
              <button
                key={it.id}
                type="button"
                onClick={() => {
                  // Clicking the "Today" tab itself always means *today's*
                  // diary — drop any diary selected from the calendar.
                  if (it.id === 'today') setActiveDiaryId('');
                  setTab(it.id);
                }}
                className={clsx(
                  'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap',
                  tab === it.id
                    ? 'border-oe-blue text-oe-blue'
                    : 'border-transparent text-content-secondary hover:text-content-primary',
                )}
              >
                <Icon size={14} />
                {it.label}
              </button>
            );
          })}
        </nav>
      </div>

      {projectsQ.isError ? (
        <Card className="py-12">
          <EmptyState
            icon={<AlertTriangle size={22} />}
            title={t('common.error', { defaultValue: 'Error' })}
            description={t('daily_diary.projects_load_error', {
              defaultValue: 'Failed to load projects. Please try again.',
            })}
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => void projectsQ.refetch(),
            }}
          />
        </Card>
      ) : !projectId ? (
        <Card>
          {projectsQ.isLoading ? (
            <SkeletonTable rows={6} columns={3} />
          ) : (
            <RequiresProject
              emptyHint={t('daily_diary.no_project_desc', {
                defaultValue:
                  'Pick a project from the top bar to start logging site diaries.',
              })}
            >{null}</RequiresProject>
          )}
        </Card>
      ) : tab === 'diaries' ? (
        diariesQ.isError ? (
          <Card className="py-12">
            <EmptyState
              icon={<AlertTriangle size={22} />}
              title={t('common.error', { defaultValue: 'Error' })}
              description={t('daily_diary.diaries_load_error', {
                defaultValue: 'Failed to load diaries. Please try again.',
              })}
              action={{
                label: t('common.retry', { defaultValue: 'Retry' }),
                onClick: () => void diariesQ.refetch(),
              }}
            />
          </Card>
        ) : (
          <DiariesCalendar
            diaries={diariesQ.data ?? []}
            loading={diariesQ.isLoading}
            year={year}
            month={month}
            locale={i18n.language || 'en'}
            onYearChange={setYear}
            onMonthChange={setMonth}
            onDayClick={(diary) => {
              setActiveDiaryId(diary.id);
              setTab('today');
            }}
            onEmptyDayClick={(iso) => openCreate(iso)}
          />
        )
      ) : tab === 'today' ? (
        activeError ? (
          <Card className="py-12">
            <EmptyState
              icon={<AlertTriangle size={22} />}
              title={t('common.error', { defaultValue: 'Error' })}
              description={t('daily_diary.today_load_error', {
                defaultValue: 'Failed to load the diary. Please try again.',
              })}
              action={{
                label: t('common.retry', { defaultValue: 'Retry' }),
                onClick: () =>
                  void (activeDiaryId
                    ? selectedDiaryQ.refetch()
                    : todayDiariesQ.refetch()),
              }}
            />
          </Card>
        ) : (
          <TodayTab
            projectId={projectId}
            diary={activeDiary}
            loading={activeLoading}
            onCreate={() => openCreate()}
            onSign={() => setSignOpen(true)}
            onDeleted={() => {
              // After delete, drop the calendar-selected diary so the
              // page falls back to the today-resolver (which will now
              // show the empty state if today was the deleted entry).
              setActiveDiaryId('');
              setTab('diaries');
            }}
          />
        )
      ) : archiveQ.isError ? (
        <Card className="py-12">
          <EmptyState
            icon={<AlertTriangle size={22} />}
            title={t('common.error', { defaultValue: 'Error' })}
            description={t('daily_diary.archive_load_error', {
              defaultValue: 'Failed to load the archive. Please try again.',
            })}
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => void archiveQ.refetch(),
            }}
          />
        </Card>
      ) : (
        <ArchiveTab
          diaries={archiveQ.data ?? []}
          loading={archiveQ.isLoading}
        />
      )}

      {createOpen && projectId && (
        <CreateDiaryModal
          projectId={projectId}
          initialDate={createDate || undefined}
          onClose={() => setCreateOpen(false)}
          onCreated={(diary) => {
            // Jump straight into the freshly-created day so the user lands on
            // the editable record they just opened from the calendar.
            setActiveDiaryId(diary.id);
            setTab('today');
          }}
        />
      )}
      {signOpen && activeDiary && (
        <SignDiaryModal
          diaryId={activeDiary.id}
          onClose={() => setSignOpen(false)}
        />
      )}

      {/* Mobile PWA — Slice 1. Bottom-anchored quick-action FAB visible
          only on viewports ≤640px so field crews on phones reach the
          primary action without scrolling. ≥44×44 tap target. */}
      <button
        type="button"
        onClick={() => openCreate()}
        disabled={!projectId}
        aria-label={t('daily_diary.new_diary', { defaultValue: 'New Diary' })}
        className="fixed bottom-5 right-5 z-40 inline-flex h-14 w-14 min-h-[44px] min-w-[44px] items-center justify-center rounded-full bg-oe-blue text-white shadow-lg ring-1 ring-black/5 transition-transform hover:scale-105 active:scale-95 disabled:opacity-50 disabled:hover:scale-100 sm:hidden"
      >
        <Plus size={22} />
      </button>
    </div>
  );
}

/* ── Diaries calendar tab ────────────────────────────────────────────── */

function DiariesCalendar({
  diaries,
  loading,
  year,
  month,
  locale,
  onYearChange,
  onMonthChange,
  onDayClick,
  onEmptyDayClick,
}: {
  diaries: DailyDiary[];
  loading: boolean;
  year: number;
  month: number;
  locale: string;
  onYearChange: (y: number) => void;
  onMonthChange: (m: number) => void;
  onDayClick: (diary: DailyDiary) => void;
  /** Open the create flow prefilled with this YYYY-MM-DD (empty, allowed day). */
  onEmptyDayClick: (iso: string) => void;
}) {
  const { t } = useTranslation();
  // Roving-tabindex focus target so arrow keys can walk the grid. Defaults to
  // today when it's in the visible month, else the first of the month.
  const initialFocus = useMemo(() => {
    const ti = todayIso();
    return ti.startsWith(`${year}-${String(month + 1).padStart(2, '0')}`)
      ? Number(ti.slice(8, 10))
      : 1;
  }, [year, month]);
  const [focusedDay, setFocusedDay] = useState(initialFocus);
  useEffect(() => setFocusedDay(initialFocus), [initialFocus]);

  const byDate = useMemo(() => {
    const map = new Map<string, DailyDiary>();
    for (const d of diaries) {
      map.set(d.diary_date, d);
    }
    return map;
  }, [diaries]);

  const daysCount = daysInMonth(year, month);
  const firstWeekday = new Date(year, month, 1).getDay(); // 0=Sun
  const offset = (firstWeekday + 6) % 7; // ISO Mon=0
  const maxIso = maxDiaryIso();

  const prevMonth = () => {
    if (month === 0) {
      onYearChange(year - 1);
      onMonthChange(11);
    } else {
      onMonthChange(month - 1);
    }
  };
  const nextMonth = () => {
    if (month === 11) {
      onYearChange(year + 1);
      onMonthChange(0);
    } else {
      onMonthChange(month + 1);
    }
  };

  const activate = (day: number) => {
    const iso = isoDate(year, month, day);
    const diary = byDate.get(iso);
    if (diary) {
      onDayClick(diary);
    } else if (iso <= maxIso) {
      onEmptyDayClick(iso);
    }
    // A future empty day is a no-op — the cell carries a tooltip explaining
    // why it can't be opened (mirrors the backend future-date rejection).
  };

  // Arrow keys move focus by ±1 / ±7 days within the month; Home/End jump to
  // the month edges; Enter/Space activate. Focus is moved imperatively to the
  // newly-focused cell so screen readers and sighted keyboard users track it.
  const onGridKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    let next = focusedDay;
    switch (e.key) {
      case 'ArrowRight':
        next = Math.min(daysCount, focusedDay + 1);
        break;
      case 'ArrowLeft':
        next = Math.max(1, focusedDay - 1);
        break;
      case 'ArrowDown':
        next = Math.min(daysCount, focusedDay + 7);
        break;
      case 'ArrowUp':
        next = Math.max(1, focusedDay - 7);
        break;
      case 'Home':
        next = 1;
        break;
      case 'End':
        next = daysCount;
        break;
      case 'Enter':
      case ' ':
        e.preventDefault();
        activate(focusedDay);
        return;
      default:
        return;
    }
    e.preventDefault();
    if (next !== focusedDay) {
      setFocusedDay(next);
      const el = document.getElementById(`dd-cell-${isoDate(year, month, next)}`);
      el?.focus();
    }
  };

  const weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  return (
    <Card padding="md">
      <div className="flex items-center justify-between mb-3">
        <button
          type="button"
          onClick={prevMonth}
          className="rounded-md p-1.5 hover:bg-surface-secondary focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
          aria-label={t('daily_diary.prev_month', { defaultValue: 'Previous month' })}
        >
          <ChevronLeft size={16} />
        </button>
        <h3 className="text-base font-semibold" aria-live="polite">
          {fmtMonth(year, month, locale)}
        </h3>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              const now = new Date();
              onYearChange(now.getFullYear());
              onMonthChange(now.getMonth());
            }}
          >
            {t('daily_diary.today', { defaultValue: 'Today' })}
          </Button>
          <button
            type="button"
            onClick={nextMonth}
            className="rounded-md p-1.5 hover:bg-surface-secondary focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
            aria-label={t('daily_diary.next_month', { defaultValue: 'Next month' })}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      <p className="mb-3 text-xs text-content-tertiary">
        {t('daily_diary.calendar_hint', {
          defaultValue:
            'Click a day to open its diary, or an empty day to start one. Arrow keys move between days, Enter opens.',
        })}
      </p>

      {loading ? (
        <SkeletonTable rows={5} columns={7} />
      ) : (
        <>
          <div className="grid grid-cols-7 gap-1 mb-2">
            {weekdays.map((w) => (
              <div
                key={w}
                className="px-1 py-1 text-center text-2xs font-medium uppercase tracking-wide text-content-tertiary"
              >
                {t(`daily_diary.weekday_${w.toLowerCase()}`, { defaultValue: w })}
              </div>
            ))}
          </div>
          <div
            role="grid"
            aria-label={fmtMonth(year, month, locale)}
            className="grid grid-cols-7 gap-1"
            onKeyDown={onGridKeyDown}
          >
            {Array.from({ length: offset }, (_, i) => (
              <div key={`pad-${i}`} className="h-20" role="presentation" />
            ))}
            {Array.from({ length: daysCount }, (_, i) => {
              const day = i + 1;
              const iso = isoDate(year, month, day);
              const diary = byDate.get(iso);
              const isToday = iso === todayIso();
              const isFuture = !diary && iso > maxIso;
              const labour = diary?.labour_count ?? 0;
              const equipment = diary?.equipment_count ?? 0;
              const cellLabel = diary
                ? t('daily_diary.cell_open', {
                    defaultValue: '{{date}} - open diary ({{status}})',
                    date: iso,
                    status: statusLabel(t, diary.status),
                  })
                : isFuture
                  ? t('daily_diary.cell_future', {
                      defaultValue:
                        '{{date}} - a site diary cannot be opened this far ahead',
                      date: iso,
                    })
                  : t('daily_diary.cell_empty', {
                      defaultValue: '{{date}} - start a diary',
                      date: iso,
                    });
              return (
                <button
                  key={iso}
                  id={`dd-cell-${iso}`}
                  type="button"
                  role="gridcell"
                  tabIndex={day === focusedDay ? 0 : -1}
                  onFocus={() => setFocusedDay(day)}
                  onClick={() => activate(day)}
                  disabled={isFuture}
                  aria-label={cellLabel}
                  title={
                    isFuture
                      ? t('daily_diary.cell_future_tooltip', {
                          defaultValue:
                            'Future-dated site diaries are not allowed - a diary is a contemporaneous record.',
                        })
                      : undefined
                  }
                  className={clsx(
                    'group relative h-20 rounded-md border p-1.5 text-left transition-colors flex flex-col focus:outline-none focus:ring-2 focus:ring-oe-blue/50',
                    diary
                      ? 'border-border-light bg-surface-elevated hover:border-oe-blue hover:shadow-sm cursor-pointer'
                      : isFuture
                        ? 'border-dashed border-border-light/40 bg-transparent text-content-tertiary cursor-not-allowed opacity-60'
                        : 'border-dashed border-border-light/60 bg-transparent text-content-tertiary hover:border-oe-blue hover:text-oe-blue hover:bg-oe-blue-subtle/10 cursor-pointer',
                    isToday && 'ring-2 ring-oe-blue/30',
                  )}
                >
                  <span className="text-xs font-semibold">{day}</span>
                  {diary ? (
                    <>
                      <Badge variant={STATUS_VARIANT[diary.status]} size="sm" dot>
                        {statusLabel(t, diary.status)}
                      </Badge>
                      <div className="mt-auto flex items-center gap-2 text-2xs text-content-tertiary">
                        {labour > 0 && (
                          <span
                            className="inline-flex items-center gap-0.5"
                            title={t('daily_diary.labour', { defaultValue: 'Labour' })}
                          >
                            <Users size={9} />
                            {labour}
                          </span>
                        )}
                        {equipment > 0 && (
                          <span
                            className="inline-flex items-center gap-0.5"
                            title={t('daily_diary.equipment', { defaultValue: 'Equipment' })}
                          >
                            <Package size={9} />
                            {equipment}
                          </span>
                        )}
                        {diary.status === 'signed' && (
                          <Lock size={9} className="ml-auto text-semantic-success" />
                        )}
                      </div>
                    </>
                  ) : (
                    !isFuture && (
                      <Plus
                        size={14}
                        className="mt-auto self-end text-content-tertiary opacity-0 transition-opacity group-hover:opacity-100"
                      />
                    )
                  )}
                </button>
              );
            })}
          </div>
        </>
      )}
    </Card>
  );
}

/* ── Today tab ───────────────────────────────────────────────────────── */

function TodayTab({
  projectId,
  diary,
  loading,
  onCreate,
  onSign,
  onDeleted,
}: {
  projectId: string;
  diary: DailyDiary | undefined;
  loading: boolean;
  onCreate: () => void;
  onSign: () => void;
  onDeleted: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const confirmCtx = useConfirm();

  // Modal toggles for the newly-wired asset/lifecycle actions.
  const [photoOpen, setPhotoOpen] = useState(false);
  const [weatherOpen, setWeatherOpen] = useState(false);
  const [droneOpen, setDroneOpen] = useState(false);
  const [realityOpen, setRealityOpen] = useState(false);
  const [sclOpen, setSclOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);

  // All asset panels are scoped to the diary's OWN date — not todayIso().
  // A diary opened from the calendar can be any past day; previously the
  // panels always queried today, so a back-dated diary showed today's
  // weather/photos beside a header for a different date.
  const diaryDate = diary?.diary_date;
  const diaryId = diary?.id;

  // Project record carries the geocoded address coords used to fetch real
  // weather from Open-Meteo for the diary's location.
  const projectQ = useQuery({
    queryKey: ['daily-diary', 'project', projectId],
    queryFn: () => projectsApi.get(projectId),
    enabled: !!projectId,
  });
  const projectCoords = useMemo(() => {
    const addr = projectQ.data?.address;
    if (addr && addr.lat != null && addr.lng != null) {
      return { lat: addr.lat, lng: addr.lng };
    }
    return null;
  }, [projectQ.data]);

  const weatherQ = useQuery({
    queryKey: ['daily-diary', 'weather', projectId, diaryDate],
    queryFn: () => weatherToday(projectId, diaryDate),
    enabled: !!projectId && !!diaryDate,
  });

  const photosQ = useQuery({
    queryKey: ['daily-diary', 'photos', projectId, diaryDate],
    queryFn: () =>
      listPhotos({
        project_id: projectId,
        date_from: `${diaryDate}T00:00:00`,
        date_to: `${diaryDate}T23:59:59`,
        limit: 200,
      }),
    enabled: !!projectId && !!diaryDate,
  });

  const droneQ = useQuery({
    queryKey: ['daily-diary', 'drone', projectId],
    queryFn: () => listDroneSurveys(projectId),
    enabled: !!projectId,
  });

  const realityQ = useQuery({
    queryKey: ['daily-diary', 'reality', projectId],
    queryFn: () => listRealityCaptures(projectId),
    enabled: !!projectId,
  });

  const signaturesQ = useQuery({
    queryKey: ['daily-diary', 'signatures', diaryId],
    queryFn: () => listArchiveSignatures(diaryId as string),
    enabled: !!diaryId && diary?.status === 'signed',
  });

  const closeMut = useMutation({
    mutationFn: (id: string) => closeDiary(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['daily-diary'] });
      addToast({ type: 'success', title: t('daily_diary.closed', { defaultValue: 'Diary closed' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteDiary(id),
    onSuccess: () => {
      // Invalidate every cached daily-diary query so the calendar grid,
      // today-resolver and archive list all re-fetch (the deleted day
      // must disappear from the calendar dot rendering).
      qc.invalidateQueries({ queryKey: ['daily-diary'] });
      addToast({
        type: 'success',
        title: t('daily_diary.deleted', { defaultValue: 'Diary deleted' }),
      });
      onDeleted();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
    onSettled: () => confirmCtx.setLoading(false),
  });

  const exportPdfMut = useMutation({
    mutationFn: (d: DailyDiary) => downloadDiaryPdf(d.id, d.diary_date),
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('daily_diary.pdf_downloaded', { defaultValue: 'Diary PDF downloaded' }),
      }),
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  // Readiness signal shown as a traffic-light chip before signing, and the
  // workforce roll-up surfaced beside the diary meta — both are headline
  // backend capabilities that previously had no UI surface.
  const completenessQ = useQuery({
    queryKey: ['daily-diary', 'completeness', diaryId],
    queryFn: () => diaryCompleteness(diaryId as string),
    enabled: !!diaryId,
  });

  const workforceQ = useQuery({
    queryKey: ['daily-diary', 'workforce', diaryId],
    queryFn: () => diaryWorkforceSummary(diaryId as string),
    enabled: !!diaryId,
  });

  const fetchWeatherMut = useMutation({
    mutationFn: (args: { lat: number; lng: number }) =>
      fetchWeather({
        project_id: projectId,
        target_date: diaryDate as string,
        lat: args.lat,
        lng: args.lng,
        persist: true,
      }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['daily-diary', 'weather'] });
      qc.invalidateQueries({ queryKey: ['daily-diary', 'completeness'] });
      addToast({
        type: res.fetched ? 'success' : 'warning',
        title: res.fetched
          ? t('daily_diary.weather_fetched', { defaultValue: 'Weather fetched from Open-Meteo' })
          : t('daily_diary.weather_unavailable', {
              defaultValue: 'No weather data available for that date.',
            }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const unlockMut = useMutation({
    mutationFn: (id: string) => unlockDiary(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['daily-diary'] });
      addToast({
        type: 'success',
        title: t('daily_diary.unlocked', { defaultValue: 'Diary unlocked for amendment' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
    onSettled: () => confirmCtx.setLoading(false),
  });

  const archiveMut = useMutation({
    mutationFn: (id: string) => archiveDiary(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['daily-diary'] });
      addToast({
        type: 'success',
        title: t('daily_diary.archived', { defaultValue: 'Diary archived' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
    onSettled: () => confirmCtx.setLoading(false),
  });

  const handleFetchWeather = () => {
    if (!projectCoords) {
      addToast({
        type: 'error',
        title: t('daily_diary.weather_no_coords', {
          defaultValue:
            'This project has no map location yet. Set the project address to auto-fetch weather, or add a reading manually.',
        }),
      });
      return;
    }
    fetchWeatherMut.mutate(projectCoords);
  };

  const handleUnlock = async () => {
    if (!diary) return;
    const ok = await confirmCtx.confirm({
      title: t('daily_diary.confirm_unlock_title', {
        defaultValue: 'Unlock this signed diary?',
      }),
      message: t('daily_diary.confirm_unlock_message', {
        defaultValue:
          'The original sha256 signature is preserved and continues to point at the pre-edit snapshot, so the integrity break is recorded and traceable. Re-sign after amending.',
      }),
      confirmLabel: t('daily_diary.unlock', { defaultValue: 'Unlock' }),
      variant: 'danger',
    });
    if (!ok) return;
    confirmCtx.setLoading(true);
    unlockMut.mutate(diary.id);
  };

  const handleArchive = async () => {
    if (!diary) return;
    const ok = await confirmCtx.confirm({
      title: t('daily_diary.confirm_archive_title', {
        defaultValue: 'Archive this diary?',
      }),
      message: t('daily_diary.confirm_archive_message', {
        defaultValue:
          'An archived diary is read-only and can no longer be unlocked or amended. It stays in the signed-record archive.',
      }),
      confirmLabel: t('daily_diary.archive', { defaultValue: 'Archive' }),
      variant: 'danger',
    });
    if (!ok) return;
    confirmCtx.setLoading(true);
    archiveMut.mutate(diary.id);
  };

  const handleDelete = async () => {
    if (!diary) return;
    const ok = await confirmCtx.confirm({
      title: t('daily_diary.confirm_delete_title', {
        defaultValue: 'Delete this diary?',
      }),
      message: t('daily_diary.confirm_delete_message', {
        defaultValue:
          'This permanently removes the diary, its entries and links to weather/photos. This cannot be undone.',
      }),
      confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
      variant: 'danger',
    });
    if (!ok) return;
    confirmCtx.setLoading(true);
    deleteMut.mutate(diary.id);
  };

  const sealed = diary?.status === 'signed' || diary?.status === 'archived';

  if (loading) {
    return (
      <Card padding="md">
        <SkeletonTable rows={6} columns={3} />
      </Card>
    );
  }

  if (!diary) {
    return (
      <Card>
        <EmptyState
          icon={<BookOpen size={22} />}
          title={t('daily_diary.no_diary_today', { defaultValue: 'No diary for today yet' })}
          description={t('daily_diary.no_diary_today_desc', {
            defaultValue: 'Start today’s diary to log weather, entries, and photos.',
          })}
          action={{
            label: t('daily_diary.new_diary', { defaultValue: 'New Diary' }),
            onClick: onCreate,
          }}
        />
      </Card>
    );
  }

  // signatures_for_diary returns revision-ascending; the latest signed
  // snapshot (after any re-sign) is the LAST element, not [0].
  const latestSignature = signaturesQ.data?.[signaturesQ.data.length - 1];
  // Most recent reading of the day is first (captured_at desc).
  const latestWeather: WeatherRecord | undefined = weatherQ.data?.[0];

  return (
    <div className="space-y-4">
      {/* Header bar with sealed status */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold">
            <DateDisplay value={diary.diary_date} />
          </h2>
          <Badge variant={STATUS_VARIANT[diary.status]} dot>
            {statusLabel(t, diary.status)}
          </Badge>
          {sealed && (
            <span className="inline-flex items-center gap-1.5 rounded-md bg-semantic-success-bg px-2 py-1 text-xs font-medium text-semantic-success">
              <Lock size={12} />
              {t('daily_diary.sealed', { defaultValue: 'Sealed' })}
            </span>
          )}
          {!sealed && completenessQ.data && (
            <CompletenessChip data={completenessQ.data} />
          )}
        </div>
        <div className="flex gap-2">
          <Button
            variant="ghost"
            size="sm"
            icon={<FileDown size={14} />}
            onClick={() => exportPdfMut.mutate(diary)}
            loading={exportPdfMut.isPending}
            data-testid="daily-diary-export-pdf"
            aria-label={t('daily_diary.export_pdf', { defaultValue: 'Export PDF' })}
          >
            {t('daily_diary.export_pdf', { defaultValue: 'Export PDF' })}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            icon={<Package size={14} />}
            onClick={() => setSclOpen(true)}
            data-testid="daily-diary-scl-bundle"
            aria-label={t('daily_diary.scl_bundle', {
              defaultValue: 'SCL evidence bundle',
            })}
            title={t('daily_diary.scl_bundle_hint', {
              defaultValue:
                'Build a hash-sealed SCL Protocol contemporary-record bundle for a date range (delay-claim evidence).',
            })}
          >
            {t('daily_diary.scl_bundle', { defaultValue: 'SCL bundle' })}
          </Button>
          {sealed && diary.status === 'signed' && (
            <Button
              variant="secondary"
              size="sm"
              icon={<LockOpen size={14} />}
              onClick={handleUnlock}
              loading={unlockMut.isPending}
              data-testid="daily-diary-unlock"
              aria-label={t('daily_diary.unlock_to_amend', {
                defaultValue: 'Unlock to amend',
              })}
            >
              {t('daily_diary.unlock_to_amend', { defaultValue: 'Unlock to amend' })}
            </Button>
          )}
          {diary.status === 'signed' && (
            <Button
              variant="ghost"
              size="sm"
              icon={<Archive size={14} />}
              onClick={handleArchive}
              loading={archiveMut.isPending}
              data-testid="daily-diary-archive"
              aria-label={t('daily_diary.archive', { defaultValue: 'Archive' })}
            >
              {t('daily_diary.archive', { defaultValue: 'Archive' })}
            </Button>
          )}
          {!sealed && (
            <Button
              variant="ghost"
              size="sm"
              icon={<Pencil size={14} />}
              onClick={() => setEditOpen(true)}
              data-testid="daily-diary-edit"
              aria-label={t('daily_diary.edit_diary', { defaultValue: 'Edit diary' })}
            >
              {t('common.edit', { defaultValue: 'Edit' })}
            </Button>
          )}
          {diary.status === 'open' && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => closeMut.mutate(diary.id)}
              loading={closeMut.isPending}
            >
              {t('daily_diary.close_diary', { defaultValue: 'Close Diary' })}
            </Button>
          )}
          {(diary.status === 'open' || diary.status === 'closed') && (
            <Button
              variant="primary"
              size="sm"
              icon={<FileSignature size={14} />}
              onClick={onSign}
            >
              {t('daily_diary.sign_diary', { defaultValue: 'Sign Diary' })}
            </Button>
          )}
          {/* Delete is intentionally gated to non-sealed diaries; the
              backend rejects DELETE on signed/archived with 409 for
              legal-record integrity, so don't even expose the button.
              W22 audit fix — was previously orphan-able. */}
          {!sealed && (
            <Button
              variant="ghost"
              size="sm"
              icon={<Trash2 size={14} />}
              onClick={handleDelete}
              loading={deleteMut.isPending}
              data-testid="daily-diary-delete"
              aria-label={t('daily_diary.delete_diary', { defaultValue: 'Delete diary' })}
            >
              {t('common.delete', { defaultValue: 'Delete' })}
            </Button>
          )}
        </div>
      </div>
      <ConfirmDialog
        open={confirmCtx.open}
        title={confirmCtx.title}
        message={confirmCtx.message}
        confirmLabel={confirmCtx.confirmLabel}
        cancelLabel={confirmCtx.cancelLabel}
        variant={confirmCtx.variant}
        loading={confirmCtx.loading}
        onConfirm={confirmCtx.onConfirm}
        onCancel={confirmCtx.onCancel}
      />

      {sealed && latestSignature && (
        <Card padding="md" className="border-semantic-success/30 bg-semantic-success-bg/30">
          <div className="flex items-start gap-3">
            <Lock size={18} className="text-semantic-success mt-0.5" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold">
                {t('daily_diary.signed_at', { defaultValue: 'Signed' })}{' '}
                <DateDisplay value={latestSignature.signed_at} />
              </p>
              <p className="mt-1 font-mono text-xs text-content-secondary break-all">
                sha256: {formatSha(latestSignature.content_sha256)}
              </p>
            </div>
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <WeatherCard
          weather={latestWeather}
          loading={weatherQ.isLoading}
          sealed={sealed}
          fetching={fetchWeatherMut.isPending}
          onFetch={handleFetchWeather}
          onAddManual={() => setWeatherOpen(true)}
        />
        <Card padding="md" className="xl:col-span-2">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-content-secondary">
              {t('daily_diary.diary_meta', { defaultValue: 'Diary' })}
            </h3>
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1 text-xs text-content-tertiary">
                <Users size={12} />
                {t('daily_diary.workforce', { defaultValue: 'Workforce' })}
              </span>
              <button
                type="button"
                onClick={() => navigate('/payroll')}
                className="inline-flex items-center gap-1 rounded-md border border-border-light bg-surface-primary px-2 py-1 text-2xs font-medium text-oe-blue hover:bg-oe-blue-subtle/10"
                title={t('daily_diary.workforce_to_payroll_hint', {
                  defaultValue: 'The headcount you log here flows into the labour roster used by Payroll.',
                })}
                data-testid="daily-diary-workforce-payroll"
              >
                <Wallet size={11} />
                {t('daily_diary.view_in_payroll', { defaultValue: 'Payroll' })}
              </button>
            </div>
          </div>
          <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-xs uppercase tracking-wide text-content-tertiary">
                {t('daily_diary.labour', { defaultValue: 'Labour' })}
              </dt>
              <dd className="text-base font-semibold">{diary.labour_count}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-content-tertiary">
                {t('daily_diary.equipment', { defaultValue: 'Equipment' })}
              </dt>
              <dd className="text-base font-semibold">{diary.equipment_count}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-content-tertiary">
                {t('daily_diary.date', { defaultValue: 'Date' })}
              </dt>
              <dd className="text-sm">
                <DateDisplay value={diary.diary_date} />
              </dd>
            </div>
          </dl>
          {workforceQ.data &&
            Object.keys(workforceQ.data.by_company).length > 0 && (
              <div className="mt-3 border-t border-border-light pt-3">
                <p className="mb-1.5 text-xs uppercase tracking-wide text-content-tertiary">
                  {t('daily_diary.by_company', { defaultValue: 'By company' })}
                </p>
                <ul className="flex flex-wrap gap-2">
                  {Object.entries(workforceQ.data.by_company).map(
                    ([company, count]) => (
                      <li
                        key={company}
                        className="inline-flex items-center gap-1.5 rounded-full border border-border-light bg-surface-secondary/40 px-2.5 py-1 text-xs"
                      >
                        <span className="font-medium">{company}</span>
                        <span className="text-content-tertiary">{count}</span>
                      </li>
                    ),
                  )}
                </ul>
              </div>
            )}
          {diary.notes && (
            <p className="mt-4 text-sm text-content-secondary whitespace-pre-wrap">
              {diary.notes}
            </p>
          )}
        </Card>
      </div>

      <EntriesTimeline projectId={projectId} diaryId={diary.id} sealed={sealed} />

      <PhotoGrid
        photos={photosQ.data ?? []}
        loading={photosQ.isLoading}
        sealed={sealed}
        onUpload={() => setPhotoOpen(true)}
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <DroneSection
          surveys={droneQ.data ?? []}
          loading={droneQ.isLoading}
          sealed={sealed}
          onAttach={() => setDroneOpen(true)}
        />
        <RealitySection
          captures={realityQ.data ?? []}
          loading={realityQ.isLoading}
          sealed={sealed}
          onAttach={() => setRealityOpen(true)}
        />
      </div>

      {photoOpen && diaryId && diaryDate && (
        <PhotoUploadModal
          projectId={projectId}
          diaryId={diaryId}
          diaryDate={diaryDate}
          onClose={() => setPhotoOpen(false)}
        />
      )}
      {weatherOpen && diaryDate && (
        <ManualWeatherModal
          projectId={projectId}
          diaryDate={diaryDate}
          onClose={() => setWeatherOpen(false)}
        />
      )}
      {droneOpen && diaryDate && (
        <DroneSurveyModal
          projectId={projectId}
          diaryDate={diaryDate}
          onClose={() => setDroneOpen(false)}
        />
      )}
      {realityOpen && diaryDate && (
        <RealityCaptureModal
          projectId={projectId}
          diaryDate={diaryDate}
          onClose={() => setRealityOpen(false)}
        />
      )}
      {sclOpen && (
        <SclBundleModal
          projectId={projectId}
          diaryDate={diaryDate ?? todayIso()}
          onClose={() => setSclOpen(false)}
        />
      )}
      {editOpen && (
        <EditDiaryModal diary={diary} onClose={() => setEditOpen(false)} />
      )}
    </div>
  );
}

/* ── Edit diary modal ──────────────────────────────────────────────────────
 *
 * Amend the diary's own fields (labour / equipment headcount, notes) via the
 * real PATCH /diaries/{id} endpoint. The backend rejects edits on
 * signed/archived diaries (409), so this is only surfaced for open/closed
 * records — matching the immutability rule in service.update_diary.
 */
function EditDiaryModal({
  diary,
  onClose,
}: {
  diary: DailyDiary;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [labour, setLabour] = useState(diary.labour_count);
  const [equipment, setEquipment] = useState(diary.equipment_count);
  const [notes, setNotes] = useState(diary.notes ?? '');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await updateDiary(diary.id, {
        labour_count: labour,
        equipment_count: equipment,
        notes,
      });
      // Refresh the diary record, its by-id view and the calendar signals.
      qc.invalidateQueries({ queryKey: ['daily-diary'] });
      addToast({
        type: 'success',
        title: t('daily_diary.updated', { defaultValue: 'Diary updated' }),
      });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      size="lg"
      title={t('daily_diary.edit_diary', { defaultValue: 'Edit diary' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={submit} loading={busy}>
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('daily_diary.date', { defaultValue: 'Date' })} span={2}>
          {/* The diary date is the record's identity and is immutable once
              opened — shown read-only so the editor is unambiguous. */}
          <div className="flex h-9 items-center rounded-lg border border-border bg-surface-secondary/40 px-3 text-sm text-content-secondary">
            <DateDisplay value={diary.diary_date} />
          </div>
        </WideModalField>
        <WideModalField label={t('daily_diary.labour', { defaultValue: 'Labour' })}>
          <input
            type="number"
            min={0}
            value={labour}
            onChange={(e) => setLabour(Number(e.target.value) || 0)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('daily_diary.equipment', { defaultValue: 'Equipment' })}>
          <input
            type="number"
            min={0}
            value={equipment}
            onChange={(e) => setEquipment(Number(e.target.value) || 0)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('common.notes')} span={2}>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className={clsx(inputCls, 'h-auto py-2')}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Completeness readiness chip ─────────────────────────────────────────
 *
 * Surfaces the backend completeness score (0..1) as a traffic-light chip so
 * a supervisor sees how "ready to sign" a diary is, and which blocks are
 * still missing, before sealing it. Green ≥ 0.8, amber ≥ 0.5, else red.
 */
function CompletenessChip({ data }: { data: DiaryCompleteness }) {
  const { t } = useTranslation();
  const pct = Math.round(Number(data.completeness ?? 0) * 100);
  const tone =
    pct >= 80
      ? 'bg-semantic-success-bg text-semantic-success'
      : pct >= 50
        ? 'bg-semantic-warning-bg text-semantic-warning'
        : 'bg-semantic-error-bg text-semantic-error';
  const missingLabels = data.missing
    .map((m) =>
      t(`daily_diary.completeness_block.${m}`, {
        defaultValue: m.replace(/_/g, ' '),
      }),
    )
    .join(', ');
  const title =
    data.missing.length > 0
      ? t('daily_diary.completeness_missing', {
          defaultValue: 'Still missing: {{items}}',
          items: missingLabels,
        })
      : t('daily_diary.completeness_ready', {
          defaultValue: 'All recommended blocks present - ready to sign.',
        });
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium',
        tone,
      )}
      title={title}
    >
      <CheckCircle2 size={12} />
      {t('daily_diary.completeness_chip', {
        defaultValue: '{{pct}}% complete',
        pct,
      })}
    </span>
  );
}

function WeatherCard({
  weather,
  loading,
  sealed,
  fetching,
  onFetch,
  onAddManual,
}: {
  weather: WeatherRecord | undefined;
  loading: boolean;
  sealed: boolean;
  fetching: boolean;
  onFetch: () => void;
  onAddManual: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Card padding="md">
      <div className="flex items-center gap-2 mb-3">
        <Cloud size={16} className="text-oe-blue" />
        <h3 className="text-sm font-semibold uppercase tracking-wide text-content-secondary">
          {t('daily_diary.weather', { defaultValue: 'Weather' })}
        </h3>
        {!sealed && (
          <div className="ml-auto flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              icon={<CloudDownload size={13} />}
              onClick={onFetch}
              loading={fetching}
              data-testid="daily-diary-fetch-weather"
              title={t('daily_diary.fetch_weather_hint', {
                defaultValue:
                  'Pull the day’s real weather from Open-Meteo for the project location.',
              })}
            >
              {t('daily_diary.fetch_weather', { defaultValue: 'Fetch' })}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              icon={<Plus size={13} />}
              onClick={onAddManual}
              data-testid="daily-diary-add-weather"
              title={t('daily_diary.add_weather_hint', {
                defaultValue: 'Record a weather reading manually.',
              })}
            >
              {t('daily_diary.add_weather', { defaultValue: 'Manual' })}
            </Button>
          </div>
        )}
      </div>
      {loading ? (
        <SkeletonTable rows={3} columns={2} />
      ) : !weather ? (
        <p className="text-sm text-content-tertiary py-4">
          {t('daily_diary.no_weather', { defaultValue: 'No reading yet.' })}
        </p>
      ) : (
        <dl className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt className="text-xs uppercase tracking-wide text-content-tertiary">
              {t('daily_diary.temp', { defaultValue: 'Temperature' })}
            </dt>
            <dd className="text-base font-semibold">
              {weather.temperature_c != null ? `${weather.temperature_c}°C` : '—'}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-content-tertiary">
              {t('daily_diary.humidity', { defaultValue: 'Humidity' })}
            </dt>
            <dd className="text-base font-semibold">
              {weather.humidity_pct != null ? `${weather.humidity_pct}%` : '—'}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-content-tertiary">
              {t('daily_diary.wind', { defaultValue: 'Wind' })}
            </dt>
            <dd className="text-base font-semibold">
              {weather.wind_speed_kmh != null ? `${weather.wind_speed_kmh} km/h` : '—'}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-content-tertiary">
              {t('daily_diary.precip', { defaultValue: 'Precipitation' })}
            </dt>
            <dd className="text-base font-semibold">
              {weather.precipitation_mm != null ? `${weather.precipitation_mm} mm` : '—'}
            </dd>
          </div>
          {weather.conditions_text && (
            <div className="col-span-2">
              <dt className="text-xs uppercase tracking-wide text-content-tertiary">
                {t('daily_diary.conditions', { defaultValue: 'Conditions' })}
              </dt>
              <dd className="text-sm">{weather.conditions_text}</dd>
            </div>
          )}
        </dl>
      )}
    </Card>
  );
}

// Diary entry types that summarise an upstream record from another module.
// Picking one of these surfaces a source picker so the entry can deep-link
// back to the incident / inspection it documents (CONN-49).
const SOURCE_ENTRY_MODULE: Partial<Record<EntryType, 'safety' | 'inspections'>> = {
  incident_summary: 'safety',
  inspection_summary: 'inspections',
};

interface SourceRecord {
  id: string;
  label: string;
}

function EntriesTimeline({
  projectId,
  diaryId,
  sealed,
}: {
  projectId: string;
  diaryId: string;
  sealed: boolean;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [entryType, setEntryType] = useState<EntryType>('general');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [sourceRef, setSourceRef] = useState('');
  const [busy, setBusy] = useState(false);

  // Which upstream module (if any) the chosen entry type links back to.
  const sourceModule = SOURCE_ENTRY_MODULE[entryType];

  // Previously this component only rendered an add-form: created entries
  // were invisible (no list endpoint, no list query). It now reads back
  // the diary's entries so the timeline actually shows them.
  const entriesQ = useQuery({
    queryKey: ['daily-diary', 'entries', diaryId],
    queryFn: () => listEntries(diaryId),
    enabled: !!diaryId,
  });

  // Lightweight pickers: when the entry summarises an incident or an
  // inspection, fetch the project's records so the user can link the exact
  // one (stored as source_module + source_ref) instead of pasting a UUID.
  const incidentsQ = useQuery({
    queryKey: ['daily-diary', 'src-incidents', projectId],
    queryFn: async () => {
      const rows = await apiGet<Record<string, unknown>[]>(
        `/v1/safety/incidents/?project_id=${encodeURIComponent(projectId)}`,
      );
      return rows.map((r) => ({
        id: String(r.id),
        label: [r.incident_number, r.description]
          .filter(Boolean)
          .map(String)
          .join(' - ')
          .slice(0, 80),
      })) as SourceRecord[];
    },
    enabled: !!projectId && sourceModule === 'safety',
  });

  const inspectionsQ = useQuery({
    queryKey: ['daily-diary', 'src-inspections', projectId],
    queryFn: async () => {
      const rows = await apiGet<Record<string, unknown>[]>(
        `/v1/inspections/?project_id=${encodeURIComponent(projectId)}`,
      );
      return rows.map((r) => ({
        id: String(r.id),
        label: [r.inspection_number, r.title]
          .filter(Boolean)
          .map(String)
          .join(' - ')
          .slice(0, 80),
      })) as SourceRecord[];
    },
    enabled: !!projectId && sourceModule === 'inspections',
  });

  const sourceOptions: SourceRecord[] =
    sourceModule === 'safety'
      ? (incidentsQ.data ?? [])
      : sourceModule === 'inspections'
        ? (inspectionsQ.data ?? [])
        : [];

  // Open the upstream record a source-linked entry was raised from.
  // Inspections already consume ?highlight (scroll + flash); Safety lands on
  // the incidents tab today and will consume ?highlight once its batch ships.
  const openSource = (mod: string, ref: string) => {
    if (mod === 'inspections') {
      navigate(`/inspections?highlight=${ref}`);
    } else if (mod === 'safety' || mod === 'hse') {
      navigate(`/safety?highlight=${ref}`);
    }
  };

  const invalidateEntries = () =>
    qc.invalidateQueries({ queryKey: ['daily-diary', 'entries', diaryId] });

  const submit = async () => {
    if (!title.trim()) return;
    setBusy(true);
    try {
      await createEntry({
        diary_id: diaryId,
        entry_type: entryType,
        // Local ISO with offset (NOT toISOString(), which is UTC). The
        // owning diary's ``diary_date`` is a local YYYY-MM-DD so the
        // entry timestamp must agree on the same local calendar day —
        // otherwise an entry created at 02:30 local on 2026-05-21 in
        // Berlin would persist as 2026-05-21T00:30:00Z and read back as
        // belonging to a different day in any UTC-anchored projection.
        entry_time: nowLocalISO(),
        title: title.trim(),
        description: description.trim() || undefined,
        // Provenance: only sent when the entry summarises an upstream record
        // and the user picked one. source_ref is a UUID the backend validates.
        source_module: sourceModule && sourceRef ? sourceModule : undefined,
        source_ref: sourceModule && sourceRef ? sourceRef : undefined,
      });
      setTitle('');
      setDescription('');
      setSourceRef('');
      void invalidateEntries();
      addToast({ type: 'success', title: t('daily_diary.entry_created', { defaultValue: 'Entry added' }) });
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteEntry(id),
    onSuccess: () => {
      void invalidateEntries();
      addToast({ type: 'success', title: t('daily_diary.entry_deleted', { defaultValue: 'Entry removed' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const entries = entriesQ.data ?? [];

  return (
    <Card padding="md">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-content-secondary">
          {t('daily_diary.entries', { defaultValue: 'Entries' })}
        </h3>
        <span className="text-xs text-content-tertiary">{entries.length}</span>
      </div>

      {!sealed && (
        <div className="space-y-2 mb-4">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
            <select
              value={entryType}
              onChange={(e) => {
                setEntryType(e.target.value as EntryType);
                // Clear any previously-picked source when switching types so
                // we never persist an inspection id under an incident entry.
                setSourceRef('');
              }}
              className={inputCls}
            >
              {(
                [
                  'general',
                  'visitor',
                  'event',
                  'delivery',
                  'completion',
                  'incident_summary',
                  'inspection_summary',
                  'photo_note',
                ] as EntryType[]
              ).map((tp) => (
                <option key={tp} value={tp}>
                  {entryTypeLabel(t, tp)}
                </option>
              ))}
            </select>
            <input
              type="text"
              placeholder={t('daily_diary.entry_title', { defaultValue: 'Title' })}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className={clsx(inputCls, 'sm:col-span-2')}
            />
            <Button
              variant="primary"
              size="sm"
              onClick={submit}
              loading={busy}
              disabled={!title.trim()}
              icon={<Plus size={14} />}
            >
              {t('daily_diary.add_entry', { defaultValue: 'Add' })}
            </Button>
          </div>
          <textarea
            placeholder={t('daily_diary.entry_description', { defaultValue: 'Description (optional)' })}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            className={clsx(inputCls, 'h-auto py-2')}
          />
          {sourceModule && (
            <div>
              <label className="mb-1 block text-xs font-medium text-content-secondary">
                {sourceModule === 'safety'
                  ? t('daily_diary.link_incident', { defaultValue: 'Link a safety incident (optional)' })
                  : t('daily_diary.link_inspection', { defaultValue: 'Link a quality inspection (optional)' })}
              </label>
              <select
                value={sourceRef}
                onChange={(e) => setSourceRef(e.target.value)}
                className={inputCls}
                data-testid="daily-diary-entry-source"
              >
                <option value="">
                  {t('daily_diary.link_source_none', { defaultValue: 'No linked record' })}
                </option>
                {sourceOptions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-2xs text-content-tertiary">
                {t('daily_diary.link_source_hint', {
                  defaultValue:
                    'Linking the source record lets the diary entry deep-link back to it for an audit trail.',
                })}
              </p>
            </div>
          )}
        </div>
      )}

      {sealed && (
        <p className="text-xs text-content-tertiary mb-3">
          {t('daily_diary.entries_sealed', { defaultValue: 'Diary is sealed - entries are read-only.' })}
        </p>
      )}

      {entriesQ.isLoading ? (
        <SkeletonTable rows={3} columns={3} />
      ) : entries.length === 0 ? (
        <p className="text-sm text-content-tertiary py-4 text-center">
          {t('daily_diary.no_entries', { defaultValue: 'No entries logged yet.' })}
        </p>
      ) : (
        <ul className="space-y-2">
          {entries.map((e: DiaryEntry) => (
            <li
              key={e.id}
              className="rounded-md border border-border-light bg-surface-secondary/40 p-2.5 text-sm"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <Badge variant="neutral" size="sm">
                      {entryTypeLabel(t, e.entry_type)}
                    </Badge>
                    <span className="font-medium truncate">{e.title || '—'}</span>
                  </div>
                  {e.description && (
                    <p className="mt-1 text-xs text-content-secondary whitespace-pre-wrap">
                      {e.description}
                    </p>
                  )}
                  {e.source_module && e.source_ref && (
                    <button
                      type="button"
                      onClick={() => openSource(e.source_module as string, e.source_ref as string)}
                      className="mt-1.5 inline-flex items-center gap-1 rounded-md border border-border-light bg-surface-primary px-2 py-1 text-2xs font-medium text-oe-blue hover:bg-oe-blue-subtle/10"
                      data-testid="daily-diary-entry-view-source"
                    >
                      <ExternalLink size={11} />
                      {e.source_module === 'inspections'
                        ? t('daily_diary.view_inspection', { defaultValue: 'View inspection' })
                        : e.source_module === 'safety' || e.source_module === 'hse'
                          ? t('daily_diary.view_incident', { defaultValue: 'View incident' })
                          : t('daily_diary.view_source', { defaultValue: 'View source' })}
                    </button>
                  )}
                  <p className="mt-1 text-2xs text-content-tertiary">
                    <DateDisplay value={e.entry_time} />
                  </p>
                </div>
                {!sealed && (
                  <button
                    type="button"
                    onClick={() => deleteMut.mutate(e.id)}
                    disabled={deleteMut.isPending}
                    className="shrink-0 rounded-md p-1 text-content-tertiary hover:bg-surface-secondary hover:text-semantic-danger disabled:opacity-50"
                    aria-label={t('common.delete', { defaultValue: 'Delete' })}
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function PhotoGrid({
  photos,
  loading,
  sealed,
  onUpload,
}: {
  photos: DiaryPhoto[];
  loading: boolean;
  sealed: boolean;
  onUpload: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Card padding="md">
      <div className="flex items-center gap-2 mb-3">
        <Camera size={16} className="text-oe-blue" />
        <h3 className="text-sm font-semibold uppercase tracking-wide text-content-secondary">
          {t('daily_diary.photos', { defaultValue: 'Photos' })}
        </h3>
        <span className="ml-auto text-xs text-content-tertiary">{photos.length}</span>
        {!sealed && (
          <Button
            variant="ghost"
            size="sm"
            icon={<Upload size={13} />}
            onClick={onUpload}
            data-testid="daily-diary-upload-photo"
          >
            {t('daily_diary.upload_photo', { defaultValue: 'Add photo' })}
          </Button>
        )}
      </div>
      {loading ? (
        <SkeletonTable rows={2} columns={6} />
      ) : photos.length === 0 ? (
        <p className="text-sm text-content-tertiary py-4 text-center">
          {t('daily_diary.no_photos', { defaultValue: 'No photos captured yet.' })}
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
          {photos.slice(0, 24).map((p) => (
            <div
              key={p.id}
              className="aspect-square overflow-hidden rounded-md bg-surface-secondary border border-border-light"
            >
              {(p.thumbnail_url || p.file_url) && (
                <img
                  src={p.thumbnail_url || p.file_url}
                  alt={p.description || ''}
                  loading="lazy"
                  className="h-full w-full object-cover"
                />
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function DroneSection({
  surveys,
  loading,
  sealed,
  onAttach,
}: {
  surveys: DroneSurvey[];
  loading: boolean;
  sealed: boolean;
  onAttach: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Card padding="md">
      <div className="flex items-center gap-2 mb-3">
        <Plane size={16} className="text-oe-blue" />
        <h3 className="text-sm font-semibold uppercase tracking-wide text-content-secondary">
          {t('daily_diary.drone', { defaultValue: 'Drone surveys' })}
        </h3>
        <span className="ml-auto text-xs text-content-tertiary">{surveys.length}</span>
        {!sealed && (
          <Button
            variant="ghost"
            size="sm"
            icon={<Plus size={13} />}
            onClick={onAttach}
            data-testid="daily-diary-attach-drone"
          >
            {t('daily_diary.attach_drone', { defaultValue: 'Attach' })}
          </Button>
        )}
      </div>
      {loading ? (
        <SkeletonTable rows={3} columns={3} />
      ) : surveys.length === 0 ? (
        <p className="text-sm text-content-tertiary py-4 text-center">
          {t('daily_diary.no_drone', { defaultValue: 'No drone surveys yet.' })}
        </p>
      ) : (
        <ul className="space-y-2">
          {surveys.slice(0, 5).map((s) => (
            <li
              key={s.id}
              className="rounded-md border border-border-light bg-surface-secondary/40 p-2 text-sm"
            >
              <div className="flex items-center justify-between">
                <span className="font-medium truncate">
                  {s.drone_model || t('daily_diary.unknown_drone', { defaultValue: 'Drone' })}
                </span>
                <span className="text-xs text-content-tertiary">
                  <DateDisplay value={s.flown_at} />
                </span>
              </div>
              {s.area_m2 && (
                <p className="mt-0.5 text-xs text-content-secondary">
                  {String(s.area_m2)} m²
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const CAPTURE_TYPE_LABEL_EN: Record<CaptureType, string> = {
  laser_scan: 'Laser scan',
  photogrammetry: 'Photogrammetry',
  mobile_scan: 'Mobile scan',
};

function captureTypeLabel(t: TFn, type: CaptureType): string {
  return t(`daily_diary.capture_type.${type}`, {
    defaultValue: CAPTURE_TYPE_LABEL_EN[type] ?? type,
  });
}

function RealitySection({
  captures,
  loading,
  sealed,
  onAttach,
}: {
  captures: RealityCapture[];
  loading: boolean;
  sealed: boolean;
  onAttach: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Card padding="md">
      <div className="flex items-center gap-2 mb-3">
        <Scan size={16} className="text-oe-blue" />
        <h3 className="text-sm font-semibold uppercase tracking-wide text-content-secondary">
          {t('daily_diary.reality_capture', { defaultValue: 'Reality captures' })}
        </h3>
        <span className="ml-auto text-xs text-content-tertiary">{captures.length}</span>
        {!sealed && (
          <Button
            variant="ghost"
            size="sm"
            icon={<Plus size={13} />}
            onClick={onAttach}
            data-testid="daily-diary-attach-reality"
          >
            {t('daily_diary.attach_reality', { defaultValue: 'Attach' })}
          </Button>
        )}
      </div>
      {loading ? (
        <SkeletonTable rows={3} columns={3} />
      ) : captures.length === 0 ? (
        <p className="text-sm text-content-tertiary py-4 text-center">
          {t('daily_diary.no_reality', { defaultValue: 'No reality captures yet.' })}
        </p>
      ) : (
        <ul className="space-y-2">
          {captures.slice(0, 5).map((c) => (
            <li
              key={c.id}
              className="rounded-md border border-border-light bg-surface-secondary/40 p-2 text-sm"
            >
              <div className="flex items-center justify-between">
                <span className="font-medium">
                  {captureTypeLabel(t, c.capture_type)}
                </span>
                <span className="text-xs text-content-tertiary">
                  <DateDisplay value={c.captured_at} />
                </span>
              </div>
              {c.point_count_estimate && (
                <p className="mt-0.5 text-xs text-content-secondary">
                  {c.point_count_estimate.toLocaleString()} pts
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/* ── Archive tab ─────────────────────────────────────────────────────── */

function ArchiveTab({
  diaries,
  loading,
}: {
  diaries: DailyDiary[];
  loading: boolean;
}) {
  const { t } = useTranslation();
  if (loading) {
    return (
      <Card padding="md">
        <SkeletonTable rows={6} columns={4} />
      </Card>
    );
  }
  if (diaries.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={<Archive size={22} />}
          title={t('daily_diary.no_archive', { defaultValue: 'No signed diaries yet' })}
          description={t('daily_diary.no_archive_desc', {
            defaultValue: 'Signed diaries appear here once sealed with sha256 fingerprint.',
          })}
        />
      </Card>
    );
  }
  return (
    <Card padding="none">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
            <tr>
              <th className="px-4 py-2.5 text-left">{t('daily_diary.date', { defaultValue: 'Date' })}</th>
              <th className="px-4 py-2.5 text-left">{t('common.status')}</th>
              <th className="px-4 py-2.5 text-left">{t('daily_diary.signed_at', { defaultValue: 'Signed' })}</th>
              <th className="px-4 py-2.5 text-left">{t('daily_diary.signature_ref', { defaultValue: 'Fingerprint' })}</th>
            </tr>
          </thead>
          <tbody>
            {diaries.map((d) => (
              <tr key={d.id} className="border-t border-border-light hover:bg-surface-secondary">
                <td className="px-4 py-2 font-medium">
                  <DateDisplay value={d.diary_date} />
                </td>
                <td className="px-4 py-2">
                  <Badge variant={STATUS_VARIANT[d.status]} dot>
                    {statusLabel(t, d.status)}
                  </Badge>
                </td>
                <td className="px-4 py-2 text-xs text-content-secondary">
                  {d.closed_at ? <DateDisplay value={d.closed_at} /> : '—'}
                </td>
                <td className="px-4 py-2">
                  <span className="font-mono text-xs text-content-secondary">
                    {d.owner_signature_ref || d.supervisor_signature_ref
                      ? formatSha(d.owner_signature_ref || d.supervisor_signature_ref || '')
                      : '—'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* ── Modals ──────────────────────────────────────────────────────────── */

function CreateDiaryModal({
  projectId,
  initialDate,
  onClose,
  onCreated,
}: {
  projectId: string;
  /** Prefill the date field (e.g. the empty calendar day that was clicked). */
  initialDate?: string;
  onClose: () => void;
  /** Invoked with the created diary so the page can open it for editing. */
  onCreated?: (diary: DailyDiary) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [diaryDate, setDiaryDate] = useState(initialDate || todayIso());
  const [labour, setLabour] = useState(0);
  const [equipment, setEquipment] = useState(0);
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const maxIso = maxDiaryIso();

  const submit = async () => {
    if (!diaryDate) {
      addToast({
        type: 'error',
        title: t('daily_diary.date_required', {
          defaultValue: 'Pick a date for the diary.',
        }),
      });
      return;
    }
    if (diaryDate > maxIso) {
      addToast({
        type: 'error',
        title: t('daily_diary.date_future', {
          defaultValue: 'A site diary cannot be dated in the future.',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      const created = await createDiary({
        project_id: projectId,
        diary_date: diaryDate,
        labour_count: labour,
        equipment_count: equipment,
        notes,
      });
      qc.invalidateQueries({ queryKey: ['daily-diary'] });
      addToast({ type: 'success', title: t('daily_diary.created', { defaultValue: 'Diary created' }) });
      onCreated?.(created);
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      size="lg"
      title={t('daily_diary.new_diary', { defaultValue: 'New Diary' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={submit} loading={busy}>
            {t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('daily_diary.date', { defaultValue: 'Date' })}
          required
          span={2}
          hint={t('daily_diary.date_hint', {
            defaultValue:
              'Today or a past day you are back-filling. Future-dated site diaries are not allowed.',
          })}
        >
          <input
            type="date"
            value={diaryDate}
            max={maxIso}
            onChange={(e) => setDiaryDate(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('daily_diary.labour', { defaultValue: 'Labour' })}>
          <input
            type="number"
            min={0}
            value={labour}
            onChange={(e) => setLabour(Number(e.target.value) || 0)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('daily_diary.equipment', { defaultValue: 'Equipment' })}>
          <input
            type="number"
            min={0}
            value={equipment}
            onChange={(e) => setEquipment(Number(e.target.value) || 0)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('common.notes')} span={2}>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className={clsx(inputCls, 'h-auto py-2')}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

function SignDiaryModal({
  diaryId,
  onClose,
}: {
  diaryId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [role, setRole] = useState<SignerRole>('supervisor');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      const sig = await signDiary(diaryId, { signer_role: role, signer_name: name });
      qc.invalidateQueries({ queryKey: ['daily-diary'] });
      addToast({
        type: 'success',
        title: t('daily_diary.sign_ok', { defaultValue: 'Diary signed and sealed' }),
        message: t('daily_diary.sign_ok_fingerprint', {
          defaultValue: 'Sealed with fingerprint sha256:{{sha}}',
          sha: formatSha(sig.content_sha256),
        }),
      });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      size="md"
      title={t('daily_diary.sign_diary', { defaultValue: 'Sign Diary' })}
      subtitle={t('daily_diary.sign_intro', {
        defaultValue:
          'Signing seals the diary with a sha256 fingerprint. All fields become read-only.',
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            icon={<FileSignature size={14} />}
          >
            {t('daily_diary.sign', { defaultValue: 'Sign' })}
          </Button>
        </>
      }
    >
      {/* High-consequence action: state plainly that signing is legally
          meaningful, closes the diary and seals it, and that any later
          unlock is a tracked integrity break. */}
      <div className="mb-3 flex items-start gap-2 rounded-md border border-semantic-warning/30 bg-semantic-warning-bg/30 px-3 py-2 text-xs text-content-secondary">
        <AlertTriangle size={14} className="mt-0.5 shrink-0 text-semantic-warning" />
        <span>
          {t('daily_diary.sign_caution', {
            defaultValue:
              'Signing is a legally meaningful act. It closes the diary if still open and seals it as tamper-evident evidence. Unlocking it later to amend is permitted but recorded as a tracked integrity break.',
          })}
        </span>
      </div>
      <WideModalSection columns={1}>
        <WideModalField
          label={t('daily_diary.signer_role', { defaultValue: 'Signer role' })}
          required
        >
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as SignerRole)}
            className={inputCls}
          >
            {(['owner', 'supervisor', 'inspector', 'client'] as SignerRole[]).map((r) => (
              <option key={r} value={r}>
                {signerRoleLabel(t, r)}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('daily_diary.signer_name', { defaultValue: 'Signer name' })}
        >
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Photo upload modal ──────────────────────────────────────────────────
 *
 * Registers a site photo against the diary. The binary itself lives in
 * object storage; this records its URL + capture metadata (POST
 * /diary-photos/). The URL field accepts an http(s) link or a relative
 * /files path — the same contract the backend schema enforces.
 */
function PhotoUploadModal({
  projectId,
  diaryId,
  diaryDate,
  onClose,
}: {
  projectId: string;
  diaryId: string;
  diaryDate: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [fileUrl, setFileUrl] = useState('');
  const [locationLabel, setLocationLabel] = useState('');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!fileUrl.trim()) {
      addToast({
        type: 'error',
        title: t('daily_diary.photo_url_required', {
          defaultValue: 'Provide the photo file URL.',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      await createPhoto({
        project_id: projectId,
        diary_id: diaryId,
        // Capture time anchored to the diary's local calendar day so the
        // photo lands in this diary's date-scoped panel (not a UTC shift).
        taken_at: `${diaryDate}T${nowLocalISO().slice(11)}`,
        file_url: fileUrl.trim(),
        location_label: locationLabel.trim() || undefined,
        description: description.trim() || undefined,
      });
      qc.invalidateQueries({ queryKey: ['daily-diary', 'photos'] });
      qc.invalidateQueries({ queryKey: ['daily-diary', 'completeness'] });
      addToast({
        type: 'success',
        title: t('daily_diary.photo_added', { defaultValue: 'Photo added' }),
      });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      size="md"
      title={t('daily_diary.upload_photo_title', { defaultValue: 'Add a site photo' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={submit} loading={busy} icon={<Upload size={14} />}>
            {t('daily_diary.upload_photo', { defaultValue: 'Add photo' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={1}>
        <WideModalField
          label={t('daily_diary.photo_url', { defaultValue: 'Photo file URL' })}
          required
          hint={t('daily_diary.photo_url_hint', {
            defaultValue:
              'An http(s) link or a relative /files path to the uploaded image (jpeg, png, heic, webp, tiff).',
          })}
        >
          <input
            type="text"
            value={fileUrl}
            onChange={(e) => setFileUrl(e.target.value)}
            placeholder="/files/site/2026-06-04/east-elevation.jpg"
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('daily_diary.photo_location', { defaultValue: 'Location label' })}
        >
          <input
            type="text"
            value={locationLabel}
            onChange={(e) => setLocationLabel(e.target.value)}
            placeholder={t('daily_diary.photo_location_ph', {
              defaultValue: 'e.g. East elevation, Level 3',
            })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('common.notes')}>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            className={clsx(inputCls, 'h-auto py-2')}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Manual weather entry modal ───────────────────────────────────────── */
function ManualWeatherModal({
  projectId,
  diaryDate,
  onClose,
}: {
  projectId: string;
  diaryDate: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [temperature, setTemperature] = useState('');
  const [humidity, setHumidity] = useState('');
  const [wind, setWind] = useState('');
  const [precip, setPrecip] = useState('');
  const [conditions, setConditions] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await createWeather({
        project_id: projectId,
        // Anchor the reading to the diary's local calendar day.
        captured_at: `${diaryDate}T${nowLocalISO().slice(11)}`,
        source: 'manual',
        temperature_c: temperature.trim() || undefined,
        humidity_pct: humidity.trim() || undefined,
        wind_speed_kmh: wind.trim() || undefined,
        precipitation_mm: precip.trim() || undefined,
        conditions_text: conditions.trim() || undefined,
      });
      qc.invalidateQueries({ queryKey: ['daily-diary', 'weather'] });
      qc.invalidateQueries({ queryKey: ['daily-diary', 'completeness'] });
      addToast({
        type: 'success',
        title: t('daily_diary.weather_added', { defaultValue: 'Weather recorded' }),
      });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      size="md"
      title={t('daily_diary.add_weather_title', { defaultValue: 'Record weather manually' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={submit} loading={busy}>
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('daily_diary.temp', { defaultValue: 'Temperature' })}>
          <input
            type="number"
            step="0.1"
            value={temperature}
            onChange={(e) => setTemperature(e.target.value)}
            placeholder="°C"
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('daily_diary.humidity', { defaultValue: 'Humidity' })}>
          <input
            type="number"
            min={0}
            max={100}
            value={humidity}
            onChange={(e) => setHumidity(e.target.value)}
            placeholder="%"
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('daily_diary.wind', { defaultValue: 'Wind' })}>
          <input
            type="number"
            min={0}
            step="0.1"
            value={wind}
            onChange={(e) => setWind(e.target.value)}
            placeholder="km/h"
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('daily_diary.precip', { defaultValue: 'Precipitation' })}>
          <input
            type="number"
            min={0}
            step="0.1"
            value={precip}
            onChange={(e) => setPrecip(e.target.value)}
            placeholder="mm"
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('daily_diary.conditions', { defaultValue: 'Conditions' })} span={2}>
          <input
            type="text"
            value={conditions}
            onChange={(e) => setConditions(e.target.value)}
            placeholder={t('daily_diary.conditions_ph', {
              defaultValue: 'e.g. Overcast with light rain',
            })}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Drone survey attach modal ────────────────────────────────────────── */
function DroneSurveyModal({
  projectId,
  diaryDate,
  onClose,
}: {
  projectId: string;
  diaryDate: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [droneModel, setDroneModel] = useState('');
  const [pilotName, setPilotName] = useState('');
  const [areaM2, setAreaM2] = useState('');
  const [orthoUrl, setOrthoUrl] = useState('');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await createDroneSurvey({
        project_id: projectId,
        flown_at: `${diaryDate}T${nowLocalISO().slice(11)}`,
        drone_model: droneModel.trim() || undefined,
        pilot_name: pilotName.trim() || undefined,
        area_m2: areaM2.trim() || undefined,
        ortho_file_url: orthoUrl.trim() || undefined,
        notes: notes.trim() || undefined,
      });
      qc.invalidateQueries({ queryKey: ['daily-diary', 'drone'] });
      addToast({
        type: 'success',
        title: t('daily_diary.drone_attached', { defaultValue: 'Drone survey attached' }),
      });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      size="md"
      title={t('daily_diary.attach_drone_title', { defaultValue: 'Attach drone survey' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={submit} loading={busy} icon={<Plane size={14} />}>
            {t('daily_diary.attach', { defaultValue: 'Attach' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('daily_diary.drone_model', { defaultValue: 'Drone model' })}>
          <input
            type="text"
            value={droneModel}
            onChange={(e) => setDroneModel(e.target.value)}
            placeholder="e.g. DJI Mavic 3 Enterprise"
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('daily_diary.pilot_name', { defaultValue: 'Pilot' })}>
          <input
            type="text"
            value={pilotName}
            onChange={(e) => setPilotName(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('daily_diary.area_m2', { defaultValue: 'Covered area (m²)' })}>
          <input
            type="number"
            min={0}
            step="0.1"
            value={areaM2}
            onChange={(e) => setAreaM2(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('daily_diary.ortho_url', { defaultValue: 'Orthophoto URL' })}
          hint={t('daily_diary.asset_url_hint', {
            defaultValue: 'http(s) link or a relative /files path (optional).',
          })}
        >
          <input
            type="text"
            value={orthoUrl}
            onChange={(e) => setOrthoUrl(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('common.notes')} span={2}>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className={clsx(inputCls, 'h-auto py-2')}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Reality capture attach modal ─────────────────────────────────────── */
function RealityCaptureModal({
  projectId,
  diaryDate,
  onClose,
}: {
  projectId: string;
  diaryDate: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [captureType, setCaptureType] = useState<CaptureType>('laser_scan');
  const [fileUrl, setFileUrl] = useState('');
  const [pointCount, setPointCount] = useState('');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!fileUrl.trim()) {
      addToast({
        type: 'error',
        title: t('daily_diary.reality_url_required', {
          defaultValue: 'Provide the dataset file URL.',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      await createRealityCapture({
        project_id: projectId,
        captured_at: `${diaryDate}T${nowLocalISO().slice(11)}`,
        capture_type: captureType,
        file_url: fileUrl.trim(),
        point_count_estimate: pointCount.trim()
          ? Number(pointCount.trim())
          : undefined,
        notes: notes.trim() || undefined,
      });
      qc.invalidateQueries({ queryKey: ['daily-diary', 'reality'] });
      addToast({
        type: 'success',
        title: t('daily_diary.reality_attached', { defaultValue: 'Reality capture attached' }),
      });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      size="md"
      title={t('daily_diary.attach_reality_title', { defaultValue: 'Attach reality capture' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={submit} loading={busy} icon={<Scan size={14} />}>
            {t('daily_diary.attach', { defaultValue: 'Attach' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={1}>
        <WideModalField
          label={t('daily_diary.capture_type_label', { defaultValue: 'Capture type' })}
          required
        >
          <select
            value={captureType}
            onChange={(e) => setCaptureType(e.target.value as CaptureType)}
            className={inputCls}
          >
            {(['laser_scan', 'photogrammetry', 'mobile_scan'] as CaptureType[]).map((ct) => (
              <option key={ct} value={ct}>
                {captureTypeLabel(t, ct)}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('daily_diary.reality_url', { defaultValue: 'Dataset file URL' })}
          required
          hint={t('daily_diary.asset_url_hint', {
            defaultValue: 'http(s) link or a relative /files path (optional).',
          })}
        >
          <input
            type="text"
            value={fileUrl}
            onChange={(e) => setFileUrl(e.target.value)}
            placeholder="/files/scans/2026-06-04/level-3.e57"
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('daily_diary.point_count', { defaultValue: 'Point count estimate' })}
        >
          <input
            type="number"
            min={0}
            value={pointCount}
            onChange={(e) => setPointCount(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('common.notes')}>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className={clsx(inputCls, 'h-auto py-2')}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── SCL Protocol evidence-bundle modal ───────────────────────────────────
 *
 * Builds a hash-sealed contemporary-record bundle manifest over a date
 * range and shows the resulting bundle sha256 + per-type counts. This is a
 * headline differentiator (delay-claim evidence) that previously had no UI.
 */
function SclBundleModal({
  projectId,
  diaryDate,
  onClose,
}: {
  projectId: string;
  diaryDate: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [dateFrom, setDateFrom] = useState(diaryDate);
  const [dateTo, setDateTo] = useState(diaryDate);
  const [busy, setBusy] = useState(false);
  const [manifest, setManifest] = useState<SclBundleManifest | null>(null);

  const submit = async () => {
    if (dateFrom > dateTo) {
      addToast({
        type: 'error',
        title: t('daily_diary.scl_range_invalid', {
          defaultValue: 'The start date must be on or before the end date.',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      const res = await exportSclBundle({
        project_id: projectId,
        date_from: dateFrom,
        date_to: dateTo,
      });
      setManifest(res);
      addToast({
        type: 'success',
        title: t('daily_diary.scl_built', { defaultValue: 'SCL bundle sealed' }),
      });
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      size="md"
      title={t('daily_diary.scl_bundle_title', {
        defaultValue: 'SCL Protocol evidence bundle',
      })}
      subtitle={t('daily_diary.scl_bundle_subtitle', {
        defaultValue:
          'Seal every diary, weather record, photo and drone survey in a date range under one tamper-evident sha256 manifest.',
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.close', { defaultValue: 'Close' })}
          </Button>
          <Button variant="primary" onClick={submit} loading={busy} icon={<Package size={14} />}>
            {t('daily_diary.scl_build', { defaultValue: 'Build bundle' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('daily_diary.scl_from', { defaultValue: 'From' })} required>
          <input
            type="date"
            value={dateFrom}
            max={dateTo}
            onChange={(e) => setDateFrom(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('daily_diary.scl_to', { defaultValue: 'To' })} required>
          <input
            type="date"
            value={dateTo}
            min={dateFrom}
            onChange={(e) => setDateTo(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>

      {manifest && (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-xs uppercase tracking-wide text-content-tertiary">
                {t('daily_diary.tab_diaries', { defaultValue: 'Diaries' })}
              </dt>
              <dd className="text-base font-semibold">{manifest.diary_count}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-content-tertiary">
                {t('daily_diary.weather', { defaultValue: 'Weather' })}
              </dt>
              <dd className="text-base font-semibold">{manifest.weather_record_count}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-content-tertiary">
                {t('daily_diary.photos', { defaultValue: 'Photos' })}
              </dt>
              <dd className="text-base font-semibold">{manifest.photo_count}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-content-tertiary">
                {t('daily_diary.drone', { defaultValue: 'Drone surveys' })}
              </dt>
              <dd className="text-base font-semibold">{manifest.drone_survey_count}</dd>
            </div>
          </div>
          <div className="rounded-md border border-semantic-success/30 bg-semantic-success-bg/30 p-3">
            <p className="text-xs font-semibold text-content-secondary">
              {t('daily_diary.scl_fingerprint', { defaultValue: 'Bundle fingerprint' })}
            </p>
            <p className="mt-1 break-all font-mono text-xs text-content-secondary">
              sha256: {manifest.bundle_sha256}
            </p>
          </div>
        </div>
      )}
    </WideModal>
  );
}
