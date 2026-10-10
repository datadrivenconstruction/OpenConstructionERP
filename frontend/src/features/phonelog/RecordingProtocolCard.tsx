// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Recording -> protocol. A site engineer drops an audio or video recording of a
// call, meeting, or site conversation; the server transcribes it and drafts a
// structured, dispute-ready protocol (participants, summary, decisions, action
// items, instructions). This card presents that draft for review - everything is
// editable and nothing is saved until the user confirms. When transcription is
// unavailable the recording is still stored and the transcript can be pasted by
// hand. AI suggests, a human confirms.

import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Check,
  ListChecks,
  Loader2,
  Mic,
  Plus,
  Sparkles,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import { Badge, Button, Card } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { deletePhoneLog, finalizePhoneLog, transcribeRecording } from './api';
import { readProtocol, readTranscription } from './protocol';
import { RecordingPlayer } from './RecordingPlayer';
import type { PhoneDirection, PhoneLog, ProtocolActionItem } from './types';

const INPUT_CLASS =
  'rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary';
const LABEL_CLASS = 'flex flex-col gap-1 text-sm text-content-secondary';
// A speech-to-text provider takes these directly, so no local transcode is needed.
const ACCEPT = 'audio/*,video/*,.mp3,.m4a,.wav,.webm,.mp4,.mpeg,.mpga';
const DIRECTIONS: PhoneDirection[] = ['inbound', 'outbound', 'internal'];

type Phase = 'idle' | 'processing' | 'review';

interface DraftState {
  direction: PhoneDirection;
  occurred_at: string;
  duration_minutes: string;
  participants: string;
  summary: string;
  decisions: string;
  instructions: string;
  transcript: string;
  actionItems: ProtocolActionItem[];
}

const EMPTY_DRAFT: DraftState = {
  direction: 'inbound',
  occurred_at: '',
  duration_minutes: '',
  participants: '',
  summary: '',
  decisions: '',
  instructions: '',
  transcript: '',
  actionItems: [],
};

const splitLines = (value: string): string[] =>
  value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);

const splitParticipants = (value: string): string[] =>
  value
    .split(/[\n,]/)
    .map((name) => name.trim())
    .filter(Boolean);

function directionLabel(
  t: (k: string, o: { defaultValue: string }) => string,
  d: PhoneDirection,
): string {
  return t(`phonelog.direction_${d}`, {
    defaultValue: { inbound: 'Inbound', outbound: 'Outbound', internal: 'Internal', unknown: 'Unknown' }[d],
  });
}

