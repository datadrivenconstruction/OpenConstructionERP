// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Inbound Email — read a stored message and show what it says about delay.
 *
 * The module keeps nothing, so the screen has no register and no list: one
 * message is open at a time and the analysis lives only as long as the page
 * does. That is stated on screen rather than left to be discovered, because a
 * reader who assumes the import was filed will go looking for it later.
 *
 * The detector is a phrase heuristic, not a model, so the matched phrases are
 * shown beside every signal. A confidence with no evidence under it invites
 * the reader to trust a number they cannot check.
 */

import { useRef, useState, type ChangeEvent, type DragEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { AlertTriangle, Inbox, Loader2, Paperclip, Upload } from 'lucide-react';
import clsx from 'clsx';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

import { analyzeInboundEmail, type DelaySignal, type InboundEmailAnalysis } from './api';
import { fmtFixed } from '@/shared/lib/formatters';

const ACCEPTED_EXTENSIONS = '.eml,message/rfc822';

/** English fallbacks for the detector's stable category tokens. */
const CATEGORY_LABELS: Record<string, string> = {
  weather: 'Weather',
  site_access: 'Site access',
  late_information: 'Late information',
  design_change: 'Design change',
  variation: 'Variation',
  resource_shortage: 'Resource shortage',
  statutory_approval: 'Statutory approval',
  unforeseen_ground: 'Unforeseen ground conditions',
};

/**
 * A signal is only ever as strong as the phrases behind it, so the strongest
 * band stops at "worth reading now" rather than claiming a breach.
 */
function confidenceVariant(confidence: number): 'neutral' | 'blue' | 'warning' {
  if (confidence >= 0.7) return 'warning';
  if (confidence >= 0.4) return 'blue';
  return 'neutral';
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${fmtFixed(bytes / 1024, 1)} KB`;
  return `${fmtFixed(bytes / (1024 * 1024), 1)} MB`;
}

export function InboundEmailPanel() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<InboundEmailAnalysis | null>(null);

  const parseMutation = useMutation({
    mutationFn: (file: File) => analyzeInboundEmail(file),
    onSuccess: (result) => setAnalysis(result),
    onError: (err: unknown) => {
      setFileName(null);
      addToast({
        type: 'error',
        title: t('inbound_email.parse_failed', { defaultValue: 'Could not read the message' }),
        message: getErrorMessage(err),
      });
    },
  });

  function accept(file: File | undefined) {
    if (!file) return;
    setAnalysis(null);
    setFileName(file.name);
    parseMutation.mutate(file);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setIsDragging(false);
    accept(e.dataTransfer.files?.[0]);
  }

  function onPick(e: ChangeEvent<HTMLInputElement>) {
    accept(e.target.files?.[0]);
    // Let the same file be chosen twice in a row.
    e.target.value = '';
  }

  return (
    <div className="space-y-4">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
        className={clsx(
          'rounded-lg border border-dashed p-6 text-center transition-colors',
          isDragging ? 'border-oe-blue bg-oe-blue-subtle' : 'border-border-light',
        )}
      >
        <Upload className="mx-auto h-6 w-6 text-content-tertiary" />
        <p className="mt-2 text-sm text-content-secondary">
          {t('inbound_email.drop_hint', {
            defaultValue: 'Drop an exported message here, or choose one to read.',
          })}
        </p>
        <p className="mt-1 text-xs text-content-tertiary">
          {t('inbound_email.drop_formats', {
            defaultValue:
              'A stored RFC-822 file (.eml), the format every mail client exports a single message to.',
          })}
        </p>
        <div className="mt-3 flex flex-wrap items-center justify-center gap-3">
          <Button
            size="sm"
            onClick={() => fileInputRef.current?.click()}
            loading={parseMutation.isPending}
          >
            {t('inbound_email.choose_file', { defaultValue: 'Choose a message' })}
          </Button>
          {fileName && (
            <span className="text-xs text-content-tertiary">{fileName}</span>
          )}
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS}
          onChange={onPick}
          className="hidden"
          aria-label={t('inbound_email.choose_file', { defaultValue: 'Choose a message' })}
        />
      </div>

      {parseMutation.isPending && (
        <p className="flex items-center gap-2 text-sm text-content-secondary">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('inbound_email.parsing', { defaultValue: 'Reading the message…' })}
        </p>
      )}

      {!analysis && !parseMutation.isPending && (
        <EmptyState
          icon={<Inbox className="h-8 w-8" />}
          title={t('inbound_email.empty_title', { defaultValue: 'No message open' })}
          description={t('inbound_email.empty_body', {
            defaultValue:
              'Export a message from your mail client and drop it here. It is read in place and never filed, so nothing about it is stored on the project.',
          })}
        />
      )}

      {analysis && (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <MessageRecord analysis={analysis} />
          <DelaySignals signals={analysis.delay_signals} />
        </div>
      )}
    </div>
  );
}

/* ── The message as a record ───────────────────────────────────────────── */

function MessageRecord({ analysis }: { analysis: InboundEmailAnalysis }) {
  const { t } = useTranslation();
  const { email } = analysis;

  const rows: Array<[string, string]> = [
    [t('inbound_email.field_from', { defaultValue: 'From' }), email.from_addr],
    [t('inbound_email.field_to', { defaultValue: 'To' }), email.to_addrs.join(', ')],
    [t('inbound_email.field_cc', { defaultValue: 'Cc' }), email.cc_addrs.join(', ')],
    [t('inbound_email.field_date', { defaultValue: 'Sent' }), email.date_iso ?? ''],
    [t('inbound_email.field_message_id', { defaultValue: 'Message id' }), email.message_id ?? ''],
    [t('inbound_email.field_in_reply_to', { defaultValue: 'In reply to' }), email.in_reply_to ?? ''],
    [
      t('inbound_email.field_references', { defaultValue: 'Thread references' }),
      String(email.references.length),
    ],
  ];

  return (
    <section className="space-y-3 rounded-lg border border-border-light p-4">
      <div>
        <p className="text-xs uppercase tracking-wide text-content-tertiary">
          {t('inbound_email.record_label', { defaultValue: 'Message' })}
        </p>
        <h3 className="text-base font-semibold">
          {email.subject || t('inbound_email.no_subject', { defaultValue: 'No subject' })}
        </h3>
      </div>

      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-content-tertiary">{label}</dt>
            <dd className="break-words text-content-secondary">
              {value || <span className="text-content-tertiary">—</span>}
            </dd>
          </div>
        ))}
      </dl>

      <div>
        <h4 className="mb-1 flex items-center gap-2 text-sm font-semibold">
          <Paperclip className="h-4 w-4 text-content-tertiary" />
          {t('inbound_email.attachments', { defaultValue: 'Attachments' })}
          <Badge size="sm">{email.attachments.length}</Badge>
        </h4>
        {email.attachments.length === 0 ? (
          <p className="text-xs text-content-tertiary">
            {t('inbound_email.no_attachments', { defaultValue: 'The message carries none.' })}
          </p>
        ) : (
          <ul className="divide-y divide-border-light rounded-lg border border-border-light">
            {email.attachments.map((att) => (
              <li
                key={`${att.filename}-${att.size_bytes}`}
                className="flex flex-wrap items-baseline justify-between gap-2 px-3 py-2 text-sm"
              >
                <span className="break-all font-medium">{att.filename}</span>
                <span className="text-xs text-content-tertiary">
                  {att.content_type} · {formatBytes(att.size_bytes)}
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-1 text-xs text-content-tertiary">
          {t('inbound_email.attachments_note', {
            defaultValue: 'Names and sizes only. The files themselves are not extracted.',
          })}
        </p>
      </div>

      <div>
        <h4 className="mb-1 text-sm font-semibold">
          {t('inbound_email.body', { defaultValue: 'Body' })}
        </h4>
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border-light bg-surface-secondary p-3 text-xs text-content-secondary">
          {email.body_text ||
            t('inbound_email.no_body', { defaultValue: 'The message has no text body.' })}
        </pre>
      </div>
    </section>
  );
}

/* ── What the message says about delay ─────────────────────────────────── */

function DelaySignals({ signals }: { signals: DelaySignal[] }) {
  const { t } = useTranslation();

  return (
    <section className="space-y-3 rounded-lg border border-border-light p-4">
      <div>
        <p className="text-xs uppercase tracking-wide text-content-tertiary">
          {t('inbound_email.signals_label', { defaultValue: 'Delay signals' })}
        </p>
        <h3 className="text-base font-semibold">
          {t('inbound_email.signals_title', {
            defaultValue: '{{count}} category read out of this message',
            defaultValue_other: '{{count}} categories read out of this message',
            count: signals.length,
          })}
        </h3>
      </div>

      {signals.length === 0 ? (
        <p className="text-sm text-content-secondary">
          {t('inbound_email.signals_none', {
            defaultValue:
              'No delay phrase was matched. That is a reading of the words, not a finding about the project, so a message that describes delay in its own vocabulary will land here too.',
          })}
        </p>
      ) : (
        <ul className="space-y-3">
          {signals.map((signal) => (
            <li key={signal.category} className="rounded-lg border border-border-light p-3">
              <div className="flex flex-wrap items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-semantic-warning" />
                <span className="font-medium">
                  {t(`inbound_email.category.${signal.category}`, {
                    defaultValue: CATEGORY_LABELS[signal.category] ?? signal.category,
                  })}
                </span>
                <Badge size="sm" variant={confidenceVariant(signal.confidence)}>
                  {t('inbound_email.confidence', {
                    defaultValue: '{{percent}}% confidence',
                    percent: Math.round(signal.confidence * 100),
                  })}
                </Badge>
              </div>

              <p className="mt-2 text-xs uppercase tracking-wide text-content-tertiary">
                {t('inbound_email.matched_phrases', { defaultValue: 'Matched in the text' })}
              </p>
              <div className="mt-1 flex flex-wrap gap-1">
                {signal.matched_phrases.map((phrase) => (
                  <span
                    key={phrase}
                    className="rounded bg-surface-secondary px-2 py-0.5 text-xs text-content-secondary"
                  >
                    {phrase}
                  </span>
                ))}
              </div>

              <p className="mt-2 text-xs uppercase tracking-wide text-content-tertiary">
                {t('inbound_email.suggested_activities', {
                  defaultValue: 'Starter activities for the fragnet',
                })}
              </p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-content-secondary">
                {signal.suggested_activities.map((activity) => (
                  <li key={activity}>{activity}</li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}

      <p className="text-xs text-content-tertiary">
        {t('inbound_email.signals_note', {
          defaultValue:
            'Every signal is a phrase match, and the activities are a fixed starter set per category. Both are a first draft for a planner to accept or discard, not an entitlement.',
        })}
      </p>
    </section>
  );
}
