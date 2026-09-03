// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The email reader — a supplier's message, read properly.
 *
 * Laid out as a full-height right-hand drawer rather than a centred
 * modal, for one reason: you read a quote *against* the other columns,
 * and a modal hides exactly the thing you are comparing it with. The
 * drawer leaves the compare strip visible behind it.
 *
 * What it has that Outlook does not: the figures this message was
 * scanned for, sitting beside the words they were read out of. That is
 * the whole argument for reading it here.
 *
 * Written in the ERP's own design language (shared Button/Badge, the
 * `oe-*` tokens) so it belongs to this product rather than looking like
 * a bolt-on.
 */

import { formatCurrency } from '@/shared/lib/money';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  CornerUpLeft,
  CornerUpRight,
  Download,
  ExternalLink,
  FileText,
  ImageOff,
  Loader2,
  Paperclip,
  Printer,
  ReplyAll,
  Search,
  Send,
  X,
} from 'lucide-react';
import { Badge, Button } from '@/shared/ui';
import { getAuthToken } from '@/shared/lib/api';
import {
  type BuiltReply,
  type ReplyMode,
  type ViewedMessage,
  fetchMessage,
  messageDocumentUrl,
  openReplyDraft,
} from './registers-api';
import { useToastStore } from '@/stores/useToastStore';
import { fmtFixed } from '@/shared/lib/formatters';

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '?';
  return (parts[0]![0]! + (parts.length > 1 ? parts[parts.length - 1]![0]! : '')).toUpperCase();
}

