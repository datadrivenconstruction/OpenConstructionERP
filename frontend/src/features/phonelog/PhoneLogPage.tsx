// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Phone Log - capture a phone call, voice note, or verbal instruction so it is
// on the project record before it is disputed. The quick-entry form takes a
// free-form capture (who was on the call, which way it went, when, how long,
// and what was said); the server normalizes it and the list below shows the
// resulting dispute-ready record: direction and channel, the parties, a short
// summary, and the instruction-bearing sentences pulled out of the transcript.

import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Phone,
  Users,
  Mic,
  MessageSquare,
  Clock,
  ListChecks,
  Inbox,
  Sparkles,
  ClipboardCheck,
  Pencil,
  Trash2,
  Search,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import {
  Card,
  Badge,
  EmptyState,
  SkeletonTable,
  DismissibleInfo,
  IntroRichText,
  ConfirmDialog,
} from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { listPhoneLogs, createPhoneLog, deletePhoneLog } from './api';
import { RecordingProtocolCard } from './RecordingProtocolCard';
import { RecordingPlayer } from './RecordingPlayer';
import { LinkToRecordMenu } from './LinkToRecordMenu';
import { PhoneLogEditDialog } from './PhoneLogEditDialog';
import {
  PhoneLogFilters,
  filterPhoneLogs,
  EMPTY_FILTER,
  type PhoneLogFilterState,
} from './PhoneLogFilters';
import { exportPhoneLogsCsv } from './exportCsv';
import {
  CHANNEL_VARIANT,
  CHANNELS,
  DIRECTION_VARIANT,
  DIRECTIONS,
  channelLabel,
  directionLabel,
  formatDuration,
} from './labels';
import { hasRecording, isRecordingDraft, readProtocol } from './protocol';
import type { PhoneChannel, PhoneDirection, PhoneLog } from './types';
import { fmtList } from '@/shared/lib/formatters';

// Badge variants, picker sets, translated labels, and formatDuration live in
// ./labels so the filter bar and the edit dialog render a call the same way.

// How many confirmed calls to show per page in the history below.
const PAGE_SIZE = 6;

interface FormState {
  raw_parties: string;
  direction: PhoneDirection;
  channel: PhoneChannel;
  started_at: string;
  duration_minutes: string;
  transcript: string;
  summary: string;
}

const EMPTY_FORM: FormState = {
  raw_parties: '',
  direction: 'inbound',
  channel: 'phone',
  started_at: '',
  duration_minutes: '',
  transcript: '',
  summary: '',
};

