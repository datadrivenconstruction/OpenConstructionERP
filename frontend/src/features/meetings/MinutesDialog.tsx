// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// MinutesDialog — auto-draft meeting minutes. From the agenda plus the
// discussion and decisions captured against each item, the backend assembles a
// structured draft: who was present and absent, what was discussed and decided
// per agenda item, the action items (brought-forward first) and the next
// meeting date. A human reviews and edits the draft, then issues it and
// distributes it to the attendees. Nothing is issued automatically.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  FileDown,
  Loader2,
  RefreshCw,
  Save,
  Send,
  Share2,
  Sparkles,
} from 'lucide-react';
import {
  Badge,
  Button,
  WideModal,
  WideModalField,
  WideModalSection,
} from '@/shared/ui';
import { triggerDownload } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  distributeMinutes,
  fetchMinutes,
  generateMinutes,
  getMinutesPdfUrl,
  issueMinutes,
  updateMinutes,
  type Minutes,
  type MinutesAgendaLine,
  type MinutesContent,
} from './api';
import { PublishRecordModal } from '@/features/record-publishing/PublishRecordModal';

interface MinutesDialogProps {
  meetingId: string;
  projectId: string;
  meetingTitle: string;
  onClose: () => void;
}

const inputCls =
  'h-9 w-full rounded-md border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-md border border-border bg-surface-primary px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-vertical';

