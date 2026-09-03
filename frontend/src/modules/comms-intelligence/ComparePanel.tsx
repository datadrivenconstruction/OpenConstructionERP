// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Compare & Award — the suppliers' own quotes, side by side.
 *
 * Comparing a table of numbers is not comparing quotes: the number is a
 * summary somebody made of a document, and the questions that decide an
 * award — did they price the whole scope, what did they exclude, is the
 * lead time real — are only answerable by looking at what they actually
 * sent. So each supplier gets a column with THEIR document rendered in
 * it, the figure read out of it underneath, the words behind that figure
 * one click away, and their email readable without leaving the screen.
 *
 * The gate still reads the PLATFORM's own RFQ record, so the count shown
 * here, the count the gate enforces and the count the award checks are
 * one number from one function. A supplier's question is never a quote;
 * a price typed here is.
 */

import { getIntlLocale } from '@/shared/lib/formatters';
import { useEffect, useMemo, useState, type MouseEvent as ReactMouseEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Check, Loader2, Mail, ShieldAlert, ShieldCheck, Trophy } from 'lucide-react';
import { Badge, Button, EmptyState } from '@/shared/ui';
import { getAuthToken } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { qAsk } from './qAsk';
import { EmailReader } from './EmailReader';
import { AwardConfirmDialog } from './AwardConfirmDialog';
import { useMenu, type MenuItem } from './ContextMenu';
import './ci.css';
import {
  type CompareColumn,
  type CompareDoc,
  type ContactRow,
  type NativeBid,
  type RegisterItemRow,
  type SideBySide,
  type TrackState,
  AWARD_REASONS,
  awardItem,
  errorDetail,
  fetchContactsByIds,
  fetchItems,
  fetchSideBySide,
  fetchSuggestions,
  messageDocumentUrl,
  recordQuote,
} from './registers-api';

/** The winning column's green. */
const WON = '#1e7a63';


/**
 * Formats the browser draws itself in a built-in viewer, rather than
 * treating as a document to script. Only these may go unsandboxed.
 */
const NATIVE_VIEW = ['.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.txt'];
function nativelyViewable(filename: string): boolean {
  const lower = filename.toLowerCase();
  return NATIVE_VIEW.some((ext) => lower.endsWith(ext));
}

function money(v: string | undefined, currency = 'AUD') {
  const n = Number(String(v ?? '0').replace(/,/g, ''));
  if (!Number.isFinite(n) || n === 0) return '—';
  return `${currency} ${n.toLocaleString(getIntlLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// ---------------------------------------------------------------------------
// Gate badge — the single source of "2 of 3 quoted"
// ---------------------------------------------------------------------------

function GateBadge({ item }: { item: RegisterItemRow }) {
  const { t } = useTranslation();
  const gate = item.native?.quote_gate;
  if (!gate) return null;
  const ok = gate.passes;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${
        ok ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300' : 'bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300'
      }`}
      title={t('compare.gate_rule', {
        defaultValue:
          'Package {{value}} — the rule requires {{required}} written price(s). ' +
          'Only prices ON THE RECORD count: read from their email with "use it", or typed and Saved. ' +
          'A reply on its own is not a quote.',
        value: gate.value,
        required: gate.required,
      })}
    >
      {ok ? <ShieldCheck className="h-3.5 w-3.5" /> : <ShieldAlert className="h-3.5 w-3.5" />}
      {t('compare.counted', {
        defaultValue: '{{counted}} of {{required}} quoted',
        counted: gate.counted,
        required: gate.required,
      })}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Where each supplier stands
// ---------------------------------------------------------------------------

const STATE_TINT: Record<TrackState, { bg: string; fg: string; edge: string; dashed: boolean }> = {
  quoted: { bg: '#eaf6ee', fg: '#1f7a44', edge: '#bbdcc8', dashed: false },
  replied: { bg: 'rgba(29, 90, 138, 0.08)', fg: 'var(--blue)', edge: '#bfd7e8', dashed: false },
  overdue: { bg: '#f8eaec', fg: '#8e2f3c', edge: '#e5b8b4', dashed: false },
  chase: { bg: '#fff1df', fg: '#9a5716', edge: '#e8c7a6', dashed: false },
  waiting: { bg: 'rgba(18, 41, 74, 0.03)', fg: 'var(--dim)', edge: 'var(--edge2)', dashed: false },
  not_asked: { bg: 'transparent', fg: 'var(--dim)', edge: 'var(--edge2)', dashed: true },
};

function StateChip({ state }: { state: TrackState }) {
  const { t } = useTranslation();
  const labels: Record<TrackState, string> = {
    quoted: t('ci.cmp_st_quoted', { defaultValue: 'quoted' }),
    replied: t('ci.cmp_st_replied', { defaultValue: 'replied' }),
    overdue: t('ci.cmp_st_overdue', { defaultValue: 'overdue' }),
    chase: t('ci.cmp_st_chase', { defaultValue: 'chase them' }),
    waiting: t('ci.cmp_st_waiting', { defaultValue: 'waiting' }),
    not_asked: t('ci.cmp_st_not_asked', { defaultValue: 'not asked' }),
  };
  const tint = STATE_TINT[state] ?? STATE_TINT.waiting;
  return (
    <span
      style={{
        border: `1px ${tint.dashed ? 'dashed' : 'solid'} ${tint.edge}`,
        background: tint.bg,
        color: tint.fg,
        borderRadius: 999,
        padding: '1px 9px',
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: 0.2,
        whiteSpace: 'nowrap',
      }}
    >
      {labels[state] ?? state}
    </span>
  );
}

