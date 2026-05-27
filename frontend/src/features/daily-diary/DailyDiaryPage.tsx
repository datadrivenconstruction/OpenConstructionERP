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
  Cloud,
  Camera,
  Plane,
  Scan,
  FileSignature,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  Trash2,
  ArrowRight,
  X,
  Globe2,
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
} from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getErrorMessage } from '@/shared/lib/api';
import { todayLocalISO, isoDateFromLocal, nowLocalISO } from '@/shared/lib/dates';
import { projectsApi } from '@/features/projects/api';
import {
  listDiaries,
  getDiary,
  createDiary,
  closeDiary,
  deleteDiary,
  signDiary,
  weatherToday,
  listEntries,
  createEntry,
  deleteEntry,
  listPhotos,
  listDroneSurveys,
  listRealityCaptures,
  listArchiveSignatures,
  type DailyDiary,
  type WeatherRecord,
  type DiaryEntry,
  type DiaryPhoto,
  type DroneSurvey,
  type RealityCapture,
  type DiaryStatus,
  type SignerRole,
  type EntryType,
} from './api';

type Tab = 'diaries' | 'today' | 'archive';

const STATUS_VARIANT: Record<DiaryStatus, 'neutral' | 'blue' | 'success' | 'warning'> = {
  open: 'blue',
  closed: 'warning',
  signed: 'success',
  archived: 'neutral',
};

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/* ── helpers ─────────────────────────────────────────────────────────── */

// Local-date helpers re-export — kept as local names for in-file readability,
// implementation lives in shared/lib/dates.ts and is shared with field-reports.
const todayIso = todayLocalISO;
const isoDate = isoDateFromLocal;

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

/* ── Workflow intro ──────────────────────────────────────────────────────
 *
 * Site teams open this page without always knowing WHY the diary matters
 * downstream. This banner states the purpose, the daily next-action, and
 * the legal/audit weight of a signed record — plus one-click jumps to the
 * modules the diary feeds into (schedule progress, tasks, photo files).
 * It is dismissible per-session so power users aren't slowed down.
 */
