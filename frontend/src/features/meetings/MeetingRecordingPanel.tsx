// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// MeetingRecordingPanel - minutes from audio, inside a meeting.
//
// 1. Consent first: the person recording confirms everybody was told and
//    agreed, picks how long the audio may be kept or that it is deleted right
//    after transcription.
// 2. Record in the browser, upload a file, or type / paste a transcript. With
//    no speech service on the server the browser's own recognition writes the
//    transcript live (where the browser has one) and no audio is kept.
// 3. Edit the transcript and name the speakers.
// 4. Propose minutes: summary, decisions, actions, open questions and spelling
//    corrections, each with a confidence, reviewed one by one.

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  BookA,
  FileAudio,
  Loader2,
  Mic,
  Play,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Square,
  Trash2,
  Upload,
  VolumeX,
  Type as TypeIcon,
} from 'lucide-react';
import { Badge, Button, ConfirmDialog, DateDisplay } from '@/shared/ui';
import { getAuthToken, getErrorMessage } from '@/shared/lib/api';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import {
  createRecording,
  deleteRecording,
  deleteRecordingAudio,
  fetchMeetingValidation,
  fetchRecordings,
  fetchSpeechCapabilities,
  getRecordingAudioUrl,
  proposeMinutes,
  retranscribeRecording,
  reviewProposals,
  updateRecording,
  type MeetingRecording,
  type ProposalEdit,
  type RecordingSource,
  type SpeakerInfo,
} from './audioApi';
import {
  failingRules,
  formatClock,
  languageLabel,
  type MeetingRuleId,
  retentionOptions,
  segmentsFromText,
  speakerLabels,
} from './audioLogic';
import { MeetingGlossaryDialog } from './MeetingGlossaryDialog';
import { ProposalReviewList, type ReviewPerson } from './ProposalReviewList';
import { useMeetingRecorder, type RecorderError } from './useMeetingRecorder';

/** Spoken languages offered; labels come from Intl in the reader's language. */
const SPOKEN_LANGUAGES = [
  'en', 'de', 'fr', 'es', 'it', 'pt', 'nl', 'pl', 'cs', 'ru', 'uk', 'bg', 'hr', 'ro', 'hu', 'el', 'tr',
  'sv', 'no', 'da', 'fi', 'et', 'zh', 'ja', 'ko', 'vi', 'th', 'id', 'hi', 'bn', 'ar', 'fa', 'he', 'ur',
  'kk', 'uz', 'ky', 'fil',
];

interface Attendee {
  name: string;
  user_id?: string | null;
}

export interface MeetingRecordingPanelProps {
  meetingId: string;
  projectId: string;
  attendees: Attendee[];
}

type CaptureMode = 'idle' | 'consent' | 'recording' | 'typing';

const RULE_DEFAULTS: Record<MeetingRuleId, string> = {
  'meetings.recording_consent': 'A recording has no recorded consent',
  'meetings.audio_retention': 'Audio is kept past its retention date',
  'meetings.proposals_reviewed': 'Proposals are waiting for review',
  'meetings.action_ownership': 'An action has no owner or due date',
};

const fieldCls =
  'h-8 rounded-md border border-border bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const areaCls =
  'w-full rounded-md border border-border bg-surface-primary px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-vertical';

