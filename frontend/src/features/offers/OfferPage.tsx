/** Customer offer for one estimate: a scrolling form on the left and a server-rendered PDF preview on the right. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { AlertTriangle, ArrowLeft, Download } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { Card } from '@/shared/ui/Card';
import { ContactSearchInput } from '@/shared/ui/ContactSearchInput';
import { formatCurrency } from '@/shared/lib/money';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  TEXT_KINDS,
  fetchPreview,
  numberTaken,
  useAcceptOffer,
  useCreateOffer,
  useResetOfferText,
  insertAt,
  useOffer,
  useOfferAction,
  useOfferContext,
  useOfferValidation,
  usePatchOffer,
  type Offer,
  type OfferFinding,
  type OfferPatch,
  type OfferSection,
  type OfferStatus,
} from './api';
import { OfferScheduleEditor } from './OfferScheduleEditor';
import { AcceptDialog, CustomerEmpty, PlaceholderChips, SendAction } from './offerParts';

const SECTIONS: OfferSection[] = ['customer', 'details', 'items', 'schedule', 'texts', 'layout'];
const STATUS_VARIANT: Record<OfferStatus, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  draft: 'neutral',
  sent: 'blue',
  accepted: 'success',
  declined: 'error',
  expired: 'warning',
  superseded: 'neutral',
};
const inputCls =
  'h-9 w-full rounded-md border border-border-light bg-surface-primary px-2.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none disabled:opacity-60';
const VALIDITY_CHIPS = [14, 30, 60];

/** The letter after `rev`: A -> B, Z -> AA. */
export function nextRevision(rev: string): string {
  const letters = rev.split('');
  let i = letters.length - 1;
  while (i >= 0) {
    if (letters[i] !== 'Z') {
      letters[i] = String.fromCharCode((letters[i] ?? 'A').charCodeAt(0) + 1);
      return letters.join('');
    }
    letters[i] = 'A';
    i -= 1;
  }
  return `A${letters.join('')}`;
}

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export function OfferPage() {
  const { t } = useTranslation();
  const { boqId } = useParams<{ boqId: string }>();
  const [params] = useSearchParams();
  const projectId = params.get('project') ?? undefined;
  const addToast = useToastStore((s) => s.addToast);
  const qc = useQueryClient();

  const ctxQ = useOfferContext(projectId, boqId);
  const create = useCreateOffer();
  const latest = ctxQ.data?.offers.find((o) => o.status !== 'superseded') ?? ctxQ.data?.offers[0];
  const [offerId, setOfferId] = useState<string | undefined>();
  const requested = useRef(false);

  useEffect(() => {
    if (latest && !offerId) setOfferId(latest.id);
  }, [latest, offerId]);

  // First offer needs no setup: create the draft as soon as the page knows there is none.
  useEffect(() => {
    if (ctxQ.data && ctxQ.data.offers.length === 0 && !requested.current && projectId && boqId) {
      requested.current = true;
      create.mutate(
        { project_id: projectId, boq_id: boqId, contact_id: ctxQ.data.client_contact_id },
        { onSuccess: (o) => setOfferId(o.id), onError: (e) => addToast({ type: 'error', title: t('offers.page_title', { defaultValue: 'Customer offer' }), message: getErrorMessage(e) }) },
      );
    }
  }, [ctxQ.data, projectId, boqId, create, addToast, t]);

  const offerQ = useOffer(offerId);
  const offer = offerQ.data;
  const valQ = useOfferValidation(offerId, offer?.updated_at);
  const patch = usePatchOffer(offerId ?? '');
  const send = useOfferAction(offerId ?? '', 'send');
  const revise = useOfferAction(offerId ?? '', 'revise');
  const decline = useOfferAction(offerId ?? '', 'decline');
  const accept = useAcceptOffer(offerId ?? '');
  const [accepting, setAccepting] = useState(false);

  const save = useCallback(
    (change: OfferPatch) => {
      if (!offerId) return;
      patch.mutate(change, { onError: (e) => addToast({ type: 'error', title: t('offers.page_title', { defaultValue: 'Customer offer' }), message: getErrorMessage(e) }) });
    },
    [offerId, patch, addToast, t],
  );

  const run = (m: typeof send, label: string, onDone?: (r: unknown) => void) =>
    m.mutate(undefined, {
      onSuccess: (r) => {
        void qc.invalidateQueries({ queryKey: ['offers'] });
        onDone?.(r);
      },
      onError: (e) => addToast({ type: 'error', title: label, message: getErrorMessage(e) }),
    });

  if (!projectId) {
    return <div className="p-6 text-sm text-content-secondary">{t('offers.no_project', { defaultValue: 'Open the offer from an estimate.' })}</div>;
  }
  if (!offer) {
    return <div className="p-6 text-sm text-content-secondary">{t('common.loading', { defaultValue: 'Loading...' })}</div>;
  }

  const findings = valQ.data?.findings ?? [];
  const bySection = (s: OfferSection) => findings.filter((f) => f.section === s);
  const readOnly = !offer.editable;

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-wrap items-center gap-3">
        <Link to={`/boq/${boqId}`} className="text-content-secondary hover:text-content-primary" aria-label={t('common.back', { defaultValue: 'Back' })}>
          <ArrowLeft size={18} />
        </Link>
        <h1 className="text-lg font-semibold">{t('offers.page_title', { defaultValue: 'Customer offer' })}</h1>
        <span className="text-sm text-content-secondary">
          {offer.number} · {t('offers.revision', { defaultValue: 'Rev' })} {offer.revision}
        </span>
        <Badge variant={STATUS_VARIANT[offer.status]}>{t(`offers.status.${offer.status}`, { defaultValue: offer.status })}</Badge>
        {valQ.data && valQ.data.errors + valQ.data.warnings > 0 && (
          <span className="flex items-center gap-1 text-sm text-semantic-warning">
            <AlertTriangle size={14} />
            {t('offers.to_fix', { count: valQ.data.errors + valQ.data.warnings, defaultValue: '{{count}} to fix' })}
          </span>
        )}
        <div className="ml-auto flex gap-2">
          <Button variant="secondary" size="sm" icon={<Download size={14} />} onClick={() => void downloadPdf(offer)}>
            {offer.status === 'draft' ? t('offers.download_draft', { defaultValue: 'Download draft' }) : t('offers.download', { defaultValue: 'Download' })}
          </Button>
          {offer.status === 'draft' && (
            <SendAction
              canSend={valQ.data?.can_send !== false}
              firstError={valQ.data?.first_error ?? null}
              pending={send.isPending}
              onSend={() => run(send, t('offers.send', { defaultValue: 'Send offer' }), (r) => void downloadPdf(r as Offer))}
            />
          )}
        </div>
      </div>

      {offer.status !== 'draft' && (
        <div className={`mb-4 rounded-md px-3 py-2 text-sm ${offer.stale ? 'bg-semantic-warning-bg text-semantic-warning' : 'bg-surface-secondary text-content-secondary'}`}>
          {offer.stale
            ? t('offers.stale_banner', { rev: offer.revision, defaultValue: 'The estimate changed after revision {{rev}} was sent.' })
            : t('offers.sent_banner', { date: offer.sent_at?.slice(0, 10) ?? '', rev: nextRevision(offer.revision), defaultValue: 'Sent on {{date}}. Changes create revision {{rev}}.' })}
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={() => run(revise, 'revise', (r) => setOfferId((r as Offer).id))}>
              {t('offers.create_revision', { rev: nextRevision(offer.revision), defaultValue: 'Create revision {{rev}}' })}
            </Button>
            {offer.status === 'sent' && (
              <>
                <Button size="sm" onClick={() => setAccepting(true)}>
                  {t('offers.mark_accepted', { defaultValue: 'Mark accepted' })}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => run(decline, t('offers.mark_declined', { defaultValue: 'Mark declined' }))}>
                  {t('offers.mark_declined', { defaultValue: 'Mark declined' })}
                </Button>
              </>
            )}
            {offer.contract_id && (
              <Link className="text-sm underline" to={`/contracts/${offer.contract_id}`}>
                {t('offers.open_contract', { defaultValue: 'Open contract' })}
              </Link>
            )}
          </div>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-4">
          <nav className="flex flex-wrap gap-2 text-sm" aria-label={t('offers.sections', { defaultValue: 'Sections' })}>
            {SECTIONS.map((s) => (
              <a key={s} href={`#offer-${s}`} className="rounded-full border border-border-light px-3 py-1 hover:bg-surface-secondary">
                {bySection(s).some((f) => f.severity === 'error') ? '! ' : ''}
                {t(`offers.section.${s}`, { defaultValue: s })}
              </a>
            ))}
          </nav>

          <SectionCard id="customer" title={t('offers.section.customer', { defaultValue: 'Customer' })} findings={bySection('customer')}>
            {offer.contact_id ? (
              <ContactSearchInput
                value={offer.contact_id}
                displayValue={String(offer.customer?.name ?? '')}
                onChange={(id) => save({ contact_id: id || null })}
                placeholder={t('offers.customer_empty', { defaultValue: 'Who is this offer for?' })}
              />
            ) : (
              <CustomerEmpty projectId={projectId} country={String(ctxQ.data?.pack.country ?? '')} onCreated={(id) => save({ contact_id: id })} />
            )}
            {ctxQ.data?.pack.consumer_rule === true && (
              <div className="mt-3" role="group" aria-label={t('offers.customer_kind_label', { defaultValue: 'Customer type' })}>
                <div className="flex gap-2">
                  {(['private', 'business'] as const).map((k) => (
                    <Button key={k} size="sm" variant={offer.customer_kind === k ? 'primary' : 'secondary'} disabled={readOnly} onClick={() => save({ customer_kind: k })}>
                      {t(`offers.customer_kind.${k}`, { defaultValue: k })}
                    </Button>
                  ))}
                </div>
                <p className="mt-1 text-xs text-content-tertiary">{t('offers.customer_kind_hint', { defaultValue: 'Private customers see prices including tax.' })}</p>
              </div>
            )}
            <label className="mt-3 flex items-center gap-2 text-sm">
              <input type="checkbox" checked={offer.site_same_as_billing} disabled={readOnly} onChange={(e) => save({ site_same_as_billing: e.target.checked })} />
              {t('offers.site_same_as_billing', { defaultValue: 'Same as billing address' })}
            </label>
          </SectionCard>

          <SectionCard id="details" title={t('offers.section.details', { defaultValue: 'Offer details' })} findings={bySection('details')}>
            <DetailsFields offer={offer} readOnly={readOnly} languages={ctxQ.data?.document_languages ?? []} onSave={save} />
          </SectionCard>

          <SectionCard id="items" title={t('offers.section.items', { defaultValue: 'Items and prices' })} findings={bySection('items')}>
            <p className="text-sm">
              {t('offers.items_summary', {
                count: offer.lines.filter((l) => l.kind === 'item').length,
                net: `${formatCurrency(Number(offer.totals.net), offer.currency)}`,
                defaultValue: '{{count}} items · net {{net}}',
              })}
            </p>
            <fieldset className="mt-3" disabled={readOnly}>
              <legend className="text-xs text-content-tertiary">{t('offers.markups_label', { defaultValue: 'How markups appear' })}</legend>
              {(['spread', 'lines', 'section'] as const).map((m) => (
                <label key={m} className="mr-4 inline-flex items-center gap-1 text-sm">
                  <input type="radio" name="markup" checked={offer.markup_presentation === m} onChange={() => save({ markup_presentation: m })} />
                  {t(`offers.markups.${m}`, { defaultValue: m })}
                </label>
              ))}
            </fieldset>
            <Link className="mt-3 inline-block text-sm underline" to={`/boq/${boqId}`}>
              {t('offers.edit_in_estimate', { defaultValue: 'Edit in estimate' })}
            </Link>
          </SectionCard>

          <SectionCard id="schedule" title={t('offers.section.schedule', { defaultValue: 'Payment schedule' })} findings={bySection('schedule')}>
            <OfferScheduleEditor
              rows={offer.instalments}
              net={offer.totals.net}
              currency={offer.currency}
              readOnly={readOnly}
              onChange={(rows) => save({ instalments: rows })}
            />
          </SectionCard>

          <SectionCard id="texts" title={t('offers.section.texts', { defaultValue: 'Texts' })} findings={bySection('texts')}>
            <div className="space-y-4">
              {TEXT_KINDS.map((kind) => (
                <TextCard key={`${offer.id}-${kind}`} offer={offer} kind={kind} readOnly={readOnly} onSave={save} />
              ))}
            </div>
          </SectionCard>

          <SectionCard id="layout" title={t('offers.section.layout', { defaultValue: 'Layout' })} findings={bySection('layout')}>
            <p className="text-sm text-content-secondary">
              {t('offers.layout_hint', { defaultValue: 'Logo, paper and margins follow Company and documents settings.' })}
            </p>
          </SectionCard>
        </div>

        {accepting && (
          <AcceptDialog
            offer={offer}
            canCreateContract={ctxQ.data?.permissions?.create_contract !== false}
            pending={accept.isPending}
            onCancel={() => setAccepting(false)}
            onConfirm={(body) =>
              accept.mutate(body, {
                onSuccess: () => setAccepting(false),
                onError: (e) => addToast({ type: 'error', title: t('offers.mark_accepted', { defaultValue: 'Mark accepted' }), message: getErrorMessage(e) }),
              })
            }
          />
        )}
        <OfferPreview offerId={offer.id} version={`${offer.totals.gross}|${JSON.stringify(offer.texts)}|${offer.status}|${offer.number}|${offer.valid_until}|${offer.locale}|${offer.instalments.length}`} />
      </div>
    </div>
  );
}