async function downloadMinutesPdf(meetingId: string): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const res = await fetch(getMinutesPdfUrl(meetingId), {
    method: 'GET',
    headers: { Accept: 'application/pdf', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!res.ok) throw new Error('PDF export failed');
  const blob = await res.blob();
  const disposition = res.headers.get('Content-Disposition');
  const filename = disposition?.match(/filename="?(.+?)"?$/)?.[1] || `minutes_${meetingId}.pdf`;
  triggerDownload(blob, filename);
}

export function MinutesDialog({ meetingId, projectId, meetingTitle, onClose }: MinutesDialogProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [publishOpen, setPublishOpen] = useState(false);
  const addToast = useToastStore((s) => s.addToast);

  const minutesQ = useQuery<Minutes | null>({
    queryKey: ['meeting-minutes', meetingId],
    queryFn: () => fetchMinutes(meetingId),
    staleTime: 10_000,
  });

  const minutes = minutesQ.data ?? null;
  const issued = minutes?.status === 'issued';

  // Local editable copy of the draft content.
  const [agenda, setAgenda] = useState<MinutesAgendaLine[]>([]);
  const [summary, setSummary] = useState('');
  const [nextDate, setNextDate] = useState('');

  useEffect(() => {
    if (!minutes) return;
    setAgenda(minutes.content.agenda ?? []);
    setSummary(minutes.content.summary ?? '');
    setNextDate(minutes.content.next_meeting_date ?? minutes.next_meeting_date ?? '');
  }, [minutes]);

  const buildContent = useMemo(
    () =>
      (base: MinutesContent): MinutesContent => ({
        ...base,
        agenda,
        summary,
        next_meeting_date: nextDate || null,
      }),
    [agenda, summary, nextDate],
  );

  const setMinutesData = (m: Minutes) => qc.setQueryData(['meeting-minutes', meetingId], m);

  const genMut = useMutation({
    mutationFn: (regenerate: boolean) => generateMinutes(meetingId, { regenerate }),
    onSuccess: (m) => {
      setMinutesData(m);
      addToast({
        type: 'success',
        title: t('meetings.minutes_generated', { defaultValue: 'Draft minutes ready' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('meetings.minutes_generate_failed', { defaultValue: 'Could not generate minutes' }),
        message: e.message,
      }),
  });

  const saveMut = useMutation({
    mutationFn: () => {
      if (!minutes) throw new Error('No minutes to save');
      return updateMinutes(meetingId, {
        content: buildContent(minutes.content),
        ...(nextDate ? { next_meeting_date: nextDate } : {}),
      });
    },
    onSuccess: (m) => {
      setMinutesData(m);
      addToast({ type: 'success', title: t('meetings.minutes_saved', { defaultValue: 'Draft saved' }) });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('meetings.minutes_save_failed', { defaultValue: 'Could not save minutes' }),
        message: e.message,
      }),
  });

  const issueMut = useMutation({
    mutationFn: async () => {
      // Persist edits first so the issue-readiness check runs on what the user sees.
      if (minutes) {
        const saved = await updateMinutes(meetingId, {
          content: buildContent(minutes.content),
          ...(nextDate ? { next_meeting_date: nextDate } : {}),
        });
        setMinutesData(saved);
      }
      return issueMinutes(meetingId);
    },
    onSuccess: (m) => {
      setMinutesData(m);
      addToast({
        type: 'success',
        title: t('meetings.minutes_issued', { defaultValue: 'Minutes issued' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('meetings.minutes_issue_failed', { defaultValue: 'Minutes are not ready to issue' }),
        message: e.message,
      }),
  });

  const distributeMut = useMutation({
    mutationFn: () => distributeMinutes(meetingId),
    onSuccess: (res) => {
      void qc.invalidateQueries({ queryKey: ['meeting-minutes', meetingId] });
      addToast({
        type: 'success',
        title: t('meetings.minutes_distributed', {
          defaultValue: 'Minutes sent to {{count}} attendee(s)',
          count: res.recipients,
        }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('meetings.minutes_distribute_failed', { defaultValue: 'Could not distribute minutes' }),
        message: e.message,
      }),
  });

  const exportMut = useMutation({
    mutationFn: async () => {
      // Persist edits first, for the same reason issueMut does, and it is the
      // same three lines. The PDF is rendered on the server from the saved
      // row, and nothing here carried the typed text to it, so exporting a
      // draft downloaded the last save while the screen showed the edits. The
      // two disagreed and neither said so.
      //
      // Only while the draft is still editable. Once the minutes are issued
      // every field is disabled and the issue itself persisted, so there is
      // nothing left to send and a write would be a no-op against a row the
      // user can no longer change.
      if (minutes && !issued) {
        const saved = await updateMinutes(meetingId, {
          content: buildContent(minutes.content),
          ...(nextDate ? { next_meeting_date: nextDate } : {}),
        });
        setMinutesData(saved);
      }
      return downloadMinutesPdf(meetingId);
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('meetings.export_failed', { defaultValue: 'Failed to export PDF' }),
        message: e.message,
      }),
  });

  const updateAgenda = (idx: number, patch: Partial<MinutesAgendaLine>) => {
    setAgenda((prev) => prev.map((item, i) => (i === idx ? { ...item, ...patch } : item)));
  };

  // The export belongs in here now that it writes. It was left out while it
  // was a bare download, which also meant a draft could be exported in the
  // middle of a save and rendered from the row the save had not replaced yet.
  const busy =
    genMut.isPending ||
    saveMut.isPending ||
    issueMut.isPending ||
    distributeMut.isPending ||
    exportMut.isPending;

  const footer = (
    <div className="flex items-center justify-between gap-2 w-full flex-wrap">
      <div className="flex items-center gap-2">
        {minutes && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => exportMut.mutate()}
            disabled={busy}
          >
            {exportMut.isPending ? (
              <Loader2 size={14} className="mr-1.5 animate-spin" />
            ) : (
              <FileDown size={14} className="mr-1.5" />
            )}
            {t('meetings.export_pdf', { defaultValue: 'Export PDF' })}
          </Button>
        )}
        {minutes && issued && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setPublishOpen(true)}
            title={t('meetings.publish_record_hint', {
              defaultValue:
                'Issue the minutes as a signed PDF transmittal that recipients acknowledge, with a no-login download link.',
            })}
          >
            <Share2 size={14} className="mr-1.5" />
            {t('record_publishing.publish_action', { defaultValue: 'Publish and distribute' })}
          </Button>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>
          {t('common.close', { defaultValue: 'Close' })}
        </Button>
        {minutes && !issued && (
          <>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => genMut.mutate(true)}
              disabled={busy}
              title={t('meetings.minutes_regenerate_hint', {
                defaultValue: 'Rebuild the draft from the current meeting data (discards edits).',
              })}
            >
              {genMut.isPending ? (
                <Loader2 size={14} className="mr-1.5 animate-spin" />
              ) : (
                <RefreshCw size={14} className="mr-1.5" />
              )}
              {t('meetings.regenerate', { defaultValue: 'Regenerate' })}
            </Button>
            <Button variant="secondary" size="sm" onClick={() => saveMut.mutate()} disabled={busy}>
              {saveMut.isPending ? (
                <Loader2 size={14} className="mr-1.5 animate-spin" />
              ) : (
                <Save size={14} className="mr-1.5" />
              )}
              {t('common.save_draft', { defaultValue: 'Save draft' })}
            </Button>
            <Button variant="primary" size="sm" onClick={() => issueMut.mutate()} disabled={busy}>
              {issueMut.isPending ? (
                <Loader2 size={14} className="mr-1.5 animate-spin" />
              ) : (
                <CheckCircle2 size={14} className="mr-1.5" />
              )}
              {t('meetings.issue_minutes', { defaultValue: 'Issue minutes' })}
            </Button>
          </>
        )}
        {minutes && issued && (
          <Button
            variant="primary"
            size="sm"
            onClick={() => distributeMut.mutate()}
            disabled={busy}
          >
            {distributeMut.isPending ? (
              <Loader2 size={14} className="mr-1.5 animate-spin" />
            ) : (
              <Send size={14} className="mr-1.5" />
            )}
            {t('meetings.distribute', { defaultValue: 'Distribute to attendees' })}
          </Button>
        )}
      </div>
    </div>
  );

  return (
    <WideModal
      open
      onClose={onClose}
      size="xl"
      busy={busy}
      title={t('meetings.minutes_title', { defaultValue: 'Meeting minutes' })}
      subtitle={meetingTitle}
      footer={footer}
    >
      {minutesQ.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-content-tertiary py-10 justify-center">
          <Loader2 size={16} className="animate-spin" />
          {t('common.loading', { defaultValue: 'Loading…' })}
        </div>
      ) : !minutes ? (
        // No draft yet — offer to generate one.
        <div className="py-8 text-center space-y-4">
          <Sparkles size={32} className="mx-auto text-oe-blue" />
          <div className="space-y-1">
            <p className="text-sm font-medium text-content-primary">
              {t('meetings.minutes_empty_title', { defaultValue: 'Draft the minutes' })}
            </p>
            <p className="text-sm text-content-secondary max-w-md mx-auto">
              {t('meetings.minutes_empty_body', {
                defaultValue:
                  'Assemble a structured draft from the agenda, attendance and action items. You review and edit it before issuing.',
              })}
            </p>
          </div>
          <Button variant="primary" onClick={() => genMut.mutate(false)} disabled={genMut.isPending}>
            {genMut.isPending ? (
              <Loader2 size={16} className="mr-1.5 animate-spin" />
            ) : (
              <Sparkles size={16} className="mr-1.5" />
            )}
            {t('meetings.generate_minutes', { defaultValue: 'Generate draft minutes' })}
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          {/* Status banner */}
          <div className="flex items-center gap-2 flex-wrap">
            <Badge variant={issued ? 'success' : 'blue'} size="sm">
              {issued
                ? t('meetings.minutes_status_issued', { defaultValue: 'Issued' })
                : t('meetings.minutes_status_draft', { defaultValue: 'Draft' })}
            </Badge>
            {issued && minutes.distributed_at && (
              <span className="text-xs text-content-tertiary">
                {t('meetings.distributed_to_count', {
                  defaultValue: 'Sent to {{count}} attendee(s)',
                  count: minutes.distributed_to.length,
                })}
              </span>
            )}
            {!issued && (
              <span className="text-xs text-content-tertiary">
                {t('meetings.minutes_draft_hint', {
                  defaultValue: 'Review and edit, then issue. Required agenda items must be addressed first.',
                })}
              </span>
            )}
          </div>

          {/* Attendance */}
          <WideModalSection
            title={t('meetings.attendance', { defaultValue: 'Attendance' })}
            columns={2}
          >
            <WideModalField label={t('meetings.present', { defaultValue: 'Present' })}>
              <div className="flex flex-wrap gap-1.5">
                {minutes.content.attendees_present.length === 0 ? (
                  <span className="text-xs text-content-tertiary italic">
                    {t('meetings.none', { defaultValue: 'None' })}
                  </span>
                ) : (
                  minutes.content.attendees_present.map((a, i) => (
                    <Badge key={`${a.name}-${i}`} variant="success" size="sm">
                      {a.name}
                    </Badge>
                  ))
                )}
              </div>
            </WideModalField>
            <WideModalField label={t('meetings.absent_excused', { defaultValue: 'Absent / excused' })}>
              <div className="flex flex-wrap gap-1.5">
                {minutes.content.attendees_absent.length === 0 ? (
                  <span className="text-xs text-content-tertiary italic">
                    {t('meetings.none', { defaultValue: 'None' })}
                  </span>
                ) : (
                  minutes.content.attendees_absent.map((a, i) => (
                    <Badge key={`${a.name}-${i}`} variant="neutral" size="sm">
                      {a.name}
                    </Badge>
                  ))
                )}
              </div>
            </WideModalField>
          </WideModalSection>

          {/* Agenda: discussion + decision per item */}
          <WideModalSection
            title={t('meetings.agenda_discussion', { defaultValue: 'Agenda, discussion and decisions' })}
            columns={1}
          >
            {agenda.length === 0 ? (
              <p className="text-sm text-content-tertiary italic">
                {t('meetings.no_agenda', { defaultValue: 'This meeting has no agenda items.' })}
              </p>
            ) : (
              <div className="space-y-3">
                {agenda.map((item, idx) => (
                  <div
                    key={`${item.number}-${idx}`}
                    className="rounded-lg border border-border-light bg-surface-secondary/40 p-3 space-y-2"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium text-content-primary">
                        <span className="font-mono text-content-tertiary mr-1.5">{item.number}.</span>
                        {item.topic || t('meetings.untitled_item', { defaultValue: 'Untitled item' })}
                      </p>
                      <label className="flex items-center gap-1.5 text-xs text-content-tertiary cursor-pointer">
                        <input
                          type="checkbox"
                          checked={item.required}
                          onChange={(e) => updateAgenda(idx, { required: e.target.checked })}
                          disabled={issued}
                          className="rounded border-border text-oe-blue focus:ring-oe-blue/30"
                        />
                        {t('meetings.required', { defaultValue: 'Required' })}
                      </label>
                    </div>
                    <textarea
                      value={item.discussion}
                      onChange={(e) => updateAgenda(idx, { discussion: e.target.value })}
                      rows={2}
                      disabled={issued}
                      placeholder={t('meetings.discussion_placeholder', {
                        defaultValue: 'What was discussed…',
                      })}
                      className={textareaCls}
                    />
                    <textarea
                      value={item.decision}
                      onChange={(e) => updateAgenda(idx, { decision: e.target.value })}
                      rows={2}
                      disabled={issued}
                      placeholder={t('meetings.decision_placeholder', {
                        defaultValue: 'Decision (if any)…',
                      })}
                      className={textareaCls}
                    />
                  </div>
                ))}
              </div>
            )}
          </WideModalSection>

          {/* Action items (read-only snapshot) */}
          {minutes.content.action_items.length > 0 && (
            <WideModalSection
              title={t('meetings.label_actions', { defaultValue: 'Action items' })}
              columns={1}
            >
              <div className="space-y-1.5">
                {minutes.content.action_items.map((ai, i) => (
                  <div
                    key={`${ai.description}-${i}`}
                    className="flex flex-wrap items-center gap-2 rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm"
                  >
                    <span className="flex-1 min-w-[160px] text-content-primary">{ai.description}</span>
                    {ai.brought_forward && (
                      <Badge variant="warning" size="sm">
                        <ArrowUpRight size={11} className="mr-0.5" />
                        {t('meetings.brought_forward', { defaultValue: 'Brought forward' })}
                      </Badge>
                    )}
                    {ai.overdue && (
                      <Badge variant="error" size="sm">
                        <AlertTriangle size={11} className="mr-0.5" />
                        {t('meetings.overdue', { defaultValue: 'Overdue' })}
                      </Badge>
                    )}
                    <span className="text-xs text-content-tertiary">
                      {ai.owner || t('meetings.unassigned', { defaultValue: 'Unassigned' })}
                      {ai.due_date ? ` · ${ai.due_date}` : ''}
                    </span>
                  </div>
                ))}
              </div>
            </WideModalSection>
          )}

          {/* Summary + next meeting */}
          <WideModalSection
            title={t('meetings.summary_next', { defaultValue: 'Summary and next meeting' })}
            columns={1}
          >
            <WideModalField label={t('meetings.label_summary', { defaultValue: 'Summary' })}>
              <textarea
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
                rows={3}
                disabled={issued}
                className={textareaCls}
              />
            </WideModalField>
            <WideModalField
              label={t('meetings.next_meeting_date', { defaultValue: 'Next meeting date' })}
            >
              <input
                type="date"
                value={nextDate}
                onChange={(e) => setNextDate(e.target.value)}
                disabled={issued}
                className={inputCls + ' max-w-[220px]'}
              />
            </WideModalField>
          </WideModalSection>
        </div>
      )}
      {publishOpen && (
        <PublishRecordModal
          sourceKind="meeting"
          sourceId={meetingId}
          projectId={projectId}
          subjectHint={meetingTitle}
          onClose={() => setPublishOpen(false)}
          onPublished={() =>
            void qc.invalidateQueries({ queryKey: ['meeting-minutes', meetingId] })
          }
        />
      )}
    </WideModal>
  );
}