export function RecordingProtocolCard({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [phase, setPhase] = useState<Phase>('idle');
  const [dragOver, setDragOver] = useState(false);
  const [draft, setDraft] = useState<PhoneLog | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [state, setState] = useState<DraftState>(EMPTY_DRAFT);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(
    () => () => {
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    },
    [audioUrl],
  );

  const setField = <K extends keyof DraftState>(key: K, value: DraftState[K]) =>
    setState((prev) => ({ ...prev, [key]: value }));

  const reset = useCallback(() => {
    setAudioUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
    setDraft(null);
    setState(EMPTY_DRAFT);
    setPhase('idle');
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, []);

  const populateFrom = useCallback((row: PhoneLog) => {
    const proto = readProtocol(row);
    setState({
      direction: row.direction === 'unknown' ? 'inbound' : row.direction,
      occurred_at: row.occurred_at ? row.occurred_at.slice(0, 16) : '',
      duration_minutes: row.duration_seconds ? String(Math.round(row.duration_seconds / 60)) : '',
      participants: (proto?.participants ?? row.parties).join(', '),
      summary: proto?.summary ?? row.summary,
      decisions: (proto?.decisions ?? []).join('\n'),
      instructions: (proto?.instructions ?? row.instructions).join('\n'),
      transcript: row.transcript,
      actionItems: proto?.action_items ?? [],
    });
  }, []);

  const uploadMutation = useMutation({
    mutationFn: (file: File) => transcribeRecording(projectId, file),
    onMutate: (file: File) => {
      setPhase('processing');
      const url = URL.createObjectURL(file);
      setAudioUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return url;
      });
    },
    onSuccess: (row) => {
      setDraft(row);
      populateFrom(row);
      setPhase('review');
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('phonelog.rec.upload_error', { defaultValue: 'Could not process the recording' }),
        message: getErrorMessage(err),
      });
      reset();
    },
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!draft) throw new Error('No draft to save');
      const proto = readProtocol(draft);
      const minutes = parseFloat(state.duration_minutes);
      const decisions = splitLines(state.decisions);
      const instructions = splitLines(state.instructions);
      const participants = splitParticipants(state.participants);
      const actionItems = state.actionItems.filter((item) => item.task.trim() !== '');
      return finalizePhoneLog(draft.id, {
        direction: state.direction,
        channel: 'voice_note',
        raw_parties: state.participants,
        occurred_at: state.occurred_at || null,
        duration_seconds: Number.isFinite(minutes) && minutes > 0 ? Math.round(minutes * 60) : null,
        transcript: state.transcript,
        summary: state.summary,
        instructions,
        protocol: {
          participants,
          summary: state.summary,
          decisions,
          action_items: actionItems,
          instructions,
          confidence: proto?.confidence ?? null,
          ai_generated: proto?.ai_generated ?? false,
        },
      });
    },
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('phonelog.rec.saved', { defaultValue: 'Protocol saved to the phone log' }),
      });
      reset();
      void queryClient.invalidateQueries({ queryKey: ['phonelog', 'list', projectId] });
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('phonelog.rec.save_error', { defaultValue: 'Could not save the protocol' }),
        message: getErrorMessage(err),
      });
    },
  });

  const discardMutation = useMutation({
    mutationFn: () => (draft ? deletePhoneLog(draft.id) : Promise.resolve()),
    onSuccess: () => {
      addToast({
        type: 'info',
        title: t('phonelog.rec.discarded', { defaultValue: 'Draft discarded' }),
      });
      reset();
      void queryClient.invalidateQueries({ queryKey: ['phonelog', 'list', projectId] });
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('phonelog.rec.discard_error', { defaultValue: 'Could not discard the draft' }),
        message: getErrorMessage(err),
      });
    },
  });

  const onFiles = useCallback(
    (files: FileList | null) => {
      const file = files?.[0];
      if (file && !uploadMutation.isPending) uploadMutation.mutate(file);
    },
    [uploadMutation],
  );

  const onDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      onFiles(e.dataTransfer.files);
    },
    [onFiles],
  );

  const updateActionItem = (index: number, field: keyof ProtocolActionItem, value: string) =>
    setState((prev) => ({
      ...prev,
      actionItems: prev.actionItems.map((item, i) =>
        i === index
          ? {
              owner: field === 'owner' ? value : item.owner,
              task: field === 'task' ? value : item.task,
              due: field === 'due' ? value || null : item.due,
            }
          : item,
      ),
    }));

  const addActionItem = () =>
    setState((prev) => ({ ...prev, actionItems: [...prev.actionItems, { owner: '', task: '', due: null }] }));

  const removeActionItem = (index: number) =>
    setState((prev) => ({ ...prev, actionItems: prev.actionItems.filter((_, i) => i !== index) }));

  // ---- idle: the upload zone ----------------------------------------------------
  if (phase !== 'review') {
    const processing = phase === 'processing';
    return (
      <Card className="space-y-3 p-4">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
            <Mic className="h-4 w-4" />
            {t('phonelog.rec.card_title', { defaultValue: 'Create a protocol from a recording' })}
          </h2>
          <p className="mt-1 text-sm text-content-secondary">
            {t('phonelog.rec.card_hint', {
              defaultValue:
                'Upload an audio or video recording of a call, meeting, or site conversation. We draft a full protocol you review before saving.',
            })}
          </p>
          <p className="mt-1 text-xs text-content-tertiary">
            {t('ai.transcription_goes_to_openai', {
              defaultValue:
                'Audio is transcribed by OpenAI with your OpenAI key, whatever AI provider you selected in Settings. Recordings are kept for 90 days by default.',
            })}
          </p>
        </div>

        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => onFiles(e.target.files)}
        />

        {processing ? (
          <div className="flex flex-col items-center gap-2 rounded-2xl border-2 border-dashed border-border-light bg-surface-secondary/40 p-8 text-center">
            <Loader2 className="h-6 w-6 animate-spin text-oe-blue" />
            <p className="text-sm font-medium text-content-primary">
              {t('phonelog.rec.transcribing', { defaultValue: 'Transcribing and drafting the protocol' })}
            </p>
            <p className="text-xs text-content-tertiary">
              {t('phonelog.rec.transcribing_hint', {
                defaultValue: 'This can take a moment for a longer recording. Please keep this tab open.',
              })}
            </p>
          </div>
        ) : (
          <div
            role="button"
            tabIndex={0}
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click();
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={(e) => {
              e.preventDefault();
              setDragOver(false);
            }}
            onDrop={onDrop}
            className={`flex cursor-pointer flex-col items-center gap-2 rounded-2xl border-2 border-dashed p-8 text-center transition ${
              dragOver
                ? 'border-oe-blue bg-oe-blue/5'
                : 'border-border-medium hover:border-oe-blue/50 hover:bg-surface-secondary/40'
            }`}
          >
            <Upload className="h-6 w-6 text-oe-blue" />
            <p className="text-sm font-medium text-content-primary">
              {t('phonelog.rec.drop_title', { defaultValue: 'Drop a recording here or click to choose' })}
            </p>
            <p className="text-xs text-content-tertiary">
              {t('phonelog.rec.drop_hint', { defaultValue: 'Audio or video up to 25 MB (mp3, m4a, wav, webm, mp4)' })}
            </p>
          </div>
        )}
      </Card>
    );
  }

  // ---- review: the editable draft protocol -------------------------------------
  const proto = draft ? readProtocol(draft) : null;
  const transcription = draft ? readTranscription(draft) : null;
  const noTranscript = !transcription?.available;
  const confidencePct = proto?.confidence != null ? Math.round(proto.confidence * 100) : null;

  return (
    <Card className="space-y-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
            <ListChecks className="h-4 w-4" />
            {t('phonelog.rec.review_title', { defaultValue: 'Review the draft protocol' })}
          </h2>
          <p className="mt-1 text-sm text-content-secondary">
            {t('phonelog.rec.review_hint', {
              defaultValue: 'Nothing is saved yet. Check the details, edit anything, then save it to the phone log.',
            })}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {proto?.ai_generated && (
            <Badge variant="blue">
              <span className="inline-flex items-center gap-1">
                <Sparkles className="h-3 w-3" />
                {t('phonelog.rec.ai_generated', { defaultValue: 'AI-drafted' })}
              </span>
            </Badge>
          )}
          {confidencePct != null && (
            <Badge variant={confidencePct >= 66 ? 'success' : confidencePct >= 33 ? 'warning' : 'neutral'}>
              {t('phonelog.rec.confidence', { defaultValue: '{{percent}}% confidence', percent: confidencePct })}
            </Badge>
          )}
        </div>
      </div>

      {noTranscript && (
        <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            {t('phonelog.rec.manual_note', {
              defaultValue:
                'Automatic transcription is not available right now, so the recording was saved without a transcript. Paste what was said below and we will build the protocol from it.',
            })}
          </span>
        </div>
      )}

      <div className="space-y-1">
        <div className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
          {t('phonelog.rec.recording', { defaultValue: 'Recording' })}
        </div>
        <RecordingPlayer id={draft?.id} src={audioUrl ?? undefined} />
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className={LABEL_CLASS}>
          {t('phonelog.rec.participants', { defaultValue: 'Participants' })}
          <input
            value={state.participants}
            onChange={(e) => setField('participants', e.target.value)}
            placeholder={t('phonelog.rec.participants_ph', { defaultValue: 'You, Acme site office' })}
            className={INPUT_CLASS}
          />
        </label>

        <label className={LABEL_CLASS}>
          {t('phonelog.rec.direction', { defaultValue: 'Direction' })}
          <select
            value={state.direction}
            onChange={(e) => setField('direction', e.target.value as PhoneDirection)}
            className={INPUT_CLASS}
          >
            {DIRECTIONS.map((d) => (
              <option key={d} value={d}>
                {directionLabel(t, d)}
              </option>
            ))}
          </select>
        </label>

        <label className={LABEL_CLASS}>
          {t('phonelog.rec.when', { defaultValue: 'When' })}
          <input
            type="datetime-local"
            value={state.occurred_at}
            onChange={(e) => setField('occurred_at', e.target.value)}
            className={INPUT_CLASS}
          />
        </label>

        <label className={LABEL_CLASS}>
          {t('phonelog.rec.duration_min', { defaultValue: 'Duration (minutes)' })}
          <input
            type="number"
            min="0"
            step="1"
            value={state.duration_minutes}
            onChange={(e) => setField('duration_minutes', e.target.value)}
            className={INPUT_CLASS}
          />
        </label>
      </div>

      <label className={LABEL_CLASS}>
        {t('phonelog.rec.summary', { defaultValue: 'Summary' })}
        <textarea
          value={state.summary}
          onChange={(e) => setField('summary', e.target.value)}
          rows={2}
          className={INPUT_CLASS}
        />
      </label>

      <label className={LABEL_CLASS}>
        {t('phonelog.rec.decisions', { defaultValue: 'Decisions' })}
        <textarea
          value={state.decisions}
          onChange={(e) => setField('decisions', e.target.value)}
          rows={3}
          placeholder={t('phonelog.rec.decisions_ph', { defaultValue: 'One decision per line' })}
          className={INPUT_CLASS}
        />
      </label>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-sm text-content-secondary">
            {t('phonelog.rec.action_items', { defaultValue: 'Action items' })}
          </span>
          <button
            type="button"
            onClick={addActionItem}
            className="inline-flex items-center gap-1 rounded-md border border-border-light px-2 py-1 text-xs text-content-secondary hover:bg-surface-secondary"
          >
            <Plus className="h-3.5 w-3.5" />
            {t('phonelog.rec.action_add', { defaultValue: 'Add action item' })}
          </button>
        </div>

        {state.actionItems.length === 0 ? (
          <p className="text-xs text-content-tertiary">
            {t('phonelog.rec.action_empty', { defaultValue: 'No action items yet. Add one if a task was agreed.' })}
          </p>
        ) : (
          <div className="space-y-2">
            {state.actionItems.map((item, index) => (
              <div key={index} className="flex flex-col gap-2 rounded-md border border-border-light p-2 sm:flex-row">
                <input
                  value={item.task}
                  onChange={(e) => updateActionItem(index, 'task', e.target.value)}
                  placeholder={t('phonelog.rec.action_task', { defaultValue: 'Task' })}
                  className={`${INPUT_CLASS} flex-1`}
                />
                <input
                  value={item.owner}
                  onChange={(e) => updateActionItem(index, 'owner', e.target.value)}
                  placeholder={t('phonelog.rec.action_owner', { defaultValue: 'Owner' })}
                  className={`${INPUT_CLASS} sm:w-40`}
                />
                <input
                  value={item.due ?? ''}
                  onChange={(e) => updateActionItem(index, 'due', e.target.value)}
                  placeholder={t('phonelog.rec.action_due', { defaultValue: 'Due (optional)' })}
                  className={`${INPUT_CLASS} sm:w-40`}
                />
                <button
                  type="button"
                  onClick={() => removeActionItem(index)}
                  aria-label={t('phonelog.rec.action_remove', { defaultValue: 'Remove action item' })}
                  className="inline-flex items-center justify-center rounded-md px-2 py-1 text-content-tertiary hover:bg-surface-secondary hover:text-red-600"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <label className={LABEL_CLASS}>
        {t('phonelog.rec.instructions', { defaultValue: 'Instructions' })}
        <textarea
          value={state.instructions}
          onChange={(e) => setField('instructions', e.target.value)}
          rows={3}
          placeholder={t('phonelog.rec.instructions_ph', { defaultValue: 'One instruction per line' })}
          className={INPUT_CLASS}
        />
      </label>

      <label className={LABEL_CLASS}>
        {t('phonelog.rec.transcript', { defaultValue: 'Transcript' })}
        <textarea
          value={state.transcript}
          onChange={(e) => setField('transcript', e.target.value)}
          rows={6}
          placeholder={t('phonelog.rec.transcript_ph', { defaultValue: 'Paste what was said on the recording.' })}
          className={INPUT_CLASS}
        />
      </label>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          icon={<Check size={16} />}
          loading={saveMutation.isPending}
          disabled={discardMutation.isPending}
          onClick={() => saveMutation.mutate()}
        >
          {t('phonelog.rec.save', { defaultValue: 'Save to phone log' })}
        </Button>
        <Button
          variant="ghost"
          icon={<X size={16} />}
          loading={discardMutation.isPending}
          disabled={saveMutation.isPending}
          onClick={() => discardMutation.mutate()}
        >
          {t('phonelog.rec.discard', { defaultValue: 'Discard' })}
        </Button>
      </div>
    </Card>
  );
}