function SectionCard({ id, title, findings, children }: { id: string; title: string; findings: OfferFinding[]; children: React.ReactNode }) {
  return (
    <Card>
      <section id={`offer-${id}`} className="p-4">
        <h2 className="mb-3 text-sm font-semibold">{title}</h2>
        {children}
        {findings.length > 0 && (
          <ul className="mt-3 space-y-1">
            {findings.map((f, i) => (
              <li key={`${f.rule_id}-${i}`} className={`text-xs ${f.severity === 'error' ? 'text-semantic-error' : 'text-semantic-warning'}`}>
                {f.message}
              </li>
            ))}
          </ul>
        )}
      </section>
    </Card>
  );
}

function DetailsFields({ offer, readOnly, languages, onSave }: { offer: Offer; readOnly: boolean; languages: string[]; onSave: (p: OfferPatch) => void }) {
  const { t } = useTranslation();
  const [number, setNumber] = useState(offer.number);
  const [taken, setTaken] = useState(false);
  const [reference, setReference] = useState(offer.reference);
  useEffect(() => setNumber(offer.number), [offer.number]);

  const commitNumber = async () => {
    if (number === offer.number || !number.trim()) return;
    const res = await numberTaken(number.trim(), offer.group_id);
    setTaken(res.taken);
    if (!res.taken) onSave({ number: number.trim() });
  };
  const setDays = (days: number) => onSave({ validity_days: days, valid_until: addDays(offer.issue_date, days) });

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="text-sm">
        {t('offers.number', { defaultValue: 'Offer number' })}
        <input className={inputCls} value={number} disabled={readOnly} onChange={(e) => setNumber(e.target.value)} onBlur={() => void commitNumber()} />
        {taken && <span className="text-xs text-semantic-error">{t('offers.number_taken', { defaultValue: 'This number is already used.' })}</span>}
      </label>
      <label className="text-sm">
        {t('offers.issue_date', { defaultValue: 'Issue date' })}
        <input type="date" className={inputCls} value={offer.issue_date} disabled={readOnly} onChange={(e) => e.target.value && onSave({ issue_date: e.target.value })} />
      </label>
      <div className="text-sm">
        <label>
          {t('offers.valid_until', { defaultValue: 'Valid until' })}
          <input type="date" className={inputCls} value={offer.valid_until ?? ''} disabled={readOnly} onChange={(e) => e.target.value && onSave({ valid_until: e.target.value })} />
        </label>
        <div className="mt-1 flex gap-1">
          {VALIDITY_CHIPS.map((d) => (
            <button key={d} type="button" disabled={readOnly} className={`rounded-full border px-2 py-0.5 text-xs ${offer.validity_days === d ? 'border-oe-blue text-oe-blue' : 'border-border-light'}`} onClick={() => setDays(d)}>
              {t('offers.valid_days', { count: d, defaultValue: '{{count}} days' })}
            </button>
          ))}
        </div>
      </div>
      <label className="text-sm">
        {t('offers.document_language', { defaultValue: 'Document language' })}
        <select className={inputCls} value={offer.locale} disabled={readOnly} onChange={(e) => onSave({ locale: e.target.value })}>
          {[...new Set([offer.locale, ...languages])].map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>
      </label>
      <label className="text-sm sm:col-span-2">
        {t('offers.your_reference', { defaultValue: 'Customer reference' })}
        <input className={inputCls} value={reference} disabled={readOnly} onChange={(e) => setReference(e.target.value)} onBlur={() => reference !== offer.reference && onSave({ reference })} />
      </label>
    </div>
  );
}

