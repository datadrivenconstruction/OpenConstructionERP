// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The conversation, read the way a conversation reads.
 *
 * The correspondence list below this answers "how many, from whom, when".
 * This answers the question people actually ask: *what did we say, and
 * what did they say back?* — the outbound mail with its real body, and
 * the replies to it sitting underneath, indented, oldest first, the way
 * a thread in any mail client reads.
 *
 * Two rules it is built on:
 *
 * 1. OUR mail is shown from the copy stored when it was sent, never
 *    rebuilt from today's fields. Rebuilding would show a supplier a
 *    document they were never sent the moment anything is corrected.
 * 2. THEIR mail is shown as text, never as their markup. A supplier's
 *    HTML rendered inside our own page is how a forwarded subject became
 *    stored XSS in the old app.
 *
 * Our own template still renders as the real document — in a sandboxed
 * iframe with scripts off, so it looks exactly like the email without
 * its full-page styling leaking into the app.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueries, useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, CornerDownRight, Mail, MailOpen } from 'lucide-react';
import {
  type ThreadEntry,
  type ViewedMessage,
  fetchMessage,
  messageDocumentUrl,
} from './registers-api';

const stamp = (s: string | null | undefined): string =>
  String(s ?? '').replace('T', ' ').slice(0, 16) || '—';

/** Oldest first — a conversation reads downwards. */
const oldestFirst = (a: ThreadEntry, b: ThreadEntry) => String(a.at ?? '').localeCompare(String(b.at ?? ''));

export interface ThreadNode {
  out: ThreadEntry;
  replies: ThreadEntry[];
}

/**
 * Group replies under the outbound mail they answer.
 *
 * Matching is by the mail's OWN number first (``REG-MSG-000042`` quoted
 * in the reply is unambiguous), then by recipient, then by "whatever came
 * after it and before the next one" — which is how a human reads a thread
 * when the sender has stripped the quoted history.
 */
export function buildThread(entries: ThreadEntry[]): { nodes: ThreadNode[]; loose: ThreadEntry[] } {
  const sends = entries.filter((e) => e.type === 'send').sort(oldestFirst);
  const inbound = entries
    .filter((e) => e.type === 'correspondence' && e.direction !== 'outgoing')
    .sort(oldestFirst);

  const nodes: ThreadNode[] = sends.map((out) => ({ out, replies: [] }));
  const loose: ThreadEntry[] = [];

  for (const reply of inbound) {
    // 1. The mail number it quotes.
    let idx = nodes.findIndex(
      (n) => !!n.out.email_ref && !!reply.reference && reply.reference === n.out.email_ref,
    );
    // 2. Failing that, whatever was sent most recently before it arrived.
    //
    // This is a GUESS and is deliberately the only fallback. It used to
    // be preceded by a "last mail sent to this person" rule that could
    // never fire: a reply entry carries the correspondence row's id, not
    // the contact's, so the comparison was between two different kinds of
    // id and was always false. Dead code that reads as a real rule is
    // worse than no rule - anyone maintaining this would believe replies
    // are matched by recipient when they are not.
    //
    // Matching by sender is the right answer and needs the inbound
    // address on the thread payload; until that exists, rule 1 carries
    // the real traffic, because every mail we send stamps its own
    // REG-MSG number and the inbound matcher looks for exactly that.
    if (idx < 0 && reply.at) {
      for (let i = nodes.length - 1; i >= 0; i -= 1) {
        if (String(nodes[i]!.out.at ?? '') <= String(reply.at)) {
          idx = i;
          break;
        }
      }
    }
    if (idx >= 0) nodes[idx]!.replies.push(reply);
    // A reply that predates every send we know of belongs to nothing —
    // it is shown on its own rather than filed under a mail it cannot be
    // an answer to.
    else loose.push(reply);
  }
  return { nodes, loose };
}