function WorkflowIntro() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [dismissed, setDismissed] = useState(
    () => sessionStorage.getItem('oe.dd.introDismissed') === '1',
  );
  if (dismissed) return null;
  const dismiss = () => {
    sessionStorage.setItem('oe.dd.introDismissed', '1');
    setDismissed(true);
  };
  return (
    <Card
      padding="md"
      className="border-oe-blue/20 bg-oe-blue-subtle/10"
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
          <BookOpen size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-content-primary">
            {t('daily_diary.intro_title', {
              defaultValue: 'One signed record per site day',
            })}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-content-secondary">
            {t('daily_diary.intro_body', {
              defaultValue:
                'Each day, open the diary and log weather, headcount, deliveries and events, attach site photos, then close and sign it. A signed diary is sealed with a sha256 fingerprint — it becomes tamper-evident evidence for delay claims, progress verification and dispute resolution.',
            })}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
              {t('daily_diary.intro_connects', { defaultValue: 'Feeds into' })}
            </span>
            <button
              type="button"
              onClick={() => navigate('/schedule')}
              className="inline-flex items-center gap-1 rounded-full border border-border-light bg-surface-primary px-2.5 py-1 text-xs font-medium text-content-secondary transition-colors hover:border-oe-blue hover:text-oe-blue"
            >
              {t('daily_diary.intro_link_schedule', {
                defaultValue: 'Schedule progress',
              })}
              <ArrowRight size={11} />
            </button>
            <button
              type="button"
              onClick={() => navigate('/tasks')}
              className="inline-flex items-center gap-1 rounded-full border border-border-light bg-surface-primary px-2.5 py-1 text-xs font-medium text-content-secondary transition-colors hover:border-oe-blue hover:text-oe-blue"
            >
              {t('daily_diary.intro_link_tasks', { defaultValue: 'Tasks' })}
              <ArrowRight size={11} />
            </button>
            <button
              type="button"
              onClick={() => navigate('/files')}
              className="inline-flex items-center gap-1 rounded-full border border-border-light bg-surface-primary px-2.5 py-1 text-xs font-medium text-content-secondary transition-colors hover:border-oe-blue hover:text-oe-blue"
            >
              {t('daily_diary.intro_link_files', { defaultValue: 'Site photos' })}
              <ArrowRight size={11} />
            </button>
          </div>
        </div>
        <button
          type="button"
          onClick={dismiss}
          className="shrink-0 rounded-md p-1 text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-content-primary"
          aria-label={t('common.dismiss', { defaultValue: 'Dismiss' })}
        >
          <X size={14} />
        </button>
      </div>
    </Card>
  );
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
  const [signOpen, setSignOpen] = useState(false);

  const projectsQ = useQuery({
    queryKey: ['projects-list-for-diary'],
    queryFn: () => projectsApi.list(),
  });

  useEffect(() => {
    if (projectId) return;
    const seed = activeProjectId || projectsQ.data?.[0]?.id;
    if (seed) setProjectId(seed);
  }, [activeProjectId, projectsQ.data, projectId]);

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
          {
            label: t('daily_diary.title', { defaultValue: 'Daily Site Diary' }),
          },
        ]}
      />

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-content-primary">
            {t('daily_diary.title', { defaultValue: 'Daily Site Diary' })}
          </h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('daily_diary.subtitle', {
              defaultValue:
                'Weather, photos, drone surveys and signed daily records.',
            })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {projectsQ.data && projectsQ.data.length > 0 && (
            <select
              value={projectId}
              onChange={(e) => {
                setProjectId(e.target.value);
                setActiveDiaryId('');
              }}
              className={clsx(inputCls, 'max-w-xs')}
            >
              {projectsQ.data.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
          {projectId && (
            <button
              type="button"
              onClick={() => navigate(`/projects/${projectId}/geo`)}
              className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-secondary hover:text-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/40 shrink-0"
              title={t('geo_hub.view_on_map', { defaultValue: 'View on map' })}
              aria-label={t('geo_hub.view_on_map', { defaultValue: 'View on map' })}
              data-testid="daily-diary-view-on-map"
            >
              <Globe2 size={13} />
              {t('geo_hub.view_on_map', { defaultValue: 'View on map' })}
            </button>
          )}
          <Button
            variant="primary"
            size="sm"
            icon={<Plus size={14} />}
            onClick={() => setCreateOpen(true)}
            disabled={!projectId}
          >
            {t('daily_diary.new_diary', { defaultValue: 'New Diary' })}
          </Button>
        </div>
      </div>

      <WorkflowIntro />

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
                defaultValue: 'Create a project first to start logging site diaries.',
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
            onCreate={() => setCreateOpen(true)}
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
          onClose={() => setCreateOpen(false)}
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
        onClick={() => setCreateOpen(true)}
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
}: {
  diaries: DailyDiary[];
  loading: boolean;
  year: number;
  month: number;
  locale: string;
  onYearChange: (y: number) => void;
  onMonthChange: (m: number) => void;
  onDayClick: (diary: DailyDiary) => void;
}) {
  const { t } = useTranslation();

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

  const weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  return (
    <Card padding="md">
      <div className="flex items-center justify-between mb-4">
        <button
          type="button"
          onClick={prevMonth}
          className="rounded-md p-1.5 hover:bg-surface-secondary"
          aria-label={t('daily_diary.prev_month', { defaultValue: 'Previous month' })}
        >
          <ChevronLeft size={16} />
        </button>
        <h3 className="text-base font-semibold">{fmtMonth(year, month, locale)}</h3>
        <button
          type="button"
          onClick={nextMonth}
          className="rounded-md p-1.5 hover:bg-surface-secondary"
          aria-label={t('daily_diary.next_month', { defaultValue: 'Next month' })}
        >
          <ChevronRight size={16} />
        </button>
      </div>

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
          <div className="grid grid-cols-7 gap-1">
            {Array.from({ length: offset }, (_, i) => (
              <div key={`pad-${i}`} className="h-20" />
            ))}
            {Array.from({ length: daysCount }, (_, i) => {
              const day = i + 1;
              const iso = isoDate(year, month, day);
              const diary = byDate.get(iso);
              const isToday = iso === todayIso();
              return (
                <button
                  key={iso}
                  type="button"
                  onClick={() => diary && onDayClick(diary)}
                  disabled={!diary}
                  className={clsx(
                    'h-20 rounded-md border p-1.5 text-left transition-colors flex flex-col',
                    diary
                      ? 'border-border-light bg-surface-elevated hover:border-oe-blue hover:shadow-sm cursor-pointer'
                      : 'border-dashed border-border-light/60 bg-transparent text-content-tertiary cursor-default',
                    isToday && 'ring-2 ring-oe-blue/30',
                  )}
                >
                  <span className="text-xs font-semibold">{day}</span>
                  {diary && (
                    <>
                      <Badge variant={STATUS_VARIANT[diary.status]} size="sm" dot>
                        {diary.status}
                      </Badge>
                      {diary.status === 'signed' && (
                        <Lock size={10} className="mt-auto text-semantic-success" />
                      )}
                    </>
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
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const confirmCtx = useConfirm();

  // All asset panels are scoped to the diary's OWN date — not todayIso().
  // A diary opened from the calendar can be any past day; previously the
  // panels always queried today, so a back-dated diary showed today's
  // weather/photos beside a header for a different date.
  const diaryDate = diary?.diary_date;
  const diaryId = diary?.id;

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
            {diary.status}
          </Badge>
          {sealed && (
            <span className="inline-flex items-center gap-1.5 rounded-md bg-semantic-success-bg px-2 py-1 text-xs font-medium text-semantic-success">
              <Lock size={12} />
              {t('daily_diary.sealed', { defaultValue: 'Sealed' })}
            </span>
          )}
        </div>
        <div className="flex gap-2">
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
        <WeatherCard weather={latestWeather} loading={weatherQ.isLoading} />
        <Card padding="md" className="xl:col-span-2">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-content-secondary">
              {t('daily_diary.diary_meta', { defaultValue: 'Diary' })}
            </h3>
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
          {diary.notes && (
            <p className="mt-4 text-sm text-content-secondary whitespace-pre-wrap">
              {diary.notes}
            </p>
          )}
        </Card>
      </div>

      <EntriesTimeline diaryId={diary.id} sealed={sealed} />

      <PhotoGrid photos={photosQ.data ?? []} loading={photosQ.isLoading} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <DroneSection surveys={droneQ.data ?? []} loading={droneQ.isLoading} />
        <RealitySection captures={realityQ.data ?? []} loading={realityQ.isLoading} />
      </div>
    </div>
  );
}

function WeatherCard({
  weather,
  loading,
}: {
  weather: WeatherRecord | undefined;
  loading: boolean;
}) {
  const { t } = useTranslation();
  return (
    <Card padding="md">
      <div className="flex items-center gap-2 mb-3">
        <Cloud size={16} className="text-oe-blue" />
        <h3 className="text-sm font-semibold uppercase tracking-wide text-content-secondary">
          {t('daily_diary.weather', { defaultValue: 'Weather' })}
        </h3>
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

function EntriesTimeline({
  diaryId,
  sealed,
}: {
  diaryId: string;
  sealed: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [entryType, setEntryType] = useState<EntryType>('general');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);

  // Previously this component only rendered an add-form: created entries
  // were invisible (no list endpoint, no list query). It now reads back
  // the diary's entries so the timeline actually shows them.
  const entriesQ = useQuery({
    queryKey: ['daily-diary', 'entries', diaryId],
    queryFn: () => listEntries(diaryId),
    enabled: !!diaryId,
  });

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
      });
      setTitle('');
      setDescription('');
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
              onChange={(e) => setEntryType(e.target.value as EntryType)}
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
                  {tp}
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
        </div>
      )}

      {sealed && (
        <p className="text-xs text-content-tertiary mb-3">
          {t('daily_diary.entries_sealed', { defaultValue: 'Diary is sealed — entries are read-only.' })}
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
                      {e.entry_type}
                    </Badge>
                    <span className="font-medium truncate">{e.title || '—'}</span>
                  </div>
                  {e.description && (
                    <p className="mt-1 text-xs text-content-secondary whitespace-pre-wrap">
                      {e.description}
                    </p>
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
}: {
  photos: DiaryPhoto[];
  loading: boolean;
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
}: {
  surveys: DroneSurvey[];
  loading: boolean;
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

function RealitySection({
  captures,
  loading,
}: {
  captures: RealityCapture[];
  loading: boolean;
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
                <span className="font-medium">{c.capture_type}</span>
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
                    {d.status}
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
  onClose,
}: {
  projectId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [diaryDate, setDiaryDate] = useState(todayIso());
  const [labour, setLabour] = useState(0);
  const [equipment, setEquipment] = useState(0);
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);

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
    if (diaryDate > todayIso()) {
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
      await createDiary({
        project_id: projectId,
        diary_date: diaryDate,
        labour_count: labour,
        equipment_count: equipment,
        notes,
      });
      qc.invalidateQueries({ queryKey: ['daily-diary'] });
      addToast({ type: 'success', title: t('daily_diary.created', { defaultValue: 'Diary created' }) });
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
            max={todayIso()}
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
      await signDiary(diaryId, { signer_role: role, signer_name: name });
      qc.invalidateQueries({ queryKey: ['daily-diary'] });
      addToast({ type: 'success', title: t('daily_diary.sign_ok', { defaultValue: 'Diary signed' }) });
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
                {r}
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
