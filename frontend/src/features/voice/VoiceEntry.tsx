// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// <VoiceEntry> - the shared, one-import voice-to-structured-entry control. Drop
// it into any feature (daily diary, defects, tasks) and it handles the whole
// flow: record in the browser (or upload a recording, or type), transcribe and
// translate, then present an editable structured DRAFT with a confidence chip.
// Nothing is saved here - on confirm it hands the reviewed fields to the parent
// via onConfirm, which maps them onto that feature's own create request.
//
// AI suggests, a human confirms: the draft is always reviewable and editable,
// and the feature stays usable with no AI keys (raw transcript / typed note).

import { useCallback, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Check, Loader2, Mic, RotateCcw, Sparkles, Square, Upload, Wand2 } from 'lucide-react';
import { Button, ConfidenceBadge } from '@/shared/ui';
import { WideModal } from '@/shared/ui/WideModal';
import { useVoiceCapture } from './useVoiceCapture';
import { getField, humanizeToken, voiceTargetDef, type VoiceFieldDef } from './targets';
import type { ConfirmedVoiceDraft, VoiceTargetType } from './types';

// A speech-to-text provider takes these directly, so no local transcode is needed.
const ACCEPT = 'audio/*,video/*,.mp3,.m4a,.wav,.webm,.mp4,.mpeg,.mpga';
const INPUT_CLASS =
  'w-full rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const LABEL_CLASS = 'flex flex-col gap-1 text-sm text-content-secondary';

const CONFIRM_DEFAULT: Record<VoiceTargetType, string> = {
  diary_note: 'Add to diary',
  defect: 'Create defect',
  task: 'Create task',
};