function TextCard({ offer, kind, readOnly, onSave }: { offer: Offer; kind: string; readOnly: boolean; onSave: (p: OfferPatch) => void }) {
  const { t } = useTranslation();
  const entry = offer.texts[kind];
  const [body, setBody] = useState(entry?.body ?? '');
  const [forProject, setForProject] = useState(entry?.source === 'project');
  const area = useRef<HTMLTextAreaElement>(null);
  const reset = useResetOfferText(offer.id);
  useEffect(() => {
    setBody(entry?.body ?? '');
    setForProject(entry?.source === 'project');
  }, [entry?.body, entry?.source]);
  const commit = () => {
    if (body !== (entry?.body ?? '') || (forProject && entry?.source !== 'project')) {
      onSave({ texts: { [kind]: { source: forProject ? 'project' : 'offer', body, block_id: null } } });
    }
  };
  const insert = (token: string) => {
    const el = area.current;
    const next = insertAt(body, el?.selectionStart ?? body.length, el?.selectionEnd ?? body.length, token);
    setBody(next.text);
  };
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <h3 className="text-sm font-medium">{t(`offers.texts.kind.${kind}`, { defaultValue: kind })}</h3>
        <span className="flex items-center gap-2">
          {entry && <Badge size="sm">{t(`offers.texts.source.${entry.source}`, { defaultValue: entry.source })}</Badge>}
          {!readOnly && entry && entry.source !== 'company' && (
            <button type="button" className="text-xs underline" onClick={() => reset.mutate(kind)}>
              {t('offers.texts.reset', { defaultValue: 'Reset to company text' })}
            </button>
          )}
        </span>
      </div>
      {!readOnly && <PlaceholderChips onInsert={insert} />}
      <textarea ref={area} className={`${inputCls} h-24 py-2`} value={body} disabled={readOnly} onChange={(e) => setBody(e.target.value)} onBlur={commit} />
      {!readOnly && (
        <label className="mt-1 flex items-center gap-2 text-xs">
          <input type="checkbox" checked={forProject} onChange={(e) => setForProject(e.target.checked)} />
          {t('offers.texts.use_for_project', { defaultValue: 'Use for all offers in this project' })}
        </label>
      )}
      {kind === 'payment_terms' && !body.trim() && (
        <p className="mt-1 text-xs text-semantic-warning">{t('offers.texts.missing_payment', { defaultValue: 'The customer will not see payment terms.' })}</p>
      )}
      {entry?.resolved && <p className="mt-1 text-xs text-content-tertiary">{entry.resolved}</p>}
    </div>
  );
}