function PhoneLogCard({
  log,
  projectId,
  onEdit,
  onDelete,
}: {
  log: PhoneLog;
  projectId: string;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const proto = readProtocol(log);
  return (
    <Card className="space-y-2 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={DIRECTION_VARIANT[log.direction]}>{directionLabel(t, log.direction)}</Badge>
        <Badge variant={CHANNEL_VARIANT[log.channel]}>{channelLabel(t, log.channel)}</Badge>
        {proto?.ai_generated && (
          <Badge variant="blue" size="sm">
            <span className="inline-flex items-center gap-1">
              <Sparkles className="h-3 w-3" />
              {t('phonelog.rec.ai_generated', { defaultValue: 'AI-drafted' })}
            </span>
          </Badge>
        )}
        {log.occurred_at && (
          <span className="text-xs text-content-tertiary">{log.occurred_at.replace('T', ' ')}</span>
        )}
        <span className="ms-auto inline-flex items-center gap-1 text-xs text-content-tertiary">
          <Clock className="h-3.5 w-3.5" />
          {formatDuration(t, log.duration_seconds)}
        </span>
      </div>

      {log.parties.length > 0 && (
        <div className="flex items-center gap-1.5 text-sm text-content-secondary">
          <Users className="h-4 w-4 shrink-0 text-content-tertiary" />
          <span>{fmtList(log.parties)}</span>
        </div>
      )}

      {log.summary && <p className="text-sm font-medium text-content-primary">{log.summary}</p>}

      {proto && proto.decisions.length > 0 && (
        <div className="space-y-1">
          <div className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
            <ClipboardCheck className="h-3.5 w-3.5" />
            {t('phonelog.rec.decisions', { defaultValue: 'Decisions' })}
          </div>
          <ul className="space-y-1">
            {proto.decisions.map((line, i) => (
              <li
                key={i}
                className="rounded-md border-s-2 border-green-500/50 bg-surface-secondary px-2 py-1 text-sm text-content-secondary"
              >
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}

      {proto && proto.action_items.length > 0 && (
        <div className="space-y-1">
          <div className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
            <ListChecks className="h-3.5 w-3.5" />
            {t('phonelog.rec.action_items', { defaultValue: 'Action items' })}
          </div>
          <ul className="space-y-1">
            {proto.action_items.map((item, i) => (
              <li
                key={i}
                className="flex flex-wrap items-center gap-x-2 rounded-md border-s-2 border-oe-blue/50 bg-surface-secondary px-2 py-1 text-sm text-content-secondary"
              >
                <span className="text-content-primary">{item.task}</span>
                {item.owner && <span className="text-xs text-content-tertiary">- {item.owner}</span>}
                {item.due && (
                  <Badge variant="neutral" size="sm">
                    {item.due}
                  </Badge>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {log.instructions.length > 0 && (
        <div className="space-y-1">
          <div className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
            <ListChecks className="h-3.5 w-3.5" />
            {t('phonelog.instructions', { defaultValue: 'Instructions captured' })}
          </div>
          <ul className="space-y-1">
            {log.instructions.map((line, i) => (
              <li
                key={i}
                className="rounded-md border-s-2 border-oe-blue/50 bg-surface-secondary px-2 py-1 text-sm text-content-secondary"
              >
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}

      {hasRecording(log) && (
        <div className="pt-1">
          <RecordingPlayer id={log.id} />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-border-light/60 pt-2">
        <LinkToRecordMenu projectId={projectId} />
        <button
          type="button"
          onClick={onEdit}
          className="inline-flex items-center gap-1.5 rounded-md border border-border-light px-2.5 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-secondary"
        >
          <Pencil className="h-3.5 w-3.5" />
          {t('phonelog.edit', { defaultValue: 'Edit' })}
        </button>
        <button
          type="button"
          onClick={onDelete}
          className="inline-flex items-center gap-1.5 rounded-md border border-border-light px-2.5 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30"
        >
          <Trash2 className="h-3.5 w-3.5" />
          {t('phonelog.delete', { defaultValue: 'Delete' })}
        </button>
      </div>
    </Card>
  );
}

export function PhoneLogPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { projectId: routeProjectId } = useParams();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectId = routeProjectId ?? activeProjectId ?? '';

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [filter, setFilter] = useState<PhoneLogFilterState>(EMPTY_FILTER);
  const [page, setPage] = useState(0);
  const [editing, setEditing] = useState<PhoneLog | null>(null);
  const [deleting, setDeleting] = useState<PhoneLog | null>(null);
  const addToast = useToastStore((s) => s.addToast);

  const logsQuery = useQuery({
    queryKey: ['phonelog', 'list', projectId],
    // Fetch a fuller page (server caps at 100) so search, filtering, and
    // pagination below work over a real history, not just the newest few.
    queryFn: () => listPhoneLogs(projectId, { limit: 100 }),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });

  // Drafts from an in-progress recording review are reviewed in the card above,
  // not in the log, so keep the log to confirmed records only.
  const logs = (logsQuery.data ?? []).filter((log) => !isRecordingDraft(log));

  const createMutation = useMutation({
    mutationFn: () => {
      const minutes = parseFloat(form.duration_minutes);
      return createPhoneLog({
        project_id: projectId,
        raw_parties: form.raw_parties,
        direction: form.direction,
        channel: form.channel,
        started_at: form.started_at || null,
        duration_seconds: Number.isFinite(minutes) && minutes > 0 ? Math.round(minutes * 60) : null,
        transcript: form.transcript,
        summary: form.summary,
      });
    },
    onSuccess: () => {
      setForm(EMPTY_FORM);
      void queryClient.invalidateQueries({ queryKey: ['phonelog', 'list', projectId] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deletePhoneLog(id),
    onSuccess: () => {
      addToast({ type: 'success', title: t('phonelog.deleted', { defaultValue: 'Call deleted' }) });
      setDeleting(null);
      void queryClient.invalidateQueries({ queryKey: ['phonelog', 'list', projectId] });
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('phonelog.delete_error', { defaultValue: 'Could not delete the call' }),
        message: getErrorMessage(err),
      });
    },
  });

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const canSubmit = !!projectId && (form.transcript.trim() !== '' || form.summary.trim() !== '');

  // Search / filter runs over the fetched calls; pagination then pages the
  // matches. safePage clamps the page when a filter shrinks the result set.
  const filtered = filterPhoneLogs(logs, filter);
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const paged = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);
  const applyFilter = (next: PhoneLogFilterState) => {
    setFilter(next);
    setPage(0);
  };

  if (!projectId) {
    return (
      <div className="p-4">
        <EmptyState
          icon={<Phone className="h-6 w-6" />}
          title={t('phonelog.no_project_title', { defaultValue: 'No project selected' })}
          description={t('phonelog.no_project_desc', {
            defaultValue: 'Select a project to capture and review its phone calls and verbal instructions.',
          })}
        />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold text-content-primary">
          <Phone className="h-5 w-5" />
          {t('phonelog.title', { defaultValue: 'Phone Log' })}
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          {t('phonelog.subtitle', {
            defaultValue: 'Put a phoned, spoken, or chatted instruction on the record before it is disputed.',
          })}
        </p>
      </div>

      <DismissibleInfo
        storageKey="phonelog-intro"
        title={t('phonelog.intro_title', { defaultValue: 'Why log a call' })}
        more={
          <IntroRichText
            text={t('phonelog.intro_more', {
              defaultValue:
                'Each entry keeps who was on the call, which way it went, when it happened, and the exact instruction sentences pulled from what was said, so weeks later there is a dated, searchable record instead of a memory.\n\nWhen a call settles a question or changes the work, use Link to record on the call to open the matching RFI or change order and raise the formal record there. The call then stands as the evidence behind it. Search and the filters find any call by party, direction, channel, or date, and Export CSV hands the whole log to a claim or an audit.',
            })}
          />
        }
      >
        {t('phonelog.intro_body', {
          defaultValue:
            'Verbal instructions given on site or over the phone routinely go unrecorded and are then disputed weeks later. Capturing the call here turns it into a searchable record - who was on it, which way it went, and the instruction-bearing sentences pulled out of what was said.',
        })}
      </DismissibleInfo>

      <RecordingProtocolCard projectId={projectId} />

      <Card className="space-y-3 p-4">
        <h2 className="text-sm font-semibold text-content-primary">
          {t('phonelog.capture_manual', { defaultValue: 'Or capture a call by hand' })}
        </h2>

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm text-content-secondary">
            {t('phonelog.parties', { defaultValue: 'Parties' })}
            <input
              value={form.raw_parties}
              onChange={(e) => set('raw_parties', e.target.value)}
              placeholder={t('phonelog.parties_ph', { defaultValue: 'You -> Acme site office' })}
              className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm text-content-secondary">
            {t('phonelog.when', { defaultValue: 'When' })}
            <input
              type="datetime-local"
              value={form.started_at}
              onChange={(e) => set('started_at', e.target.value)}
              className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm text-content-secondary">
            {t('phonelog.direction', { defaultValue: 'Direction' })}
            <select
              value={form.direction}
              onChange={(e) => set('direction', e.target.value as PhoneDirection)}
              className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary"
            >
              {DIRECTIONS.map((d) => (
                <option key={d} value={d}>
                  {directionLabel(t, d)}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-sm text-content-secondary">
            {t('phonelog.channel', { defaultValue: 'Channel' })}
            <select
              value={form.channel}
              onChange={(e) => set('channel', e.target.value as PhoneChannel)}
              className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary"
            >
              {CHANNELS.map((c) => (
                <option key={c} value={c}>
                  {channelLabel(t, c)}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-sm text-content-secondary">
            {t('phonelog.duration_min', { defaultValue: 'Duration (minutes)' })}
            <input
              type="number"
              min="0"
              step="1"
              value={form.duration_minutes}
              onChange={(e) => set('duration_minutes', e.target.value)}
              className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm text-content-secondary">
            {t('phonelog.summary', { defaultValue: 'Summary (optional)' })}
            <input
              value={form.summary}
              onChange={(e) => set('summary', e.target.value)}
              placeholder={t('phonelog.summary_ph', { defaultValue: 'Agreed to revise the slab pour date' })}
              className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary"
            />
          </label>
        </div>

        <label className="flex flex-col gap-1 text-sm text-content-secondary">
          {t('phonelog.transcript', { defaultValue: 'What was said' })}
          <textarea
            value={form.transcript}
            onChange={(e) => set('transcript', e.target.value)}
            rows={4}
            placeholder={t('phonelog.transcript_ph', {
              defaultValue: 'Type or paste the conversation. Instruction sentences are pulled out automatically.',
            })}
            className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary"
          />
        </label>

        {createMutation.isError && (
          <p className="text-sm text-red-600">{getErrorMessage(createMutation.error)}</p>
        )}

        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={!canSubmit || createMutation.isPending}
            onClick={() => createMutation.mutate()}
            className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {form.channel === 'voice_note' ? <Mic className="h-4 w-4" /> : <Phone className="h-4 w-4" />}
            {t('phonelog.log_call', { defaultValue: 'Log the call' })}
          </button>
          <span className="text-xs text-content-tertiary">
            {t('phonelog.log_hint', { defaultValue: 'Add a summary or what was said to log the call.' })}
          </span>
        </div>
      </Card>

      <div className="space-y-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
          <MessageSquare className="h-4 w-4" />
          {t('phonelog.recent', { defaultValue: 'Recent calls' })}
        </h2>

        {logsQuery.isLoading ? (
          <SkeletonTable rows={3} />
        ) : logsQuery.isError ? (
          <EmptyState
            icon={<Inbox className="h-6 w-6" />}
            title={t('phonelog.error_title', { defaultValue: 'Could not load the phone log' })}
            description={getErrorMessage(logsQuery.error)}
          />
        ) : logs.length === 0 ? (
          <EmptyState
            icon={<Phone className="h-6 w-6" />}
            title={t('phonelog.empty_title', { defaultValue: 'No calls logged yet' })}
            description={t('phonelog.empty_desc', {
              defaultValue: 'Capture the next phone call or verbal instruction above and it will show up here.',
            })}
          />
        ) : (
          <>
            <PhoneLogFilters
              value={filter}
              onChange={applyFilter}
              total={logs.length}
              shown={filtered.length}
              onExport={() => exportPhoneLogsCsv(filtered, t)}
            />

            {filtered.length === 0 ? (
              <EmptyState
                icon={<Search className="h-6 w-6" />}
                title={t('phonelog.no_matches_title', { defaultValue: 'No calls match your filters' })}
                description={t('phonelog.no_matches_desc', {
                  defaultValue: 'Try a different search, direction, channel, or date range.',
                })}
                action={{
                  label: t('phonelog.clear_filters', { defaultValue: 'Clear' }),
                  onClick: () => applyFilter(EMPTY_FILTER),
                }}
              />
            ) : (
              <>
                <div className="space-y-3">
                  {paged.map((log) => (
                    <PhoneLogCard
                      key={log.id}
                      log={log}
                      projectId={projectId}
                      onEdit={() => setEditing(log)}
                      onDelete={() => setDeleting(log)}
                    />
                  ))}
                </div>

                {pageCount > 1 && (
                  <div className="flex items-center justify-center gap-3 pt-1">
                    <button
                      type="button"
                      disabled={safePage === 0}
                      onClick={() => setPage(safePage - 1)}
                      className="inline-flex items-center gap-1 rounded-md border border-border-light px-2.5 py-1.5 text-sm text-content-secondary hover:bg-surface-secondary disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <ChevronLeft className="h-4 w-4" />
                      {t('phonelog.prev', { defaultValue: 'Previous' })}
                    </button>
                    <span className="text-xs text-content-tertiary">
                      {t('phonelog.page_of', {
                        defaultValue: 'Page {{page}} of {{count}}',
                        page: safePage + 1,
                        count: pageCount,
                      })}
                    </span>
                    <button
                      type="button"
                      disabled={safePage >= pageCount - 1}
                      onClick={() => setPage(safePage + 1)}
                      className="inline-flex items-center gap-1 rounded-md border border-border-light px-2.5 py-1.5 text-sm text-content-secondary hover:bg-surface-secondary disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {t('phonelog.next', { defaultValue: 'Next' })}
                      <ChevronRight className="h-4 w-4" />
                    </button>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>

      {editing && (
        <PhoneLogEditDialog
          key={editing.id}
          log={editing}
          open
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void queryClient.invalidateQueries({ queryKey: ['phonelog', 'list', projectId] });
          }}
        />
      )}

      <ConfirmDialog
        open={!!deleting}
        title={t('phonelog.delete_title', { defaultValue: 'Delete this call?' })}
        message={t('phonelog.delete_message', {
          defaultValue: 'This removes the logged call and any stored recording. This cannot be undone.',
        })}
        confirmLabel={t('phonelog.delete_confirm', { defaultValue: 'Delete call' })}
        loading={deleteMutation.isPending}
        onConfirm={() => deleting && deleteMutation.mutate(deleting.id)}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}