/** Our own sent document, shown as the document. */
function SentBody({ html }: { html: string }) {
  const { t } = useTranslation();
  if (!html.trim()) {
    return (
      <div className="v" style={{ padding: '8px 10px', fontSize: 12 }}>
        {/* Say only what is true. This covers BOTH a send logged after the
            fact and one drafted before copies were kept - guessing between
            them would put a false account on the record. */}
        {t('ci.thr_no_body', {
          defaultValue:
            'No copy of this one was kept — it was either logged as already sent, or drafted before copies were stored. The subject, recipient and mail number above are the record of it.',
        })}
      </div>
    );
  }
  return (
    <iframe
      title="sent email"
      // Scripts OFF. This is our own template, but a sandbox costs
      // nothing and the day somebody pastes supplier markup into a note
      // is the day it matters.
      sandbox=""
      srcDoc={html}
      style={{
        width: '100%',
        height: 420,
        border: '1px solid var(--edge2)',
        borderRadius: 6,
        background: '#fff',
      }}
    />
  );
}

/** Their reply, shown as text. */
function ReplyBody({ itemId, entry }: { itemId: string; entry: ThreadEntry }) {
  const { t } = useTranslation();
  const q = useQuery<ViewedMessage>({
    queryKey: ['register-message', itemId, entry.id],
    queryFn: () => fetchMessage(itemId, entry.id as string),
    enabled: !!entry.id,
    staleTime: 60_000,
  });

  if (!entry.id) return null;
  if (q.isError) {
    return (
      <div className="v" style={{ padding: 8, fontSize: 12 }}>
        {t('ci.log_unreadable', { defaultValue: 'this message could not be read' })}
      </div>
    );
  }
  const msg = q.data;
  if (!msg) {
    return (
      <div className="v" style={{ padding: 8, fontSize: 12 }}>
        {t('ci.log_loading', { defaultValue: 'reading the message…' })}
      </div>
    );
  }
  const who = (list: { name?: string; email?: string }[]) =>
    list.map((p) => p.name || p.email || '').filter(Boolean).join('; ') || '—';
  return (
    <div style={{ padding: '6px 10px' }}>
      <div className="v" style={{ fontSize: 11.5, marginBottom: 4 }}>
        {who(msg.from_people)} · {stamp(msg.date)}
      </div>
      <pre
        style={{
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          fontFamily: 'inherit',
          fontSize: 12.5,
          margin: 0,
          padding: 8,
          background: '#fff',
          border: '1px solid var(--edge2)',
          borderRadius: 6,
          maxHeight: 320,
          overflow: 'auto',
        }}
      >
        {msg.text.trim() || t('ci.thr_empty_body', { defaultValue: '(no text in this message)' })}
      </pre>
      {msg.documents.length > 0 && (
        <div style={{ marginTop: 5, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {msg.documents.map((d) => (
            <a
              key={d.filename}
              className="badge"
              href={messageDocumentUrl(itemId, entry.id as string, d.filename)}
              target="_blank"
              rel="noreferrer"
              style={{ textDecoration: 'none' }}
            >
              📎 {d.filename}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

export function EmailThread({
  itemId,
  entries,
  onReply,
  onContext,
}: {
  itemId: string;
  entries: ThreadEntry[];
  onReply?: (correspondenceId: string) => void;
  onContext?: (e: React.MouseEvent, entry: ThreadEntry) => void;
}) {
  const { t } = useTranslation();
  const { nodes, loose } = useMemo(() => buildThread(entries), [entries]);
  // The most recent exchange is the one you came to read — it starts open,
  // the rest start folded so a long job is still a page you can scan.
  //
  // Seeded in an effect, NOT in useState's initialiser: on first render
  // the thread is still loading and `nodes` is empty, so the initialiser
  // latched an empty set and nothing ever opened. `seeded` makes it fire
  // once, so folding that last one shut afterwards stays shut.
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [seeded, setSeeded] = useState(false);
  useEffect(() => {
    if (seeded || nodes.length === 0) return;
    setOpen(new Set([nodes.length - 1]));
    setSeeded(true);
  }, [nodes.length, seeded]);

  // Warm the replies so an expand is instant rather than a spinner.
  useQueries({
    queries: nodes
      .flatMap((n) => n.replies)
      .filter((r) => !!r.id)
      .map((r) => ({
        queryKey: ['register-message', itemId, r.id],
        queryFn: () => fetchMessage(itemId, r.id as string),
        staleTime: 60_000,
      })),
  });

  if (nodes.length === 0 && loose.length === 0) {
    return (
      <div className="v" style={{ padding: '6px 2px' }}>
        {t('ci.thr_nothing', {
          defaultValue: 'no email on this item yet — the first draft you send starts the thread',
        })}
      </div>
    );
  }

  const toggle = (i: number) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });

  return (
    <div className="qthr">
      {nodes.map((n, i) => {
        const isOpen = open.has(i);
        return (
          <div key={i} className="qthr-x" onContextMenu={onContext ? (e) => onContext(e, n.out) : undefined}>
            <button type="button" className="qthr-h" onClick={() => toggle(i)}>
              {isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
              <Mail size={13} />
              <b>{t('ci.thr_we_sent', { defaultValue: 'We sent' })}</b>
              <span>{n.out.who || '—'}</span>
              {n.out.email_ref && <span className="badge">{n.out.email_ref}</span>}
              <span className={`badge ${n.replies.length ? 'b-green' : 'b-amber'}`}>
                {n.replies.length
                  ? t('ci.thr_n_replies', { defaultValue: '{{n}} replied', n: n.replies.length })
                  : t('ci.thr_awaiting', { defaultValue: 'no reply yet' })}
              </span>
              <span className="v" style={{ marginLeft: 'auto' }}>{stamp(n.out.at)}</span>
            </button>

            {isOpen && (
              <div className="qthr-b">
                <div style={{ fontSize: 11.5, marginBottom: 5 }} className="v">
                  {n.out.subject}
                </div>
                <SentBody html={n.out.html ?? ''} />

                {n.replies.map((r) => (
                  <div
                    key={r.id ?? r.at}
                    className="qthr-r"
                    onContextMenu={onContext ? (e) => onContext(e, r) : undefined}
                  >
                    <div className="qthr-rh">
                      <CornerDownRight size={13} />
                      <MailOpen size={13} />
                      <b>{t('ci.thr_they_said', { defaultValue: 'They replied' })}</b>
                      <span>{r.subject}</span>
                      {r.reference && <span className="badge">{r.reference}</span>}
                      {r.category && <span className="badge b-amber">{r.category.replace(/_/g, ' ')}</span>}
                      {onReply && r.id && (
                        <button
                          type="button"
                          className="badge clk"
                          onClick={() => onReply(r.id as string)}
                          title={t('ci.thr_reply_hint', {
                            defaultValue: 'Answer this — opens the reader with reply and forward',
                          })}
                        >
                          {t('ci.log_reply', { defaultValue: 'reply ↗' })}
                        </button>
                      )}
                      <span className="v" style={{ marginLeft: 'auto' }}>{stamp(r.at)}</span>
                    </div>
                    <ReplyBody itemId={itemId} entry={r} />
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}

      {loose.length > 0 && (
        <div className="qthr-x">
          <div className="qthr-h" style={{ cursor: 'default' }}>
            <MailOpen size={13} />
            <b>{t('ci.thr_unmatched', { defaultValue: 'Arrived before anything was sent' })}</b>
            <span className="badge b-amber">{loose.length}</span>
          </div>
          <div className="qthr-b">
            {loose.map((r) => (
              <div
                key={r.id ?? r.at}
                className="qthr-r"
                onContextMenu={onContext ? (e) => onContext(e, r) : undefined}
              >
                <div className="qthr-rh">
                  <b>{r.subject}</b>
                  <span className="v" style={{ marginLeft: 'auto' }}>{stamp(r.at)}</span>
                </div>
                <ReplyBody itemId={itemId} entry={r} />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
