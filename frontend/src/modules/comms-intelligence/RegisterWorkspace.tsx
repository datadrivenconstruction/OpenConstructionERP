// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The register workspace — the correspondence job tab, rebuilt.
 *
 * Layout follows the original: KPI tiles, kind tabs, a four-column
 * register table whose rows expand in place to show the workflow, and a
 * raise form that opens INLINE under the table with the email preview
 * pinned to the right of the screen so it never moves while you type.
 *
 * The supplier picker is the ranked table from the original — project
 * directory first, then last-used, then recent — click a row to add it,
 * right-click to fix the company's details without leaving the form.
 */

import { Fragment, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { qAsk } from './qAsk';
import { openWorkflowEditor } from './WorkflowEditor';
import { PasteGrid } from './PasteGrid';
import { Fold } from './Fold';
import { EmailReader } from './EmailReader';
import { ConversationLog } from './ConversationLog';
import { menuAt, useMenu, type MenuItem } from './ContextMenu';
import { KIND_COLOR, KIND_LABEL, RecordPicker } from './RecordPicker';
import './ci.css';
import {
  type ContactRow,
  type ItemLink,
  type Kind,
  type KindSpec,
  type RegisterItemRow,
  type ReplyMode,
  type SendLogEntry,
  type StepRow,
  type Summary,
  type ThreadEntry,
  addStep,
  completeStep,
  documentUrl,
  fetchItems,
  fetchItemThread,
  fetchItemTracking,
  fetchPrefill,
  fetchContactsByIds,
  logReply,
  fetchSpec,
  fetchStats,
  fetchSummary,
  logAlreadySentMany,
  notRequiredStep,
  errorDetail,
  previewComposeEmail,
  setProjectJobNumber,
  raiseItem,
  fetchFieldSuggestions,
  addItemLink,
  fetchSupplierRanking,
  searchContacts,
  setAttachmentEmailFlag,
  takeRoute,
  uncompleteStep,
  updateContact,
  linksOf,
  removeItemLink,
  updateItem,
  uploadItemAttachment,
} from './registers-api';
import { LogSentDialog, logSentRows, type LogSentRow } from './LogSentDialog';
import {
  WithdrawnBanner,
  isWithdrawn,
  removeMenuItems,
  withdrawnNote,
  withdrawnRowStyle,
  withdrawnTitle,
  type RemoveCtx,
} from './RegisterRemove';

const KIND_ORDER: Kind[] = ['rfi', 'rfq', 'order', 'variation', 'delay', 'toolbox'];
const KIND_SHORT: Record<Kind, string> = {
  rfi: 'RFI',
  rfq: 'RFQ',
  order: 'Orders',
  variation: 'Variations',
  delay: 'Delays',
  toolbox: 'Toolbox',
};

const sendLog = (i: RegisterItemRow): SendLogEntry[] => {
  const l = (i.fields as Record<string, unknown>)['_send_log'];
  return Array.isArray(l) ? (l as SendLogEntry[]) : [];
};
const attachmentsOf = (i: RegisterItemRow): { filename: string; size: number; email?: boolean }[] => {
  const a = (i.fields as Record<string, unknown>)['_attachments'];
  return Array.isArray(a) ? (a as { filename: string; size: number; email?: boolean }[]) : [];
};
const visibleFields = (i: RegisterItemRow): [string, string][] =>
  Object.entries(i.fields).filter(([k, v]) => !k.startsWith('_') && String(v ?? '').trim()) as [string, string][];
const contactName = (c: ContactRow) =>
  c.company_name || [c.first_name, c.last_name].filter(Boolean).join(' ') || c.primary_email || '—';

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

/** Gate and decision colours, as the step rows draw them. */
const GATE_C = '#8e2f3c';
const ROUTE_C = '#1d5a8a';
const STEP_C = '#12294a';

const copyText = (s: string) => void navigator.clipboard.writeText(s);

/**
 * Manually file a reply that came back outside the app. On a server with
 * no mailbox bridge this is how the workflow keeps moving: paste what a
 * supplier said, pick who it was from, and the item's tracking flips to
 * "replied" (or "quoted" when the paste carries a price) — the server
 * routes it through the same inbound-capture path the bridge would.
 *
 * Exported because the tracking tab offers the same action on its rows.
 */
export async function attachReplyFlow(
  item: { id: string; reference: string },
  ctx: {
    t: TFunction;
    addToast: (toast: { type: 'success' | 'error'; title: string }) => void;
    queryClient: QueryClient;
    projectId: string | null;
  },
): Promise<void> {
  const { t, addToast, queryClient, projectId } = ctx;
  // Offer everyone this item was sent to, so the reply attributes to the
  // right supplier row. Tracking may not exist yet (nothing sent) — that
  // is fine, the sender can still be typed by hand.
  let options: { label: string; contact_id: string | null; email: string }[] = [];
  try {
    const tr = await fetchItemTracking(item.id);
    options = tr.rows
      .filter((r) => r.name)
      .map((r) => ({ label: r.name, contact_id: r.contact_id, email: r.email }));
  } catch {
    /* no tracking yet — leave the picker free-text */
  }
  const answers = await qAsk({
    title: t('ci.attach_reply_title', {
      defaultValue: 'Attach a reply to {{ref}}',
      ref: item.reference,
    }),
    note: t('ci.attach_reply_note', {
      defaultValue:
        'Paste a reply that came back outside the app. It lands on this item and marks the sender replied — a price in the text is picked up as their quote.',
    }),
    fields: [
      {
        label: t('ci.attach_reply_from', { defaultValue: 'From — who replied' }),
        placeholder: t('ci.attach_reply_from_ph', { defaultValue: 'pick or type a supplier / name' }),
        options: options.map((o) => o.label),
      },
      {
        label: t('ci.attach_reply_body', { defaultValue: 'Their reply' }),
        placeholder: t('ci.attach_reply_body_ph', {
          defaultValue: 'paste the message they sent back',
        }),
        multiline: true,
      },
    ],
    okLabel: t('ci.attach_reply_ok', { defaultValue: 'Attach the reply' }),
  });
  if (!answers) return; // cancelled
  const who = (answers[0] ?? '').trim();
  const replyBody = (answers[1] ?? '').trim();
  if (!who && !replyBody) return;
  const matched = options.find((o) => o.label.toLowerCase() === who.toLowerCase());
  try {
    // A matched pick sends the contact id and lets the server resolve the
    // canonical name/email; an unmatched entry rides as a free-text name.
    await logReply(item.id, {
      contact_id: matched?.contact_id ?? null,
      from_name: matched ? '' : who,
      body: replyBody,
    });
    addToast({
      type: 'success',
      title: t('ci.attach_reply_done', { defaultValue: 'Reply attached — tracking updated' }),
    });
    for (const key of [
      ['registers', projectId],
      ['register-tracking', projectId],
      ['item-tracking', item.id],
      ['thread', item.id],
      ['suggestions', item.id],
      ['compare-side-by-side', item.id],
    ]) {
      void queryClient.invalidateQueries({ queryKey: key });
    }
  } catch (e) {
    addToast({ type: 'error', title: (e as Error).message });
  }
}

// ---------------------------------------------------------------------------
// The supplier picker — ranked table, click to toggle, right-click to fix
// ---------------------------------------------------------------------------

export function RecipientBlock({
  spec,
  kind,
  projectId,
  selected,
  onChange,
  variant = 'form',
}: {
  spec: KindSpec;
  kind: Kind;
  projectId: string;
  selected: ContactRow[];
  onChange: (rows: ContactRow[]) => void;
  /** 'form' is the raise form's full-width table in the workspace style.
   *  'rail' is a compact single-column list in the ERP's own tokens, for
   *  the email dialog's sidebar - the full table transplanted into a
   *  400px column wrapped its own instructions four lines deep and
   *  clipped every name it was there to offer. */
  variant?: 'form' | 'rail';
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [term, setTerm] = useState('');
  const [debounced, setDebounced] = useState('');
  const menu = useMenu();
  const mode = spec.recipient;

  // 160ms, matching the original's picker debounce.
  useEffect(() => {
    const h = setTimeout(() => setDebounced(term), 160);
    return () => clearTimeout(h);
  }, [term]);

  const contactType = mode === 'client' ? 'client' : mode === 'any' ? undefined : 'supplier';
  const list = useQuery({
    queryKey: ['picker', debounced, contactType],
    queryFn: () => searchContacts(debounced, contactType),
    enabled: mode !== 'none',
  });

  // THE RANKING. Alphabetical order in a 434-company directory is a
  // search box you have to type into every time; the people already on
  // this job should be a click. Tiers come from the server because
  // "recent" and "on this job" are facts about the data, not about what
  // this particular search returned.
  const ranking = useQuery({
    queryKey: ['picker-ranking', projectId, kind],
    queryFn: () => fetchSupplierRanking(projectId, kind),
    enabled: mode !== 'none' && !!projectId,
    staleTime: 60_000,
  });

  // The search endpoint answers with 25 rows. Ranking only those would
  // sort a page that may not CONTAIN the supplier you used yesterday -
  // the ranking would look like it was doing nothing. So the ranked
  // contacts are fetched by id and merged in: they are the whole point
  // of the feature, and there are never many of them.
  const rankedIds = useMemo(
    () => Object.keys(ranking.data?.tiers ?? {}),
    [ranking.data],
  );
  const rankedRows = useQuery({
    queryKey: ['picker-ranked-rows', rankedIds.join(',')],
    queryFn: () => fetchContactsByIds(rankedIds),
    enabled: rankedIds.length > 0,
    staleTime: 60_000,
  });

  const editContact = async (c: ContactRow) => {
    // WHO you are writing to, not just where. The greeting on every email
    // is built from the contact's FIRST NAME, so a company with the wrong
    // person on it produces "Hi <wrong person>," on an RFQ - and this
    // dialog used to ask for two fields, neither of them the name.
    const answers = await qAsk({
      title: t('ci.fix_company', { defaultValue: 'Company and contact details' }),
      note: t('ci.fix_company_note', {
        defaultValue:
          'Corrected here, corrected in the directory for everyone. The first name is what the email greeting uses.',
      }),
      fields: [
        { label: t('ci.company', { defaultValue: 'Company' }), value: c.company_name ?? '' },
        {
          label: t('ci.contact_first', { defaultValue: 'Contact — first name (the greeting uses this)' }),
          value: c.first_name ?? '',
          placeholder: 'Dave',
        },
        {
          label: t('ci.contact_last', { defaultValue: 'Contact — surname' }),
          value: c.last_name ?? '',
          placeholder: 'Whitfield',
        },
        { label: 'Email', value: c.primary_email ?? '', placeholder: 'name@company.com.au' },
        {
          label: t('ci.contact_phone', { defaultValue: 'Phone' }),
          value: (c as ContactRow & { primary_phone?: string | null }).primary_phone ?? '',
          placeholder: '02 9000 0000',
        },
      ],
      okLabel: t('ci.save', { defaultValue: 'Save' }),
    });
    if (!answers) return;
    try {
      const saved = await updateContact(String(c.id), {
        company_name: answers[0],
        first_name: answers[1],
        last_name: answers[2],
        primary_email: answers[3],
        primary_phone: answers[4],
      });
      onChange(selected.map((s) => (String(s.id) === String(c.id) ? saved : s)));
      void list.refetch();
      void rankedRows.refetch();
      addToast({ type: 'success', title: t('ci.contact_saved', { defaultValue: 'Directory updated' }) });
    } catch (e) {
      addToast({ type: 'error', title: (e as Error).message });
    }
  };

  // Right-click a company anywhere in the picker: fix its details, copy
  // its address, add or drop it from the recipients.
  const contactMenu = (e: ReactMouseEvent, c: ContactRow) =>
    menu.openFromEvent(
      e,
      [
        {
          label: isSel(c)
            ? t('ci.menu_remove_recipient', { defaultValue: 'Remove from the recipients' })
            : t('ci.menu_add_recipient', { defaultValue: 'Add to the recipients' }),
          onClick: () => toggle(c),
        },
        { label: t('ci.menu_edit', { defaultValue: 'Edit company details…' }), onClick: () => void editContact(c) },
        c.primary_email
          ? {
              label: t('ci.menu_copy_email', { defaultValue: 'Copy email address' }),
              note: c.primary_email,
              onClick: () => copyText(c.primary_email ?? ''),
            }
          : null,
      ],
      { head: c.company_name || contactName(c) },
    );

  if (mode === 'none') return null;

  const searchRows = list.data ?? [];
  const tiers = ranking.data?.tiers ?? {};
  // Merged, de-duplicated by id. When a search is running the ranked rows
  // are filtered by the same term, so typing still narrows the list -
  // otherwise "on this job" suppliers would stick to the top for ever.
  const needle = debounced.trim().toLowerCase();
  const rows = useMemo(() => {
    const byId = new Map<string, ContactRow>();
    for (const c of rankedRows.data ?? []) {
      const hay = `${c.company_name ?? ''} ${contactName(c)} ${c.primary_email ?? ''}`.toLowerCase();
      if (!needle || hay.includes(needle)) byId.set(String(c.id), c);
    }
    for (const c of searchRows) byId.set(String(c.id), c);
    return [...byId.values()];
  }, [rankedRows.data, searchRows, needle]);
  const tierOf = (c: ContactRow) => tiers[String(c.id)]?.tier ?? 4;
  const tierLabelOf = (c: ContactRow) => tiers[String(c.id)]?.label ?? '';
  // Sorted BEFORE the slice, or the top 40 would be the first 40 the
  // search returned rather than the 40 most likely - which is what it
  // was doing, while the tint CSS for the top three sat unused.
  const ordered = [...rows].sort(
    (a, b) =>
      tierOf(a) - tierOf(b) ||
      (a.company_name || contactName(a)).localeCompare(b.company_name || contactName(b)),
  );
  const shown = ordered.slice(0, 40);
  const isSel = (c: ContactRow) => selected.some((s) => String(s.id) === String(c.id));
  const toggle = (c: ContactRow) => {
    if (isSel(c)) onChange(selected.filter((s) => String(s.id) !== String(c.id)));
    // 'any' is multi-select too: an RFI often goes to the engineer AND
    // the architect AND the client's PM in one issue.
    else onChange(mode === 'multi' || mode === 'any' ? [...selected, c] : [c]);
  };

  if (variant === 'rail') {
    return (
      <div className="flex min-h-0 flex-col gap-2">
        <input
          className="w-full rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm"
          placeholder={t('ci.picker_search_rail', { defaultValue: 'search the directory…' })}
          value={term}
          onChange={(e) => setTerm(e.target.value)}
        />
        <div className="max-h-[38vh] min-h-0 overflow-auto rounded-md border border-border-light">
          {list.isLoading ? (
            <p className="p-2 text-xs text-content-tertiary">…</p>
          ) : shown.length === 0 ? (
            <p className="p-2 text-xs text-content-tertiary">
              {t('ci.picker_none', { defaultValue: 'nobody matches — try a shorter search' })}
            </p>
          ) : (
            shown.map((c) => {
              const on = isSel(c);
              return (
                <button
                  key={String(c.id)}
                  type="button"
                  onClick={() => toggle(c)}
                  onContextMenu={(e) => contactMenu(e, c)}
                  className={`block w-full border-b border-border-light/60 px-2.5 py-1.5 text-left last:border-b-0 ${
                    on ? 'bg-oe-blue-subtle' : 'hover:bg-surface-secondary'
                  }`}
                  style={!on && tierOf(c) < 3 ? { background: '#fff9f0' } : undefined}
                >
                  <span className="flex items-center gap-1.5">
                    <span
                      className={`text-xs ${on ? 'text-oe-blue-text' : 'text-transparent'}`}
                      aria-hidden
                    >
                      ✓
                    </span>
                    <span className="min-w-0 flex-1 truncate text-sm font-medium text-content-primary">
                      {c.company_name || contactName(c)}
                    </span>
                    {tierLabelOf(c) && (
                      <span className="shrink-0 rounded-full bg-surface-secondary px-1.5 py-0.5 text-[10px] text-content-tertiary">
                        {tierLabelOf(c)}
                      </span>
                    )}
                  </span>
                  <span className="block truncate pl-5 text-xs text-content-tertiary">
                    {c.primary_email ||
                      t('ci.rail_no_email', { defaultValue: 'no email — right-click to add one' })}
                  </span>
                </button>
              );
            })
          )}
        </div>
        <p className="text-[11px] text-content-tertiary">
          {t('ci.rail_hint', {
            defaultValue: 'Click adds or removes. Right-click edits the company and contact.',
          })}
        </p>
        {menu.element}
      </div>
    );
  }

  const label =
    mode === 'multi'
      ? t('ci.to_multi', { defaultValue: 'To · pick the suppliers' })
      : mode === 'any'
        ? t('ci.to_any', { defaultValue: 'To · anyone in the directory' })
        : mode === 'single'
          ? t('ci.to_single', { defaultValue: 'To · the supplier' })
          : t('ci.to_client', { defaultValue: 'To · the client / consultant' });

  return (
    <div className="qtorow">
      <span className="qlab" style={{ color: 'var(--amber)' }}>
        {label}
        <span className="v" style={{ fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>
          {mode === 'multi'
            ? t('ci.to_multi_note', { defaultValue: '— click a row to add it; each supplier gets its own tailored email' })
            : t('ci.to_note', { defaultValue: '— click a row to add it' })}
        </span>
      </span>

      {selected.length > 0 && (
        <div style={{ marginTop: 4 }}>
          {selected.map((c) => (
            <span
              key={String(c.id)}
              className="qselchip on"
              onContextMenu={(e) => contactMenu(e, c)}
            >
              <b style={{ color: 'var(--navy)' }}>{c.company_name || contactName(c)}</b>
              {/* The person, named. The greeting is built from this, so
                  when it is missing the email opens "Hi," and nobody can
                  tell until the supplier reads it. */}
              {c.first_name ? (
                <span className="qsupc2 on">{[c.first_name, c.last_name].filter(Boolean).join(' ')}</span>
              ) : (
                <span className="badge b-amber">
                  {t('ci.no_person', { defaultValue: 'no contact name — right-click to add' })}
                </span>
              )}
              {c.primary_email ? (
                <span className="qsupc2 on">{c.primary_email}</span>
              ) : (
                <span className="badge b-red">
                  {t('ci.no_email', { defaultValue: 'no email — right-click to add' })}
                </span>
              )}
              <button type="button" className="b mini" onClick={() => toggle(c)} aria-label="remove">
                ✕
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="row" style={{ marginTop: 6 }}>
        <input
          style={{ flex: 1, minWidth: 220 }}
          placeholder={t('ci.picker_search', { defaultValue: 'search your directory — name, tag, person, email' })}
          value={term}
          onChange={(e) => setTerm(e.target.value)}
        />
        <span className="badge">
          {t('ci.n_selected', { defaultValue: '{{n}} selected', n: selected.length })}
        </span>
        {selected.length > 0 && (
          <button type="button" className="b mini" onClick={() => onChange([])}>
            {t('ci.clear_all', { defaultValue: 'clear all' })}
          </button>
        )}
      </div>

      <div className="picker" style={{ marginTop: 6 }}>
        <table className="t" style={{ margin: 0 }}>
          <thead>
            <tr>
              <th>{t('ci.col_company', { defaultValue: 'company — click to add / remove · RIGHT-CLICK to edit details' })}</th>
              <th>{t('ci.col_contact', { defaultValue: 'contact' })}</th>
            </tr>
          </thead>
          <tbody>
            {list.isLoading ? (
              <tr>
                <td colSpan={2} className="v">
                  …
                </td>
              </tr>
            ) : shown.length === 0 ? (
              <tr>
                <td colSpan={2} className="v">
                  {t('ci.picker_none', { defaultValue: 'nobody matches — try a shorter search' })}
                </td>
              </tr>
            ) : (
              shown.map((c) => (
                <tr
                  key={String(c.id)}
                  // r0/r1/r2 tint the top three tiers amber, the way the
                  // original marked them. The CSS was ported months ago
                  // and never applied to anything.
                  className={`qfindrow ${isSel(c) ? 'sel' : ''} ${tierOf(c) < 3 ? `r${tierOf(c)}` : ''}`}
                  onClick={() => toggle(c)}
                  onContextMenu={(e) => contactMenu(e, c)}
                >
                  <td>
                    {isSel(c) ? '✓ ' : ''}
                    <b>{c.company_name || contactName(c)}</b>
                    {tierLabelOf(c) && (
                      <span className="badge" style={{ marginLeft: 6 }}>
                        {tierLabelOf(c)}
                      </span>
                    )}
                  </td>
                  <td className="v">{c.primary_email || '—'}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        {rows.length > 40 && (
          <div className="v" style={{ padding: 6 }}>
            {t('ci.picker_more_ranked', {
              defaultValue: 'showing the 40 most likely of {{n}} — refine the search for the rest',
              n: rows.length,
            })}
          </div>
        )}
      </div>

      {menu.element}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The raise form — inline panel, pinned live preview
// ---------------------------------------------------------------------------

function RaiseForm({
  spec,
  projectId,
  prefill,
  onCancel,
  onRaised,
}: {
  spec: KindSpec;
  projectId: string;
  prefill?: { fields: Record<string, string>; title: string; raised_from_id: string; ref: string } | null;
  onCancel: () => void;
  onRaised: (item: RegisterItemRow) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [title, setTitle] = useState(prefill?.title ?? '');
  const [fields, setFields] = useState<Record<string, string>>(prefill?.fields ?? {});
  const [recipients, setRecipients] = useState<ContactRow[]>([]);
  const [missing, setMissing] = useState<string[]>([]);
  // FILES STAGED ON THE FORM. They cannot be uploaded yet - the item they
  // attach to does not exist until Create succeeds - so they are held
  // here and pushed straight afterwards, which is what turns
  // create -> expand -> drop -> tick -> draft back into one pass.
  const [staged, setStaged] = useState<{ file: globalThis.File; email: boolean }[]>([]);
  // WHAT THIS JOB HAS SAID BEFORE. The form used to open blank every
  // time, so the same delivery address was retyped onto every RFQ - and a
  // retyped address is a mistyped one.
  const memory = useQuery({
    queryKey: ['field-memory', projectId, spec.kind],
    queryFn: () => fetchFieldSuggestions(projectId, spec.kind),
    enabled: !!projectId,
    staleTime: 60_000,
  });
  // Applied ONCE, and never over anything already there: a prefill from
  // another register, or something already typed, outranks a default.
  const seeded = useRef(false);
  useEffect(() => {
    const known = memory.data?.fields;
    if (!known || seeded.current) return;
    seeded.current = true;
    setFields((current) => {
      const next = { ...current };
      for (const [label, s] of Object.entries(known)) {
        if (s.default && !String(next[label] ?? '').trim()) next[label] = s.default;
      }
      return next;
    });
  }, [memory.data]);
  const [dragging, setDragging] = useState(false);
  const stageRef = useRef<HTMLInputElement | null>(null);
  const [previewFor, setPreviewFor] = useState<string | null>(null);
  const [prevOff, setPrevOff] = useState(() => localStorage.getItem('ciPrevOff') === '1');
  const topRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    topRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  // 550ms debounce, exactly the original's live-preview cadence.
  const [debounced, setDebounced] = useState({ title: '', fields: {} as Record<string, string> });
  useEffect(() => {
    const h = setTimeout(() => setDebounced({ title, fields }), 550);
    return () => clearTimeout(h);
  }, [title, fields]);

  const previewContact = previewFor ?? (recipients[0] ? String(recipients[0].id) : null);
  const preview = useQuery({
    queryKey: [
      'compose',
      spec.kind,
      debounced.title,
      JSON.stringify(debounced.fields),
      recipients.map((r) => r.id).join(','),
      previewContact,
    ],
    queryFn: () =>
      previewComposeEmail({
        project_id: projectId,
        kind: spec.kind,
        title: debounced.title,
        fields: debounced.fields,
        recipient_contact_ids: recipients.map((r) => String(r.id)),
        contact_id: previewContact,
      }),
    placeholderData: (p) => p,
    enabled: spec.recipient !== 'none',
  });

  const set = (label: string, value: string) => {
    setFields((f) => ({ ...f, [label]: value }));
    setMissing((m) => m.filter((x) => x !== label));
  };

  // THE JOB-NUMBER REFUSAL, FIXABLE WHERE IT HAPPENS. The gate is right to
  // refuse a raise on a job with no job number - but sending the user off
  // to the project settings page to set one, then back here, loses the
  // half-filled form they were standing in. So when THAT refusal comes
  // back (from the live preview or from the Raise itself), the panel grows
  // a job-number field of its own. Saving writes the project's real
  // "Project number / code" through the native endpoint - same field, same
  // server-side validation (normalisation, length, shared-number refusal) -
  // then re-runs whatever was refused. Nothing is bypassed: a bad number
  // is refused again, right here.
  const [jobNo, setJobNo] = useState('');
  const jobNoMut = useMutation({
    mutationFn: () => setProjectJobNumber(projectId, jobNo.trim()),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('ci.jobno_saved', { defaultValue: 'Job number {{n}} saved to the project', n: jobNo.trim() }),
      });
      void queryClient.invalidateQueries({ queryKey: ['compose'] });
      void queryClient.invalidateQueries({ queryKey: ['registers', projectId] });
      // If it was the Raise itself that got refused, run it again now the
      // number is set - the user already said "raise this", and the gate
      // will still have the final word.
      if (mut.isError) {
        mut.reset();
        mut.mutate();
      }
    },
    onError: (e: Error) => {
      addToast({ type: 'error', title: e.message });
    },
  });

  const mut = useMutation({
    mutationFn: () =>
      raiseItem({
        project_id: projectId,
        kind: spec.kind,
        title,
        fields,
        recipient_contact_ids: recipients.map((r) => String(r.id)),
        raised_from_id: prefill?.raised_from_id ?? null,
      }),
    onSuccess: async (item) => {
      addToast({ type: 'success', title: t('ci.raised', { defaultValue: 'Raised {{r}}', r: item.reference }) });
      // The staged files, now that there is something to attach them to.
      // A failure here must NOT read as a failed raise: the item is
      // already on the register, so the toast names the file that did
      // not make it rather than implying the whole thing came apart.
      let latest = item;
      for (const s of staged) {
        try {
          latest = await uploadItemAttachment(item.id, s.file);
          if (!s.email) {
            latest = await setAttachmentEmailFlag(item.id, s.file.name, false);
          }
        } catch (e) {
          addToast({
            type: 'error',
            title: t('ci.attach_failed', {
              defaultValue: '{{f}} did not attach - {{m}}',
              f: s.file.name,
              m: (e as Error).message,
            }),
          });
        }
      }
      setStaged([]);
      void queryClient.invalidateQueries({ queryKey: ['registers', projectId] });
      onRaised(latest);
    },
    onError: (e: Error) => {
      // Name the gaps and mark them, the way the original does.
      const gaps = spec.fields.filter((f) => f.required && !String(fields[f.label] ?? '').trim()).map((f) => f.label);
      setMissing(gaps);
      addToast({ type: 'error', title: e.message });
    },
  });

  // Required first, the rest folded. A form where everything looks
  // equally important is a form where the four fields that actually
  // stop the raise are as hard to find as the ten that do not.
  const required = spec.fields.filter((f) => f.required);
  const optional = spec.fields.filter((f) => !f.required);

  const renderField = (f: KindSpec['fields'][number]) => {
              const isTable = /materials|scope of works|attendees|breakdown/i.test(f.label) && f.type === 'area';
              return (
                <div key={f.label} className={f.type === 'area' ? 'qcell wide' : 'qcell'}>
                  <span className="qlab">
                    {f.label}
                    {f.required && <span className="req">*</span>}
                    {f.is_due && (
                      <span className="badge b-amber">{t('ci.sets_due', { defaultValue: 'sets the due date' })}</span>
                    )}
                    {f.internal && (
                      <span className="badge">{t('ci.card_only', { defaultValue: '🔒 internal — money never leaves the building' })}</span>
                    )}
                  </span>
                  {f.type === 'area' && isTable ? (
                    // The grid, not a textarea. It still hands back
                    // tab-separated text, which is exactly what the email
                    // builder already reads - so nothing downstream changes
                    // and an item raised before this existed still opens.
                    <PasteGrid value={fields[f.label] ?? ''} onChange={(v) => set(f.label, v)} />
                  ) : f.type === 'area' ? (
                    <textarea
                      className={missing.includes(f.label) ? 'miss' : ''}
                      value={fields[f.label] ?? ''}
                      onChange={(e) => set(f.label, e.target.value)}
                    />
                  ) : f.type === 'select' ? (
                    <>
                      <input
                        className={missing.includes(f.label) ? 'miss' : ''}
                        list={`o-${f.label.replace(/\W/g, '')}`}
                        value={fields[f.label] ?? ''}
                        onChange={(e) => set(f.label, e.target.value)}
                      />
                      <datalist id={`o-${f.label.replace(/\W/g, '')}`}>
                        {/* This job's own answers first, then the standing
                            list - what you used last time on this job is a
                            better guess than the top of an alphabet. */}
                        {(memory.data?.fields?.[f.label]?.recent ?? [])
                          .filter((o) => !f.options.includes(o))
                          .map((o) => (
                            <option key={`mem-${o}`} value={o} />
                          ))}
                        {f.options.map((o) => (
                          <option key={o} value={o} />
                        ))}
                      </datalist>
                    </>
                  ) : (
                    <>
                      {/* A datalist, not a locked dropdown: this job's past
                          answers are offered on click and you can still type
                          anything you like over them. A pick-list that
                          refused a new address would be worse than none. */}
                      <input
                        className={missing.includes(f.label) ? 'miss' : ''}
                        type={f.type === 'date' ? 'date' : 'text'}
                        inputMode={f.type === 'money' ? 'decimal' : undefined}
                        list={
                          (memory.data?.fields?.[f.label]?.recent?.length ?? 0) > 0
                            ? `mem-${f.label.replace(/\W/g, '')}`
                            : undefined
                        }
                        value={fields[f.label] ?? ''}
                        onChange={(e) => set(f.label, e.target.value)}
                      />
                      {(memory.data?.fields?.[f.label]?.recent?.length ?? 0) > 0 && (
                        <datalist id={`mem-${f.label.replace(/\W/g, '')}`}>
                          {(memory.data?.fields?.[f.label]?.recent ?? []).map((o) => (
                            <option key={o} value={o} />
                          ))}
                        </datalist>
                      )}
                    </>
                  )}
                </div>
              );
  };
  const showPreview = spec.recipient !== 'none' && !prevOff;
  const rfqRule = spec.kind === 'rfq' ? Number(String(fields['Estimated value $'] ?? '0').replace(/[^\d.]/g, '')) : 0;
  // Which refusal is on screen, and is it the one this panel can fix here?
  // The wording is the backend's own (job_number_for in service.py); if it
  // ever drifts the inline editor quietly disappears and the message still
  // shows - degraded, never wrong.
  const previewMsg = preview.isError ? ((preview.error as { message?: string } | null)?.message ?? '') : '';
  const raiseMsg = mut.isError ? ((mut.error as Error | null)?.message ?? '') : '';
  const jobNoAsk = /job number|project number/i.test(`${previewMsg} ${raiseMsg}`);

  return (
    <div ref={topRef} className="pcard" style={{ borderLeftColor: 'var(--amber)' }}>
      <div className={`qformcol ${showPreview ? 'withprev' : ''}`}>
        <h3 className="ph">
          {prefill
            ? t('ci.raise_from', { defaultValue: 'Raise a {{k}} from {{r}}', k: spec.label, r: prefill.ref })
            : t('ci.raise_new', { defaultValue: 'Raise a new {{k}}', k: spec.label })}
          {preview.data && <span className="badge b-amber">{preview.data.peeked_reference}</span>}
        </h3>

        {/* THE PREVIEW'S REFUSAL, SAID OUT LOUD. It used to be swallowed:
            the panel simply went blank and you found out what was wrong
            only when you pressed Raise. The one that matters is a job with
            no job number - references carry it, so nothing can be minted
            until it is set, and the message says exactly that. */}
        {(preview.isError || jobNoAsk) && (
          <div
            className="pcard"
            style={{ borderLeftColor: 'var(--red)', padding: 10, margin: '2px 0 10px' }}
          >
            <b style={{ color: 'var(--red)' }}>
              {t('ci.preview_blocked', { defaultValue: 'This cannot be raised yet' })}
            </b>
            <div style={{ marginTop: 3, fontSize: 12.5 }}>
              {previewMsg ||
                raiseMsg ||
                t('ci.preview_blocked_generic', {
                  defaultValue: 'The preview could not be built.',
                })}
            </div>
            {/* The fix, right here: type the job number, it lands on the
                project as "Project number / code", and the refused thing
                runs again. Same field, same server-side rails as setting it
                on the project page - just without losing this form. */}
            {jobNoAsk && (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8, flexWrap: 'wrap' }}>
                <span className="qlab" style={{ margin: 0 }}>
                  {t('ci.jobno_label', { defaultValue: 'Job number' })}
                </span>
                <input
                  value={jobNo}
                  onChange={(e) => setJobNo(e.target.value)}
                  placeholder="25406"
                  style={{ width: 130 }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && jobNo.trim() && !jobNoMut.isPending) {
                      e.preventDefault();
                      jobNoMut.mutate();
                    }
                  }}
                />
                <button
                  type="button"
                  className="b pri"
                  disabled={!jobNo.trim() || jobNoMut.isPending}
                  onClick={() => jobNoMut.mutate()}
                >
                  {jobNoMut.isPending
                    ? t('ci.jobno_saving', { defaultValue: 'Saving…' })
                    : t('ci.jobno_save', { defaultValue: 'Set it on the project + continue' })}
                </button>
              </div>
            )}
          </div>
        )}

        <RecipientBlock
          spec={spec}
          kind={spec.kind}
          projectId={projectId}
          selected={recipients}
          onChange={setRecipients}
        />

        {/* ATTACHMENTS, ON THE FORM. Until now the only drop zone was on
            the expanded row of an item that already existed, so a drawing
            took create -> expand -> drop -> tick -> draft. Each file gets
            the per-file "email it" tick the original had: some files
            belong on the record without riding out to the supplier. */}
        <div className="qtorow">
          <span className="qlab" style={{ color: 'var(--amber)' }}>
            {t('ci.attachments', { defaultValue: 'Attachments' })}
            <span className="v" style={{ fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>
              {t('ci.attachments_note', {
                defaultValue: '— drawings and specs; untick one to keep it on the record without emailing it',
              })}
            </span>
          </span>
          <div
            className={`qdrop ${dragging ? 'on' : ''}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              // preventDefault FIRST: a file dropped slightly off target
              // navigates the browser to it and the whole form is gone.
              e.preventDefault();
              setDragging(false);
              const files = [...(e.dataTransfer?.files ?? [])];
              if (files.length) setStaged((s) => [...s, ...files.map((f) => ({ file: f, email: true }))]);
            }}
            onClick={() => stageRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') stageRef.current?.click();
            }}
          >
            {t('ci.drop_files', { defaultValue: 'drop files here, or click to choose — several at once is fine' })}
          </div>
          <input
            ref={stageRef}
            type="file"
            multiple
            style={{ display: 'none' }}
            onChange={(e) => {
              const files = [...(e.target.files ?? [])];
              if (files.length) setStaged((s) => [...s, ...files.map((f) => ({ file: f, email: true }))]);
              e.currentTarget.value = '';
            }}
          />
          {staged.length > 0 && (
            <table className="t" style={{ marginTop: 6 }}>
              <tbody>
                {staged.map((s, i) => (
                  <tr key={`${s.file.name}:${i}`}>
                    <td>{s.file.name}</td>
                    <td className="v">{Math.max(1, Math.round(s.file.size / 1024))} KB</td>
                    <td>
                      <label className="v" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                        <input
                          type="checkbox"
                          checked={s.email}
                          onChange={(e) =>
                            setStaged((list) =>
                              list.map((x, j) => (j === i ? { ...x, email: e.target.checked } : x)),
                            )
                          }
                        />
                        {t('ci.attach_email_it', { defaultValue: 'email it' })}
                      </label>
                    </td>
                    <td style={{ width: 1 }}>
                      <button
                        type="button"
                        className="b mini"
                        onClick={() => setStaged((list) => list.filter((_, j) => j !== i))}
                        aria-label={t('ci.attach_remove', { defaultValue: 'Remove {{f}}', f: s.file.name })}
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="qgrid">
          <div className="qcell wide">
            <span className="qlab">
              {t('ci.subject', { defaultValue: 'Short description' })}
              <span className="req">*</span>
            </span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={spec.label} />
          </div>

          {required.map((f) => renderField(f))}
        </div>

        {/* THE REST, FOLDED. The RFQ form is fourteen fields tall and
            four of them are required; as one wall the Create button
            sits off the bottom of a laptop and the required fields are
            no easier to pick out than the optional ones. It opens by
            itself when anything in here is already filled - a prefill
            from another register, or a draft being come back to. */}
        {optional.length > 0 && (
          <Fold
            id="raise-more"
            title={t('ci.fold_more', { defaultValue: 'the rest of the detail' })}
            count={optional.filter((f) => String(fields[f.label] ?? '').trim()).length || undefined}
            defaultOpen={false}
            openWhen={optional.some((f) => String(fields[f.label] ?? '').trim() !== '')}
          >
            <div className="qgrid">{optional.map((f) => renderField(f))}</div>
          </Fold>
        )}

        {spec.kind === 'rfq' && (
          <div
            className="row"
            style={{
              marginTop: 6,
              padding: '7px 10px',
              background: 'var(--panel2)',
              borderLeft: '3px solid var(--amber)',
              borderRadius: 8,
            }}
          >
            {rfqRule > 7500 ? (
              <span className="badge b-amber">⛔ {t('ci.three_quotes', { defaultValue: '3 quotes required' })}</span>
            ) : rfqRule > 3000 ? (
              <span className="badge b-amber">⛔ {t('ci.two_quotes', { defaultValue: '2 quotes required' })}</span>
            ) : (
              <span className="badge b-green">{t('ci.one_quote', { defaultValue: '1 quote is enough' })}</span>
            )}
            <span className="v">
              {t('ci.rule_note', {
                defaultValue:
                  'Set by the estimated value. The compare gate and the award both hold you to it — a question is never a quote.',
              })}
            </span>
          </div>
        )}

        <div className="row" style={{ marginTop: 12 }}>
          <button type="button" className="b pri" onClick={() => mut.mutate()} disabled={mut.isPending}>
            {mut.isPending
              ? t('ci.raising', { defaultValue: 'Raising…' })
              : spec.recipient === 'none'
                ? t('ci.create', { defaultValue: 'Create the record' })
                : t('ci.create_preview', { defaultValue: 'Create + preview the emails' })}
          </button>
          <button type="button" className="b" onClick={onCancel}>
            {t('ci.cancel', { defaultValue: 'Cancel' })}
          </button>
          <span className="v" style={{ marginLeft: 'auto' }}>
            {t('ci.flow_note', { defaultValue: '{{n}} workflow steps, gates included', n: spec.flow.length })}
          </span>
        </div>
      </div>

      {/* Live preview — pinned, so it never moves while you type. */}
      {showPreview && (
        <div className="qprevcol">
          <div className="qprevbar">
            📧 {t('ci.live_preview', { defaultValue: 'live preview' })}
            <span className="sub v" style={{ fontWeight: 400, letterSpacing: 0, textTransform: 'none' }}>
              {preview.data?.contact_name || t('ci.nobody_yet', { defaultValue: 'nobody picked yet' })}
            </span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
              <button type="button" className="b mini" onClick={() => void preview.refetch()} title="refresh">
                ↻
              </button>
              <button
                type="button"
                className="b mini"
                onClick={() => {
                  setPrevOff(true);
                  localStorage.setItem('ciPrevOff', '1');
                }}
                title="hide"
              >
                ✕
              </button>
            </span>
          </div>
          {recipients.length > 1 && (
            <div className="row" style={{ gap: 4, padding: '0 2px 6px' }}>
              {recipients.map((c) => (
                <button
                  key={String(c.id)}
                  type="button"
                  className={`b mini ${previewContact === String(c.id) ? 'on' : ''}`}
                  onClick={() => setPreviewFor(String(c.id))}
                >
                  {contactName(c).slice(0, 22)}
                </button>
              ))}
            </div>
          )}
          <div className="qmailhdr">
            <div>
              <span className="k">To</span>
              {preview.data?.to.join('; ') || '—'}
            </div>
            <div>
              <span className="k">Cc</span>
              {preview.data?.cc.join('; ') || '—'}
            </div>
            <div>
              <span className="k">Subject</span>
              <b>{preview.data?.subject || '…'}</b>
            </div>
          </div>
          <iframe title="live-preview" className="qlive" srcDoc={preview.data?.html ?? ''} />
        </div>
      )}
      {spec.recipient !== 'none' && prevOff && (
        <button
          type="button"
          className="qlivetab"
          onClick={() => {
            setPrevOff(false);
            localStorage.removeItem('ciPrevOff');
          }}
        >
          📧 {t('ci.preview', { defaultValue: 'preview' })}
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Workflow steps — numbered, current highlighted, gates and routes coloured
// ---------------------------------------------------------------------------

function Steps({
  item,
  spec,
  projectId,
  onRaiseFrom,
  onConfigure,
}: {
  item: RegisterItemRow;
  spec: KindSpec | undefined;
  projectId: string;
  onRaiseFrom: (kind: Kind, itemId: string) => void;
  /** The expanded row's configureWorkflow() - one flow, two doors. */
  onConfigure: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const menu = useMenu();
  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ['registers', projectId] });

  // A withdrawn item's workflow is history, not a to-do list: it still
  // renders in full, but nothing on it can be ticked, routed or added to.
  const wd = isWithdrawn(item);
  const wdTitle = withdrawnTitle(item, t);
  const currentPos = item.steps.find((s) => s.state === 'open')?.position ?? Infinity;

  const run = async (fn: () => Promise<unknown>, step?: StepRow) => {
    try {
      await fn();
      invalidate();
    } catch (e) {
      let detail = errorDetail(e);
      let msg = detail?.error ?? (e as Error).message;
      // KEEP ASKING WHILE THE REASON IS REFUSED. The server checks the gate
      // FIRST and only then weighs the reason, so a non-answer ("x", "n/a")
      // comes back as another blocked gate. Firing once and giving up threw
      // that second refusal away unhandled, and the tick silently did nothing.
      while (detail?.can_force && step) {
        // qAsk, never prompt(): this browser blocks prompt() outright and
        // the refusal would vanish silently.
        const answers = await qAsk({
          title: t('ci.gate_title', { defaultValue: 'Pass the gate anyway?' }),
          note: msg,
          fields: [
            {
              label: t('ci.gate_reason', { defaultValue: 'Reason — it goes on the record' }),
              placeholder: t('ci.gate_ph', { defaultValue: 'e.g. two suppliers declined in writing' }),
              multiline: true,
            },
          ],
          okLabel: t('ci.gate_ok', { defaultValue: 'Pass it, with the reason' }),
          danger: true,
        });
        if (!answers?.[0]?.trim()) return;
        try {
          await completeStep(step.id, answers[0].trim());
          invalidate();
          return;
        } catch (again) {
          detail = errorDetail(again);
          msg = detail?.error ?? (again as Error).message;
          if (!detail?.can_force) break;
        }
      }
      addToast({ type: 'error', title: msg });
    }
  };

  // Where an added step lands: AFTER THE STEP YOU ARE STANDING ON, not
  // after the last finished one. Sending no position put every added
  // action BEFORE the current step - the one place it never belongs.
  const afterCurrent = () => item.steps.find((s) => s.state === 'open')?.position;

  const addFromLibrary = (a: KindSpec['actions'][number], afterPos: number | undefined) =>
    run(() =>
      addStep(
        item.id,
        a.name,
        a.t === 'gate' ? 'gate' : a.t === 'route' ? 'route' : 'step',
        afterPos,
        // A decision brings its branches from the library - one with no
        // paths renders a fork whose picker is empty and which nothing can
        // ever get past. The server refuses that too.
        a.t === 'route' ? ((a.branches ?? {}) as Record<string, string[]>) : undefined,
      ),
    );

  // "Type your own…": the name first, then what kind of thing it is.
  const typeOwn = async (afterPos: number | undefined, at: { x: number; y: number }) => {
    const answers = await qAsk({
      title: t('ci.own_step_title', { defaultValue: 'Add a step of your own' }),
      note: t('ci.own_step_note', {
        defaultValue: 'Name it the way it should read on the workflow. A decision also needs its paths.',
      }),
      fields: [
        {
          label: t('ci.own_step_name', { defaultValue: 'Step' }),
          placeholder: t('ci.own_step_ph', { defaultValue: 'e.g. Confirm the delivery date with the supplier' }),
        },
        {
          label: t('ci.own_step_paths', { defaultValue: 'Paths — decisions only, comma-separated' }),
          placeholder: t('ci.own_step_paths_ph', { defaultValue: 'Approved, Rejected' }),
        },
      ],
      okLabel: t('ci.own_step_ok', { defaultValue: 'Next — what kind of step?' }),
    });
    const name = answers?.[0]?.trim();
    if (!name) return;
    const paths = (answers?.[1] ?? '')
      .split(',')
      .map((p) => p.trim())
      .filter(Boolean);
    menu.openAt(
      at.x,
      at.y,
      [
        {
          label: t('ci.own_kind_step', { defaultValue: 'A step' }),
          color: STEP_C,
          note: t('ci.own_kind_step_note', { defaultValue: 'somebody does it' }),
          onClick: () => void run(() => addStep(item.id, name, 'step', afterPos)),
        },
        {
          label: t('ci.own_kind_gate', { defaultValue: '⛔ A gate' }),
          color: GATE_C,
          note: t('ci.own_kind_gate_note', { defaultValue: 'a hold point' }),
          onClick: () => void run(() => addStep(item.id, name, 'gate', afterPos)),
        },
        {
          label: t('ci.own_kind_route', { defaultValue: '🔀 A decision' }),
          color: ROUTE_C,
          note: paths.length ? paths.join(' / ') : t('ci.own_kind_route_none', { defaultValue: 'needs paths' }),
          disabled: paths.length === 0,
          onClick: () =>
            void run(() =>
              addStep(item.id, name, 'route', afterPos, Object.fromEntries(paths.map((p) => [p, [] as string[]]))),
            ),
        },
      ],
      { head: t('ci.own_kind_head', { defaultValue: 'What kind of step is "{{n}}"?', n: name }) },
    );
  };

  // The library, grouped: steps, then gates, then decisions. Long enough
  // to earn a filter box.
  const openAddMenu = (at: { x: number; y: number }, afterPos: number | undefined) => {
    const acts = spec?.actions ?? [];
    const entry = (a: KindSpec['actions'][number]): MenuItem => ({
      label: a.name,
      note: a.owner || undefined,
      color: a.t === 'gate' ? GATE_C : a.t === 'route' ? ROUTE_C : STEP_C,
      onClick: () => void addFromLibrary(a, afterPos),
    });
    const noop = () => undefined;
    const items: (MenuItem | null)[] = [];
    const steps = acts.filter((a) => a.t !== 'gate' && a.t !== 'route');
    const gates = acts.filter((a) => a.t === 'gate');
    const routes = acts.filter((a) => a.t === 'route');
    if (steps.length) {
      items.push({ label: t('ci.lib_steps', { defaultValue: 'Steps' }), heading: true, onClick: noop });
      steps.forEach((a) => items.push(entry(a)));
    }
    if (gates.length) {
      items.push(null, { label: t('ci.lib_gates', { defaultValue: '⛔ Gates' }), heading: true, onClick: noop });
      gates.forEach((a) => items.push(entry(a)));
    }
    if (routes.length) {
      items.push(null, { label: t('ci.lib_routes', { defaultValue: '🔀 Decisions' }), heading: true, onClick: noop });
      routes.forEach((a) => items.push(entry(a)));
    }
    items.push(null, {
      label: t('ci.lib_own', { defaultValue: 'Type your own…' }),
      note: t('ci.lib_own_note', { defaultValue: 'name it' }),
      sticky: true,
      onClick: () => void typeOwn(afterPos, at),
    });
    menu.openAt(at.x, at.y, items, {
      head:
        afterPos === undefined
          ? t('ci.add_step_head', { defaultValue: 'Add a step' })
          : t('ci.add_step_after', { defaultValue: 'Add a step after {{n}}', n: afterPos + 1 }),
      search: t('ci.menu_filter', { defaultValue: 'Type to filter…' }),
    });
  };

  // Every step row has a menu: what the inline buttons offer, plus insert,
  // configure and copy - so nothing depends on which buttons are showing.
  const stepMenu = (e: ReactMouseEvent, s: StepRow, curNow: boolean, doneNow: boolean) => {
    const at = { x: e.clientX, y: e.clientY };
    const items: (MenuItem | null)[] = [];
    // Withdrawn: no verbs at all, only the read-only entries at the bottom.
    const cur = curNow && !wd;
    const done = doneNow && !wd;
    if (cur && s.type !== 'route') {
      items.push({
        label:
          s.type === 'gate'
            ? t('ci.pass_gate_menu', { defaultValue: 'Pass the gate' })
            : t('ci.mark_done_menu', { defaultValue: 'Mark done' }),
        color: s.type === 'gate' ? GATE_C : '#2e9e5b',
        onClick: () => void run(() => completeStep(s.id), s),
      });
    }
    if (cur && s.type === 'route') {
      s.branches.forEach((b) =>
        items.push({
          label: t('ci.take_route', { defaultValue: 'Take route → {{b}}', b }),
          color: ROUTE_C,
          onClick: () => void run(() => takeRoute(s.id, b)),
        }),
      );
    }
    if (cur && s.type !== 'gate') {
      items.push({
        label: t('ci.not_required_menu', { defaultValue: '⊘ Not required' }),
        onClick: () => void run(() => notRequiredStep(s.id)),
      });
    }
    if (cur && s.raises_kind && !s.raised_reference) {
      const k = s.raises_kind;
      items.push({
        label: t('ci.raise_the_menu', { defaultValue: '＋ Raise the {{k}}', k: KIND_LABEL[k] ?? k }),
        color: KIND_COLOR[k],
        onClick: () => onRaiseFrom(k, item.id),
      });
    }
    if (done && s.state === 'done' && s.position === currentPos - 1) {
      items.push({
        label:
          s.type === 'route'
            ? t('ci.undo_decision', { defaultValue: 'undo the decision' })
            : t('ci.undo_menu', { defaultValue: 'Undo' }),
        onClick: () => void run(() => uncompleteStep(s.id)),
      });
    }
    if (items.length) items.push(null);
    items.push(
      {
        label: t('ci.insert_after', { defaultValue: 'Insert a step after this one…' }),
        note: t('ci.insert_after_note', { defaultValue: 'after {{n}}', n: s.position + 1 }),
        onClick: () => openAddMenu(at, s.position),
      },
      { label: t('ci.configure_menu', { defaultValue: 'Configure the workflow…' }), onClick: onConfigure },
      { label: t('ci.copy_step_name', { defaultValue: 'Copy step name' }), onClick: () => copyText(s.name) },
    );
    menu.openFromEvent(e, items, { head: s.name });
  };

  return (
    <div style={{ padding: '10px 14px 4px' }}>
      {item.steps.map((s) => {
        const done = s.state !== 'open';
        const cur = s.state === 'open' && s.position === currentPos && !wd;
        const locked = s.state === 'open' && s.position > currentPos;
        const cls = [
          'li',
          done ? 'done' : '',
          cur ? 'cur' : '',
          locked ? 'lock' : '',
          s.type === 'gate' ? 'gateli' : '',
          s.type === 'route' ? 'routeli' : '',
        ]
          .filter(Boolean)
          .join(' ');
        return (
          <div
            key={s.id}
            className={cls}
            onContextMenu={(e) => stepMenu(e, s, cur, done)}
            title={t('ci.rightclick', { defaultValue: 'right-click for actions' })}
          >
            <span className="stepno">{s.position + 1}</span>
            <span style={{ width: 16 }}>{done ? (s.state === 'not_required' ? '⊘' : '✓') : cur ? '▶' : '🔒'}</span>
            <span className="nm">
              <span style={done ? { textDecoration: 'line-through' } : undefined}>{s.name}</span>
              {s.chosen_branch && <b style={{ color: 'var(--navy)' }}> → {s.chosen_branch}</b>}
              {s.raised_reference && <b style={{ color: 'var(--navy)' }}> → {s.raised_reference}</b>}
              {s.type === 'gate' && <span className="gatechip" style={{ marginLeft: 6 }}>gate{s.owner ? ` · ${s.owner}` : ''}</span>}
              {s.type === 'route' && <span className="routechip" style={{ marginLeft: 6 }}>decision</span>}
              {s.override_reason && (
                // A retired hold point carries a reason too, and it says the
                // opposite thing: the gate came OFF this workflow, it was not
                // passed below its rule.
                <span
                  className={s.state === 'not_required' ? 'badge' : 'badge b-red'}
                  style={{ marginLeft: 6 }}
                  title={s.override_reason}
                >
                  {s.state === 'not_required'
                    ? t('ci.gate_retired', { defaultValue: 'off this workflow' })
                    : t('ci.gate_forced', { defaultValue: 'passed below the rule' })}
                </span>
              )}
              {s.completed_at && (
                <span className="badge" style={{ marginLeft: 6 }}>
                  {s.completed_at.slice(8, 10)}/{s.completed_at.slice(5, 7)}
                </span>
              )}
            </span>

            <span className="qsact">
              {cur && s.type === 'route' &&
                s.branches.map((b) => (
                  <button
                    key={b}
                    type="button"
                    className="b mini"
                    disabled={wd}
                    title={wdTitle}
                    onClick={() => void run(() => takeRoute(s.id, b))}
                  >
                    {b}
                  </button>
                ))}
              {cur && s.type !== 'route' && (
                <>
                  <button
                    type="button"
                    className="b pri mini"
                    disabled={wd}
                    title={wdTitle}
                    onClick={() => void run(() => completeStep(s.id), s)}
                  >
                    {s.type === 'gate'
                      ? t('ci.pass_gate', { defaultValue: 'pass the gate' })
                      : t('ci.mark_done', { defaultValue: 'mark done' })}
                  </button>
                  {s.type !== 'gate' && (
                    <button
                      type="button"
                      className="b mini"
                      disabled={wd}
                      title={wdTitle}
                      onClick={() => void run(() => notRequiredStep(s.id))}
                    >
                      ⊘ {t('ci.not_required', { defaultValue: 'not required' })}
                    </button>
                  )}
                </>
              )}
              {cur && s.raises_kind && !s.raised_reference && (
                <button
                  type="button"
                  className="b mini"
                  disabled={wd}
                  title={wdTitle}
                  onClick={() => onRaiseFrom(s.raises_kind as Kind, item.id)}
                >
                  ＋ {t('ci.raise_the', { defaultValue: 'raise the {{k}}', k: s.raises_kind })}
                </button>
              )}
              {done && s.state === 'done' && s.position === currentPos - 1 && (
                // Routes included: one mis-click on a four-way fork used to
                // have no fix inside the app. Undoing it strips the wrong
                // branch's still-open steps and puts the options back.
                <button
                  type="button"
                  className="b mini"
                  disabled={wd}
                  title={wdTitle}
                  onClick={() => void run(() => uncompleteStep(s.id))}
                >
                  {s.type === 'route'
                    ? t('ci.undo_decision', { defaultValue: 'undo the decision' })
                    : t('ci.undo', { defaultValue: 'undo' })}
                </button>
              )}
            </span>
          </div>
        );
      })}

      <div className="row" style={{ marginTop: 8 }}>
        {/* The library as a dropdown - steps, gates and decisions grouped,
            a filter box, and "Type your own…" at the bottom. Decisions are
            offered too: stripped from the library, a job that hit a second
            fork could not be modelled at all. */}
        <button
          type="button"
          className="pickbtn"
          style={{ maxWidth: 320 }}
          aria-haspopup="menu"
          disabled={wd}
          title={wdTitle}
          onClick={(e) => {
            e.stopPropagation();
            openAddMenu(menuAt(e.currentTarget), afterCurrent());
          }}
        >
          <span className="pname ghost">{t('ci.add_step_btn', { defaultValue: 'Add a step...' })}</span>
        </button>
        <span className="v">
          {t('ci.add_step_hint', { defaultValue: 'lands after the step you are on · right-click a step for more' })}
        </span>
      </div>
      {menu.element}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The expanded row: details, evidence, workflow, thread
// ---------------------------------------------------------------------------

function ExpandedRow({
  item,
  spec,
  projectId,
  onRaiseFrom,
  onEmail,
  focusSection,
  onOpenLinked,
}: {
  item: RegisterItemRow;
  spec: KindSpec | undefined;
  projectId: string;
  onRaiseFrom: (kind: Kind, itemId: string) => void;
  onEmail: (item: RegisterItemRow) => void;
  /** Which fold the click that opened this row was really about, and a
   *  nonce so a repeat click re-opens what was folded shut since. */
  focusSection?: {
    section: 'details' | 'evidence' | 'workflow' | 'thread' | 'edit' | 'configure' | 'logsent';
    n: number;
  } | null;
  /** Open a linked register item - the workspace derives its kind tab
   *  from the reference prefix and expands it. */
  onOpenLinked?: (itemId: string, reference: string) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [hot, setHot] = useState(false);
  // EDITING A RAISED ITEM. updateItem has been typed and live all along
  // and nothing ever called it, so a typo'd quantity, due date or
  // delivery address was permanent - the only fix was to raise the whole
  // thing again under a new reference.
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [draftTitle, setDraftTitle] = useState('');
  const [logSent, setLogSent] = useState<{ item: RegisterItemRow; rows: LogSentRow[] } | null>(null);
  // A thread entry being read - the full reader, reply and forward
  // included, over this row.
  const [readingMsg, setReadingMsg] = useState<{ id: string; mode?: ReplyMode } | null>(null);
  // The record picker - "Link to an existing record" - over this row.
  const [picking, setPicking] = useState(false);
  const menu = useMenu();
  const projectName = useProjectContextStore((s) => s.activeProjectName);
  const fileRef = useRef<HTMLInputElement>(null);
  const thread = useQuery<ThreadEntry[]>({
    queryKey: ['thread', item.id],
    queryFn: () => fetchItemThread(item.id),
  });

  const flagMut = useMutation({
    mutationFn: (v: { filename: string; email: boolean }) =>
      setAttachmentEmailFlag(item.id, v.filename, v.email),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['registers', projectId] }),
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const linkMut = useMutation({
    mutationFn: (v: { type: ItemLink['type']; value: string }) => addItemLink(item.id, v.type, v.value.trim()),
    onSuccess: (_r, v) => {
      addToast({ type: 'success', title: t('ci.pick_linked', { defaultValue: 'Linked to {{r}}', r: v.value.trim() }) });
      void queryClient.invalidateQueries({ queryKey: ['registers', projectId] });
    },
    // The refusal names the problem ("no item carries REG-RFI-000009") -
    // show it rather than a generic failure.
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  // Cost centre, deliverable, URL: a name is all the link needs.
  const askLink = async (type: Exclude<ItemLink['type'], 'item'>) => {
    const labels: Record<Exclude<ItemLink['type'], 'item'>, { title: string; label: string; ph: string }> = {
      cost_centre: {
        title: t('ci.link_cc_title', { defaultValue: 'Link to a cost centre' }),
        label: t('ci.link_cc', { defaultValue: 'Cost centre' }),
        ph: t('ci.link_cc_ph', { defaultValue: 'e.g. CC-104 Switchboards' }),
      },
      deliverable: {
        title: t('ci.link_deliv_title', { defaultValue: 'Link to a deliverable' }),
        label: t('ci.link_deliv', { defaultValue: 'Deliverable' }),
        ph: t('ci.link_deliv_ph', { defaultValue: 'e.g. Level 2 lighting layout' }),
      },
      url: {
        title: t('ci.link_url_title', { defaultValue: 'Link to a folder or web page' }),
        label: t('ci.link_url', { defaultValue: 'Link / folder (URL)' }),
        ph: 'https://…',
      },
    };
    const l = labels[type];
    const answers = await qAsk({
      title: l.title,
      fields: [{ label: l.label, placeholder: l.ph }],
      okLabel: t('ci.link_add', { defaultValue: 'Link it' }),
    });
    const value = answers?.[0]?.trim();
    if (!value) return;
    linkMut.mutate({ type, value });
  };

  // "Add link..." - the one dropdown behind every kind of link, and the
  // door to raising a new item from this one.
  const openLinkMenu = (el: HTMLElement) => {
    const at = menuAt(el);
    menu.openAt(
      at.x,
      at.y,
      [
        {
          label: t('ci.link_item', { defaultValue: 'Register item' }),
          note: t('ci.link_item_note', { defaultValue: 'pick one' }),
          color: KIND_COLOR.rfi,
          onClick: () => setPicking(true),
        },
        { label: t('ci.link_cc', { defaultValue: 'Cost centre' }), color: '#8a5406', onClick: () => void askLink('cost_centre') },
        { label: t('ci.link_deliv', { defaultValue: 'Deliverable' }), color: '#0a6f66', onClick: () => void askLink('deliverable') },
        { label: t('ci.link_url', { defaultValue: 'Link / folder (URL)' }), color: '#06657f', onClick: () => void askLink('url') },
        null,
        {
          label: t('ci.link_raise', { defaultValue: 'Raise a new item from this one' }),
          note: t('ci.link_raise_note', { defaultValue: 'prefilled, linked both ways' }),
          onClick: () =>
            menu.openAt(
              at.x,
              at.y,
              KIND_ORDER.map((k) => ({
                label: KIND_LABEL[k],
                color: KIND_COLOR[k],
                note: spec?.kind === k ? t('ci.link_same_kind', { defaultValue: 'same register' }) : undefined,
                onClick: () => onRaiseFrom(k, item.id),
              })),
              { head: t('ci.link_raise_head', { defaultValue: 'Raise from {{r}}', r: item.reference }) },
            ),
        },
      ],
      { head: t('ci.link_to', { defaultValue: 'Link to' }) },
    );
  };

  const linkTag = (l: ItemLink) =>
    l.type === 'item' ? 'ITEM' : l.type === 'cost_centre' ? 'CC' : l.type === 'deliverable' ? 'DELIV' : 'URL';
  const linkOpens = (l: ItemLink) => (l.type === 'item' && !!l.target_id) || l.type === 'url';
  const openLink = (l: ItemLink) => {
    if (l.type === 'item' && l.target_id) onOpenLinked?.(l.target_id, l.reference ?? '');
    else if (l.type === 'url') window.open(l.label, '_blank', 'noopener');
  };
  const linkMenu = (e: ReactMouseEvent, l: ItemLink, idx: number) =>
    menu.openFromEvent(
      e,
      [
        linkOpens(l)
          ? {
              label:
                l.type === 'url'
                  ? t('ci.link_open_url', { defaultValue: 'Open the link' })
                  : t('ci.link_open', { defaultValue: 'Open {{r}}', r: l.reference ?? l.label }),
              onClick: () => openLink(l),
            }
          : null,
        {
          label: t('ci.link_copy_ref', { defaultValue: 'Copy reference' }),
          note: l.reference ?? undefined,
          onClick: () => copyText(l.reference ?? l.label),
        },
        null,
        { label: t('ci.link_unlink', { defaultValue: 'Unlink' }), danger: true, onClick: () => unlinkMut.mutate(idx) },
      ],
      { head: `${linkTag(l)} · ${l.label}` },
    );

  // Attachments: open, download, and whether it rides the email.
  const attachmentMenu = (e: ReactMouseEvent, a: { filename: string; email?: boolean }) =>
    menu.openFromEvent(
      e,
      [
        { label: t('ci.att_open', { defaultValue: 'Open' }), onClick: () => window.open(documentUrl(item.id, a.filename), '_blank') },
        {
          label: t('ci.att_download', { defaultValue: 'Download' }),
          onClick: () => {
            const link = document.createElement('a');
            link.href = documentUrl(item.id, a.filename);
            link.download = a.filename;
            link.rel = 'noreferrer';
            document.body.appendChild(link);
            link.click();
            link.remove();
          },
        },
        null,
        {
          label:
            a.email !== false
              ? t('ci.att_email_off', { defaultValue: 'Keep it off the email' })
              : t('ci.att_email_on', { defaultValue: 'Email it with the item' }),
          color: a.email !== false ? '#2e9e5b' : undefined,
          onClick: () => flagMut.mutate({ filename: a.filename, email: a.email === false }),
        },
        { label: t('ci.cm_copy_filename', { defaultValue: 'Copy the filename' }), onClick: () => copyText(a.filename) },
      ],
      { head: a.filename },
    );

  // Thread entries: the reader's own verbs, only where a filed message
  // exists to answer - a logged send has no body to reply to.
  const threadMenu = (e: ReactMouseEvent, entry: ThreadEntry) => {
    const readable = entry.type === 'correspondence' && !!entry.id;
    const id = entry.id as string;
    menu.openFromEvent(
      e,
      [
        readable ? { label: t('ci.thr_open', { defaultValue: 'Open' }), onClick: () => setReadingMsg({ id }) } : null,
        readable ? { label: t('ci.rd_reply', { defaultValue: 'Reply' }), onClick: () => setReadingMsg({ id, mode: 'reply' }) } : null,
        readable
          ? { label: t('ci.rd_reply_all', { defaultValue: 'Reply all' }), onClick: () => setReadingMsg({ id, mode: 'reply_all' }) }
          : null,
        readable ? { label: t('ci.rd_forward', { defaultValue: 'Forward' }), onClick: () => setReadingMsg({ id, mode: 'forward' }) } : null,
        ...(readable ? [null] : []),
        entry.email_ref || entry.reference
          ? {
              label: t('ci.cm_copy_ref', { defaultValue: 'Copy the mail number' }),
              note: String(entry.email_ref || entry.reference),
              onClick: () => copyText(String(entry.email_ref || entry.reference)),
            }
          : null,
        { label: t('ci.cm_copy_subject', { defaultValue: 'Copy the subject' }), onClick: () => copyText(entry.subject || '') },
      ],
      { head: entry.email_ref || entry.reference || entry.subject || (entry.who ?? '') },
    );
  };
  const unlinkMut = useMutation({
    mutationFn: (index: number) => removeItemLink(item.id, index),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['registers', projectId] }),
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const saveMut = useMutation({
    mutationFn: () => updateItem(item.id, { title: draftTitle, fields: draft }),
    onSuccess: () => {
      addToast({ type: 'success', title: t('ci.saved_item', { defaultValue: 'Saved' }) });
      setEditing(false);
      void queryClient.invalidateQueries({ queryKey: ['registers', projectId] });
    },
    // The server refuses a downward correction to an ISSUED package's
    // value, because the quote gate tiers off that figure. Show the
    // refusal rather than swallowing it - the edit did not happen.
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  useEffect(() => {
    if (focusSection?.section === 'edit') startEditing();
    // The register row's menu opens the row and then asks for the flow
    // that lives here - configure, or log as sent.
    if (focusSection?.section === 'configure') void configureWorkflow();
    if (focusSection?.section === 'logsent') void openLogSent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusSection?.n]);

  // The item already knows who it is addressed to, so the dialog shows
  // that list ticked with today's date in - rather than asking the user
  // to retype both, once per supplier.
  const openLogSent = async () => {
    let known: ContactRow[] = [];
    try {
      known = await fetchContactsByIds(item.recipient_contact_ids ?? []);
    } catch {
      known = [];
    }
    setLogSent({ item, rows: logSentRows(item, known) });
  };

  // ONE flow behind the toolbar button, the step menu and the row menu.
  // The structured editor: history locked, to-do rows reorderable.
  const configureWorkflow = async () => {
    const saved = await openWorkflowEditor({
      item,
      spec,
      onSaved: () => void queryClient.invalidateQueries({ queryKey: ['registers', projectId] }),
    });
    if (saved) addToast({ type: 'success', title: t('ci.flow_saved', { defaultValue: 'Workflow updated' }) });
  };

  const startEditing = () => {
    const current: Record<string, string> = {};
    for (const f of spec?.fields ?? []) {
      current[f.label] = String((item.fields ?? {})[f.label] ?? '');
    }
    setDraft(current);
    setDraftTitle(item.title ?? '');
    setEditing(true);
  };

  const upload = useMutation({
    mutationFn: (f: globalThis.File) => uploadItemAttachment(item.id, f),
    onSuccess: () => {
      addToast({ type: 'success', title: t('ci.attached', { defaultValue: 'Attached — and the step ticked' }) });
      void queryClient.invalidateQueries({ queryKey: ['registers', projectId] });
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const atts = attachmentsOf(item);
  const native = item.native ?? {};
  // Withdrawn: the card still tells the whole story, but every verb on it
  // is off. Greyed with the reason in the title, never hidden - a button
  // that vanishes reads as a bug, one that explains itself reads as a rule.
  const wd = isWithdrawn(item);
  const wdTitle = withdrawnTitle(item, t);

  return (
    <div style={{ padding: '10px 14px 14px' }}>
      <WithdrawnBanner item={item} t={t} />
      <div className="row" style={{ marginBottom: 8 }}>
        {native.rfq_number && <span className="badge">{native.rfq_number}</span>}
        {native.rfi_number && <span className="badge">{native.rfi_number}</span>}
        {native.code && <span className="badge">{native.code}</span>}
        {native.po_number && <span className="badge">PO {native.po_number}</span>}
        {native.quote_gate && (
          <span className={`badge ${native.quote_gate.passes ? 'b-green' : 'b-amber'}`}>
            {native.quote_gate.counted} of {native.quote_gate.required} quoted
          </span>
        )}
        {native.award && <span className="badge b-green">🏆 awarded</span>}
        <span style={{ flex: 1 }} />
        <button
          type="button"
          className="b mini"
          disabled={wd}
          title={wdTitle}
          onClick={() => (editing ? setEditing(false) : startEditing())}
        >
          ✎ {editing ? t('ci.stop_editing', { defaultValue: 'stop editing' }) : t('ci.edit', { defaultValue: 'edit' })}
        </button>
        <button type="button" className="b mini" disabled={wd} title={wdTitle} onClick={() => onEmail(item)}>
          📧 {t('ci.email', { defaultValue: 'email' })}
        </button>
        <button
          type="button"
          className="b mini"
          disabled={wd}
          title={wdTitle}
          onClick={() => fileRef.current?.click()}
        >
          📎 {t('ci.attach', { defaultValue: 'attach' })}
        </button>
        <button type="button" className="b mini" disabled={wd} title={wdTitle} onClick={() => void openLogSent()}>
          📝 {t('ci.log_sent', { defaultValue: 'log as sent' })}
        </button>
        <button
          type="button"
          className="b mini"
          disabled={wd}
          title={wdTitle}
          onClick={() => void configureWorkflow()}
        >
          ⚙ {t('ci.configure_short', { defaultValue: 'configure' })}
        </button>
        <input
          ref={fileRef}
          type="file"
          style={{ display: 'none' }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) upload.mutate(f);
            e.currentTarget.value = '';
          }}
        />
      </div>

      <Fold
        id="details"
        openSignal={
          focusSection?.section === 'details' || focusSection?.section === 'edit'
            ? focusSection.n
            : 0
        }
        title={t('ci.fold_details', { defaultValue: 'details' })}
        count={visibleFields(item).length}
        hint={t('ci.fold_details_hint', { defaultValue: 'What this item says. Click to fold it away.' })}
      >
      {editing ? (
        <div className="pcard" style={{ borderLeftColor: 'var(--amber)', padding: 10 }}>
          <div className="qcell wide" style={{ marginBottom: 8 }}>
            <span className="qlab">{t('ci.subject', { defaultValue: 'Short description' })}</span>
            <input value={draftTitle} onChange={(e) => setDraftTitle(e.target.value)} />
          </div>
          <div className="qgrid">
            {(spec?.fields ?? []).map((f) => {
              const isTable = /materials|scope of works|attendees|breakdown/i.test(f.label) && f.type === 'area';
              return (
                <div key={f.label} className={f.type === 'area' ? 'qcell wide' : 'qcell'}>
                  <span className="qlab">
                    {f.label}
                    {f.internal && (
                      <span className="badge">{t('ci.card_only', { defaultValue: '🔒 internal — money never leaves the building' })}</span>
                    )}
                  </span>
                  {f.type === 'area' && isTable ? (
                    <PasteGrid
                      value={draft[f.label] ?? ''}
                      onChange={(v) => setDraft((d) => ({ ...d, [f.label]: v }))}
                    />
                  ) : f.type === 'area' ? (
                    <textarea
                      value={draft[f.label] ?? ''}
                      onChange={(e) => setDraft((d) => ({ ...d, [f.label]: e.target.value }))}
                    />
                  ) : (
                    <input
                      type={f.type === 'date' ? 'date' : 'text'}
                      inputMode={f.type === 'money' ? 'decimal' : undefined}
                      value={draft[f.label] ?? ''}
                      onChange={(e) => setDraft((d) => ({ ...d, [f.label]: e.target.value }))}
                    />
                  )}
                </div>
              );
            })}
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <button
              type="button"
              className="b pri"
              disabled={saveMut.isPending}
              onClick={() => saveMut.mutate()}
            >
              {saveMut.isPending
                ? t('ci.saving', { defaultValue: 'saving…' })
                : t('ci.save_changes', { defaultValue: 'Save the changes' })}
            </button>
            <button type="button" className="b" onClick={() => setEditing(false)}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </button>
            <span className="v">
              {t('ci.edit_note', {
                defaultValue:
                  'The reference and the workflow stay as they are — this corrects what the item SAYS.',
              })}
            </span>
          </div>
        </div>
      ) : (
        <table className="t" style={{ background: 'var(--panel)', border: '1px solid var(--edge)' }}>
          <tbody>
            {visibleFields(item).map(([k, v]) => {
              const internal = spec?.fields.find((f) => f.label === k)?.internal;
              return (
                <tr key={k}>
                  <td style={{ width: 210, whiteSpace: 'nowrap' }}>
                    <span className="qlab">{k}</span>
                    {internal && <span className="badge">card only</span>}
                  </td>
                  <td style={{ whiteSpace: 'pre-wrap' }}>{String(v)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      </Fold>

      <Fold
        id="evidence"
        openSignal={focusSection?.section === 'evidence' ? focusSection.n : 0}
        title={t('ci.fold_evidence', { defaultValue: 'attachments' })}
        count={atts.length}
        hint={t('ci.fold_evidence_hint', {
          defaultValue: 'Drawings, quotes, dockets. The tick controls whether each one rides the email.',
        })}
        defaultOpen={false}
      >
      <div
        className={`qdrop ${hot ? 'hot' : ''}`}
        onClick={() => fileRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setHot(true);
        }}
        onDragLeave={() => setHot(false)}
        onDrop={(e) => {
          e.preventDefault();
          setHot(false);
          const f = e.dataTransfer.files?.[0];
          if (f) upload.mutate(f);
        }}
      >
        {upload.isPending
          ? t('ci.uploading', { defaultValue: 'attaching…' })
          : t('ci.drop_here', {
              defaultValue: 'drop the quote, docket, photo or signed sheet here — it attaches and ticks the step',
            })}
      </div>
      {atts.length > 0 && (
        <div style={{ marginTop: 6 }}>
          <span className="qlab">{t('ci.evidence', { defaultValue: 'evidence' })}</span>
          <table className="t" style={{ marginTop: 4 }}>
            <tbody>
              {atts.map((a) => (
                <tr
                  key={a.filename}
                  onContextMenu={(e) => attachmentMenu(e, a)}
                  title={t('ci.rightclick', { defaultValue: 'right-click for actions' })}
                >
                  <td>
                    <a href={documentUrl(item.id, a.filename)} target="_blank" rel="noreferrer">
                      📎 {a.filename}
                    </a>{' '}
                    <span className="v">{Math.round(a.size / 1024)} KB</span>
                  </td>
                  <td style={{ width: 190, whiteSpace: 'nowrap' }}>
                    <label className="v" style={{ display: 'inline-flex', gap: 5, alignItems: 'center' }}>
                      <input
                        type="checkbox"
                        checked={a.email !== false}
                        onChange={(e) => flagMut.mutate({ filename: a.filename, email: e.target.checked })}
                      />
                      {t('ci.rides_email', { defaultValue: 'goes with the email' })}
                    </label>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      </Fold>

      {/* The WORKFLOW is the part worked from daily, so it opens by
          default and sits above the thread rather than under it. */}
      <Fold
        id="workflow"
        openSignal={focusSection?.section === 'workflow' ? focusSection.n : 0}
        title={t('ci.fold_workflow', { defaultValue: 'workflow' })}
        count={`${item.steps.filter((s) => s.state !== 'open').length} of ${item.steps.length}`}
      >
        <Steps
          item={item}
          spec={spec}
          projectId={projectId}
          onRaiseFrom={onRaiseFrom}
          onConfigure={() => void configureWorkflow()}
        />
      </Fold>

      <Fold
        id="links"
        title={t('ci.fold_links', { defaultValue: 'linked to' })}
        count={linksOf(item).length || undefined}
        defaultOpen={false}
        openWhen={linksOf(item).length > 0}
        hint={t('ci.fold_links_hint', {
          defaultValue: 'What this item is connected to — RFIs, cost centres, deliverables, folders.',
        })}
      >
        <div className="row" style={{ gap: 4, flexWrap: 'wrap', marginBottom: 6 }}>
          {linksOf(item).map((l, idx) => {
            const shown =
              l.type === 'url' ? l.label.replace(/^https?:\/\//, '').slice(0, 48) : l.label;
            return (
              <span
                key={`${l.type}:${l.label}:${idx}`}
                className="lchip"
                onContextMenu={(e) => linkMenu(e, l, idx)}
                title={t('ci.rightclick', { defaultValue: 'right-click for actions' })}
              >
                <span className="ltag" data-type={l.type}>
                  {linkTag(l)}
                </span>
                {linkOpens(l) ? (
                  <button
                    type="button"
                    className="linkish llabel"
                    title={
                      l.type === 'url'
                        ? l.label
                        : t('ci.link_open', { defaultValue: 'Open {{r}}', r: l.reference ?? l.label })
                    }
                    onClick={() => openLink(l)}
                  >
                    {shown}
                  </button>
                ) : (
                  <span className="llabel">{shown}</span>
                )}
                <button
                  type="button"
                  className="lx"
                  aria-label={t('ci.link_remove', { defaultValue: 'Remove this link' })}
                  title={t('ci.link_unlink', { defaultValue: 'Unlink' })}
                  onClick={() => unlinkMut.mutate(idx)}
                >
                  ✕
                </button>
              </span>
            );
          })}
        </div>
        <div className="row" style={{ gap: 8 }}>
          {/* ONE dropdown - the same "Add link..." as the standup task list,
              so it means one thing everywhere. */}
          <button
            type="button"
            className="pickbtn"
            style={{ maxWidth: 260 }}
            aria-haspopup="menu"
            disabled={linkMut.isPending}
            onClick={(e) => {
              e.stopPropagation();
              openLinkMenu(e.currentTarget);
            }}
          >
            <span className="pname ghost">{t('ci.link_add_btn', { defaultValue: 'Add link...' })}</span>
          </button>
          {linksOf(item).length === 0 && (
            <span className="v">{t('ci.links_none', { defaultValue: 'nothing linked yet' })}</span>
          )}
        </div>
      </Fold>

      <Fold
        id="thread"
        openSignal={focusSection?.section === 'thread' ? focusSection.n : 0}
        title={t('ci.thread', { defaultValue: 'correspondence' })}
        count={(thread.data ?? []).length}
        defaultOpen={false}
      >
      <div>
        {(thread.data ?? []).length === 0 ? (
          <div className="v" style={{ padding: '6px 2px' }}>
            {t('ci.thread_empty', { defaultValue: 'nothing yet — drafts and captured replies land here' })}
          </div>
        ) : (
          <div className="qthread" style={{ marginTop: 6 }}>
            {/* The document-control discipline: every mail shows ITS OWN NUMBER, its
                direction, and its state - and a captured reply opens right
                here to be read and ANSWERED, so the conversation lives on
                the item instead of somewhere in an inbox. */}
            {(thread.data ?? []).map((e, i) => {
              const outbound = e.type === 'send' || e.direction === 'outgoing';
              const readable = e.type === 'correspondence' && !!e.id;
              return (
                <div
                  key={i}
                  className={`tmsg ${outbound ? 'tout' : 'tin'} ${readable ? 'topen' : ''}`}
                  role={readable ? 'button' : undefined}
                  tabIndex={readable ? 0 : undefined}
                  title={
                    readable
                      ? t('ci.thread_open', { defaultValue: 'Read it — reply and forward live inside' })
                      : undefined
                  }
                  onClick={readable ? () => setReadingMsg({ id: e.id as string }) : undefined}
                  onContextMenu={(ev) => threadMenu(ev, e)}
                  onKeyDown={
                    readable
                      ? (ev) => {
                          if (ev.key === 'Enter' || ev.key === ' ') setReadingMsg({ id: e.id as string });
                        }
                      : undefined
                  }
                >
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                    <span className={`badge ${outbound ? '' : 'b-green'}`}>
                      {outbound
                        ? t('ci.from_us', { defaultValue: '▶ from us' })
                        : t('ci.from_them', { defaultValue: '◀ from them' })}
                    </span>
                    {(e.email_ref || e.reference) && (
                      <span className="badge" title={t('ci.mail_no', { defaultValue: 'This mail\u2019s own number' })}>
                        {e.email_ref || e.reference}
                      </span>
                    )}
                    <b style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {e.type === 'send'
                        ? t('ci.draft_to', { defaultValue: 'To {{w}}', w: e.who || '—' })
                        : e.subject}
                    </b>
                    {e.category && <span className="badge b-amber">{e.category.replace(/_/g, ' ')}</span>}
                    {e.status && e.type === 'correspondence' && (
                      <span className="badge">{String(e.status).replace(/_/g, ' ')}</span>
                    )}
                    {readable && (
                      <span className="v">{t('ci.thread_reply_hint', { defaultValue: 'open · reply' })}</span>
                    )}
                    <span className="v" style={{ marginLeft: 'auto' }}>
                      {(e.at ?? '').replace('T', ' ').slice(0, 16)}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
      </Fold>

      {readingMsg && (
        <EmailReader
          itemId={item.id}
          correspondenceId={readingMsg.id}
          initialMode={readingMsg.mode}
          onClose={() => setReadingMsg(null)}
        />
      )}

      {picking && (
        <RecordPicker
          item={item}
          projectId={projectId}
          projectName={projectName}
          exclude={linksOf(item)
            .map((l) => l.reference ?? '')
            .filter(Boolean)}
          onClose={() => setPicking(false)}
        />
      )}
      {menu.element}

      {logSent && (
        <LogSentDialog
          item={logSent.item}
          recipients={logSent.rows}
          onCancel={() => setLogSent(null)}
          onConfirm={async (entries) => {
            setLogSent(null);
            try {
              await logAlreadySentMany(logSent.item.id, entries);
              void queryClient.invalidateQueries({ queryKey: ['registers'] });
              addToast({
                type: 'success',
                title: t('ci.logged_n', {
                  defaultValue: '{{count}} logged on the record',
                  count: entries.length,
                }),
              });
            } catch (e) {
              addToast({ type: 'error', title: (e as Error).message });
            }
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The workspace
// ---------------------------------------------------------------------------

export function RegisterWorkspace({
  onEmailItem,
  focus,
  onOpenCompare,
  onOpenTracking,
}: {
  onEmailItem: (i: RegisterItemRow) => void;
  /** An item another tab asked us to open - see the effect below. */
  focus?: { id: string; kind: Kind } | null;
  /** The "N of M quoted" badge is a fact FROM the compare tab; clicking
   *  it should land on that package's columns, not on a tooltip. */
  onOpenCompare?: (itemId: string) => void;
  /** "with us / with them" is tracking's verdict; clicking it opens the
   *  ledger it came from. */
  onOpenTracking?: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const [kind, setKind] = useState<Kind>('rfq');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [raising, setRaising] = useState<{ kind: Kind; prefill: { fields: Record<string, string>; title: string; raised_from_id: string; ref: string } | null } | null>(null);
  const [showClosed, setShowClosed] = useState(false);
  // OPEN WHAT ANOTHER TAB POINTED AT. Switching to Registers is not
  // enough on its own: the item is very likely under a different kind
  // tab, so landing here with RFQ selected shows a list that does not
  // contain the thing that was clicked.
  useEffect(() => {
    if (!focus) return;
    // The KIND tab first. Expanding alone was not enough: the item is
    // very likely filed under a different register, so landing here with
    // RFQ selected showed a list that did not contain the row that was
    // clicked - the click looked broken.
    setKind(focus.kind);
    setExpanded(focus.id);
  }, [focus]);
  const menu = useMenu();
  const navigate = useNavigate();
  // The whole account of one item, on one screen. The folds below answer
  // "what does this item say"; this answers "what has HAPPENED on it".
  const [logItem, setLogItem] = useState<RegisterItemRow | null>(null);
  // Which fold the click that expanded a row was really about - the 📧
  // badge opens the correspondence, the step chip opens the workflow.
  // The nonce is what makes REPEAT clicks work: pressing the 📧 badge
  // again after folding the section shut re-opens it, because the number
  // changed even though the section name did not. 'configure' and
  // 'logsent' open the row and run that flow.
  const [focusSection, setFocusSection] = useState<{
    section: 'details' | 'evidence' | 'workflow' | 'thread' | 'edit' | 'configure' | 'logsent';
    n: number;
  } | null>(null);
  const expandAt = (id: string, section: NonNullable<typeof focusSection>['section'] | null) => {
    setFocusSection(section ? { section, n: (focusSection?.n ?? 0) + 1 } : null);
    setExpanded(id);
  };

  const specQuery = useQuery({ queryKey: ['registers-spec'], queryFn: fetchSpec });
  const itemsQuery = useQuery<RegisterItemRow[]>({
    queryKey: ['registers', projectId, kind, showClosed],
    queryFn: () => fetchItems(projectId as string, kind, showClosed ? undefined : 'open'),
    enabled: !!projectId,
  });
  const summaryQuery = useQuery<Summary>({
    queryKey: ['registers', projectId, 'summary'],
    queryFn: () => fetchSummary(projectId as string),
    enabled: !!projectId,
  });
  const statsQuery = useQuery({
    queryKey: ['registers', projectId, 'stats'],
    queryFn: () => fetchStats(projectId as string),
    enabled: !!projectId,
  });

  // A WITHDRAWN item is only here when closed items are being shown. The
  // server already excludes it from the open list; this repeats the rule
  // client-side so an older backend - or a row still in the cache from
  // before it was pulled - cannot put junk back beside the live work.
  const items = useMemo(
    () => (itemsQuery.data ?? []).filter((i) => showClosed || !isWithdrawn(i)),
    [itemsQuery.data, showClosed],
  );
  const sum = summaryQuery.data;

  // LAND ON THE ROW. Expanding it is not enough on a long register: a
  // chip on an RFI row, a PO row or the project hub deep-links here, and
  // the item should be on screen - and revealed if it has since closed.
  // Once per focus, not once per refetch: the list refreshes every 45s
  // and nobody wants the page yanked back to the row each time.
  const landedOn = useRef<typeof focus>(null);
  useEffect(() => {
    if (!focus || landedOn.current === focus) return;
    const rows = itemsQuery.data;
    if (!rows || kind !== focus.kind) return;
    if (!rows.some((i) => i.id === focus.id)) {
      if (!showClosed) setShowClosed(true);
      return;
    }
    landedOn.current = focus;
    document
      .getElementById(`rw-item-${focus.id}`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [focus, itemsQuery.data, kind, showClosed]);

  const startRaiseFrom = async (targetKind: Kind, itemId: string) => {
    try {
      const pre = await fetchPrefill(itemId, targetKind);
      setRaising({
        kind: targetKind,
        prefill: { fields: pre.fields, title: pre.title, raised_from_id: pre.raised_from_id, ref: pre.raised_from_reference },
      });
    } catch {
      setRaising({ kind: targetKind, prefill: null });
    }
  };

  const attachReply = (item: RegisterItemRow) =>
    attachReplyFlow(item, { t, addToast, queryClient, projectId });

  // Everything the remove/withdraw flows need. `onGone` collapses the row:
  // a deleted item's expanded card would otherwise sit there until the
  // refetch landed, showing a card for something that no longer exists.
  const removeCtx: RemoveCtx = {
    t,
    addToast,
    queryClient,
    projectId,
    onGone: (id) => setExpanded((cur) => (cur === id ? null : cur)),
  };

  // The register row's menu: every door the row has, in one place.
  const rowMenu = (e: ReactMouseEvent, item: RegisterItemRow) => {
    const open = expanded === item.id;
    // A withdrawn item is a RECORD, not a live one: it can still be read,
    // copied and opened, but nothing further goes out on it - so every
    // door that would send, log or progress it is greyed with the reason.
    const wd = isWithdrawn(item);
    const wdNote = wd ? t('ci.rm_badge', { defaultValue: 'withdrawn' }) : undefined;
    const nativePath =
      item.linked_entity_type === 'rfi' && item.linked_entity_id
        ? `/rfi/${encodeURIComponent(item.linked_entity_id)}`
        : item.linked_entity_type === 'order'
          ? '/procurement'
          : item.linked_entity_type === 'rfq'
            ? '/bid-management'
            : null;
    const nativeName =
      item.linked_entity_type === 'rfi'
        ? t('ci.native_rfi', { defaultValue: 'RFIs' })
        : item.linked_entity_type === 'order'
          ? t('ci.native_procurement', { defaultValue: 'Procurement' })
          : t('ci.native_bids', { defaultValue: 'Bid management' });
    menu.openFromEvent(
      e,
      [
        {
          label: open
            ? t('ci.menu_close', { defaultValue: 'Close the card' })
            : t('ci.menu_open', { defaultValue: 'Open the card' }),
          onClick: () => {
            if (open) setExpanded(null);
            else expandAt(item.id, null);
          },
        },
        {
          label: t('ci.menu_raise_from', { defaultValue: '＋ Raise from this…' }),
          note: t('ci.menu_raise_from_note', { defaultValue: 'prefilled, linked' }),
          onClick: () =>
            menu.openAt(
              e.clientX,
              e.clientY,
              KIND_ORDER.map((k) => ({
                label: KIND_LABEL[k],
                color: KIND_COLOR[k],
                onClick: () => void startRaiseFrom(k, item.id),
              })),
              { head: t('ci.link_raise_head', { defaultValue: 'Raise from {{r}}', r: item.reference }) },
            ),
        },
        null,
        {
          label: t('ci.menu_email', { defaultValue: '📧 Preview / draft the email' }),
          disabled: wd,
          note: wdNote,
          onClick: () => onEmailItem(item),
        },
        {
          label: t('ci.menu_log_sent', { defaultValue: '📝 Log as sent' }),
          disabled: wd,
          note: wdNote,
          onClick: () => expandAt(item.id, 'logsent'),
        },
        {
          label: t('ci.menu_attach_reply', { defaultValue: '📥 Attach a reply / response' }),
          disabled: wd,
          note: wdNote,
          onClick: () => void attachReply(item),
        },
        sendLog(item).length > 0
          ? {
              label: t('ci.menu_thread', { defaultValue: '📨 See the correspondence' }),
              onClick: () => expandAt(item.id, 'thread'),
            }
          : null,
        null,
        {
          label: t('ci.menu_edit_item', { defaultValue: '✎ Edit the details' }),
          disabled: wd,
          note: wdNote,
          onClick: () => expandAt(item.id, 'edit'),
        },
        {
          label: t('ci.menu_configure', { defaultValue: '⚙ Configure the workflow…' }),
          disabled: wd,
          note: wdNote,
          onClick: () => expandAt(item.id, 'configure'),
        },
        item.kind === 'rfq' && item.native?.quote_gate
          ? {
              label: t('ci.menu_compare', { defaultValue: '⚖ Compare the quotes side by side' }),
              disabled: wd,
              note: wdNote,
              onClick: () => onOpenCompare?.(item.id),
            }
          : null,
        {
          label: t('ci.menu_tracking', { defaultValue: '📌 Who owes an answer on this' }),
          onClick: () => onOpenTracking?.(),
        },
        nativePath
          ? {
              label: t('ci.menu_native', { defaultValue: 'Open in {{m}}', m: nativeName }),
              note: item.linked_entity_type ?? undefined,
              onClick: () => navigate(nativePath),
            }
          : null,
        null,
        {
          label: t('ci.menu_copy', { defaultValue: 'Copy the reference' }),
          note: item.reference,
          onClick: () => copyText(item.reference),
        },
        // Raised in error? The last entry on the menu, behind its own
        // separator and its own confirmation - and gone entirely once the
        // item has been withdrawn.
        ...removeMenuItems(item, removeCtx),
      ],
      { head: `${item.reference} · ${item.title}` },
    );
  };

  // The kind chips: open that register, raise into it, show or hide closed.
  const kindMenu = (e: ReactMouseEvent, k: Kind) =>
    menu.openFromEvent(
      e,
      [
        {
          label: t('ci.menu_open_register', { defaultValue: 'Open the {{k}} register', k: KIND_SHORT[k] }),
          color: KIND_COLOR[k],
          note: sum?.[k]?.open ? t('ci.menu_n_open', { defaultValue: '{{n}} open', n: sum[k].open }) : undefined,
          onClick: () => setKind(k),
        },
        {
          label: t('ci.new', { defaultValue: 'Create new {{k}}', k: KIND_SHORT[k] }),
          onClick: () => {
            setKind(k);
            setRaising({ kind: k, prefill: null });
          },
        },
        null,
        {
          label: showClosed
            ? t('ci.menu_hide_closed', { defaultValue: 'Hide closed items' })
            : t('ci.menu_show_closed', { defaultValue: 'Show closed items' }),
          onClick: () => setShowClosed((v) => !v),
        },
      ],
      { head: KIND_SHORT[k] },
    );

  // The KPI tiles: each is a number from a tab; the menu jumps to it.
  const tileMenu = (e: ReactMouseEvent, head: string) =>
    menu.openFromEvent(
      e,
      [
        {
          label: t('ci.menu_go_tracking', { defaultValue: 'Email tracking' }),
          note: t('ci.menu_go_tracking_note', { defaultValue: 'who owes whom' }),
          onClick: () => onOpenTracking?.(),
        },
        {
          label: t('ci.menu_go_compare', { defaultValue: 'Compare & award' }),
          note: t('ci.menu_go_compare_note', { defaultValue: 'the quotes' }),
          onClick: () => onOpenCompare?.(''),
        },
        null,
        {
          label: showClosed
            ? t('ci.menu_hide_closed', { defaultValue: 'Hide closed items' })
            : t('ci.menu_show_closed', { defaultValue: 'Show closed items' }),
          onClick: () => setShowClosed((v) => !v),
        },
      ],
      { head },
    );

  if (!projectId) {
    return (
      <div className="ci">
        <div className="pcard" style={{ textAlign: 'center', color: 'var(--dim)', padding: 26 }}>
          {t('ci.no_project', { defaultValue: 'Pick a job from the switcher above — the registers are per job.' })}
        </div>
      </div>
    );
  }

  const totals = KIND_ORDER.reduce(
    (a, k) => ({
      open: a.open + (sum?.[k]?.open ?? 0),
      overdue: a.overdue + (sum?.[k]?.overdue ?? 0),
      them: a.them + (sum?.[k]?.with_them ?? 0),
    }),
    { open: 0, overdue: 0, them: 0 },
  );

  return (
    <div className="ci">
      {/* Every tile is a number from a tab; right-click jumps to it. */}
      <div className="tiles">
        <div className="tile" onContextMenu={(e) => tileMenu(e, t('ci.tile_open', { defaultValue: 'open items' }))}>
          <b>{totals.open}</b>
          <span>{t('ci.tile_open', { defaultValue: 'open items' })}</span>
        </div>
        <div
          className={`tile ${totals.overdue ? 'bad' : 'good'}`}
          onContextMenu={(e) => tileMenu(e, t('ci.tile_overdue', { defaultValue: 'overdue' }))}
        >
          <b>{totals.overdue}</b>
          <span>{t('ci.tile_overdue', { defaultValue: 'overdue' })}</span>
        </div>
        <div className="tile" onContextMenu={(e) => tileMenu(e, t('ci.tile_them', { defaultValue: 'waiting on them' }))}>
          <b>{totals.them}</b>
          <span>{t('ci.tile_them', { defaultValue: 'waiting on them' })}</span>
        </div>
        <div className="tile good" onContextMenu={(e) => tileMenu(e, t('ci.tile_closed', { defaultValue: 'closed out' }))}>
          <b>{statsQuery.data?.closed ?? 0}</b>
          <span>{t('ci.tile_closed', { defaultValue: 'closed out' })}</span>
        </div>
      </div>

      {/* How the job is actually running - the numbers the tracking tab
          carries, including the lost-hours claim figure. */}
      <div className="tiles">
        <div className="tile" onContextMenu={(e) => tileMenu(e, t('ci.tile_avg', { defaultValue: 'avg days to close' }))}>
          <b>{statsQuery.data?.avg_days_to_close ?? '—'}</b>
          <span>{t('ci.tile_avg', { defaultValue: 'avg days to close' })}</span>
        </div>
        <div className="tile" onContextMenu={(e) => tileMenu(e, t('ci.tile_ontime', { defaultValue: 'closed on time' }))}>
          <b>{statsQuery.data?.closed_on_time_pct != null ? `${statsQuery.data.closed_on_time_pct}%` : '—'}</b>
          <span>{t('ci.tile_ontime', { defaultValue: 'closed on time' })}</span>
        </div>
        <div
          className={`tile ${(statsQuery.data?.oldest_open_days ?? 0) > 21 ? 'bad' : ''}`}
          onContextMenu={(e) => tileMenu(e, t('ci.tile_oldest', { defaultValue: 'oldest open' }))}
        >
          <b>{statsQuery.data?.oldest_open_days ? `${statsQuery.data.oldest_open_days}d` : '—'}</b>
          <span>
            {t('ci.tile_oldest', { defaultValue: 'oldest open' })}
            {statsQuery.data?.oldest_open_reference ? ` · ${statsQuery.data.oldest_open_reference}` : ''}
          </span>
        </div>
        <div
          className={`tile ${Number(statsQuery.data?.lost_hours ?? 0) > 0 ? 'bad' : ''}`}
          onContextMenu={(e) => tileMenu(e, t('ci.tile_lost', { defaultValue: 'lost time on the claim' }))}
        >
          <b>{statsQuery.data?.lost_hours ?? '0'}h</b>
          <span>{t('ci.tile_lost', { defaultValue: 'lost time on the claim' })}</span>
        </div>
      </div>

      <div className="pcard">
        <h3 className="ph">{t('ci.registers', { defaultValue: 'Job registers' })}</h3>

        <div className="row" style={{ marginBottom: 10 }}>
          {KIND_ORDER.map((k) => (
            <button
              key={k}
              type="button"
              className={`b mini ${kind === k ? 'on' : ''}`}
              onClick={() => setKind(k)}
              onContextMenu={(e) => kindMenu(e, k)}
            >
              {KIND_SHORT[k]}
              {sum?.[k]?.open ? ` · ${sum[k].open}` : ''}
            </button>
          ))}
          <span style={{ flex: 1 }} />
          <label className="v" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} />
            {t('ci.show_closed', { defaultValue: 'show closed' })}
          </label>
          <button type="button" className="b mini" onClick={() => void queryClient.invalidateQueries({ queryKey: ['registers', projectId] })}>
            ↻
          </button>
          <button type="button" className="b pri" onClick={() => setRaising({ kind, prefill: null })}>
            ＋ {t('ci.new', { defaultValue: 'Create new {{k}}', k: KIND_SHORT[kind] })}
          </button>
        </div>

        {itemsQuery.isLoading ? (
          <div className="v" style={{ padding: 20, textAlign: 'center' }}>…</div>
        ) : items.length === 0 ? (
          // The list is PER KIND, so "nothing raised" beside a header
          // counting open items was a lie. Name the register, and point at
          // where the open items actually are.
          <div style={{ color: 'var(--dim)', padding: 26, textAlign: 'center', border: '1px dashed var(--edge)', borderRadius: 14 }}>
            <div>
              {(sum?.[kind]?.total ?? 0) > 0 && !showClosed
                ? t('ci.empty_closed', {
                    defaultValue_one:
                      'Nothing open in the {{k}} register on this job — {{count}} closed. Tick "show closed" to see it.',
                    defaultValue_other:
                      'Nothing open in the {{k}} register on this job — {{count}} closed. Tick "show closed" to see them.',
                    k: KIND_SHORT[kind],
                    count: sum?.[kind]?.total ?? 0,
                  })
                : t('ci.empty_kind', {
                    defaultValue:
                      'Nothing in the {{k}} register on this job yet — create the first one and its workflow comes with it.',
                    k: KIND_SHORT[kind],
                  })}
            </div>
            {KIND_ORDER.some((k) => k !== kind && (sum?.[k]?.open ?? 0) > 0) && (
              <div className="row" style={{ justifyContent: 'center', gap: 8, marginTop: 10 }}>
                <span className="v">{t('ci.empty_elsewhere', { defaultValue: 'The open items are in:' })}</span>
                {KIND_ORDER.filter((k) => k !== kind && (sum?.[k]?.open ?? 0) > 0).map((k) => (
                  <button key={k} type="button" className="b mini" onClick={() => setKind(k)}>
                    {KIND_SHORT[k]} · {sum?.[k]?.open}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="qreg" style={{ overflowX: 'auto' }}>
            <table className="t">
              <thead>
                <tr>
                  <th>{t('ci.col_card', { defaultValue: 'card' })}</th>
                  <th>{t('ci.col_workflow', { defaultValue: 'workflow' })}</th>
                  <th>{t('ci.col_due', { defaultValue: 'due' })}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.map((i) => {
                  const open = expanded === i.id;
                  const wd = isWithdrawn(i);
                  const wdWhy = wd ? withdrawnNote(i, t) : undefined;
                  const sent = new Set(sendLog(i).map((s) => s.contact_name || s.contact_id)).size;
                  const age = i.created_at
                    ? Math.floor((Date.now() - new Date(i.created_at).getTime()) / 86400000)
                    : null;
                  const gate = i.native?.quote_gate;
                  return (
                    <Fragment key={i.id}>
                      <tr
                        id={`rw-item-${i.id}`}
                        className={`qrow ${open ? 'act' : ''}`}
                        style={
                          wd
                            ? withdrawnRowStyle(i)
                            : i.status === 'closed'
                              ? { opacity: 0.55 }
                              : undefined
                        }
                        onClick={() => {
                          setFocusSection(null);
                          setExpanded(open ? null : i.id);
                        }}
                        onContextMenu={(e) => rowMenu(e, i)}
                        /* The reason IS the tooltip on a withdrawn row -
                           "why is that struck out?" is the only question
                           anybody asks of one. */
                        title={wdWhy ?? t('ci.rightclick', { defaultValue: 'right-click for actions' })}
                      >
                        <td>
                          <span className="b mini" style={{ padding: '1px 6px', marginRight: 6 }}>{open ? '▾' : '▸'}</span>
                          <b style={{ color: 'var(--navy)' }}>{i.reference}</b>{' '}
                          {/* Raised without a title, an item carries its
                              reference as one - shown once, not twice. */}
                          <span>{i.title && i.title !== i.reference ? i.title : ''}</span>{' '}
                          {wd && (
                            <span className="badge b-red" title={wdWhy}>
                              {t('ci.rm_badge', { defaultValue: 'withdrawn' })}
                            </span>
                          )}{' '}
                          {/* EVERY BADGE IS A DOOR to the screen its fact
                              came from. A count you cannot click is a
                              corridor with a window painted on it. */}
                          {gate && (
                            <span
                              className={`badge clk ${gate.passes ? 'b-green' : 'b-amber'}`}
                              title={t('ci.badge_quoted_hint', {
                                defaultValue: 'Open this package in Compare & award',
                              })}
                              onClick={(e) => {
                                e.stopPropagation();
                                onOpenCompare?.(i.id);
                              }}
                            >
                              {gate.counted} of {gate.required} quoted
                            </span>
                          )}{' '}
                          {i.native?.award && (
                            <span
                              className="badge clk b-green"
                              title={t('ci.badge_award_hint', {
                                defaultValue: 'Open the award in Compare & award',
                              })}
                              onClick={(e) => {
                                e.stopPropagation();
                                onOpenCompare?.(i.id);
                              }}
                            >
                              🏆 awarded
                            </span>
                          )}{' '}
                          {sent > 0 && (
                            <span
                              className="badge clk"
                              title={t('ci.badge_mail_hint', {
                                defaultValue: 'See the {{n}} email(s) on this item',
                                n: sent,
                              })}
                              onClick={(e) => {
                                e.stopPropagation();
                                expandAt(i.id, 'thread');
                              }}
                            >
                              📧 {sent}
                            </span>
                          )}{' '}
                          {age !== null && age > 14 && <span className="badge b-amber">{age}d</span>}{' '}
                          {(() => {
                            const who = String(
                              (i.fields as Record<string, unknown> | undefined)?.Responsible ?? '',
                            ).trim();
                            return who ? (
                              <span
                                className="badge"
                                title={t('ci.responsible_hint', { defaultValue: 'Responsible person' })}
                              >
                                👤 {who}
                              </span>
                            ) : null;
                          })()}
                        </td>
                        <td>
                          <span
                            className={`badge clk ${
                              i.steps_done === 0 ? '' : i.steps_done >= i.steps_total ? 'b-green' : 'b-amber'
                            }`}
                            title={t('ci.badge_step_hint', { defaultValue: 'Open the workflow at this step' })}
                            onClick={(e) => {
                              e.stopPropagation();
                              expandAt(i.id, 'workflow');
                            }}
                          >
                            {i.steps_done >= i.steps_total
                              ? t('ci.complete', { defaultValue: '✓ complete' })
                              : t('ci.step_of', {
                                  defaultValue: 'step {{a}} of {{b}}',
                                  a: i.steps_done + 1,
                                  b: i.steps_total,
                                })}
                          </span>{' '}
                          <span
                            className={`badge clk ${i.ball_in_court === 'them' ? 'b-amber' : ''}`}
                            title={t('ci.badge_ball_hint', { defaultValue: 'Open email tracking - who owes whom' })}
                            onClick={(e) => {
                              e.stopPropagation();
                              onOpenTracking?.();
                            }}
                          >
                            {i.ball_in_court === 'them'
                              ? t('ci.with_them', { defaultValue: 'with them' })
                              : t('ci.with_us', { defaultValue: 'with us' })}
                          </span>
                          {/* THE WHOLE STORY, one click, from the row. The
                              folds each answer a piece; on a live item the
                              question is almost always "what has actually
                              happened here" - which is every piece at once,
                              in time order. */}
                          <button
                            type="button"
                            className="qlogbtn"
                            onClick={(e) => {
                              e.stopPropagation();
                              setLogItem(i);
                            }}
                            title={t('ci.log_btn_hint', {
                              defaultValue:
                                'Every detail on one screen — what we asked, who we asked, and what they said back',
                            })}
                          >
                            {t('ci.log_btn', {
                              defaultValue: 'View {{k}} workflow / conversation log',
                              k: (specQuery.data?.specs?.[i.kind]?.prefix ?? i.kind).toUpperCase(),
                            })}
                          </button>
                        </td>
                        <td
                          className={`${i.is_overdue ? 'bad' : ''} clkcell`}
                          title={t('ci.due_hint', { defaultValue: 'Click to correct the dates' })}
                          onClick={(e) => {
                            e.stopPropagation();
                            expandAt(i.id, 'edit');
                          }}
                        >
                          {i.due_date ? (
                            <span style={i.is_overdue ? { color: 'var(--red)', fontWeight: 600 } : undefined}>
                              {i.due_date}
                              {i.days_until_due !== null && (
                                <span className="v"> ({i.days_until_due}d)</span>
                              )}
                            </span>
                          ) : (
                            <span className="v">—</span>
                          )}
                        </td>
                        <td onClick={(e) => e.stopPropagation()}>
                          <button
                            type="button"
                            className="b mini"
                            disabled={wd}
                            title={
                              withdrawnTitle(i, t) ??
                              t('ci.preview_hint', {
                                defaultValue: 'See each recipient\u2019s email exactly as it will send',
                              })
                            }
                            onClick={() => onEmailItem(i)}
                          >
                            📧 {t('ci.preview_email', { defaultValue: 'preview email' })}
                          </button>{' '}
                          <button type="button" className="b mini" onClick={() => setExpanded(open ? null : i.id)}>
                            {open ? t('ci.close', { defaultValue: 'close' }) : t('ci.open', { defaultValue: 'open' })}
                          </button>
                        </td>
                      </tr>
                      {open && (
                        <tr>
                          <td className="sub" colSpan={4}>
                            <ExpandedRow
                              item={i}
                              spec={specQuery.data?.specs?.[i.kind]}
                              projectId={projectId}
                              onRaiseFrom={startRaiseFrom}
                              onEmail={onEmailItem}
                              focusSection={focusSection}
                              onOpenLinked={(id, ref) => {
                                // REG-RFI-000004 / RFI-004 → the rfi tab. The
                                // optional leading "<prefix>-" tolerates any
                                // house prefix a workspace mints references
                                // with, so we key on the kind, not the prefix.
                                const m = ref.match(/(?:[A-Za-z0-9]{1,8}-)?(RFI|RFQ|ORD|VO|DEL|TBX)-/i);
                                const kindOf: Record<string, Kind> = {
                                  RFI: 'rfi', RFQ: 'rfq', ORD: 'order', VO: 'variation', DEL: 'delay', TBX: 'toolbox',
                                };
                                const k = m?.[1] ? kindOf[m[1].toUpperCase()] : undefined;
                                if (k) setKind(k);
                                expandAt(id, null);
                              }}
                            />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {raising && specQuery.data?.specs?.[raising.kind] && (
          <div style={{ marginTop: 10 }}>
            <RaiseForm
              spec={specQuery.data.specs[raising.kind]}
              projectId={projectId}
              prefill={raising.prefill}
              onCancel={() => setRaising(null)}
              onRaised={(item) => {
                setRaising(null);
                setExpanded(item.id);
                if ((item.recipient_contact_ids ?? []).length > 0) onEmailItem(item);
              }}
            />
          </div>
        )}
      </div>

      {logItem && (
        <ConversationLog
          item={logItem}
          spec={specQuery.data?.specs?.[logItem.kind]}
          onClose={() => setLogItem(null)}
        />
      )}

      {menu.element}
    </div>
  );
}