function prettySize(bytes: number): string {
  if (!bytes) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${fmtFixed(bytes / (1024 * 1024), 1)} MB`;
}

/** Formats the browser renders itself; anything else is a download. */
function viewable(filename: string): boolean {
  return /\.(pdf|png|jpe?g|gif|webp|txt)$/i.test(filename);
}

function Party({ label, people }: { label: string; people: { name: string; email: string }[] }) {
  if (!people.length) return null;
  return (
    <div className="flex gap-2 text-sm">
      <span className="w-10 shrink-0 text-content-tertiary">{label}</span>
      <span className="min-w-0 text-content-secondary">
        {people.map((p, i) => (
          <span key={`${p.email}:${i}`}>
            {i > 0 && ', '}
            <span className="text-content-primary">{p.name}</span>
            {p.email && <span className="text-content-tertiary"> &lt;{p.email}&gt;</span>}
          </span>
        ))}
      </span>
    </div>
  );
}

/** One attachment, previewable in place. */
function Attachment({
  itemId,
  correspondenceId,
  filename,
  size,
  onOpen,
}: {
  itemId: string;
  correspondenceId: string;
  filename: string;
  size: number;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  const download = async () => {
    const token = getAuthToken();
    const res = await fetch(messageDocumentUrl(itemId, correspondenceId, filename), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-surface-primary px-3 py-2">
      <FileText className="h-4 w-4 shrink-0 text-content-tertiary" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm text-content-primary" title={filename}>
          {filename}
        </div>
        {size > 0 && <div className="text-xs text-content-tertiary">{prettySize(size)}</div>}
      </div>
      {viewable(filename) && (
        <Button size="sm" variant="ghost" onClick={onOpen}>
          {t('ci.rd_view', { defaultValue: 'View' })}
        </Button>
      )}
      <Button size="sm" variant="ghost" icon={<Download className="h-3.5 w-3.5" />} onClick={() => void download()}>
        {t('ci.rd_save', { defaultValue: 'Save' })}
      </Button>
    </div>
  );
}

/**
 * Replying, in the reader rather than somewhere else.
 *
 * The recipients are computed SERVER-SIDE from the one message being
 * read (see register_workflow/replying.py) - this pane shows them and
 * lets you add to them, but it never assembles the list itself. On an
 * RFQ the item's recipient list is every supplier quoting the package,
 * so an address list built in the browser is one refactor away from
 * handing each supplier its competitor list.
 */
function Compose({
  itemId,
  correspondenceId,
  mode,
  msg,
  onDone,
  onCancel,
}: {
  itemId: string;
  correspondenceId: string;
  mode: ReplyMode;
  msg: ViewedMessage;
  onDone: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [extra, setExtra] = useState('');
  const [body, setBody] = useState('');

  // Who this goes to before anything is typed - mirrors the server's rule
  // so the pane is honest the moment it opens rather than after a round
  // trip. The server still decides; this only says what to expect.
  const implied = useMemo(() => {
    if (mode === 'forward') return [];
    const people = [...(msg.from_people ?? [])];
    if (mode === 'reply_all') people.push(...(msg.to_people ?? []));
    const seen = new Set<string>();
    return people
      .filter((p) => {
        const key = (p.email || p.name || '').toLowerCase();
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .map((p) => (p.name && p.email ? `${p.name} <${p.email}>` : p.email || p.name));
  }, [mode, msg]);

  const typed = extra
    .split(/[;,\n]/)
    .map((a) => a.trim())
    .filter(Boolean);

  const draft = useMutation({
    mutationFn: () => openReplyDraft(itemId, correspondenceId, { mode, to: typed, body }),
    onSuccess: (r: BuiltReply) => {
      if (r.opened) {
        addToast({
          type: 'success',
          title: t('ci.rd_draft_open', {
            defaultValue: 'Draft opened in Outlook - read it and press Send there',
          }),
        });
        onDone();
        return;
      }
      // No Outlook on this machine is an ordinary state, not a failure -
      // and what was typed is still here.
      addToast({
        type: 'error',
        title:
          r.error ??
          t('ci.rd_no_outlook', { defaultValue: 'Outlook could not be opened on this machine' }),
      });
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const label =
    mode === 'forward'
      ? t('ci.rd_forwarding', { defaultValue: 'Forwarding' })
      : mode === 'reply_all'
        ? t('ci.rd_replying_all', { defaultValue: 'Replying to all' })
        : t('ci.rd_replying', { defaultValue: 'Replying' });

  return (
    <div className="border-t border-border bg-surface-secondary px-6 py-4">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">{label}</span>
        <Button size="sm" variant="ghost" className="ml-auto" onClick={onCancel}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
      </div>

      <div className="mb-2 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm">
        <span className="text-content-tertiary">{t('ci.rd_to', { defaultValue: 'To' })}</span>
        {implied.length > 0 ? (
          implied.map((a) => (
            <Badge key={a} variant="neutral" size="sm">
              {a}
            </Badge>
          ))
        ) : (
          <span className="text-xs italic text-content-tertiary">
            {t('ci.rd_fwd_nobody', { defaultValue: 'a forward goes only where you send it' })}
          </span>
        )}
      </div>

      <input
        className="mb-2 w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary"
        placeholder={
          mode === 'forward'
            ? t('ci.rd_fwd_to', { defaultValue: 'Forward to — name@company.com.au' })
            : t('ci.rd_add_to', { defaultValue: 'Add anyone else — separate with a comma' })
        }
        value={extra}
        onChange={(e) => setExtra(e.target.value)}
      />
      <textarea
        className="min-h-[120px] w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm leading-relaxed text-content-primary"
        placeholder={t('ci.rd_body_ph', { defaultValue: 'Type your reply — their message is quoted underneath it' })}
        value={body}
        onChange={(e) => setBody(e.target.value)}
      />
      <div className="mt-2 flex items-center gap-2">
        <Button
          size="sm"
          variant="primary"
          icon={draft.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
          disabled={draft.isPending || (mode === 'forward' && typed.length === 0)}
          onClick={() => draft.mutate()}
        >
          {t('ci.rd_open_draft', { defaultValue: 'Open the draft in Outlook' })}
        </Button>
        <span className="text-xs text-content-tertiary">
          {t('ci.rd_nothing_sent', { defaultValue: 'Nothing is sent from here — you press Send in Outlook' })}
        </span>
      </div>
    </div>
  );
}

export function EmailReader({
  itemId,
  correspondenceId,
  fallbackSubject = '',
  fallbackText = '',
  onClose,
  onReply,
  onForward,
  initialMode,
}: {
  itemId: string;
  /** Null when the reply was captured as loose text with no filed record. */
  correspondenceId: string | null;
  fallbackSubject?: string;
  fallbackText?: string;
  onClose: () => void;
  onReply?: (msg: ViewedMessage, all: boolean) => void;
  onForward?: (msg: ViewedMessage) => void;
  /** Open with the compose pane already on Reply / Reply all / Forward -
   *  a thread entry's right-click menu lands straight on the verb. */
  initialMode?: ReplyMode | null;
}) {
  const { t } = useTranslation();
  const [showEvidence, setShowEvidence] = useState(false);
  const [preview, setPreview] = useState<{ filename: string; url: string } | null>(null);
  const [composing, setComposing] = useState<ReplyMode | null>(initialMode ?? null);

  const q = useQuery({
    queryKey: ['register-message', itemId, correspondenceId],
    queryFn: () => fetchMessage(itemId, correspondenceId as string),
    enabled: !!correspondenceId,
  });
  // A message with no filed correspondence row still opens in the SAME
  // reader rather than a thinner second one - one layout, whatever there
  // is to show. Two readers was how the rich one ended up unreachable.
  const msg: ViewedMessage | undefined = correspondenceId
    ? q.data
    : ({
        correspondence_id: '',
        reference_number: '',
        subject: fallbackSubject,
        direction: 'inbound',
        date: null,
        from_people: [],
        to_people: [],
        text: fallbackText,
        html: '',
        remote_content_blocked: false,
        documents: [],
      } satisfies ViewedMessage);

  // Escape closes the topmost thing: the attachment preview first, then
  // the drawer - so Escape never skips a layer.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (preview) setPreview(null);
      else if (composing) setComposing(null);
      else onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [preview, composing, onClose]);

  // Attachments only exist on a filed message, so `correspondenceId` is
  // never null on either of these paths - the fallback message carries an
  // empty document list.
  const cid = correspondenceId ?? '';

  const openDoc = async (filename: string) => {
    const token = getAuthToken();
    const res = await fetch(messageDocumentUrl(itemId, cid, filename), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) return;
    setPreview({ filename, url: URL.createObjectURL(await res.blob()) });
  };

  const ex = msg?.extracted;
  const hasFigures = !!(ex && (ex.amount || ex.quote_number || ex.lead_time));
  // Only a filed message can be replied to: a loose captured body has no
  // record behind it to address or quote.
  const canReply = !!correspondenceId;

  return (
    <div className="fixed inset-0 z-[80] flex justify-end" role="dialog" aria-modal="true" aria-label="Email">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" onClick={onClose} />

      <aside className="relative flex h-full w-full max-w-[760px] flex-col bg-surface-primary shadow-2xl">
        {/* Controls first: this is a mail client, and a mail client's verbs live at the top. */}
        <div className="flex items-center gap-1.5 border-b border-border px-3 py-2">
          {/* These three were rendered disabled unless a caller passed a
              handler, and no caller ever passed one - three dead buttons
              at the top of a mail reader. They open the compose pane. */}
          <Button
            size="sm"
            variant={composing === 'reply' ? 'primary' : 'secondary'}
            icon={<CornerUpLeft className="h-3.5 w-3.5" />}
            disabled={!msg || !canReply}
            onClick={() => (msg && onReply ? onReply(msg, false) : setComposing('reply'))}
          >
            {t('ci.rd_reply', { defaultValue: 'Reply' })}
          </Button>
          <Button
            size="sm"
            variant={composing === 'reply_all' ? 'primary' : 'ghost'}
            icon={<ReplyAll className="h-3.5 w-3.5" />}
            disabled={!msg || !canReply}
            onClick={() => (msg && onReply ? onReply(msg, true) : setComposing('reply_all'))}
          >
            {t('ci.rd_reply_all', { defaultValue: 'Reply all' })}
          </Button>
          <Button
            size="sm"
            variant={composing === 'forward' ? 'primary' : 'ghost'}
            icon={<CornerUpRight className="h-3.5 w-3.5" />}
            disabled={!msg || !canReply}
            onClick={() => (msg && onForward ? onForward(msg) : setComposing('forward'))}
          >
            {t('ci.rd_forward', { defaultValue: 'Forward' })}
          </Button>
          <div className="mx-1 h-5 w-px bg-border" />
          <Button size="sm" variant="ghost" icon={<Printer className="h-3.5 w-3.5" />} onClick={() => window.print()}>
            {t('ci.rd_print', { defaultValue: 'Print' })}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={onClose}
            className="ml-auto"
            icon={<X className="h-4 w-4" />}
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <span className="sr-only">{t('common.close', { defaultValue: 'Close' })}</span>
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {!!correspondenceId && q.isLoading && (
            <div className="flex h-40 items-center justify-center">
              <Loader2 className="h-5 w-5 animate-spin text-content-tertiary" />
            </div>
          )}
          {!!correspondenceId && q.error && (
            <div className="p-6 text-sm text-semantic-error">{(q.error as Error).message}</div>
          )}

          {msg && (
            <>
              <header className="border-b border-border px-6 py-5">
                <h2 className="text-lg font-semibold leading-snug text-content-primary">{msg.subject}</h2>
                <div className="mt-3 flex items-start gap-3">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle text-xs font-semibold text-oe-blue-text">
                    {initials(msg.from_people?.[0]?.name ?? '?')}
                  </div>
                  <div className="min-w-0 flex-1 space-y-0.5">
                    <Party label={t('ci.rd_from', { defaultValue: 'From' })} people={msg.from_people ?? []} />
                    <Party label={t('ci.rd_to', { defaultValue: 'To' })} people={msg.to_people ?? []} />
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1.5">
                    {msg.date && <span className="text-xs text-content-tertiary">{msg.date}</span>}
                    {msg.reference_number && <Badge variant="neutral" size="sm">{msg.reference_number}</Badge>}
                  </div>
                </div>
              </header>

              {hasFigures && (
                <section className="border-b border-border bg-surface-secondary px-6 py-4">
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                    {t('ci.rd_read_from', { defaultValue: 'Read from this message' })}
                  </div>
                  <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
                    {ex?.amount && (
                      <div>
                        <div className="text-lg font-semibold tabular-nums text-content-primary">
                          {/* No currency code: the extractor reads a figure out of a
                              message body and never learns which currency it is in, so
                              naming one here would be the screen asserting something
                              nothing established. The separators follow the reader. */}
                          {formatCurrency(ex.amount)}
                        </div>
                        {ex.basis && <div className="text-xs text-content-tertiary">{ex.basis}</div>}
                      </div>
                    )}
                    {ex?.quote_number && (
                      <div className="text-sm">
                        <span className="text-content-tertiary">{t('ci.rd_quote_no', { defaultValue: 'Quote no.' })} </span>
                        <span className="text-content-primary">{ex.quote_number}</span>
                      </div>
                    )}
                    {ex?.lead_time && (
                      <div className="text-sm">
                        <span className="text-content-tertiary">{t('ci.rd_lead', { defaultValue: 'Lead time' })} </span>
                        <span className="text-content-primary">{ex.lead_time}</span>
                      </div>
                    )}
                    {ex?.evidence && (
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={<Search className="h-3.5 w-3.5" />}
                        onClick={() => setShowEvidence((v) => !v)}
                      >
                        {t('ci.rd_why', { defaultValue: 'why' })}
                      </Button>
                    )}
                  </div>
                  {showEvidence && ex?.evidence && (
                    // Verbatim, because an extracted figure is only worth
                    // as much as the words behind it.
                    <blockquote className="mt-3 border-l-2 border-oe-blue bg-surface-primary px-3 py-2 text-xs italic text-content-secondary">
                      …{ex.evidence}…
                    </blockquote>
                  )}
                  {(ex?.warnings ?? []).map((w) => (
                    <div key={w} className="mt-2 flex items-start gap-2 text-xs text-[#b45309]">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      <span>{w}</span>
                    </div>
                  ))}
                </section>
              )}

              {msg.remote_content_blocked && (
                <div className="flex items-center gap-2 border-b border-border bg-semantic-warning-bg px-6 py-2 text-xs text-[#b45309]">
                  <ImageOff className="h-3.5 w-3.5 shrink-0" />
                  {t('ci.rd_blocked', {
                    defaultValue:
                      'Remote images were blocked — in a quote they tell the sender when you opened it.',
                  })}
                </div>
              )}

              <div className="px-6 py-5">
                {msg.html ? (
                  // Server-sanitised through an allowlist before it ever
                  // reaches here; see register_workflow/sanitise.py.
                  <div
                    className="oe-email-body text-sm leading-relaxed text-content-primary"
                    dangerouslySetInnerHTML={{ __html: msg.html }}
                  />
                ) : msg.text ? (
                  <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-content-primary">
                    {msg.text}
                  </pre>
                ) : (
                  <p className="text-sm italic text-content-tertiary">
                    {t('ci.rd_no_body', { defaultValue: 'Nothing was saved of the body.' })}
                  </p>
                )}
              </div>

              {composing && correspondenceId && (
                <Compose
                  itemId={itemId}
                  correspondenceId={correspondenceId}
                  mode={composing}
                  msg={msg}
                  onDone={() => setComposing(null)}
                  onCancel={() => setComposing(null)}
                />
              )}

              {msg.documents.length > 0 && (
                <section className="border-t border-border px-6 py-4">
                  <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                    <Paperclip className="h-3.5 w-3.5" />
                    {t('ci.rd_attached', { defaultValue: '{{count}} attached', count: msg.documents.length })}
                  </div>
                  <div className="space-y-2">
                    {msg.documents.map((d) => (
                      <Attachment
                        key={d.filename}
                        itemId={itemId}
                        correspondenceId={cid}
                        filename={d.filename}
                        size={(d as { size?: number }).size ?? 0}
                        onOpen={() => void openDoc(d.filename)}
                      />
                    ))}
                  </div>
                </section>
              )}
            </>
          )}
        </div>
      </aside>

      {preview && (
        <div className="absolute inset-0 z-10 flex flex-col bg-surface-primary">
          <div className="flex items-center gap-2 border-b border-border px-4 py-2">
            <FileText className="h-4 w-4 text-content-tertiary" />
            <span className="truncate text-sm text-content-primary">{preview.filename}</span>
            <a
              href={preview.url}
              target="_blank"
              rel="noreferrer"
              className="ml-auto inline-flex items-center gap-1 text-xs text-oe-blue-text hover:underline"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              {t('ci.rd_new_tab', { defaultValue: 'Open in a tab' })}
            </a>
            <Button size="sm" variant="ghost" icon={<X className="h-4 w-4" />} onClick={() => setPreview(null)}>
              <span className="sr-only">{t('common.close', { defaultValue: 'Close' })}</span>
            </Button>
          </div>
          {/* No sandbox on a PDF or an image: the browser's own viewer is
              script driven and a sandbox silently blanks it - the defect
              that killed the quote viewer in an earlier version. */}
          <iframe title={preview.filename} src={preview.url} className="min-h-0 flex-1 border-0" />
        </div>
      )}
    </div>
  );
}