// ---------------------------------------------------------------------------
// The document itself, in the column
// ---------------------------------------------------------------------------

function shortName(filename: string) {
  return filename.length > 22 ? `${filename.slice(0, 12)}…${filename.slice(-8)}` : filename;
}

function DocumentFrame({ itemId, docs }: { itemId: string; docs: CompareDoc[] }) {
  const { t } = useTranslation();
  const [picked, setPicked] = useState<number | null>(null);
  // Default to the first real quote document; a signature logo is not a quote.
  const preferred = Math.max(0, docs.findIndex((d) => d.is_quote_document));
  const idx = picked !== null && picked >= 0 && picked < docs.length ? picked : preferred;
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const doc = docs[idx];
    if (!doc) {
      setUrl(null);
      return;
    }
    let cancelled = false;
    let created: string | null = null;
    setUrl(null);
    setFailed(false);
    // The document endpoint sits behind the bearer token and an <iframe src>
    // navigation carries no Authorization header — it would 401 and frame an
    // error page. Fetch the bytes with the header, frame the blob instead.
    const token = getAuthToken();
    void fetch(messageDocumentUrl(itemId, doc.correspondence_id, doc.filename), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
      .then((blob) => {
        if (cancelled) return;
        created = URL.createObjectURL(blob);
        setUrl(created);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [itemId, docs, idx]);

  const frameStyle = {
    width: '100%',
    minHeight: 220,
    height: 240,
    border: 0,
    borderTop: '1px solid var(--edge)',
    borderBottom: '1px solid var(--edge)',
    background: 'var(--bg)',
    display: 'block',
  } as const;

  const doc = docs[idx];
  if (!doc) {
    return (
      <div
        style={{
          ...frameStyle,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          textAlign: 'center',
          padding: '0 16px',
          color: 'var(--dim)',
          fontSize: 12.5,
        }}
      >
        {t('ci.cmp_no_doc', { defaultValue: 'No quote document received' })}
      </div>
    );
  }

  return (
    <div>
      {docs.length > 1 && (
        <div className="row" style={{ gap: 5, padding: '6px 10px 0' }}>
          {docs.map((d, i) => (
            <button
              key={`${d.correspondence_id}-${d.filename}`}
              type="button"
              className={`b mini ${i === idx ? 'on' : ''}`}
              title={d.filename}
              onClick={() => setPicked(i)}
            >
              {d.is_quote_document ? '📄 ' : '📎 '}
              {shortName(d.filename)}
            </button>
          ))}
        </div>
      )}

      {failed ? (
        <div
          style={{
            ...frameStyle,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            textAlign: 'center',
            padding: '0 16px',
            color: 'var(--dim)',
            fontSize: 12.5,
          }}
        >
          {t('ci.cmp_doc_failed', { defaultValue: 'That document would not open — {{f}}', f: doc.filename })}
        </div>
      ) : url === null ? (
        <div style={{ ...frameStyle, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Loader2 className="h-5 w-5 animate-spin" style={{ color: 'var(--dim)' }} />
        </div>
      ) : (
        // NO SANDBOX ON A PDF OR AN IMAGE, and that is deliberate.
        //
        // Chrome renders these in its own built-in viewer, which is script
        // driven; a `sandbox` attribute blocks it and you get a blank frame
        // with no error - the exact defect that killed the quote viewer in
        // an earlier version of this flow. The whole point of this column
        // is that the quote is ON SCREEN, so a silently empty frame is a
        // worse outcome than the risk it avoids:
        // the browser's PDF viewer does not execute PDF JavaScript, and the
        // bytes came from our own authenticated endpoint.
        //
        // Anything else - an HTML attachment, say - is a scripting context
        // and stays fully sandboxed.
        <iframe
          title={doc.filename}
          src={url}
          {...(nativelyViewable(doc.filename) ? {} : { sandbox: '' })}
          style={frameStyle}
        />
      )}

      <div
        className="row"
        style={{ gap: 8, padding: '5px 10px 0', fontSize: 11.5, color: 'var(--dim)', justifyContent: 'space-between' }}
      >
        <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={doc.filename}>
          {doc.filename}
        </span>
        {url && (
          <a href={url} target="_blank" rel="noreferrer" style={{ color: 'var(--blue)', whiteSpace: 'nowrap' }}>
            {t('ci.cmp_doc_open', { defaultValue: 'full size ↗' })}
          </a>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// One supplier's column
// ---------------------------------------------------------------------------

/**
 * No document arrived - but their EMAIL did, and a grey box saying "No
 * quote document received" where the supplier has in fact replied reads
 * as "nothing came". So the reply itself takes the document slot: the
 * formatted original when the sweep kept one (sanitised server-side at
 * capture), the plain text otherwise, with the full reader one click
 * away. Attachments, when a reply carries them, take this slot instead -
 * that is the DocumentFrame branch.
 */
function EmailInFrame({ col, onRead }: { col: CompareColumn; onRead: () => void }) {
  const { t } = useTranslation();
  return (
    <div
      style={{
        minHeight: 220,
        height: 240,
        borderTop: '1px solid var(--edge)',
        borderBottom: '1px solid var(--edge)',
        background: 'var(--bg)',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div
        className="row"
        style={{ gap: 6, padding: '6px 10px', borderBottom: '1px dashed var(--edge)', flex: '0 0 auto' }}
      >
        <span className="badge">
          📧 {t('ci.cmp_email_only', { defaultValue: 'their reply — no document attached' })}
        </span>
        <button type="button" className="b mini" onClick={onRead}>
          {t('ci.cmp_open_reader', { defaultValue: 'open the email' })}
        </button>
      </div>
      <div style={{ overflow: 'auto', padding: '8px 12px', fontSize: 12, lineHeight: 1.55, minHeight: 0 }}>
        {col.reply_html ? (
          // Sanitised at capture with the register allowlist - the same
          // guarantee the .eml reader relies on.
          <div dangerouslySetInnerHTML={{ __html: col.reply_html }} />
        ) : (
          <div style={{ whiteSpace: 'pre-wrap' }}>{col.reply_body}</div>
        )}
      </div>
    </div>
  );
}

interface Draft {
  amount: string;
  lead: string;
  qno: string;
}

function SupplierColumn({
  itemId,
  col,
  draft,
  saved,
  isWinner,
  isLowest,
  saving,
  onDraft,
  onSave,
  onRead,
  onContext,
  priceInputId,
}: {
  itemId: string;
  col: CompareColumn;
  draft: Draft;
  saved: NativeBid | undefined;
  isWinner: boolean;
  isLowest: boolean;
  saving: boolean;
  onDraft: (next: Draft) => void;
  onSave: () => void;
  onRead: () => void;
  /** The column's right-click menu, owned by the package. */
  onContext?: (e: ReactMouseEvent) => void;
  /** So "Record a quote" from the menu can land the cursor on the price. */
  priceInputId?: string;
}) {
  const { t } = useTranslation();
  const [why, setWhy] = useState(false);
  const canSave = col.contact_id !== null;
  const hasBody = Boolean(col.reply_subject) || Boolean(col.reply_body);

  return (
    <div
      onContextMenu={onContext}
      style={{
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--panel)',
        border: '1px solid var(--edge)',
        borderTop: `3px solid ${isWinner ? WON : 'var(--edge2)'}`,
        borderRadius: 12,
        boxShadow: isWinner ? `0 0 0 2px rgba(30, 122, 99, 0.25), var(--sh2)` : 'var(--sh2)',
        overflow: 'hidden',
        minWidth: 0,
      }}
    >
      <div style={{ padding: '10px 12px 8px' }}>
        <div style={{ fontWeight: 700, color: 'var(--navy)', lineHeight: 1.3, wordBreak: 'break-word' }}>{col.name}</div>
        <div className="row" style={{ gap: 6, marginTop: 5 }}>
          <StateChip state={col.state} />
          {col.days_waiting !== null && (
            <span className="v">
              {t('ci.cmp_days_waiting', { defaultValue: '{{n}}d waiting', n: col.days_waiting })}
            </span>
          )}
          {isWinner && (
            <span className="badge b-green">🏆 {t('ci.cmp_awarded', { defaultValue: 'awarded' })}</span>
          )}
        </div>
        {col.email && (
          <div className="v" style={{ marginTop: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {col.email}
          </div>
        )}
      </div>

      {col.documents.length === 0 && hasBody ? (
        <EmailInFrame col={col} onRead={onRead} />
      ) : (
        <DocumentFrame itemId={itemId} docs={col.documents} />
      )}

      {/* When the email already fills the document slot, a second
          "read the email" row underneath is the same door twice. */}
      {hasBody && col.documents.length > 0 && (
        <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--edge)' }}>
          {col.reply_subject && (
            <div
              style={{ fontSize: 12.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
              title={col.reply_subject}
            >
              {col.reply_subject}
            </div>
          )}
          <button type="button" className="b mini" style={{ marginTop: 5 }} onClick={onRead}>
            <Mail className="h-3 w-3" />
            {t('ci.cmp_read_email', { defaultValue: 'read the email' })}
          </button>
        </div>
      )}

      <div style={{ padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8, marginTop: 'auto' }}>
        {col.amount && (
          <div className="row" style={{ gap: 6 }}>
            <span className="badge">{t('ci.cmp_read_from', { defaultValue: 'read from their reply' })}</span>
            <b style={{ fontSize: 15, color: 'var(--navy)' }}>{col.amount}</b>
            {col.basis && <span className="v">{col.basis}</span>}
            {col.quote_number && <span className="v">#{col.quote_number}</span>}
            {col.lead_time && <span className="v">· {col.lead_time}</span>}
            <button
              type="button"
              className="b mini"
              onClick={() => onDraft({ amount: col.amount, lead: col.lead_time, qno: col.quote_number })}
            >
              {t('ci.cmp_use_it', { defaultValue: 'use it' })}
            </button>
          </div>
        )}

        {/* Real doubts about the figure — a warning hidden is a wrong award. */}
        {col.warnings.map((w, i) => (
          <div
            key={`${i}-${w}`}
            style={{
              display: 'flex',
              gap: 6,
              fontSize: 11.5,
              color: '#9a5716',
              background: '#fff1df',
              border: '1px solid #e8c7a6',
              borderRadius: 8,
              padding: '4px 8px',
            }}
          >
            <AlertTriangle className="h-3.5 w-3.5" style={{ flex: '0 0 auto', marginTop: 2 }} />
            <span>{w}</span>
          </div>
        ))}

        {col.evidence && (
          <div>
            <button type="button" className={`b mini ${why ? 'on' : ''}`} onClick={() => setWhy((v) => !v)}>
              🔍 {t('ci.cmp_why', { defaultValue: 'why' })}
            </button>
            {why && (
              <div
                style={{
                  marginTop: 6,
                  fontSize: 11.5,
                  color: 'var(--dim)',
                  background: 'var(--panel2)',
                  border: '1px solid var(--edge)',
                  borderRadius: 8,
                  padding: '6px 8px',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  maxHeight: 130,
                  overflow: 'auto',
                }}
              >
                {col.evidence}
              </div>
            )}
          </div>
        )}

        {/* Replied, but nothing counted: say WHY in the column itself, at
            the field that fixes it. The money-reader refuses a bare number
            on purpose (that is how quote NUMBERS became prices once), so a
            price it could not trust has to be typed by a person. */}
        {col.state === 'replied' && !col.amount && !(saved && Number(saved.amount) > 0) && (
          <div
            style={{
              display: 'flex',
              gap: 6,
              fontSize: 11.5,
              color: '#9a5716',
              background: '#fff1df',
              border: '1px solid #e8c7a6',
              borderRadius: 8,
              padding: '4px 8px',
            }}
          >
            <AlertTriangle className="h-3.5 w-3.5" style={{ flex: '0 0 auto', marginTop: 2 }} />
            <span>
              {t('ci.cmp_replied_unpriced', {
                defaultValue:
                  'They replied, but no price could be read from it (a readable price looks like $9,350.00). Open the email, then type the price below and Save — that is what turns replied into quoted.',
              })}
            </span>
          </div>
        )}

        <div className="qlab">{t('ci.cmp_price', { defaultValue: 'Price on the record' })}</div>
        <input
          id={priceInputId}
          className="cmpbig"
          inputMode="decimal"
          placeholder="0.00"
          disabled={!canSave}
          value={draft.amount}
          onChange={(e) => onDraft({ ...draft, amount: e.target.value })}
          style={isLowest ? { borderColor: WON } : undefined}
        />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
          <input
            className="cmpin"
            placeholder={t('ci.cmp_lead_ph', { defaultValue: '6-8 weeks' })}
            disabled={!canSave}
            value={draft.lead}
            onChange={(e) => onDraft({ ...draft, lead: e.target.value })}
          />
          <input
            className="cmpin"
            placeholder={t('ci.cmp_qno_ph', { defaultValue: 'Quote no.' })}
            disabled={!canSave}
            value={draft.qno}
            onChange={(e) => onDraft({ ...draft, qno: e.target.value })}
          />
        </div>

        <div className="row" style={{ justifyContent: 'space-between', gap: 6 }}>
          <span className="v" style={{ minWidth: 0 }}>
            {saved && Number(saved.amount) > 0
              ? t('ci.cmp_recorded', { defaultValue: 'recorded {{v}}', v: money(saved.amount, saved.currency) })
              : canSave
                ? t('ci.cmp_not_recorded', { defaultValue: 'no price recorded' })
                : t('ci.cmp_no_contact', { defaultValue: 'not in the directory — no price can be recorded' })}
            {isLowest && ` · ${t('ci.cmp_lowest', { defaultValue: 'lowest' })}`}
          </span>
          <button
            type="button"
            className="b pri mini"
            onClick={onSave}
            disabled={saving || !canSave || !draft.amount.trim()}
          >
            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
            {t('ci.cmp_save', { defaultValue: 'Save' })}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Award panel
// ---------------------------------------------------------------------------

function AwardPanel({
  item,
  projectId,
  bids,
  nameFor,
  onDone,
  pickBidId,
}: {
  item: RegisterItemRow;
  projectId: string;
  bids: NativeBid[];
  nameFor: (id: string) => string;
  onDone: () => void;
  /** A column's "Award to this supplier" preselects the winner here. */
  pickBidId?: string | null;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const priced = bids.filter((b) => Number(b.amount) > 0);
  const [bidId, setBidId] = useState(priced[0]?.id ?? '');
  useEffect(() => {
    if (pickBidId && priced.some((b) => b.id === pickBidId)) setBidId(pickBidId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickBidId]);
  const [reason, setReason] = useState<string>(AWARD_REASONS[0] ?? 'Best price');
  const [po, setPo] = useState('');
  // The winner to notify, once the award lands. Set on success so the
  // confirmation email opens straight away — the workflow does not stop at
  // "awarded", it continues to telling the supplier and issuing the PO.
  const [notifyWinner, setNotifyWinner] = useState<{ contactId: string; amount: string } | null>(null);

  const mut = useMutation({
    mutationFn: (override?: string) =>
      awardItem(item.id, { bid_id: bidId, reason, po_number: po, gate_override_reason: override }),
    onSuccess: () => {
      addToast({ type: 'success', title: t('compare.toast.awarded', { defaultValue: 'Awarded and recorded' }) });
      const winner = bids.find((b) => b.id === bidId);
      const cid = winner?.bidder_contact_id ? String(winner.bidder_contact_id) : '';
      if (cid) setNotifyWinner({ contactId: cid, amount: String(winner?.amount ?? '') });
      onDone();
    },
    onError: (e: unknown) => {
      const detail = errorDetail(e);
      const msg = detail?.error ?? (e as Error).message;
      if (detail?.can_force) {
        // qAsk, never prompt(): this browser blocks prompt() outright, so
        // a prompt-based override showed the user nothing at all.
        void qAsk({
          title: t('compare.override_title', { defaultValue: 'Award below the quote rule?' }),
          note: msg,
          fields: [
            {
              label: t('compare.override_reason', { defaultValue: 'Reason — it goes on the award record' }),
              placeholder: t('compare.override_ph', { defaultValue: 'e.g. the third supplier declined in writing' }),
              multiline: true,
            },
          ],
          okLabel: t('compare.override_ok', { defaultValue: 'Award it, with the reason' }),
          danger: true,
        }).then((answers) => {
          if (answers?.[0]?.trim()) mut.mutate(answers[0].trim());
        });
        return;
      }
      addToast({ type: 'error', title: msg });
    },
  });

  if (item.native?.award) {
    const a = item.native.award;
    const winnerCid = bids.find((b) => b.id === a.bid_id)?.bidder_contact_id ?? '';
    return (
      <>
        <div className="rounded-lg border border-emerald-300/60 bg-emerald-50/60 p-3 dark:border-emerald-800 dark:bg-emerald-950/30">
          <div className="flex flex-wrap items-center gap-2">
            <Trophy className="h-4 w-4 text-emerald-600" />
            <span className="font-semibold">
              {t('compare.awarded_to', { defaultValue: 'Awarded to' })} {nameFor(String(winnerCid))}
            </span>
            <Badge variant="success">{money(a.amount, a.currency)}</Badge>
            {a.po_number && <Badge variant="blue">PO {a.po_number}</Badge>}
            {a.is_override && <Badge variant="warning">{t('compare.past_ranking', { defaultValue: 'past the ranking' })}</Badge>}
            {a.quote_gate && !a.quote_gate.passes && (
              <Badge variant="error">{t('compare.below_rule', { defaultValue: 'below the quote rule' })}</Badge>
            )}
          </div>
          <div className="mt-1 text-sm text-text-secondary">{a.reason ?? ''}</div>
          {a.quote_gate?.passes === false && (
            <div className="mt-1 text-xs text-text-tertiary">
              {t('compare.override_recorded', { defaultValue: 'Override reason on the record' })}
            </div>
          )}
          {/* The award is not the end of the RFQ — the winner still has to be
              told and issued a PO. This re-opens that confirmation any time. */}
          {winnerCid ? (
            <div className="mt-2">
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  setNotifyWinner({ contactId: String(winnerCid), amount: String(a.amount ?? '') })
                }
              >
                <Mail className="h-4 w-4" />
                {t('compare.notify_winner', { defaultValue: 'Notify the winner — order confirmation' })}
              </Button>
            </div>
          ) : null}
        </div>
        {notifyWinner ? (
          <AwardConfirmDialog
            item={item}
            projectId={projectId}
            contactId={notifyWinner.contactId}
            poNumber={a.po_number ?? po}
            amount={notifyWinner.amount}
            onClose={() => setNotifyWinner(null)}
          />
        ) : null}
      </>
    );
  }

  if (priced.length === 0) return null;

  return (
    <>
    <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <Trophy className="h-4 w-4 text-text-tertiary" />
        {t('compare.award', { defaultValue: 'Award' })}
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <div>
          <label className="mb-1 block text-xs text-text-secondary">
            {t('compare.winner', { defaultValue: 'Winner' })}
          </label>
          <select
            className="w-full rounded border border-border-light bg-surface-primary px-2 py-1.5 text-sm"
            value={bidId}
            onChange={(e) => setBidId(e.target.value)}
          >
            {priced.map((b) => (
              <option key={b.id} value={b.id}>
                {nameFor(b.bidder_contact_id)} — {money(b.amount, b.currency)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs text-text-secondary">
            {t('compare.reason', { defaultValue: 'Reason (goes on the file)' })}
          </label>
          <input
            list="award-reasons"
            className="w-full rounded border border-border-light bg-surface-primary px-2 py-1.5 text-sm"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <datalist id="award-reasons">
            {AWARD_REASONS.map((r) => (
              <option key={r} value={r} />
            ))}
          </datalist>
        </div>
        <div>
          <label className="mb-1 block text-xs text-text-secondary">
            {t('compare.po', { defaultValue: 'PO # (optional)' })}
          </label>
          <input
            className="w-full rounded border border-border-light bg-surface-primary px-2 py-1.5 text-sm"
            value={po}
            onChange={(e) => setPo(e.target.value)}
          />
        </div>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <span className="text-xs text-text-tertiary">
          {t('compare.award_note', {
            defaultValue: 'Awarding opens an order confirmation to the winner, carrying this PO.',
          })}
        </span>
        <Button
          size="sm"
          variant="primary"
          className="ml-auto"
          onClick={() => mut.mutate(undefined)}
          disabled={mut.isPending || !bidId || !reason.trim()}
        >
          {mut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trophy className="h-4 w-4" />}
          {t('compare.award_it', { defaultValue: 'Award it' })}
        </Button>
      </div>
    </div>
    {notifyWinner ? (
      <AwardConfirmDialog
        item={item}
        projectId={projectId}
        contactId={notifyWinner.contactId}
        poNumber={po}
        amount={notifyWinner.amount}
        onClose={() => setNotifyWinner(null)}
      />
    ) : null}
    </>
  );
}

// ---------------------------------------------------------------------------
// One package's comparison
// ---------------------------------------------------------------------------

interface Reading {
  correspondenceId: string | null;
  subject: string;
  text: string;
}

function PackageCompare({ item, projectId }: { item: RegisterItemRow; projectId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const bids = item.native?.bids ?? [];
  const asked = item.recipient_contact_ids ?? [];

  // One column per supplier — their reply, their documents, their figure.
  // Already ordered by the server the way a decision is made: whoever
  // priced it first, then repliers, then the silent.
  const compare = useQuery<SideBySide>({
    queryKey: ['compare-side-by-side', item.id],
    queryFn: () => fetchSideBySide(item.id),
  });
  const columns = compare.data?.columns ?? [];

  // Everyone asked still needs a name in the award select even if the
  // comparison itself has not loaded.
  const columnIds = useMemo(() => {
    const ids = new Set<string>(asked.map(String));
    bids.forEach((b) => ids.add(String(b.bidder_contact_id)));
    return [...ids];
  }, [asked, bids]);

  const contactsQuery = useQuery({
    queryKey: ['compare-contacts', columnIds.join(',')],
    queryFn: () => fetchContactsByIds(columnIds),
    enabled: columnIds.length > 0,
  });
  const nameFor = (id: string) => {
    const fromColumn = columns.find((c) => c.contact_id !== null && String(c.contact_id) === String(id));
    if (fromColumn) return fromColumn.name;
    const c = (contactsQuery.data ?? []).find((x: ContactRow) => String(x.id) === String(id));
    return c?.company_name || [c?.first_name, c?.last_name].filter(Boolean).join(' ') || String(id).slice(0, 8);
  };

  // Priced replies the analyser could not pin on a supplier. Filed rather
  // than guessed onto the wrong column.
  const suggestions = useQuery({
    queryKey: ['suggestions', item.id],
    queryFn: () => fetchSuggestions(item.id),
  });

  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [reading, setReading] = useState<Reading | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const menu = useMenu();
  // The bid a column's menu chose to award - lands on the award panel.
  const [awardPick, setAwardPick] = useState<string | null>(null);

  // A quote document sits behind the bearer token, so a plain window.open
  // would 401 - fetch the bytes with the header and open the blob.
  const openDocument = async (correspondenceId: string, filename: string) => {
    const token = getAuthToken();
    try {
      const res = await fetch(messageDocumentUrl(item.id, correspondenceId, filename), {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(String(res.status));
      window.open(URL.createObjectURL(await res.blob()), '_blank');
    } catch {
      addToast({
        type: 'error',
        title: t('ci.cmp_doc_failed', { defaultValue: 'That document would not open — {{f}}', f: filename }),
      });
    }
  };

  // Right-click a supplier's column: record, award, read - what the
  // column's own buttons do, in one place, only where it applies.
  const columnMenu = (e: ReactMouseEvent, col: CompareColumn, bid: NativeBid | undefined, priceInputId: string) => {
    const hasBody = Boolean(col.reply_subject) || Boolean(col.reply_body);
    const priced = Boolean(bid && Number(bid.amount) > 0);
    const awarded = Boolean(item.native?.award);
    const doc = col.documents.find((d) => d.is_quote_document) ?? col.documents[0];
    const items: (MenuItem | null)[] = [
      {
        label: col.amount
          ? t('ci.cmp_menu_use', { defaultValue: 'Record their quote — use the figure read' })
          : t('ci.cmp_menu_record', { defaultValue: 'Record a quote' }),
        note: col.amount || undefined,
        color: '#2e9e5b',
        disabled: col.contact_id === null,
        onClick: () => {
          if (col.amount) {
            const key = col.contact_id ?? col.name;
            setDrafts((d) => ({ ...d, [key]: { amount: col.amount, lead: col.lead_time, qno: col.quote_number } }));
          }
          window.setTimeout(() => document.getElementById(priceInputId)?.focus(), 30);
        },
      },
      {
        label: t('ci.cmp_menu_award', { defaultValue: 'Award to this supplier' }),
        note: priced ? money(bid?.amount, bid?.currency) : t('ci.cmp_menu_no_price', { defaultValue: 'no price on the record' }),
        color: WON,
        disabled: !priced || awarded,
        onClick: () => {
          setAwardPick(bid?.id ?? null);
          document.getElementById(`award-${item.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        },
      },
      null,
      hasBody || col.documents.length > 0
        ? {
            label: t('ci.cmp_menu_reply', { defaultValue: 'Open the reply' }),
            onClick: () =>
              setReading({
                correspondenceId: col.documents[0]?.correspondence_id ?? null,
                subject: col.reply_subject ?? '',
                text: col.reply_body,
              }),
          }
        : null,
      doc
        ? {
            label: t('ci.cmp_menu_doc', { defaultValue: 'Open the quote document' }),
            note: doc.filename.length > 28 ? `${doc.filename.slice(0, 26)}…` : doc.filename,
            onClick: () => void openDocument(doc.correspondence_id, doc.filename),
          }
        : null,
      col.email
        ? {
            label: t('ci.menu_copy_email', { defaultValue: 'Copy email address' }),
            note: col.email,
            onClick: () => void navigator.clipboard.writeText(col.email as string),
          }
        : null,
    ];
    menu.openFromEvent(e, items, { head: col.name });
  };

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['registers', projectId] });
    void queryClient.invalidateQueries({ queryKey: ['compare-side-by-side', item.id] });
  };

  // The figures travel WITH the mutation rather than being read back out of
  // `drafts`: a column saved straight from its recorded price never lands in
  // that state, and the closure would have posted an empty amount.
  const quoteMut = useMutation({
    mutationFn: (v: { contactId: string; draft: Draft }) =>
      recordQuote(item.id, {
        bidder_contact_id: v.contactId,
        amount: v.draft.amount,
        lead_time: v.draft.lead,
        quote_number: v.draft.qno,
      }),
    onSuccess: () => {
      addToast({ type: 'success', title: t('compare.toast.saved', { defaultValue: 'Price recorded' }) });
      setSavingKey(null);
      refresh();
    },
    onError: (e: Error) => {
      setSavingKey(null);
      addToast({ type: 'error', title: e.message });
    },
  });

  const bidFor = (contactId: string | null) =>
    contactId === null ? undefined : bids.find((b) => String(b.bidder_contact_id) === String(contactId));
  const lowest = Math.min(
    ...bids.filter((b) => Number(b.amount) > 0).map((b) => Number(b.amount)),
    Number.POSITIVE_INFINITY,
  );
  const awardedContactId = item.native?.award
    ? (bids.find((b) => b.id === item.native?.award?.bid_id)?.bidder_contact_id ?? null)
    : (bids.find((b) => b.is_awarded)?.bidder_contact_id ?? null);

  const draftFor = (col: CompareColumn): Draft => {
    const key = col.contact_id ?? col.name;
    const existing = drafts[key];
    if (existing) return existing;
    const bid = bidFor(col.contact_id);
    const recorded = bid && Number(bid.amount) > 0 ? bid.amount : '';
    // The extracted figure is NOT prefilled — a machine read it, and the
    // record only ever carries a price a person put there ("use it" fills
    // this in when they have looked at the document and agree).
    return { amount: recorded, lead: '', qno: '' };
  };

  const totals = compare.data?.totals;

  return (
    <div className="ci" style={{ background: 'var(--panel)', border: '1px solid var(--edge)', borderRadius: 14, padding: 14 }}>
      <div className="row" style={{ marginBottom: 10 }}>
        <span className="font-mono text-sm font-bold">{item.reference}</span>
        <span style={{ fontWeight: 600 }}>{item.title}</span>
        <GateBadge item={item} />
        {item.native?.quote_gate && (
          <span className="v">
            {t('compare.package_value', { defaultValue: 'package {{v}}', v: money(item.native.quote_gate.value) })}
          </span>
        )}
        {totals && (
          // Deliberately NOT a second "quoted" count: the gate badge above owns
          // that number, and a tracking count beside it saying something else
          // is how "0 of 2 quoted" once appeared next to two priced columns.
          <span className="v">
            {t('ci.cmp_totals', {
              defaultValue: '{{asked}} emailed · {{replied}} replied',
              asked: totals.asked,
              replied: totals.replied,
            })}
          </span>
        )}
        {item.is_overdue && (
          <Badge variant="error">
            <AlertTriangle className="mr-1 inline h-3 w-3" />
            {t('compare.overdue', { defaultValue: 'quotes overdue' })}
          </Badge>
        )}
      </div>

      {/* THE RECONCILIATION LINE. "0 of 3 quoted" beside "1 replied" is two
          true numbers that read as a contradiction unless somebody says how
          one becomes the other. Shown only while a reply sits uncounted. */}
      {totals &&
        item.native?.quote_gate &&
        totals.replied > item.native.quote_gate.counted && (
          <div
            style={{
              display: 'flex',
              gap: 7,
              alignItems: 'flex-start',
              fontSize: 12,
              color: '#9a5716',
              background: '#fff1df',
              border: '1px solid #e8c7a6',
              borderRadius: 8,
              padding: '6px 10px',
              marginBottom: 10,
            }}
          >
            <AlertTriangle className="h-3.5 w-3.5" style={{ flex: '0 0 auto', marginTop: 2 }} />
            <span>
              {t('ci.cmp_reconcile', {
                defaultValue:
                  'A reply only counts as QUOTED once its price is on the record. If a figure was read from their email, press "use it"; otherwise open the email, type the price into their column and press Save.',
              })}
            </span>
          </div>
        )}

      {compare.isLoading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 22 }}>
          <Loader2 className="h-5 w-5 animate-spin" style={{ color: 'var(--dim)' }} />
        </div>
      ) : compare.isError ? (
        <p className="v">
          {t('ci.cmp_failed', { defaultValue: 'The comparison could not be loaded — the award below still works.' })}
        </p>
      ) : columns.length === 0 ? (
        <p className="v">
          {t('ci.cmp_nobody', {
            defaultValue: 'Nobody has been asked for a price yet. Add the suppliers on the item and send the RFQ — their quotes line up here.',
          })}
        </p>
      ) : (
        // Only this strip scrolls sideways; the page underneath never does.
        <div
          style={{
            display: 'grid',
            gridAutoFlow: 'column',
            gridAutoColumns: 'minmax(320px, 1fr)',
            gap: 12,
            overflowX: 'auto',
            overflowY: 'hidden',
            paddingBottom: 8,
            minWidth: 0,
            alignItems: 'stretch',
          }}
        >
          {columns.map((col) => {
            const key = col.contact_id ?? col.name;
            const bid = bidFor(col.contact_id);
            return (
              <SupplierColumn
                key={key}
                itemId={item.id}
                col={col}
                draft={draftFor(col)}
                saved={bid}
                isWinner={awardedContactId !== null && String(col.contact_id) === String(awardedContactId)}
                isLowest={Number(bid?.amount ?? 0) > 0 && Number(bid?.amount ?? 0) === lowest}
                saving={quoteMut.isPending && savingKey === key}
                onDraft={(next) => setDrafts((d) => ({ ...d, [key]: next }))}
                onSave={() => {
                  if (col.contact_id === null) return;
                  setSavingKey(key);
                  quoteMut.mutate({ contactId: col.contact_id, draft: draftFor(col) });
                }}
                onRead={() =>
                  setReading({
                    correspondenceId: col.documents[0]?.correspondence_id ?? null,
                    subject: col.reply_subject ?? '',
                    text: col.reply_body,
                  })
                }
                priceInputId={`cmp-price-${item.id}-${String(key).replace(/\W/g, '')}`}
                onContext={(e) => columnMenu(e, col, bid, `cmp-price-${item.id}-${String(key).replace(/\W/g, '')}`)}
              />
            );
          })}
        </div>
      )}
      {menu.element}

      {(suggestions.data?.unmatched ?? []).length > 0 && (
        <div
          style={{
            marginTop: 10,
            border: '1px solid #e8c7a6',
            background: '#fff1df',
            borderRadius: 10,
            padding: '8px 10px',
            fontSize: 12,
            color: '#9a5716',
          }}
        >
          <b>{t('compare.unmatched', { defaultValue: 'Priced replies nobody could be sure about' })}</b>
          {(suggestions.data?.unmatched ?? []).map((u) => (
            <div key={u.correspondence_id} style={{ marginTop: 3 }}>
              {u.reference} · {u.amount} {u.basis} — <span style={{ opacity: 0.8 }}>{u.subject}</span>
            </div>
          ))}
          <div style={{ marginTop: 3, opacity: 0.85 }}>
            {t('compare.unmatched_note', {
              defaultValue: 'Filed here rather than guessed onto a supplier — type the figure into the right column.',
            })}
          </div>
        </div>
      )}

      <div style={{ marginTop: 12 }} id={`award-${item.id}`}>
        <AwardPanel
          item={item}
          projectId={projectId}
          bids={bids}
          nameFor={nameFor}
          onDone={refresh}
          pickBidId={awardPick}
        />
      </div>

      {reading && (
        // The RICH reader - full headers, the figures beside the words
        // they were read out of, attachments you can open, and the mail
        // verbs. It was built, exported and then never imported: what
        // this button actually opened was a subject line, a body and a
        // list of filenames you could not click.
        <EmailReader
          itemId={item.id}
          correspondenceId={reading.correspondenceId}
          fallbackSubject={reading.subject}
          fallbackText={reading.text}
          onClose={() => setReading(null)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab
// ---------------------------------------------------------------------------

export function ComparePanel({
  projectId,
  focusItemId,
}: {
  projectId: string;
  /** Scroll this package into view on arrival - the register's "N of M
   *  quoted" badge lands here, and landing at the top of a long list of
   *  packages is not landing anywhere. */
  focusItemId?: string | null;
}) {
  const { t } = useTranslation();
  const itemsQuery = useQuery<RegisterItemRow[]>({
    queryKey: ['registers', projectId, 'rfq', 'compare'],
    queryFn: () => fetchItems(projectId, 'rfq'),
  });

  const packages = (itemsQuery.data ?? []).filter((i) => i.native?.native === 'rfq');

  if (itemsQuery.isLoading) {
    return (
      <div className="flex justify-center p-8">
        <Loader2 className="h-6 w-6 animate-spin text-text-tertiary" />
      </div>
    );
  }
  if (packages.length === 0) {
    return (
      <EmptyState
        icon={<Trophy className="h-8 w-8" />}
        title={t('compare.empty', { defaultValue: 'No packages out for quote' })}
        description={t('compare.empty_desc', {
          defaultValue: 'Raise an RFQ in the Registers tab and its quotes line up here.',
        })}
      />
    );
  }
  return (
    <div className="space-y-3">
      {packages.map((p) => (
        <div
          key={p.id}
          id={`cmp-${p.id}`}
          ref={
            focusItemId === p.id
              ? (el) => {
                  // A callback ref fires when the card actually exists -
                  // no timers guessing when the query has rendered.
                  el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
              : undefined
          }
        >
          <PackageCompare item={p} projectId={projectId} />
        </div>
      ))}
    </div>
  );
}