export function MeetingRecordingPanel({ meetingId, projectId, attendees }: MeetingRecordingPanelProps) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const [glossaryOpen, setGlossaryOpen] = useState(false);
  const [mode, setMode] = useState<CaptureMode>('idle');
  const [consent, setConsent] = useState(false);
  const [deleteAfter, setDeleteAfter] = useState(false);
  const [retention, setRetention] = useState<number | null>(null);
  const [language, setLanguage] = useState('');
  const [typed, setTyped] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  const capsQ = useQuery({ queryKey: ['meetings-speech-capabilities'], queryFn: fetchSpeechCapabilities, staleTime: 60_000 });
  const recQ = useQuery({ queryKey: ['meeting-recordings', meetingId], queryFn: () => fetchRecordings(meetingId) });
  const validationQ = useQuery({
    queryKey: ['meeting-validation', meetingId],
    queryFn: () => fetchMeetingValidation(meetingId),
    enabled: (recQ.data?.length ?? 0) > 0,
  });
  const failing = failingRules(validationQ.data?.results ?? []);
  const caps = capsQ.data;
  const recorder = useMeetingRecorder(caps?.max_upload_mb ?? 25);
  const serverSpeech = !!caps?.server_transcription;
  // Without server speech the browser's recognition is the transcript; nothing is uploaded.
  const browserOnly = !serverSpeech;

  const people: ReviewPerson[] = useMemo(
    () => attendees.filter((a) => a.name).map((a) => ({ name: a.name, contact_id: a.user_id ?? null })),
    [attendees],
  );

  const setRecordings = (rows: MeetingRecording[]) => {
    qc.setQueryData(['meeting-recordings', meetingId], rows);
    void qc.invalidateQueries({ queryKey: ['meeting-validation', meetingId] });
  };
  const upsert = (row: MeetingRecording) =>
    setRecordings([row, ...(recQ.data ?? []).filter((r) => r.id !== row.id)].sort((a, b) => b.created_at.localeCompare(a.created_at)));
  const fail = (title: string) => (e: unknown) => addToast({ type: 'error', title, message: getErrorMessage(e) });

  const createMut = useMutation({
    mutationFn: (input: { file?: File | null; transcript?: string; source: RecordingSource }) =>
      createRecording(meetingId, {
        ...input,
        segments: input.transcript ? segmentsFromText(input.transcript) : undefined,
        language: language || undefined,
        consentConfirmed: consent,
        deleteAudioAfterTranscription: deleteAfter,
        retentionDays: retention,
      }),
    onSuccess: (row) => {
      upsert(row);
      setMode('idle');
      setTyped('');
      setConsent(false);
      addToast({
        type: row.status === 'transcribed' ? 'success' : 'info',
        title:
          row.status === 'transcribed'
            ? t('meetings.audio.saved_transcribed', { defaultValue: 'Transcript ready for review' })
            : t('meetings.audio.saved_waiting', {
                defaultValue: 'Recording saved. Add the transcript to continue.',
              }),
      });
    },
    onError: fail(t('meetings.audio.save_failed', { defaultValue: 'Could not save the recording' })),
  });

  useEffect(() => {
    if (recorder.limitReached) void finishRecording();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recorder.limitReached]);

  async function startRecording() {
    await recorder.start({
      keepAudio: !browserOnly,
      liveRecognition: recorder.speechSupported,
      language: language || i18n.language,
    });
    setMode('recording');
  }

  async function finishRecording() {
    const result = await recorder.stop();
    if (!browserOnly && result.file) {
      createMut.mutate({ file: result.file, transcript: result.liveText, source: 'browser_record' });
    } else if (result.liveText) {
      createMut.mutate({ transcript: result.liveText, source: 'browser_speech' });
    } else {
      setMode('consent');
    }
  }

  function onFile(file: File | undefined) {
    if (!file) return;
    createMut.mutate({ file, source: 'upload' });
  }

  const busy = createMut.isPending;
  const recordings = recQ.data ?? [];

  const errorText = (code: RecorderError) =>
    t(`meetings.audio.recorder_error_${code}`, {
      defaultValue: {
        unsupported: 'This browser cannot record here. Upload a file or type the transcript.',
        mic_blocked: 'The microphone is blocked. Allow it in the browser, upload a file or type the transcript.',
        empty: 'Nothing was captured. Try again, upload a file or type the transcript.',
      }[code],
    });

  return (
    <div className="rounded-lg bg-surface-secondary p-3 space-y-3" data-testid="meeting-recording-panel" onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-xs text-content-tertiary font-medium uppercase tracking-wide flex items-center gap-1.5">
          <FileAudio size={12} />
          {t('meetings.audio.title', { defaultValue: 'Recording and transcript' })}
        </p>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => setGlossaryOpen(true)} data-testid="open-glossary">
            <BookA size={14} className="mr-1.5" />
            {t('meetings.audio.glossary', { defaultValue: 'Glossary' })}
          </Button>
          {mode === 'idle' && (
            <Button variant="secondary" size="sm" onClick={() => setMode('consent')} data-testid="add-recording">
              <Mic size={14} className="mr-1.5" />
              {t('meetings.audio.add', { defaultValue: 'Record or add transcript' })}
            </Button>
          )}
        </div>
      </div>

      {caps && (
        <p className="text-xs text-content-secondary" data-testid="speech-capability-note">
          {serverSpeech
            ? t('meetings.audio.cap_server', {
                defaultValue: 'Audio is transcribed by the speech service configured for this workspace.',
              })
            : recorder.speechSupported
              ? t('meetings.audio.cap_browser', {
                  defaultValue:
                    'No speech service is configured. This browser writes the transcript live while you record; no audio is stored.',
                })
              : t('meetings.audio.cap_manual', {
                  defaultValue:
                    'No speech service is configured and this browser has no speech recognition. Paste or type the transcript.',
                })}{' '}
          {!caps.llm_available &&
            t('meetings.audio.cap_no_ai', {
              defaultValue: 'No AI is configured, so proposals come from simple keyword rules.',
            })}
        </p>
      )}

      {failing.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5" data-testid="meeting-checks">
          {failing.map(({ rule, severity }) => (
            <Badge key={rule} variant={severity === 'error' ? 'error' : 'warning'} size="sm">
              {t(`meetings.audio.rule_${rule.replace('meetings.', '')}`, { defaultValue: RULE_DEFAULTS[rule] })}
            </Badge>
          ))}
        </div>
      )}

      {mode === 'consent' && caps && (
        <div className="rounded-lg border border-border-light bg-surface-primary p-3 space-y-3" data-testid="recording-consent">
          <div className="flex items-start gap-2">
            <ShieldCheck size={16} className="text-oe-blue shrink-0 mt-0.5" />
            <p className="text-sm text-content-primary">
              {t('meetings.audio.consent_notice', {
                defaultValue:
                  'Before recording, tell everyone in the meeting that it is recorded and transcribed, what it is used for (the minutes) and how long the audio is kept. Record only if everyone agrees.',
              })}
            </p>
          </div>
          <label className="flex items-start gap-2 text-sm text-content-primary">
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
              data-testid="consent-checkbox"
              className="mt-0.5"
            />
            {t('meetings.audio.consent_confirm', {
              defaultValue: 'I confirm that every participant was told about the recording and agreed.',
            })}
          </label>
          <div className="flex items-center gap-3 flex-wrap text-xs text-content-secondary">
            <label className="flex items-center gap-1.5">
              {t('meetings.audio.language', { defaultValue: 'Spoken language' })}
              <select className={fieldCls} value={language} onChange={(e) => setLanguage(e.target.value)} data-testid="recording-language">
                <option value="">{t('meetings.audio.language_auto', { defaultValue: 'Meeting language' })}</option>
                {SPOKEN_LANGUAGES.map((code) => (
                  <option key={code} value={code}>
                    {languageLabel(code, i18n.language)}
                  </option>
                ))}
              </select>
            </label>
            {serverSpeech && (
              <>
                <label className="flex items-center gap-1.5">
                  {t('meetings.audio.retention', { defaultValue: 'Keep audio for (days)' })}
                  <select
                    className={fieldCls}
                    value={retention ?? ''}
                    onChange={(e) => setRetention(e.target.value ? Number(e.target.value) : null)}
                    disabled={deleteAfter}
                  >
                    <option value="">
                      {caps.default_retention_days > 0
                        ? t('meetings.audio.retention_default', {
                            defaultValue: 'Workspace default ({{days}})',
                            days: caps.default_retention_days,
                          })
                        : t('meetings.audio.retention_forever', { defaultValue: 'Until deleted' })}
                    </option>
                    {retentionOptions(caps.default_retention_days, caps.max_retention_days).map((d) => (
                      <option key={d} value={d}>
                        {d}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={deleteAfter}
                    onChange={(e) => setDeleteAfter(e.target.checked)}
                    data-testid="delete-after-checkbox"
                  />
                  {t('meetings.audio.delete_after', { defaultValue: 'Delete audio right after transcription' })}
                </label>
              </>
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <Button
              variant="primary"
              size="sm"
              disabled={!consent || busy || (browserOnly ? !recorder.speechSupported : !recorder.micSupported)}
              onClick={() => void startRecording()}
              data-testid="start-recording"
            >
              <Mic size={14} className="mr-1.5" />
              {t('meetings.audio.start', { defaultValue: 'Start recording' })}
            </Button>
            {serverSpeech && (
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!consent || busy}
                  onClick={() => fileRef.current?.click()}
                  data-testid="upload-audio"
                >
                  <Upload size={14} className="mr-1.5" />
                  {t('meetings.audio.upload', { defaultValue: 'Upload audio' })}
                </Button>
                <input
                  ref={fileRef}
                  type="file"
                  className="hidden"
                  accept={caps.accepted_formats.map((f) => `.${f}`).join(',')}
                  onChange={(e) => onFile(e.target.files?.[0])}
                />
              </>
            )}
            <Button variant="ghost" size="sm" disabled={busy} onClick={() => setMode('typing')} data-testid="type-transcript">
              <TypeIcon size={14} className="mr-1.5" />
              {t('meetings.audio.type', { defaultValue: 'Type or paste transcript' })}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setMode('idle')}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            {busy && <Loader2 size={14} className="animate-spin text-content-tertiary" />}
          </div>
          {recorder.error && <p className="text-xs text-semantic-error">{errorText(recorder.error)}</p>}
        </div>
      )}

      {mode === 'recording' && (
        <div className="rounded-lg border border-semantic-error/40 bg-surface-primary p-3 space-y-2" data-testid="recording-live">
          <div className="flex items-center gap-3">
            <span className="h-2.5 w-2.5 rounded-full bg-semantic-error animate-pulse" />
            <span className="font-mono text-sm">{formatClock(recorder.seconds)}</span>
            <span className="text-xs text-content-tertiary">
              {t('meetings.audio.limit', { defaultValue: 'max {{time}}', time: formatClock(recorder.maxSeconds) })}
            </span>
            <div className="flex-1" />
            <Button variant="primary" size="sm" onClick={() => void finishRecording()} data-testid="stop-recording">
              <Square size={14} className="mr-1.5" />
              {t('meetings.audio.stop', { defaultValue: 'Stop and transcribe' })}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                recorder.cancel();
                setMode('idle');
              }}
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
          {(recorder.liveText || recorder.interimText) && (
            <p className="text-sm text-content-secondary whitespace-pre-wrap max-h-40 overflow-y-auto">
              {recorder.liveText}
              {recorder.interimText && <span className="text-content-tertiary"> {recorder.interimText}</span>}
            </p>
          )}
        </div>
      )}

      {mode === 'typing' && (
        <div className="rounded-lg border border-border-light bg-surface-primary p-3 space-y-2">
          <textarea
            className={areaCls}
            rows={8}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={t('meetings.audio.type_placeholder', {
              defaultValue: 'One line per turn, for example: "Anna: The slab pour moves to Friday."',
            })}
            data-testid="typed-transcript"
          />
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              disabled={!typed.trim() || busy}
              onClick={() => createMut.mutate({ transcript: typed, source: 'manual' })}
              data-testid="save-typed"
            >
              {t('meetings.audio.save_transcript', { defaultValue: 'Save transcript' })}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setMode('idle')}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        </div>
      )}

      {recordings.map((rec) => (
        <RecordingCard key={rec.id} rec={rec} people={people} onChange={upsert} confirm={confirm} onRemoved={(id) => setRecordings(recordings.filter((r) => r.id !== id))} />
      ))}

      {glossaryOpen && <MeetingGlossaryDialog projectId={projectId} onClose={() => setGlossaryOpen(false)} />}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

