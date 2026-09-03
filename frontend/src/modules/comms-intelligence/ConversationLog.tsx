// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The conversation log — one item's whole life on a single screen.
 *
 * The expanded row already holds all of this, but spread across five
 * folds you have to open one at a time. When somebody asks "what has
 * actually happened on this RFI", the answer is a story, not five
 * drawers: what we asked, who we asked, what they said back, what we
 * said to that, which gates were signed and by whom.
 *
 * So this is the DOSSIER view. Every detail, in time order, printable,
 * with each message openable in full without leaving the page.
 *
 * It reads what is already there — no new endpoints. The thread, the
 * tracking rows, the send log and the steps are the same data the folds
 * render; this arranges them as one continuous account.
 *
 * Layered at 70: UNDER the reader drawer (80) so a message opens on top
 * of the log rather than behind it, and under qAsk (82) so a
 * confirmation is never trapped beneath.
 */

import { Fragment, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Loader2, Paperclip, Printer, X } from 'lucide-react';
import { Button } from '@/shared/ui';
import {
  type ItemTracking,
  type KindSpec,
  type RegisterItemRow,
  type SendLogEntry,
  type ThreadEntry,
  type ViewedMessage,
  fetchItemThread,
  fetchItemTracking,
  fetchMessage,
  messageDocumentUrl,
} from './registers-api';
import { EmailReader } from './EmailReader';
import { EmailThread } from './EmailThread';
import { ContextMenu, type MenuItem } from './ContextMenu';

/** Copy without a permissions prompt where the clipboard API is blocked. */
async function copy(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
    } finally {
      document.body.removeChild(ta);
    }
  }
}

const stamp = (s: string | null | undefined): string =>
  String(s ?? '').replace('T', ' ').slice(0, 16) || '—';

const sendLogOf = (i: RegisterItemRow): SendLogEntry[] => {
  const l = (i.fields as Record<string, unknown>)['_send_log'];
  return Array.isArray(l) ? (l as SendLogEntry[]) : [];
};
const attachmentsOf = (i: RegisterItemRow): { filename: string; size: number; email?: boolean }[] => {
  const a = (i.fields as Record<string, unknown>)['_attachments'];
  return Array.isArray(a) ? (a as { filename: string; size: number; email?: boolean }[]) : [];
};

function Section({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          borderBottom: '2px solid var(--edge2)',
          paddingBottom: 4,
          marginBottom: 8,
        }}
      >
        <b style={{ color: 'var(--navy)', fontSize: 13, letterSpacing: 0.3, textTransform: 'uppercase' }}>
          {title}
        </b>
        {count !== undefined && <span className="badge">{count}</span>}
      </div>
      {children}
    </div>
  );
}

/**
 * One captured message, opened in place.
 *
 * The body is shown as TEXT, not the sender's HTML: this view is a
 * record of what was said, and rendering a supplier's markup inside our
 * own page is how a forwarded subject became stored XSS in the old app.
 * The reader drawer is one click away for anyone who wants the rich
 * version, its attachments and the reply buttons.
 */
