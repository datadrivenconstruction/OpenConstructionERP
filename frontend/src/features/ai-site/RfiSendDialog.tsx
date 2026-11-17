// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** "Check before sending" for a draft RFI: rule checks first, AI advice on ambiguity, send anyway with a reason. */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Loader2, Send, XCircle } from 'lucide-react';
import { Button, WideModal } from '@/shared/ui';
import { checkRfi, overrideRfiCheck, type RfiCheckEnvelope, type RfiCheckItem } from './api';
import { DegradedBanner } from './ProposalReview';
import { ConfidenceBadge } from '@/shared/ui/ConfidenceBadge';

interface Props {
  open: boolean;
  rfiId: string;
  onClose: () => void;
  /** Performs the actual send (draft to open). */
  onSend: () => void;
  sending?: boolean;
}

const DEFAULTS: Record<string, Record<string, string>> = {
  question: {
    ok: 'The question is stated.',
    warn: 'The question is short. Say what you need answered and why.',
    fail: 'The question is empty or too short to answer.',
  },
  reference: {
    ok: 'A drawing or specification reference is given.',
    warn: 'No drawing or specification reference found. Name the sheet, detail or clause.',
    fail: 'No drawing or specification reference.',
  },
  attachment_or_location: {
    ok: 'An attachment, drawing link or location is given.',
    warn: 'No attachment or location. Add a photo, sketch or the level and zone.',
    fail: 'No attachment or location.',
  },
  discipline: {
    ok: 'The discipline is set.',
    warn: 'The discipline is missing.',
    fail: 'Set the discipline so the RFI reaches the right reviewer.',
  },
  due_date: {
    ok: 'The response date leaves {{working_days}} working days.',
    warn: 'The response date leaves {{working_days}} working days; at least {{minimum_days}} are usual.',
    fail: 'Set a response date at least {{minimum_days}} working days ahead.',
  },
  impact: {
    ok: 'Cost or schedule impact is stated.',
    warn: 'No cost or schedule impact stated. Say if there is none.',
    fail: 'No cost or schedule impact stated.',
  },
};

function StatusIcon({ status }: { status: RfiCheckItem['status'] }) {
  if (status === 'ok') return <CheckCircle2 size={16} className="text-emerald-600" />;
  if (status === 'warn') return <AlertTriangle size={16} className="text-amber-500" />;
  return <XCircle size={16} className="text-semantic-error" />;
}

export function RfiSendDialog({ open, rfiId, onClose, onSend, sending }: Props) {
  const { t } = useTranslation();
  const [result, setResult] = useState<RfiCheckEnvelope | null>(null);
  const [reason, setReason] = useState('');
  const [unavailable, setUnavailable] = useState(false);

  const check = useMutation({
    mutationFn: () => checkRfi(rfiId),
    onSuccess: (r) => {
      setResult(r);
      setUnavailable(false);
    },
    onError: () => setUnavailable(true),
  });
  const override = useMutation({
    mutationFn: () => overrideRfiCheck(rfiId, reason.trim(), result?.proposal_id),
    onSuccess: onSend,
  });

  useEffect(() => {
    if (open) {
      setResult(null);
      setReason('');
      check.mutate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, rfiId]);

  const message = (c: RfiCheckItem) => {
    if (c.source === 'ai') {
      return (
        <>
          <span className="font-medium">{String(c.params.issue ?? '')}</span>
          {c.params.suggestion ? <span className="text-content-secondary"> {String(c.params.suggestion)}</span> : null}
        </>
      );
    }
    return t(`site_ai.rfi.check.${c.id}.${c.status}`, {
      defaultValue: DEFAULTS[c.id]?.[c.status] ?? c.id,
      ...c.params,
    });
  };

  const failing = !!result?.has_fail;
  const reasonOk = reason.trim().length >= 5;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      size="md"
      busy={sending || override.isPending}
      title={t('site_ai.rfi.title', { defaultValue: 'Check before sending' })}
      subtitle={t('site_ai.rfi.subtitle', { defaultValue: 'A complete RFI gets a faster, clearer answer.' })}
      testId="rfi-send-dialog"
      footer={
        <div className="flex w-full flex-wrap items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={sending}>
            {t('site_ai.rfi.back', { defaultValue: 'Back to editing' })}
          </Button>
          <Button
            variant="primary"
            icon={sending || override.isPending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
            disabled={sending || override.isPending || check.isPending || (failing && !reasonOk)}
            onClick={() => (failing ? override.mutate() : onSend())}
            data-testid="rfi-send-confirm"
          >
            {failing
              ? t('site_ai.rfi.send_anyway', { defaultValue: 'Send anyway' })
              : t('site_ai.rfi.send', { defaultValue: 'Send' })}
          </Button>
        </div>
      }
    >
      {check.isPending && (
        <p className="flex items-center gap-2 text-sm text-content-tertiary">
          <Loader2 size={14} className="animate-spin" />
          {t('site_ai.rfi.checking', { defaultValue: 'Checking the RFI...' })}
        </p>
      )}
      {unavailable && (
        <p className="text-sm text-content-secondary" data-testid="rfi-check-unavailable">
          {t('site_ai.rfi.unavailable', { defaultValue: 'The check is not available right now. You can still send.' })}
        </p>
      )}
      {result && (
        <div className="flex flex-col gap-3">
          {result.degraded && <DegradedBanner />}
          <p className="text-sm text-content-primary" data-testid="rfi-check-score">
            {t('site_ai.rfi.score', { defaultValue: 'Completeness {{score}} of 100', score: result.score })}
          </p>
          <ul className="flex flex-col gap-2">
            {result.checks.map((c) => (
              <li
                key={c.id}
                data-testid={`rfi-check-${c.id}`}
                data-status={c.status}
                className="flex items-start gap-2 rounded-lg border border-border-light p-2 text-sm"
              >
                <StatusIcon status={c.status} />
                <span className="flex-1">{message(c)}</span>
                {c.source === 'ai' && <ConfidenceBadge score={c.confidence} />}
              </li>
            ))}
          </ul>
          {failing && (
            <div className="flex flex-col gap-1">
              <label htmlFor="rfi-send-reason" className="text-sm font-medium text-content-primary">
                {t('site_ai.rfi.reason', { defaultValue: 'Why send it as it is? (recorded)' })}
              </label>
              <textarea
                id="rfi-send-reason"
                className="min-h-[70px] w-full rounded-md border border-border-light bg-surface-primary p-2 text-sm"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                data-testid="rfi-send-reason"
              />
            </div>
          )}
        </div>
      )}
    </WideModal>
  );
}
