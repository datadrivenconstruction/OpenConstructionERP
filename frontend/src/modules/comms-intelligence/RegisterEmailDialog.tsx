// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The register email flow — preview-first, one tailored draft per person.
 *
 * Pick a recipient on the left, see EXACTLY their copy on the right
 * (byte-for-byte what the draft carries), then open it in Outlook,
 * download the .eml, or Draft ALL in one confirmed click. Every draft
 * logs on the item — the register's "sent to N".
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, Loader2, Mail, Send, X } from 'lucide-react';
import { Badge, Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  type ContactRow,
  type ItemEmailPreview,
  type RegisterItemRow,
  downloadItemEml,
  draftItemEmail,
  fetchContactsByIds,
  fetchSpec,
  previewItemEmail,
  updateItem,
} from './registers-api';
import { RecipientBlock } from './RegisterWorkspace';

export function RegisterEmailDialog({
  item,
  projectId,
  onClose,
}: {
  item: RegisterItemRow;
  projectId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  // LIVE STATE, seeded from the prop. The prop is a snapshot from when
  // the dialog opened; rendering from it meant a supplier added through
  // the picker saved to the server (the PATCH answered 200) while the
  // rail still read "opens unaddressed" - the save worked and the screen
  // called it broken. Every mutation answers with the fresh item, and
  // that answer is what this dialog believes from then on.
  const [recipientIds, setRecipientIds] = useState<string[]>(item.recipient_contact_ids ?? []);
  const [selected, setSelected] = useState<string | null>(
    (item.recipient_contact_ids ?? [])[0] ?? null,
  );
  // ADDING PEOPLE FROM HERE, with the same ranked table as the raise
  // form. The rail only LISTED whoever was picked at raise time - an
  // item raised without recipients said "opens unaddressed" and offered
  // no way to fix it except closing the dialog, editing the item, and
  // coming back.
  const [picking, setPicking] = useState(recipientIds.length === 0);
  const specQuery = useQuery({
    queryKey: ['register-spec'],
    queryFn: fetchSpec,
    staleTime: 300_000,
  });
  const spec = specQuery.data?.specs?.[item.kind];
  // Anyone not in the directory rail: an estimator's personal address, a
  // client copied in, the site super. Typed as free text, comma or
  // semicolon separated, exactly as Outlook takes them.
  const [extraTo, setExtraTo] = useState('');
  // A sentence for THIS send. It rides above the details block and is
  // deliberately not written back to the item - saying something to one
  // supplier is not an edit to the record.
  const [note, setNote] = useState('');
  const [showCompose, setShowCompose] = useState(false);

  const extras = extraTo
    .split(/[;,\n]/)
    .map((a) => a.trim())
    .filter(Boolean);

  const contactsQuery = useQuery({
    // Keyed on the LIVE id list: add somebody and this refetches by
    // itself, because the key changed.
    queryKey: ['register-email-contacts', recipientIds.join(',')],
    queryFn: () => fetchContactsByIds(recipientIds),
    enabled: recipientIds.length > 0,
  });
  // 400ms so the preview follows what is being typed without a request
  // per keystroke - the same cadence as the raise form's live preview.
  const [debounced, setDebounced] = useState({ extras, note });
  useEffect(() => {
    const h = setTimeout(() => setDebounced({ extras, note }), 400);
    return () => clearTimeout(h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [extraTo, note]);

  const previewQuery = useQuery<ItemEmailPreview>({
    queryKey: ['register-email-preview', item.id, selected, debounced.extras.join(','), debounced.note],
    queryFn: () => previewItemEmail(item.id, selected, debounced.extras, debounced.note),
  });

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ['registers', projectId] });

  const recipientsMut = useMutation({
    // Saved onto the ITEM, so the send log, the compare panel and the
    // tracking rows all see the same list this dialog drafts to - and
    // the server's answer becomes the dialog's state, so the rail, the
    // picker's ticks and the preview all move the moment it lands.
    mutationFn: (rows: ContactRow[]) =>
      updateItem(item.id, { recipient_contact_ids: rows.map((r) => String(r.id)) }),
    onSuccess: (updated) => {
      const ids = updated.recipient_contact_ids ?? [];
      setRecipientIds(ids);
      // Keep the preview pointed at somebody real: the first added
      // supplier readdresses an unaddressed email; removing whoever was
      // being previewed falls back rather than previewing a ghost.
      setSelected((cur) => (cur && ids.includes(cur) ? cur : (ids[0] ?? null)));
      invalidate();
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const draftMut = useMutation({
    mutationFn: (contactId: string | null) => draftItemEmail(item.id, contactId, extras, note),
    onSuccess: (r) => {
      addToast({
        type: 'success',
        title:
          r.opened > 1
            ? t('regmail.toast.all', { defaultValue: '{{n}} drafts opened in Outlook - one per supplier', n: r.opened })
            : t('regmail.toast.one', { defaultValue: 'Draft opened in Outlook - review and press Send there' }),
      });
      invalidate();
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const emlMut = useMutation({
    mutationFn: () => downloadItemEml(item.id, selected, item.reference),
    onSuccess: () => {
      addToast({ type: 'success', title: t('regmail.toast.eml', { defaultValue: '.eml saved - open it and press Send' }) });
      invalidate();
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const name = (c: ContactRow) =>
    c.company_name || [c.first_name, c.last_name].filter(Boolean).join(' ') || c.primary_email || '—';
  const p = previewQuery.data;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        // 96vw, not max-w-5xl: the rail now carries the ranked supplier
        // table, and the preview beside it is a real 700px email. At 5xl
        // the two fought and the table lost - names, contacts and the
        // search box all truncated.
        className="flex h-[94vh] w-[96vw] max-w-[1500px] overflow-hidden rounded-lg border border-border-light bg-surface-primary shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Recipient rail */}
        <div className="flex w-[400px] shrink-0 flex-col border-r border-border-light">
          <div className="border-b border-border-light p-3 text-sm font-semibold">
            {t('regmail.recipients', { defaultValue: 'Recipients' })}
          </div>
          {/* WHO IT GOES TO, first. Each row IS the preview switcher -
              every supplier gets their own tailored copy and clicking a
              row shows exactly theirs. That affordance existed and read
              as a plain list; now it says so. */}
          <div className="min-h-0 flex-1 overflow-auto">
            <div className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-content-tertiary">
              {t('regmail.sending_to', {
                defaultValue: 'Sending to {{n}} — each gets their own copy',
                n: recipientIds.length,
              })}
            </div>
            {(contactsQuery.data ?? []).map((c) => {
              const on = selected === String(c.id);
              return (
                <div
                  key={c.id}
                  className={`group flex items-stretch border-b border-border-light/60 ${
                    on ? 'border-l-2 border-l-oe-blue bg-oe-blue-subtle' : 'hover:bg-surface-secondary'
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => setSelected(String(c.id))}
                    className="min-w-0 flex-1 px-3 py-2 text-left"
                  >
                    <div className={`truncate text-sm ${on ? 'font-semibold' : ''}`}>{name(c)}</div>
                    <div className="truncate text-xs text-text-tertiary">{c.primary_email}</div>
                    <div className={`text-[11px] ${on ? 'text-oe-blue-text' : 'text-content-tertiary opacity-0 group-hover:opacity-100'}`}>
                      {on
                        ? t('regmail.previewing', { defaultValue: '◀ previewing their copy' })
                        : t('regmail.click_preview', { defaultValue: 'click to preview their copy' })}
                    </div>
                  </button>
                  <button
                    type="button"
                    className="shrink-0 px-2 text-content-tertiary opacity-0 hover:text-semantic-error group-hover:opacity-100"
                    title={t('regmail.remove_recipient', { defaultValue: 'Take {{w}} off this item', w: name(c) })}
                    onClick={() =>
                      recipientsMut.mutate((contactsQuery.data ?? []).filter((x) => String(x.id) !== String(c.id)))
                    }
                  >
                    ✕
                  </button>
                </div>
              );
            })}
            {recipientIds.length === 0 && (
              <p className="p-3 text-xs text-text-tertiary">
                {t('regmail.none_yet', {
                  defaultValue: 'Nobody yet — pick suppliers below and the email addresses itself.',
                })}
              </p>
            )}

            <div className="border-t border-border-light p-2">
              <Button size="sm" variant="ghost" className="w-full" onClick={() => setPicking((v) => !v)}>
                {picking
                  ? t('regmail.hide_picker', { defaultValue: 'Hide the supplier picker' })
                  : t('regmail.show_picker', { defaultValue: '+ Add or remove suppliers' })}
              </Button>
              {picking && spec && (
                <div className="pt-2">
                  <RecipientBlock
                    spec={spec}
                    kind={item.kind}
                    projectId={projectId}
                    selected={contactsQuery.data ?? []}
                    onChange={(rows) => recipientsMut.mutate(rows)}
                    variant="rail"
                  />
                </div>
              )}
            </div>
          </div>
          {recipientIds.length > 1 && (
            <div className="border-t border-border-light p-2">
              <Button
                size="sm"
                variant="primary"
                className="w-full"
                onClick={() => draftMut.mutate(null)}
                disabled={draftMut.isPending}
              >
                {draftMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                {t('regmail.draft_all', { defaultValue: 'Draft ALL ({{n}})', n: recipientIds.length })}
              </Button>
              <p className="mt-1 text-center text-[11px] text-text-tertiary">
                {t('regmail.draft_all_note', { defaultValue: 'One tailored draft each — nobody sees the others.' })}
              </p>
            </div>
          )}
        </div>

        {/* Preview pane */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center gap-2 border-b border-border-light p-3">
            <Mail className="h-4 w-4 text-text-tertiary" />
            <span className="truncate text-sm font-semibold">{p?.subject ?? '…'}</span>
            {p && p.cc.length > 0 && <Badge variant="neutral">Cc {p.cc.join('; ')}</Badge>}
            <span className="ml-auto flex items-center gap-1">
              <Button size="sm" variant="ghost" onClick={() => emlMut.mutate()} disabled={emlMut.isPending}>
                <Download className="h-4 w-4" />
                .eml
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => draftMut.mutate(selected)}
                disabled={draftMut.isPending}
              >
                {draftMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
                {t('regmail.open_outlook', { defaultValue: 'Open in Outlook' })}
              </Button>
              <Button size="sm" variant="ghost" onClick={onClose}>
                <X className="h-4 w-4" />
              </Button>
            </span>
          </div>
          {/* ADD PEOPLE, AND SAY SOMETHING. Both were supported by the
              backend and unreachable from here - the client sent an empty
              extra_to on every call and there was no note field at all. */}
          <div className="border-b border-border-light px-3 py-2">
            <button
              type="button"
              className="text-xs font-medium text-accent-primary hover:underline"
              onClick={() => setShowCompose((v) => !v)}
            >
              {showCompose
                ? t('regmail.hide_compose', { defaultValue: 'Hide the extra recipients and note' })
                : t('regmail.show_compose', { defaultValue: '+ Copy someone in, or add a note to this email' })}
              {(extras.length > 0 || note.trim()) && !showCompose ? ` (${extras.length + (note.trim() ? 1 : 0)})` : ''}
            </button>
            {showCompose && (
              <div className="mt-2 space-y-2">
                <div>
                  <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-text-tertiary">
                    {t('regmail.extra_to', { defaultValue: 'Also send to' })}
                  </label>
                  <input
                    className="w-full rounded border border-border-light bg-surface-primary px-2 py-1.5 text-sm"
                    placeholder={t('regmail.extra_to_ph', {
                      defaultValue: 'name@company.com.au, someone.else@client.com.au',
                    })}
                    value={extraTo}
                    onChange={(e) => setExtraTo(e.target.value)}
                  />
                  {extras.length > 0 && (
                    <p className="mt-1 text-[11px] text-text-tertiary">
                      {t('regmail.extra_to_note', {
                        defaultValue:
                          '{{n}} added to THIS copy only — the other suppliers still never see each other.',
                        n: extras.length,
                      })}
                    </p>
                  )}
                </div>
                <div>
                  <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-text-tertiary">
                    {t('regmail.note', { defaultValue: 'Add a note to this email' })}
                  </label>
                  <textarea
                    className="min-h-[64px] w-full rounded border border-border-light bg-surface-primary px-2 py-1.5 text-sm"
                    placeholder={t('regmail.note_ph', {
                      defaultValue: 'e.g. Pricing the ladder only for now — brackets to follow next week.',
                    })}
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                  />
                  <p className="mt-1 text-[11px] text-text-tertiary">
                    {t('regmail.note_hint', {
                      defaultValue: 'Goes out with this email. It is not saved onto the item.',
                    })}
                  </p>
                </div>
              </div>
            )}
          </div>

          <div className="min-h-0 flex-1 overflow-auto bg-white">
            {previewQuery.isLoading ? (
              <div className="flex justify-center p-8">
                <Loader2 className="h-6 w-6 animate-spin text-text-tertiary" />
              </div>
            ) : (
              <iframe title="register-email" className="h-full w-full border-0" srcDoc={p?.html ?? ''} />
            )}
          </div>
          <div className="border-t border-border-light p-2 text-center text-xs text-text-tertiary">
            {t('regmail.note', {
              defaultValue:
                'This preview is byte-for-byte the draft. Internal figures never leave; the Notified block shows everyone told. Sending stays in your hands.',
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