function LogMessage({ itemId, corrId }: { itemId: string; corrId: string }) {
  const { t } = useTranslation();
  const q = useQuery<ViewedMessage>({
    queryKey: ['register-message', itemId, corrId],
    queryFn: () => fetchMessage(itemId, corrId),
  });

  if (q.isLoading) {
    return (
      <div className="v" style={{ padding: 8, display: 'flex', gap: 6, alignItems: 'center' }}>
        <Loader2 size={13} className="animate-spin" />
        {t('ci.log_loading', { defaultValue: 'reading the message…' })}
      </div>
    );
  }
  if (q.isError || !q.data) {
    return (
      <div className="v" style={{ padding: 8 }}>
        {t('ci.log_unreadable', { defaultValue: 'this message could not be read' })}
      </div>
    );
  }
  const m = q.data;
  const people = (list: { name?: string; email?: string }[]) =>
    list.map((p) => p.name || p.email || '').filter(Boolean).join('; ') || '—';

  return (
    <div style={{ padding: '8px 10px', borderTop: '1px dashed var(--edge2)', background: 'rgba(12,29,56,0.02)' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '2px 10px', fontSize: 12 }}>
        <span className="v">{t('ci.log_from', { defaultValue: 'From' })}</span>
        <span>{people(m.from_people)}</span>
        <span className="v">{t('ci.log_to', { defaultValue: 'To' })}</span>
        <span>{people(m.to_people)}</span>
        <span className="v">{t('ci.log_sent', { defaultValue: 'Sent' })}</span>
        <span>{stamp(m.date)}</span>
      </div>
      {!!m.text.trim() && (
        <pre
          style={{
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            fontFamily: 'inherit',
            fontSize: 12.5,
            margin: '8px 0 0',
            padding: 8,
            background: '#fff',
            border: '1px solid var(--edge2)',
            borderRadius: 6,
            maxHeight: 320,
            overflow: 'auto',
          }}
        >
          {m.text.trim()}
        </pre>
      )}
      {m.documents.length > 0 && (
        <div style={{ marginTop: 6, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {m.documents.map((d) => (
            <a
              key={d.filename}
              className="badge"
              href={messageDocumentUrl(itemId, corrId, d.filename)}
              target="_blank"
              rel="noreferrer"
              style={{ textDecoration: 'none' }}
            >
              <Paperclip size={11} style={{ verticalAlign: -1 }} /> {d.filename}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

export function ConversationLog({
  item,
  spec,
  onClose,
}: {
  item: RegisterItemRow;
  spec?: KindSpec;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [openMsg, setOpenMsg] = useState<Set<string>>(new Set());
  const [reading, setReading] = useState<string | null>(null);
  // EVERY element right-clicks. The workspace rows already did, and an
  // app where only some things answer the right button teaches you not
  // to try - so details, steps, mail and recipients all carry one.
  const [menu, setMenu] = useState<{ x: number; y: number; items: (MenuItem | null)[] } | null>(null);
  const openMenu = (e: React.MouseEvent, items: (MenuItem | null)[]) => {
    e.preventDefault();
    e.stopPropagation();
    setMenu({ x: e.clientX, y: e.clientY, items: items.filter(Boolean) as MenuItem[] });
  };

  const thread = useQuery<ThreadEntry[]>({
    queryKey: ['thread', item.id],
    queryFn: () => fetchItemThread(item.id),
  });
  const tracking = useQuery<ItemTracking>({
    queryKey: ['item-tracking', item.id],
    queryFn: () => fetchItemTracking(item.id),
  });

  // Escape closes the reader first, then the log — never skips a layer.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (reading) setReading(null);
      else onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [reading, onClose]);

  const entries = thread.data ?? [];
  const sends = sendLogOf(item);
  const atts = attachmentsOf(item);
  const fields = Object.entries(item.fields).filter(
    ([k, v]) => !k.startsWith('_') && String(v ?? '').trim(),
  ) as [string, string][];
  const internalLabels = new Set((spec?.fields ?? []).filter((f) => f.internal).map((f) => f.label));
  const replies = entries.filter((e) => e.type === 'correspondence' && e.direction !== 'outgoing').length;

  const toggle = (id: string) =>
    setOpenMsg((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="ci" style={{ position: 'fixed', inset: 0, zIndex: 70 }}>
      <div className="ci-scrim" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('ci.log_title', { defaultValue: 'Workflow and conversation log' })}
        style={{
          position: 'relative',
          margin: '3vh auto',
          width: 'min(1040px, 94vw)',
          maxHeight: '94vh',
          display: 'flex',
          flexDirection: 'column',
          background: '#fff',
          border: '1px solid var(--edge2)',
          borderRadius: 12,
          boxShadow: '0 18px 48px rgba(18,41,74,0.28)',
          overflow: 'hidden',
        }}
      >
        {/* Hero — the item's identity, the way the emails carry it. */}
        <div
          style={{
            background: 'var(--navy)',
            color: '#fff',
            padding: '12px 16px',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 10.5, letterSpacing: 1.4, textTransform: 'uppercase', opacity: 0.75 }}>
              {spec?.label ?? item.kind}
            </div>
            <div style={{ fontSize: 16, fontWeight: 700, marginTop: 1 }}>
              {item.reference} <span style={{ fontWeight: 400, opacity: 0.9 }}>{item.title}</span>
            </div>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
            <Button variant="ghost" size="sm" onClick={() => window.print()} title={t('ci.log_print', { defaultValue: 'Print this log' })}>
              <Printer size={15} color="#fff" />
            </Button>
            <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
              <X size={17} color="#fff" />
            </Button>
          </div>
        </div>

        {/* The facts you would otherwise gather off four folds. */}
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 6,
            padding: '8px 16px',
            borderBottom: '1px solid var(--edge2)',
            background: 'rgba(12,29,56,0.03)',
          }}
        >
          <span className={`badge ${item.status === 'closed' ? '' : 'b-green'}`}>{item.status}</span>
          <span className={`badge ${item.steps_done >= item.steps_total ? 'b-green' : 'b-amber'}`}>
            {t('ci.log_steps', {
              defaultValue: 'workflow {{a}} of {{b}}',
              a: item.steps_done,
              b: item.steps_total,
            })}
          </span>
          {/* Which SIDE it sits with is derived from the step; WHO it has
              been put on is assigned. Both are shown - "with them" alone
              never told you who to ring. */}
          <span className={`badge ${item.ball_in_court === 'them' ? 'b-amber' : ''}`}>
            {item.ball_in_court === 'them'
              ? t('ci.with_them', { defaultValue: 'with them' })
              : t('ci.with_us', { defaultValue: 'with us' })}
            {item.ball_in_court_name ? ` · ${item.ball_in_court_name}` : ''}
          </span>
          {item.responsible && (
            <span className="badge" title={t('ci.responsible_hint', { defaultValue: 'Responsible person' })}>
              👤 {item.responsible}
            </span>
          )}
          <span className="badge">📧 {t('ci.log_sent_n', { defaultValue: '{{n}} sent', n: sends.length })}</span>
          <span className="badge">📥 {t('ci.log_replies_n', { defaultValue: '{{n}} received', n: replies })}</span>
          {item.due_date && (
            <span className={`badge ${item.is_overdue ? 'b-red' : ''}`}>
              {t('ci.log_due', { defaultValue: 'due {{d}}', d: item.due_date })}
            </span>
          )}
          <span className="v" style={{ marginLeft: 'auto', fontSize: 11.5 }}>
            {t('ci.log_raised', { defaultValue: 'raised {{d}}', d: stamp(item.created_at) })}
          </span>
        </div>

        <div style={{ overflow: 'auto', padding: '14px 16px' }}>
          <Section title={t('ci.fold_details', { defaultValue: 'details' })} count={fields.length}>
            {fields.length === 0 ? (
              <div className="v">{t('ci.log_no_details', { defaultValue: 'no details recorded' })}</div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'minmax(140px,220px) 1fr', gap: '4px 12px' }}>
                {fields.map(([k, v]) => (
                  <Fragment key={k}>
                    <span
                      className="v"
                      style={{ fontSize: 12 }}
                      onContextMenu={(e) =>
                        openMenu(e, [
                          { label: t('ci.cm_copy_value', { defaultValue: 'Copy the value' }), onClick: () => void copy(v) },
                          {
                            label: t('ci.cm_copy_pair', { defaultValue: 'Copy label and value' }),
                            onClick: () => void copy(`${k}: ${v}`),
                          },
                        ])
                      }
                    >
                      {k}
                      {internalLabels.has(k) && (
                        <span className="badge" style={{ marginLeft: 4 }}>
                          {t('ci.card_only', { defaultValue: '🔒 internal — money never leaves the building' })}
                        </span>
                      )}
                    </span>
                    <span
                      style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 12.5 }}
                      onContextMenu={(e) =>
                        openMenu(e, [
                          { label: t('ci.cm_copy_value', { defaultValue: 'Copy the value' }), onClick: () => void copy(v) },
                          {
                            label: t('ci.cm_copy_pair', { defaultValue: 'Copy label and value' }),
                            onClick: () => void copy(`${k}: ${v}`),
                          },
                        ])
                      }
                    >
                      {v}
                    </span>
                  </Fragment>
                ))}
              </div>
            )}
          </Section>

          <Section title={t('ci.fold_workflow', { defaultValue: 'workflow' })} count={item.steps.length}>
            {item.steps.length === 0 ? (
              <div className="v">{t('ci.log_no_steps', { defaultValue: 'no workflow on this item' })}</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {item.steps.map((s) => (
                  <div
                    key={s.id}
                    onContextMenu={(e) =>
                      openMenu(e, [
                        {
                          label: t('ci.cm_copy_step', { defaultValue: 'Copy the step' }),
                          onClick: () => void copy(s.name),
                        },
                        s.completed_by_name || s.completed_by
                          ? {
                              label: t('ci.cm_copy_signer', { defaultValue: 'Copy who signed it' }),
                              onClick: () => void copy(`${s.completed_by_name || s.completed_by} · ${stamp(s.completed_at)}`),
                            }
                          : null,
                        s.override_reason
                          ? {
                              label: t('ci.cm_copy_override', { defaultValue: 'Copy the override reason' }),
                              onClick: () => void copy(s.override_reason as string),
                            }
                          : null,
                        s.chosen_branch
                          ? {
                              label: t('ci.cm_copy_route', { defaultValue: 'Copy the route taken' }),
                              onClick: () => void copy(`${s.name}: ${s.chosen_branch}`),
                            }
                          : null,
                        null,
                        {
                          label: t('ci.cm_copy_all_steps', { defaultValue: 'Copy the whole workflow' }),
                          onClick: () =>
                            void copy(
                              item.steps
                                .map(
                                  (x) =>
                                    `${x.position + 1}. ${x.name} — ${x.state}${
                                      x.completed_at
                                        ? ` (${x.completed_by_name || x.completed_by} ${stamp(x.completed_at)})`
                                        : ''
                                    }`,
                                )
                                .join('\n'),
                            ),
                        },
                      ])
                    }
                    style={{
                      display: 'flex',
                      gap: 8,
                      alignItems: 'baseline',
                      flexWrap: 'wrap',
                      padding: '5px 8px',
                      borderLeft: `3px solid ${
                        s.state === 'done'
                          ? 'var(--green)'
                          : s.state === 'not_required'
                            ? 'var(--edge2)'
                            : 'var(--amber)'
                      }`,
                      background: 'rgba(12,29,56,0.02)',
                      borderRadius: 4,
                    }}
                  >
                    <span className="v" style={{ minWidth: 20 }}>{s.position + 1}</span>
                    <b style={{ fontSize: 12.5 }}>
                      {s.type === 'gate' ? '⛔ ' : s.type === 'route' ? '🔀 ' : ''}
                      {s.name}
                    </b>
                    <span className="badge">{s.owner}</span>
                    <span
                      className={`badge ${
                        s.state === 'done' ? 'b-green' : s.state === 'not_required' ? '' : 'b-amber'
                      }`}
                    >
                      {s.state.replace(/_/g, ' ')}
                    </span>
                    {s.chosen_branch && (
                      <span className="badge">
                        {t('ci.log_route', { defaultValue: 'took: {{b}}', b: s.chosen_branch })}
                      </span>
                    )}
                    {s.raised_reference && <span className="badge">→ {s.raised_reference}</span>}
                    {/* An override without its reason on the record is the
                        rail quietly removed. It shows here in full. */}
                    {s.override_reason && (
                      <span className="badge b-amber" title={s.override_reason}>
                        {t('ci.log_override', { defaultValue: 'overridden: {{r}}', r: s.override_reason })}
                      </span>
                    )}
                    <span className="v" style={{ marginLeft: 'auto', fontSize: 11.5 }}>
                      {s.completed_at
                        ? `${s.completed_by_name || s.completed_by || '—'} · ${stamp(s.completed_at)}`
                        : t('ci.log_open_step', { defaultValue: 'not done' })}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Section>

          {/* THE CONVERSATION ITSELF. What we sent, and what came back to
              it, in the order it happened — the question everyone actually
              opens this to answer. The list below stays as the index. */}
          <Section
            title={t('ci.thr_title', { defaultValue: 'the conversation' })}
            count={entries.filter((e) => e.type === 'send').length}
          >
            <EmailThread
              itemId={item.id}
              entries={entries}
              onReply={(cid) => setReading(cid)}
              onContext={(e, entry) =>
                openMenu(e, [
                  entry.email_ref || entry.reference
                    ? {
                        label: t('ci.cm_copy_ref', { defaultValue: 'Copy the mail number' }),
                        onClick: () => void copy(String(entry.email_ref || entry.reference)),
                      }
                    : null,
                  {
                    label: t('ci.cm_copy_subject', { defaultValue: 'Copy the subject' }),
                    onClick: () => void copy(entry.subject || ''),
                  },
                  {
                    label: t('ci.cm_copy_when', { defaultValue: 'Copy the date and time' }),
                    onClick: () => void copy(stamp(entry.at)),
                  },
                  entry.type === 'correspondence' && entry.id
                    ? {
                        label: t('ci.cm_open_reader', { defaultValue: 'Open it — reply or forward' }),
                        onClick: () => setReading(entry.id as string),
                      }
                    : null,
                ])
              }
            />
          </Section>

          <Section title={t('ci.thread', { defaultValue: 'correspondence' })} count={entries.length}>
            {thread.isLoading ? (
              <div className="v" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <Loader2 size={13} className="animate-spin" />
                {t('ci.log_loading_thread', { defaultValue: 'gathering the conversation…' })}
              </div>
            ) : entries.length === 0 ? (
              <div className="v">
                {t('ci.thread_empty', { defaultValue: 'nothing yet — drafts and captured replies land here' })}
              </div>
            ) : (
              <div className="qthread">
                {entries.map((e, idx) => {
                  const outbound = e.type === 'send' || e.direction === 'outgoing';
                  const readable = e.type === 'correspondence' && !!e.id;
                  const isOpen = readable && openMsg.has(e.id as string);
                  return (
                    <div
                      key={idx}
                      className={`tmsg ${outbound ? 'tout' : 'tin'}`}
                      style={{ padding: 0 }}
                      onContextMenu={(ev) =>
                        openMenu(ev, [
                          e.email_ref || e.reference
                            ? {
                                label: t('ci.cm_copy_ref', { defaultValue: 'Copy the mail number' }),
                                onClick: () => void copy(String(e.email_ref || e.reference)),
                              }
                            : null,
                          {
                            label: t('ci.cm_copy_subject', { defaultValue: 'Copy the subject' }),
                            onClick: () => void copy(e.subject || ''),
                          },
                          readable
                            ? {
                                label: t('ci.cm_open_reader', { defaultValue: 'Open it — reply or forward' }),
                                onClick: () => setReading(e.id as string),
                              }
                            : null,
                        ])
                      }
                    >
                      <div
                        style={{
                          display: 'flex',
                          gap: 6,
                          alignItems: 'center',
                          flexWrap: 'wrap',
                          padding: '6px 8px',
                          cursor: readable ? 'pointer' : 'default',
                        }}
                        onClick={readable ? () => toggle(e.id as string) : undefined}
                      >
                        <span className={`badge ${outbound ? '' : 'b-green'}`}>
                          {outbound
                            ? t('ci.from_us', { defaultValue: '▶ from us' })
                            : t('ci.from_them', { defaultValue: '◀ from them' })}
                        </span>
                        {(e.email_ref || e.reference) && (
                          <span className="badge" title={t('ci.mail_no', { defaultValue: 'This mail’s own number' })}>
                            {e.email_ref || e.reference}
                          </span>
                        )}
                        <b style={{ fontSize: 12.5 }}>
                          {e.type === 'send'
                            ? t('ci.draft_to', { defaultValue: 'To {{w}}', w: e.who || '—' })
                            : e.subject}
                        </b>
                        {e.category && <span className="badge b-amber">{e.category.replace(/_/g, ' ')}</span>}
                        {readable && (
                          <span className="v" style={{ fontSize: 11.5 }}>
                            {isOpen
                              ? t('ci.log_collapse', { defaultValue: 'hide' })
                              : t('ci.log_expand', { defaultValue: 'read it' })}
                          </span>
                        )}
                        {readable && (
                          <button
                            type="button"
                            className="badge clk"
                            onClick={(ev) => {
                              ev.stopPropagation();
                              setReading(e.id as string);
                            }}
                            title={t('ci.log_open_reader', {
                              defaultValue: 'Open in the reader — reply and forward live there',
                            })}
                          >
                            {t('ci.log_reply', { defaultValue: 'reply ↗' })}
                          </button>
                        )}
                        <span className="v" style={{ marginLeft: 'auto', fontSize: 11.5 }}>{stamp(e.at)}</span>
                      </div>
                      {isOpen && <LogMessage itemId={item.id} corrId={e.id as string} />}
                    </div>
                  );
                })}
              </div>
            )}
          </Section>

          <Section
            title={t('ci.log_who', { defaultValue: 'who was told, who answered' })}
            count={tracking.data?.rows.length ?? 0}
          >
            {(tracking.data?.rows ?? []).length === 0 ? (
              <div className="v">{t('ci.log_nobody', { defaultValue: 'nobody has been emailed yet' })}</div>
            ) : (
              <table className="t" style={{ width: '100%' }}>
                <thead>
                  <tr>
                    <th>{t('ci.log_person', { defaultValue: 'person' })}</th>
                    <th>{t('ci.log_asked', { defaultValue: 'asked' })}</th>
                    <th>{t('ci.log_chases', { defaultValue: 'chases' })}</th>
                    <th>{t('ci.log_answered', { defaultValue: 'answered' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {(tracking.data?.rows ?? []).map((r, i) => (
                    <tr
                      key={r.contact_id ?? `${r.email}-${i}`}
                      onContextMenu={(ev) =>
                        openMenu(ev, [
                          {
                            label: t('ci.cm_copy_email', { defaultValue: 'Copy the address' }),
                            onClick: () => void copy(r.email || ''),
                          },
                          {
                            label: t('ci.cm_copy_name_email', { defaultValue: 'Copy name and address' }),
                            onClick: () => void copy(`${r.name} <${r.email}>`),
                          },
                          r.correspondence_id
                            ? {
                                label: t('ci.cm_open_their_reply', { defaultValue: 'Open their reply' }),
                                onClick: () => setReading(r.correspondence_id as string),
                              }
                            : null,
                          null,
                          {
                            label: t('ci.cm_copy_all_addresses', { defaultValue: 'Copy every address' }),
                            onClick: () =>
                              void copy(
                                (tracking.data?.rows ?? []).map((x) => x.email).filter(Boolean).join('; '),
                              ),
                          },
                        ])
                      }
                    >
                      <td>
                        <b>{r.name}</b> <span className="v">{r.email}</span>
                      </td>
                      <td>
                        {r.sent_count > 0 ? stamp(r.first_sent_at) : <span className="v">—</span>}
                      </td>
                      <td>{r.chases || <span className="v">—</span>}</td>
                      <td>
                        {r.replied_at ? (
                          <span className="badge b-green">{stamp(r.replied_at)}</span>
                        ) : (
                          <span className="badge b-amber">
                            {t('ci.log_silent', { defaultValue: 'silent' })}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>

          {atts.length > 0 && (
            <Section title={t('ci.fold_evidence', { defaultValue: 'attachments' })} count={atts.length}>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {atts.map((a) => (
                  <span
                    key={a.filename}
                    className="badge"
                    onContextMenu={(ev) =>
                      openMenu(ev, [
                        {
                          label: t('ci.cm_copy_filename', { defaultValue: 'Copy the filename' }),
                          onClick: () => void copy(a.filename),
                        },
                        {
                          label: t('ci.cm_open_file', { defaultValue: 'Open the file' }),
                          onClick: () =>
                            window.open(
                              `/api/v1/register-workflow/items/${item.id}/documents/${encodeURIComponent(a.filename)}`,
                              '_blank',
                            ),
                        },
                      ])
                    }
                  >
                    <Paperclip size={11} style={{ verticalAlign: -1 }} /> {a.filename}
                    {a.email && ' · rides the email'}
                  </span>
                ))}
              </div>
            </Section>
          )}
        </div>
      </div>

      {reading && (
        <EmailReader itemId={item.id} correspondenceId={reading} onClose={() => setReading(null)} />
      )}

      {menu && <ContextMenu x={menu.x} y={menu.y} items={menu.items} onClose={() => setMenu(null)} />}
    </div>
  );
}