interface RecordingCardProps {
  rec: MeetingRecording;
  people: ReviewPerson[];
  onChange: (row: MeetingRecording) => void;
  onRemoved: (id: string) => void;
  confirm: ReturnType<typeof useConfirm>['confirm'];
}

function RecordingCard({ rec, people, onChange, onRemoved, confirm }: RecordingCardProps) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [transcript, setTranscript] = useState(rec.transcript);
  const [speakers, setSpeakers] = useState<Record<string, SpeakerInfo>>(rec.speakers ?? {});
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [audioLoading, setAudioLoading] = useState(false);

  useEffect(() => {
    setTranscript(rec.transcript);
    setSpeakers(rec.speakers ?? {});
  }, [rec.transcript, rec.speakers]);

  useEffect(() => () => {
    if (audioUrl) URL.revokeObjectURL(audioUrl);
  }, [audioUrl]);

  const labels = speakerLabels(rec.segments ?? []);
  const dirty = transcript !== rec.transcript || JSON.stringify(speakers) !== JSON.stringify(rec.speakers ?? {});
  const fail = (title: string) => (e: unknown) => addToast({ type: 'error', title, message: getErrorMessage(e) });

  const saveMut = useMutation({
    mutationFn: () =>
      updateRecording(rec.id, {
        ...(transcript !== rec.transcript ? { transcript } : {}),
        speakers,
      }),
    onSuccess: onChange,
    onError: fail(t('meetings.audio.save_failed', { defaultValue: 'Could not save the recording' })),
  });

  const proposeMut = useMutation({
    mutationFn: async () => {
      if (dirty) await saveMut.mutateAsync();
      return proposeMinutes(rec.id);
    },
    onSuccess: onChange,
    onError: fail(t('meetings.audio.propose_failed', { defaultValue: 'Could not build proposals' })),
  });

  const retryMut = useMutation({
    mutationFn: () => retranscribeRecording(rec.id),
    onSuccess: onChange,
    onError: fail(t('meetings.audio.save_failed', { defaultValue: 'Could not save the recording' })),
  });

  const reviewMut = useMutation({
    mutationFn: ({ entry, createTask }: { entry: ProposalEdit; createTask: boolean }) =>
      reviewProposals(rec.id, [entry], createTask),
    onSuccess: (res) => {
      onChange(res.recording);
      if (res.errors.length) {
        addToast({
          type: 'error',
          title: t('meetings.audio.review_failed', { defaultValue: 'Could not apply the proposal' }),
          message: res.errors.map((e) => e.error).join(' '),
        });
        return;
      }
      if (res.actions_created.length) {
        void qc.invalidateQueries({ queryKey: ['meeting-actions'] });
        addToast({
          type: 'success',
          title: t('meetings.audio.action_created', {
            defaultValue: 'Action added to the register',
          }),
          message: res.tasks_created.length
            ? t('meetings.audio.task_created', { defaultValue: 'A task was opened for the owner.' })
            : undefined,
        });
      }
      void qc.invalidateQueries({ queryKey: ['meeting-minutes', rec.meeting_id] });
      void qc.invalidateQueries({ queryKey: ['meetings'] });
    },
    onError: fail(t('meetings.audio.review_failed', { defaultValue: 'Could not apply the proposal' })),
  });

  const deleteAudioMut = useMutation({
    mutationFn: () => deleteRecordingAudio(rec.id),
    onSuccess: onChange,
    onError: fail(t('meetings.audio.delete_failed', { defaultValue: 'Could not delete' })),
  });

  const deleteMut = useMutation({
    mutationFn: () => deleteRecording(rec.id),
    onSuccess: () => onRemoved(rec.id),
    onError: fail(t('meetings.audio.delete_failed', { defaultValue: 'Could not delete' })),
  });

  async function playAudio() {
    if (audioUrl) return;
    setAudioLoading(true);
    try {
      const token = getAuthToken();
      const res = await fetch(getRecordingAudioUrl(rec.id), {
        headers: { 'X-DDC-Client': 'OE/1.0', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setAudioUrl(URL.createObjectURL(await res.blob()));
    } catch (e) {
      fail(t('meetings.audio.play_failed', { defaultValue: 'Could not load the audio' }))(e);
    } finally {
      setAudioLoading(false);
    }
  }

  const statusLabel = t(`meetings.audio.status_${rec.status}`, {
    defaultValue: {
      pending: 'Waiting',
      transcribed: 'Transcribed',
      awaiting_transcript: 'Waiting for transcript',
      failed: 'Transcription failed',
    }[rec.status],
  });
  const sourceLabel = t(`meetings.audio.source_${rec.source}`, {
    defaultValue: {
      upload: 'Uploaded file',
      browser_record: 'Recorded in browser',
      browser_speech: 'Browser speech recognition',
      manual: 'Typed transcript',
    }[rec.source],
  });
  const pendingCount = (rec.proposals.items ?? []).filter((p) => p.status === 'pending').length;

  return (
    <div className="rounded-lg border border-border-light bg-surface-primary p-3 space-y-3" data-testid={`recording-${rec.id}`}>
      <div className="flex items-center gap-2 flex-wrap text-xs text-content-secondary">
        <Badge variant={rec.status === 'transcribed' ? 'success' : rec.status === 'failed' ? 'error' : 'warning'} size="sm">
          {statusLabel}
        </Badge>
        <span>{sourceLabel}</span>
        {rec.language && <span>&middot; {languageLabel(rec.language, i18n.language)}</span>}
        <span>
          &middot; <DateDisplay value={rec.created_at} />
        </span>
        {rec.consent_confirmed_at && (
          <span className="inline-flex items-center gap-1" title={rec.consent_confirmed_at}>
            &middot; <ShieldCheck size={12} />
            {t('meetings.audio.consent_recorded', { defaultValue: 'Consent recorded' })}
          </span>
        )}
        {rec.glossary_replacements > 0 && (
          <span>
            &middot;{' '}
            {t('meetings.audio.glossary_fixed', {
              defaultValue: 'Glossary corrections: {{n}}',
              n: rec.glossary_replacements,
            })}
          </span>
        )}
        <div className="flex-1" />
        <Button
          variant="ghost"
          size="sm"
          onClick={async () => {
            const ok = await confirm({
              title: t('meetings.audio.delete_title', { defaultValue: 'Delete this recording?' }),
              message: t('meetings.audio.delete_msg', {
                defaultValue: 'The audio, transcript and open proposals are deleted. Confirmed minutes items stay.',
              }),
              confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
              variant: 'danger',
            });
            if (ok) deleteMut.mutate();
          }}
          aria-label={t('common.delete', { defaultValue: 'Delete' })}
        >
          <Trash2 size={14} />
        </Button>
      </div>

      {rec.has_audio ? (
        <div className="flex items-center gap-2 flex-wrap text-xs text-content-secondary">
          {audioUrl ? (
            <audio controls src={audioUrl} className="h-8" />
          ) : (
            <Button variant="ghost" size="sm" onClick={() => void playAudio()} disabled={audioLoading}>
              {audioLoading ? <Loader2 size={14} className="mr-1.5 animate-spin" /> : <Play size={14} className="mr-1.5" />}
              {t('meetings.audio.play', { defaultValue: 'Play audio' })}
            </Button>
          )}
          {rec.audio_expires_at && (
            <span>
              {t('meetings.audio.expires', { defaultValue: 'Audio is deleted on' })} <DateDisplay value={rec.audio_expires_at} />
            </span>
          )}
          {(rec.status === 'failed' || rec.status === 'awaiting_transcript') && (
            <Button variant="ghost" size="sm" onClick={() => retryMut.mutate()} disabled={retryMut.isPending}>
              <RefreshCw size={14} className="mr-1.5" />
              {t('meetings.audio.retry', { defaultValue: 'Transcribe again' })}
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => deleteAudioMut.mutate()}
            disabled={deleteAudioMut.isPending}
            data-testid={`delete-audio-${rec.id}`}
          >
            <VolumeX size={14} className="mr-1.5" />
            {t('meetings.audio.delete_audio', { defaultValue: 'Delete audio now' })}
          </Button>
        </div>
      ) : (
        rec.audio_deleted_at && (
          <p className="text-xs text-content-tertiary">
            {t('meetings.audio.audio_deleted', { defaultValue: 'Audio deleted; the transcript is kept.' })}
          </p>
        )
      )}

      {rec.transcription_error && rec.status !== 'transcribed' && (
        <p className="text-xs text-semantic-warning">
          {t('meetings.audio.no_transcript', {
            defaultValue: 'The audio could not be transcribed on the server. Paste or type the transcript below.',
          })}
        </p>
      )}

      {labels.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-content-secondary">
            {t('meetings.audio.speakers', { defaultValue: 'Speakers' })}
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
            {labels.map((label) => (
              <label key={label} className="flex items-center gap-2 text-xs text-content-secondary">
                <span className="w-24 shrink-0 truncate font-mono">{label}</span>
                <input
                  className={`${fieldCls} flex-1`}
                  list={`speakers-${rec.id}`}
                  value={speakers[label]?.name ?? ''}
                  placeholder={t('meetings.audio.speaker_name', { defaultValue: 'Who is this?' })}
                  onChange={(e) => {
                    const name = e.target.value;
                    const hit = people.find((p) => p.name === name);
                    setSpeakers((prev) => ({ ...prev, [label]: { name, contact_id: hit?.contact_id ?? null } }));
                  }}
                  data-testid={`speaker-${label}`}
                />
              </label>
            ))}
          </div>
          <datalist id={`speakers-${rec.id}`}>
            {people.map((p) => (
              <option key={`${p.name}-${p.contact_id ?? ''}`} value={p.name} />
            ))}
          </datalist>
        </div>
      )}

      <textarea
        className={areaCls}
        rows={6}
        value={transcript}
        onChange={(e) => setTranscript(e.target.value)}
        placeholder={t('meetings.audio.type_placeholder', {
          defaultValue: 'One line per turn, for example: "Anna: The slab pour moves to Friday."',
        })}
        aria-label={t('meetings.audio.transcript', { defaultValue: 'Transcript' })}
        data-testid={`transcript-${rec.id}`}
      />

      <div className="flex items-center gap-2 flex-wrap">
        <Button variant="secondary" size="sm" disabled={!dirty || saveMut.isPending} onClick={() => saveMut.mutate()}>
          {t('meetings.audio.save_transcript', { defaultValue: 'Save transcript' })}
        </Button>
        <Button
          variant="primary"
          size="sm"
          disabled={!transcript.trim() || proposeMut.isPending}
          onClick={() => proposeMut.mutate()}
          data-testid={`propose-${rec.id}`}
        >
          {proposeMut.isPending ? <Loader2 size={14} className="mr-1.5 animate-spin" /> : <Sparkles size={14} className="mr-1.5" />}
          {(rec.proposals.items ?? []).length
            ? t('meetings.audio.propose_again', { defaultValue: 'Propose again' })
            : t('meetings.audio.propose', { defaultValue: 'Propose minutes' })}
        </Button>
        {pendingCount > 0 && (
          <span className="text-xs text-content-tertiary">
            {t('meetings.audio.pending_count', { defaultValue: 'To review: {{n}}', n: pendingCount })}
          </span>
        )}
      </div>

      {rec.proposals.items && (
        <ProposalReviewList
          proposals={rec.proposals}
          people={[
            ...people,
            ...Object.values(speakers)
              .filter((s) => s.name && !people.some((p) => p.name === s.name))
              .map((s) => ({ name: s.name, contact_id: s.contact_id })),
          ]}
          busy={reviewMut.isPending}
          onReview={(entry, createTask) => reviewMut.mutate({ entry, createTask })}
        />
      )}
    </div>
  );
}