function OfferPreview({ offerId, version }: { offerId: string; version: string }) {
  const { t } = useTranslation();
  const [url, setUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [pages, setPages] = useState(0);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let live = true;
    const timer = window.setTimeout(async () => {
      setBusy(true);
      try {
        const res = await fetchPreview(offerId);
        if (!live) return;
        const bytes = Uint8Array.from(atob(res.pdf_base64), (c) => c.charCodeAt(0));
        const next = URL.createObjectURL(new Blob([bytes], { type: 'application/pdf' }));
        setUrl((old) => {
          if (old) URL.revokeObjectURL(old);
          return next;
        });
        setPages(res.page_count);
        setFailed(false);
      } catch {
        if (live) setFailed(true);
      } finally {
        if (live) setBusy(false);
      }
    }, 800);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [offerId, version, retry]);

  return (
    <div className="sticky top-4 h-[calc(100vh-6rem)] rounded-lg border border-border-light bg-surface-secondary">
      {failed && (
        <div className="p-3 text-sm text-semantic-error">
          {t('offers.preview_failed', { defaultValue: 'Preview could not be drawn.' })}{' '}
          <button type="button" className="underline" onClick={() => setRetry((n) => n + 1)}>
            {t('common.retry', { defaultValue: 'Try again' })}
          </button>
        </div>
      )}
      {url && <iframe title="offer-preview" src={url} className={`h-full w-full rounded-lg ${busy ? 'opacity-60' : ''}`} />}
      {pages > 0 && <span className="absolute bottom-2 right-3 text-xs text-content-tertiary">{pages}</span>}
    </div>
  );
}

async function downloadPdf(offer: Offer) {
  const res = await fetchPreview(offer.id);
  const bytes = Uint8Array.from(atob(res.pdf_base64), (c) => c.charCodeAt(0));
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([bytes], { type: 'application/pdf' }));
  a.download = res.filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
