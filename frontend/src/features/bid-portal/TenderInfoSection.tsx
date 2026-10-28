// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Addenda and clarifications on the bidder price-entry page: acknowledge addenda, read published answers, ask a question.

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, Megaphone } from 'lucide-react';

import { Button } from '@/shared/ui';
import { formatDateValue } from '@/shared/lib/formatters';

import {
  acknowledgeAddendumAsBidder,
  askQuestion,
  fetchTenderInfo,
  type TenderInfo,
} from './api';

export function TenderInfoSection({ token }: { token: string }) {
  const { t } = useTranslation();
  const [info, setInfo] = useState<TenderInfo | null>(null);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    fetchTenderInfo(token)
      .then(setInfo)
      .catch(() => setInfo(null));
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  if (!info) return null;
  const hasContent = info.addenda.length > 0 || info.clarifications.length > 0;

  const acknowledge = async (id: string) => {
    setBusy(true);
    setFailed(false);
    try {
      await acknowledgeAddendumAsBidder(token, id);
      load();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  const ask = async () => {
    const text = question.trim();
    if (!text) return;
    setBusy(true);
    setFailed(false);
    try {
      const res = await askQuestion(token, text);
      setSent(res.number);
      setQuestion('');
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mt-4 space-y-3 rounded-lg border border-border-light p-4" data-testid="tender-info">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
        <Megaphone size={16} aria-hidden />
        {t('bid_portal.addenda.title', { defaultValue: 'Addenda and clarifications' })}
      </h2>

      {!hasContent && (
        <p className="text-sm text-content-tertiary">
          {t('bid_portal.addenda.none', { defaultValue: 'No addenda or published answers yet.' })}
        </p>
      )}

      {info.addenda.map((a) => (
        <div key={a.id} className="rounded-md bg-surface-secondary px-3 py-2 text-sm" data-testid="portal-addendum">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-content-primary">
              {t('bid_portal.addenda.revision', { defaultValue: 'Addendum {{n}}', n: a.revision_no })}
            </span>
            <span className="text-content-primary">{a.title}</span>
            {a.published_at && (
              <span className="text-xs text-content-tertiary">
                {formatDateValue(a.published_at, { dateStyle: 'medium' })}
              </span>
            )}
          </div>
          {a.body && <p className="mt-1 whitespace-pre-line text-content-secondary">{a.body}</p>}
          {a.new_deadline && (
            <p className="mt-1 text-xs font-medium text-semantic-warning">
              {t('bid_portal.addenda.new_deadline', {
                defaultValue: 'New deadline: {{date}}',
                date: formatDateValue(a.new_deadline, { dateStyle: 'medium' }),
              })}
            </p>
          )}
          {a.boq_revision_no != null && (
            <p className="mt-1 text-xs text-content-secondary">
              {t('bid_portal.addenda.boq_revision', {
                defaultValue: 'The bill was revised (revision {{n}}). Price the current bill.',
                n: a.boq_revision_no,
              })}
            </p>
          )}
          {a.document_changes.length > 0 && (
            <ul className="mt-1 text-xs text-content-secondary">
              {a.document_changes.map((d, i) => (
                <li key={`${d.drawing_number ?? ''}-${i}`}>
                  {[d.drawing_number, d.title, d.revision].filter(Boolean).join(' ')}
                  {d.superseded && (
                    <span className="ml-2 text-semantic-warning">
                      {t('bid_portal.addenda.superseded', { defaultValue: 'superseded' })}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
          <div className="mt-2">
            {a.acknowledged ? (
              <span className="inline-flex items-center gap-1 text-xs text-semantic-success">
                <CheckCircle2 size={13} aria-hidden />
                {t('bid_portal.addenda.acknowledged', { defaultValue: 'Acknowledged' })}
              </span>
            ) : (
              <Button variant="secondary" size="sm" disabled={busy} onClick={() => void acknowledge(a.id)}>
                {t('bid_portal.addenda.acknowledge', { defaultValue: 'Acknowledge' })}
              </Button>
            )}
          </div>
        </div>
      ))}

      {info.clarifications.map((c) => (
        <div key={c.number} className="text-sm" data-testid="portal-clarification">
          <p className="font-medium text-content-primary">
            {t('bid_portal.addenda.question', { defaultValue: 'Q{{n}}: {{text}}', n: c.number, text: c.question })}
          </p>
          <p className="whitespace-pre-line text-content-secondary">{c.answer}</p>
        </div>
      ))}

      <div className="space-y-2 border-t border-border-light pt-3">
        <label className="text-xs font-medium text-content-secondary" htmlFor="bid-portal-question">
          {t('bid_portal.addenda.ask', { defaultValue: 'Ask a question' })}
        </label>
        <textarea
          id="bid-portal-question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={2}
          className="w-full resize-none rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
        />
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" size="sm" disabled={busy || !question.trim()} onClick={() => void ask()}>
            {t('bid_portal.addenda.send_question', { defaultValue: 'Send question' })}
          </Button>
          {sent !== null && (
            <span className="text-xs text-semantic-success" role="status">
              {t('bid_portal.addenda.question_sent', {
                defaultValue: 'Question {{n}} sent. The answer goes to all bidders without your name.',
                n: sent,
              })}
            </span>
          )}
          {failed && (
            <span className="text-xs text-semantic-error" role="alert">
              {t('bid_portal.addenda.failed', { defaultValue: 'That did not go through. Please try again.' })}
            </span>
          )}
        </div>
      </div>
    </section>
  );
}