function formatSeconds(total: number): string {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export interface VoiceEntryProps {
  projectId: string;
  target: VoiceTargetType;
  /** Save the reviewed draft. May be async; the dialog stays busy until it
   *  settles and closes on success. Map `fields` onto your create request. */
  onConfirm: (draft: ConfirmedVoiceDraft) => void | Promise<void>;
  /** Working language the draft is written in. Defaults to the UI language. */
  targetLanguage?: string;
  disabled?: boolean;
  /** Override the trigger button label. */
  triggerLabel?: string;
  /** Icon-only trigger for tight toolbars. */
  compact?: boolean;
  /** Confirm-button label override (defaults per target). */
  confirmLabel?: string;
  className?: string;
}

export function VoiceEntry({
  projectId,
  target,
  onConfirm,
  targetLanguage,
  disabled = false,
  triggerLabel,
  compact = false,
  confirmLabel,
  className,
}: VoiceEntryProps) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState('');
  const [confirming, setConfirming] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const capture = useVoiceCapture({
    projectId,
    target,
    targetLanguage: targetLanguage ?? i18n.language,
  });

  const def = voiceTargetDef(target);

  const close = useCallback(() => {
    capture.reset();
    setTyped('');
    setConfirming(false);
    setOpen(false);
  }, [capture]);

  const handleConfirm = useCallback(async () => {
    if (!capture.draft) return;
    setConfirming(true);
    try {
      await onConfirm({
        target,
        fields: capture.fields,
        transcript: capture.transcript,
        confidence: capture.draft.confidence,
        aiGenerated: capture.draft.ai_generated,
      });
      close();
    } catch {
      // The parent surfaces its own save error (toast); keep the draft open so
      // the user can retry without losing their edits.
      setConfirming(false);
    }
  }, [capture.draft, capture.fields, capture.transcript, onConfirm, target, close]);

  const onFileChosen = useCallback(
    (files: FileList | null) => {
      const file = files?.[0];
      if (file) capture.uploadFile(file);
      if (fileInputRef.current) fileInputRef.current.value = '';
    },
    [capture],
  );

  const titleValue = getField(capture.fields, 'title');
  const canConfirm = titleValue.trim() !== '' && !confirming;
  const busy = confirming || capture.phase === 'processing' || capture.phase === 'recording';
  const resolvedConfirmLabel =
    confirmLabel ?? t(`voice.confirm_${target}`, { defaultValue: CONFIRM_DEFAULT[target] });

  const renderField = (field: VoiceFieldDef) => {
    const value = getField(capture.fields, field.name);
    const label = t(field.labelKey, { defaultValue: field.defaultLabel });
    if (field.kind === 'enum' && field.choices) {
      return (
        <label key={field.name} className={LABEL_CLASS}>
          {label}
          <select
            value={value}
            onChange={(e) => capture.setField(field.name, e.target.value)}
            className={INPUT_CLASS}
          >
            {field.choices.map((choice) => (
              <option key={choice} value={choice}>
                {field.optionKey
                  ? t(field.optionKey(choice), { defaultValue: humanizeToken(choice) })
                  : humanizeToken(choice)}
              </option>
            ))}
          </select>
        </label>
      );
    }
    if (field.kind === 'longtext') {
      return (
        <label key={field.name} className={LABEL_CLASS}>
          {label}
          <textarea
            value={value}
            onChange={(e) => capture.setField(field.name, e.target.value)}
            rows={3}
            className={INPUT_CLASS}
          />
        </label>
      );
    }
    return (
      <label key={field.name} className={LABEL_CLASS}>
        {label}
        <input
          type={field.kind === 'date' ? 'date' : 'text'}
          value={value}
          onChange={(e) => capture.setField(field.name, e.target.value)}
          className={INPUT_CLASS}
        />
      </label>
    );
  };

  // ── Modal body per phase ─────────────────────────────────────────────────
  const renderBody = () => {
    if (capture.phase === 'recording') {
      return (
        <div className="flex flex-col items-center gap-4 py-6 text-center">
          <span className="relative flex h-16 w-16 items-center justify-center">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400/40" />
            <span className="relative inline-flex h-16 w-16 items-center justify-center rounded-full bg-red-500 text-white">
              <Mic className="h-7 w-7" />
            </span>
          </span>
          <div className="text-2xl font-semibold tabular-nums text-content-primary">
            {formatSeconds(capture.seconds)}
          </div>
          <p className="text-sm text-content-secondary">
            {t('voice.recording_hint', { defaultValue: 'Speak clearly. Tap stop when you are done.' })}
          </p>
          <Button variant="primary" icon={<Square size={16} />} onClick={capture.stopRecording}>
            {t('voice.stop', { defaultValue: 'Stop and transcribe' })}
          </Button>
        </div>
      );
    }

    if (capture.phase === 'processing') {
      const msg =
        capture.processingKind === 'transcribing'
          ? t('voice.transcribing', { defaultValue: 'Transcribing your note' })
          : t('voice.structuring', { defaultValue: 'Turning it into a draft' });
      return (
        <div className="flex flex-col items-center gap-3 py-10 text-center">
          <Loader2 className="h-7 w-7 animate-spin text-oe-blue" />
          <p className="text-sm font-medium text-content-primary">{msg}</p>
          <p className="text-xs text-content-tertiary">
            {t('voice.processing_hint', { defaultValue: 'This can take a moment. Please keep this open.' })}
          </p>
        </div>
      );
    }

    if (capture.phase === 'review') {
      const confidencePct = capture.draft?.confidence;
      const transcriptionUnavailable =
        capture.draft?.transcription != null &&
        !capture.draft.transcription.available &&
        capture.draft.transcription.error != null;
      return (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-1.5">
            {capture.draft?.ai_generated ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-oe-blue/10 px-2 py-0.5 text-xs font-medium text-oe-blue">
                <Sparkles className="h-3 w-3" />
                {t('voice.ai_drafted', { defaultValue: 'AI-drafted' })}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full bg-surface-secondary px-2 py-0.5 text-xs font-medium text-content-secondary">
                {t('voice.basic_draft', { defaultValue: 'Draft (no AI)' })}
              </span>
            )}
            {typeof confidencePct === 'number' && <ConfidenceBadge score={confidencePct} showScore />}
          </div>

          <p className="text-sm text-content-secondary">
            {t('voice.review_hint', {
              defaultValue: 'Nothing is saved yet. Check the details, edit anything, then confirm.',
            })}
          </p>

          {transcriptionUnavailable && (
            <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-300">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                {t('voice.no_transcription', {
                  defaultValue:
                    'Automatic transcription was not available, so the note below is what you typed. Edit it and re-structure if needed.',
                })}
              </span>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">{def.fields.map(renderField)}</div>

          <details className="rounded-md border border-border-light">
            <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-content-secondary">
              {t('voice.show_transcript', { defaultValue: 'Transcript / spoken note' })}
            </summary>
            <div className="space-y-2 px-3 pb-3">
              <textarea
                value={capture.transcript}
                onChange={(e) => capture.setTranscript(e.target.value)}
                rows={4}
                className={INPUT_CLASS}
                placeholder={t('voice.transcript_ph', { defaultValue: 'What was said.' })}
              />
              <Button
                variant="ghost"
                size="sm"
                icon={<Wand2 size={14} />}
                onClick={() => capture.structureText(capture.transcript)}
                disabled={capture.transcript.trim() === ''}
              >
                {t('voice.restructure', { defaultValue: 'Re-structure from this text' })}
              </Button>
            </div>
          </details>
        </div>
      );
    }

    if (capture.phase === 'error') {
      return (
        <div className="space-y-4">
          <div className="flex items-start gap-2 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-300">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{capture.error ?? t('voice.error', { defaultValue: 'Something went wrong.' })}</span>
          </div>
          <Button variant="secondary" icon={<RotateCcw size={16} />} onClick={capture.reset}>
            {t('voice.start_over', { defaultValue: 'Start over' })}
          </Button>
        </div>
      );
    }

    // idle: choose how to capture
    return (
      <div className="space-y-4">
        <p className="text-sm text-content-secondary">
          {t('voice.idle_hint', {
            defaultValue:
              'Say what happened in your own words and we will draft a structured entry for you to check. AI suggests, you confirm.',
          })}
        </p>
        <p className="text-xs text-content-tertiary">
          {t('voice.transcription_goes_to_openai', {
            defaultValue: 'Speech is transcribed by OpenAI with your OpenAI key, whatever AI provider you selected in Settings.',
          })}
        </p>

        {capture.micSupported ? (
          <button
            type="button"
            onClick={capture.startRecording}
            className="flex w-full flex-col items-center gap-2 rounded-2xl border-2 border-dashed border-oe-blue/40 bg-oe-blue/5 p-6 text-center transition hover:border-oe-blue hover:bg-oe-blue/10"
          >
            <span className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-oe-blue text-white">
              <Mic className="h-6 w-6" />
            </span>
            <span className="text-sm font-medium text-content-primary">
              {t('voice.tap_to_record', { defaultValue: 'Tap to record' })}
            </span>
          </button>
        ) : (
          <p className="rounded-md bg-surface-secondary px-3 py-2 text-xs text-content-tertiary">
            {t('voice.mic_unsupported', {
              defaultValue: 'Recording is not available in this browser. Upload a recording or type the note below.',
            })}
          </p>
        )}

        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => onFileChosen(e.target.files)}
        />
        <div className="flex items-center gap-3">
          <div className="h-px flex-1 bg-border-light" />
          <span className="text-xs uppercase tracking-wide text-content-tertiary">
            {t('voice.or', { defaultValue: 'or' })}
          </span>
          <div className="h-px flex-1 bg-border-light" />
        </div>

        <Button
          variant="secondary"
          icon={<Upload size={16} />}
          onClick={() => fileInputRef.current?.click()}
          className="w-full"
        >
          {t('voice.upload_recording', { defaultValue: 'Upload a recording' })}
        </Button>

        <label className={LABEL_CLASS}>
          {t('voice.type_instead', { defaultValue: 'Or type the note' })}
          <textarea
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            rows={3}
            className={INPUT_CLASS}
            placeholder={t('voice.type_ph', { defaultValue: 'e.g. Crack in the column on level 3, needs checking urgently' })}
          />
        </label>
        <Button
          variant="primary"
          icon={<Wand2 size={16} />}
          onClick={() => capture.structureText(typed)}
          disabled={typed.trim() === ''}
          className="w-full"
        >
          {t('voice.make_draft', { defaultValue: 'Make a draft' })}
        </Button>
      </div>
    );
  };

  const footer =
    capture.phase === 'review' ? (
      <>
        <Button variant="ghost" onClick={close} disabled={confirming}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          icon={<Check size={16} />}
          onClick={handleConfirm}
          loading={confirming}
          disabled={!canConfirm}
        >
          {resolvedConfirmLabel}
        </Button>
      </>
    ) : (
      <Button variant="ghost" onClick={close} disabled={busy}>
        {t('common.close', { defaultValue: 'Close' })}
      </Button>
    );

  const dialogTitle = t(def.titleKey, { defaultValue: def.defaultTitle });
  const label = triggerLabel ?? t('voice.trigger', { defaultValue: 'Voice entry' });

  return (
    <>
      <Button
        variant="secondary"
        size="sm"
        icon={<Mic size={14} />}
        onClick={() => setOpen(true)}
        disabled={disabled || !projectId}
        className={className}
        aria-label={compact ? label : undefined}
        title={label}
      >
        {compact ? null : label}
      </Button>

      {open && (
        <WideModal open={open} onClose={close} busy={busy} size="md" title={dialogTitle} footer={footer}>
          {renderBody()}
        </WideModal>
      )}
    </>
  );
}
