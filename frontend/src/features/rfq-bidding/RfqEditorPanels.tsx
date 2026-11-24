// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Save, Trash2 } from 'lucide-react';
import { fetchContacts, type Contact, type ContactType } from '@/features/contacts/api';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  addScopeLine,
  deleteScopeLine,
  updateScopeLine,
  type RFQ,
  type ScopeLine,
} from './api';

type Translate = (k: string, o?: Record<string, unknown>) => string;

/** How a contact is named in a picker: company first, then the person. */
export function contactLabel(contact: Contact): string {
  return (
    contact.company_name ||
    contact.legal_name ||
    [contact.first_name, contact.last_name].filter(Boolean).join(' ') ||
    contact.primary_email ||
    contact.id
  );
}

/** The kinds of contact an RFQ is sent to. */
const INVITEE_TYPES: ContactType[] = ['supplier', 'subcontractor', 'contractor'];

/**
 * Pick the contacts an RFQ goes to: suppliers, subcontractors and contractors
 * from the address book, filtered by kind and searchable. The ids are kept as a
 * list so the caller saves them with the rest of the header.
 */
export function RfqInviteePicker({
  selected,
  onChange,
  t,
}: {
  selected: string[];
  onChange: (next: string[]) => void;
  t: Translate;
}) {
  const [kind, setKind] = useState<ContactType | ''>('');
  const [search, setSearch] = useState('');

  const { data, isLoading, error } = useQuery({
    queryKey: ['rfq-bidding', 'invitee-contacts', kind, search],
    queryFn: () => fetchContacts({ limit: 200, contact_type: kind, search: search.trim() || undefined }),
    staleTime: 60_000,
  });

  const items = useMemo(
    () => (data?.items ?? []).filter((c) => (kind ? true : INVITEE_TYPES.includes(c.contact_type))),
    [data, kind],
  );
  const chosen = useMemo(() => new Set(selected), [selected]);

  const toggle = (id: string) => {
    onChange(chosen.has(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  };

  return (
    <fieldset data-testid="rfq-invitees">
      <legend className="oe-label">
        {t('rfq_bidding.invitees_label', { defaultValue: 'Invite vendors' })}
        <span className="ms-2 text-xs font-normal text-content-tertiary">
          {t('rfq_bidding.invitees_selected', { defaultValue: '{{n}} selected', n: selected.length })}
        </span>
      </legend>
      <div className="mb-2 flex gap-2">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as ContactType | '')}
          className="oe-select"
          aria-label={t('rfq_bidding.invitees_kind', { defaultValue: 'Contact type' })}
        >
          <option value="">{t('rfq_bidding.invitees_kind_all', { defaultValue: 'All vendor types' })}</option>
          {INVITEE_TYPES.map((k) => (
            <option key={k} value={k}>
              {t(`contacts.type_${k}`, { defaultValue: k.charAt(0).toUpperCase() + k.slice(1) })}
            </option>
          ))}
        </select>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('rfq_bidding.invitees_search', { defaultValue: 'Search contacts...' })}
          className="oe-input flex-1"
        />
      </div>
      <div className="max-h-48 overflow-y-auto rounded-lg border border-border-light">
        {isLoading && (
          <p className="p-3 text-xs text-content-tertiary">{t('common.loading', { defaultValue: 'Loading...' })}</p>
        )}
        {error && (
          <p className="p-3 text-xs text-semantic-error">
            {t('rfq_bidding.invitees_load_error', { defaultValue: 'Could not load contacts' })}
          </p>
        )}
        {!isLoading && !error && items.length === 0 && (
          <p className="p-3 text-xs text-content-tertiary">
            {t('rfq_bidding.invitees_empty', { defaultValue: 'No matching contacts. Add vendors under Contacts.' })}
          </p>
        )}
        {items.map((c) => (
          <label
            key={c.id}
            className="flex cursor-pointer items-center gap-2 border-b border-border-light px-3 py-1.5 text-sm last:border-b-0 hover:bg-surface-secondary"
          >
            <input type="checkbox" checked={chosen.has(c.id)} onChange={() => toggle(c.id)} />
            <span className="min-w-0 flex-1 truncate text-content-primary">{contactLabel(c)}</span>
            <span className="text-xs text-content-tertiary">
              {t(`contacts.type_${c.contact_type}`, { defaultValue: c.contact_type })}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/* ── Scope lines ──────────────────────────────────────────────────────── */

function LineRow({
  rfqId,
  line,
  onChanged,
  t,
}: {
  rfqId: string;
  line: ScopeLine;
  onChanged: () => void;
  t: Translate;
}) {
  const addToast = useToastStore((s) => s.addToast);
  const [description, setDescription] = useState(line.description);
  const [unit, setUnit] = useState(line.unit);
  const [quantity, setQuantity] = useState(String(line.quantity));
  const dirty = description !== line.description || unit !== line.unit || quantity !== String(line.quantity);

  const fail = (err: unknown) =>
    addToast({
      type: 'error',
      title: t('rfq_bidding.line_error', { defaultValue: 'Could not change the scope line' }),
      message: getErrorMessage(err),
    });

  const save = useMutation({
    mutationFn: () =>
      updateScopeLine(rfqId, line.id, { description: description.trim(), unit: unit.trim(), quantity }),
    onSuccess: onChanged,
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: () => deleteScopeLine(rfqId, line.id),
    onSuccess: onChanged,
    onError: fail,
  });

  return (
    <div className="flex items-center gap-2" data-testid="rfq-line-row">
      <span className="w-6 text-xs text-content-tertiary">{line.line_no}</span>
      <input
        className="oe-input flex-1"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        aria-label={t('rfq_bidding.line_description', { defaultValue: 'Description' })}
      />
      <input
        className="oe-input w-16"
        value={unit}
        onChange={(e) => setUnit(e.target.value)}
        aria-label={t('rfq_bidding.line_unit', { defaultValue: 'Unit' })}
      />
      <input
        className="oe-input w-24"
        inputMode="decimal"
        value={quantity}
        onChange={(e) => setQuantity(e.target.value)}
        aria-label={t('rfq_bidding.line_quantity', { defaultValue: 'Quantity' })}
      />
      <button
        type="button"
        disabled={!dirty || !description.trim() || !unit.trim() || save.isPending}
        onClick={() => save.mutate()}
        className="rounded-lg border border-border-light p-1.5 text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
        title={t('rfq_bidding.line_save', { defaultValue: 'Save line' })}
        aria-label={t('rfq_bidding.line_save', { defaultValue: 'Save line' })}
      >
        <Save className="h-3.5 w-3.5" aria-hidden />
      </button>
      <button
        type="button"
        disabled={remove.isPending}
        onClick={() => remove.mutate()}
        className="rounded-lg border border-border-light p-1.5 text-content-tertiary hover:border-semantic-error/40 hover:text-semantic-error"
        title={t('rfq_bidding.line_delete', { defaultValue: 'Delete line' })}
        aria-label={t('rfq_bidding.line_delete', { defaultValue: 'Delete line' })}
      >
        <Trash2 className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}

/**
 * The scope lines of an RFQ: add, change and remove them while it is a draft.
 * Once the RFQ is out the server freezes the scope, so the list is read-only.
 */
export function RfqLinesEditor({ rfq, t }: { rfq: RFQ; t: Translate }) {
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const editable = rfq.status === 'draft';
  const [description, setDescription] = useState('');
  const [unit, setUnit] = useState('');
  const [quantity, setQuantity] = useState('1');
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['rfq-bidding'] });

  const add = useMutation({
    mutationFn: () => addScopeLine(rfq.id, { description: description.trim(), unit: unit.trim(), quantity }),
    onSuccess: () => {
      setDescription('');
      setUnit('');
      setQuantity('1');
      refresh();
    },
    onError: (err: unknown) =>
      addToast({
        type: 'error',
        title: t('rfq_bidding.line_error', { defaultValue: 'Could not change the scope line' }),
        message: getErrorMessage(err),
      }),
  });

  const lines = rfq.lines ?? [];
  return (
    <fieldset data-testid="rfq-lines">
      <legend className="oe-label">{t('rfq_bidding.lines_label', { defaultValue: 'Scope lines' })}</legend>
      {!editable && (
        <p className="mb-2 text-xs text-content-tertiary">
          {t('rfq_bidding.lines_frozen', {
            defaultValue: 'Vendors have already been asked to price this scope, so the lines can no longer be changed.',
          })}
        </p>
      )}
      <div className="space-y-2">
        {lines.length === 0 && (
          <p className="text-xs text-content-tertiary">
            {t('rfq_bidding.lines_empty', { defaultValue: 'No scope lines yet.' })}
          </p>
        )}
        {editable
          ? lines.map((l) => (
              <LineRow key={`${l.id}:${l.updated_at}`} rfqId={rfq.id} line={l} onChanged={refresh} t={t} />
            ))
          : lines.map((l) => (
              <div key={l.id} className="flex gap-2 text-sm text-content-primary">
                <span className="w-6 text-xs text-content-tertiary">{l.line_no}</span>
                <span className="flex-1">{l.description}</span>
                <span className="text-content-secondary">
                  {l.quantity} {l.unit}
                </span>
              </div>
            ))}
        {editable && (
          <div className="flex items-center gap-2 pt-1">
            <span className="w-6" />
            <input
              className="oe-input flex-1"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('rfq_bidding.line_description', { defaultValue: 'Description' })}
              aria-label={t('rfq_bidding.line_new_description', { defaultValue: 'New line description' })}
            />
            <input
              className="oe-input w-16"
              value={unit}
              onChange={(e) => setUnit(e.target.value)}
              placeholder={t('rfq_bidding.line_unit', { defaultValue: 'Unit' })}
              aria-label={t('rfq_bidding.line_new_unit', { defaultValue: 'New line unit' })}
            />
            <input
              className="oe-input w-24"
              inputMode="decimal"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              aria-label={t('rfq_bidding.line_new_quantity', { defaultValue: 'New line quantity' })}
            />
            <button
              type="button"
              disabled={!description.trim() || !unit.trim() || add.isPending}
              onClick={() => add.mutate()}
              className="flex items-center gap-1 rounded-lg border border-border-light px-2 py-1.5 text-xs font-medium text-content-primary hover:bg-surface-secondary disabled:opacity-40"
            >
              <Plus className="h-3.5 w-3.5" aria-hidden />
              {t('rfq_bidding.line_add', { defaultValue: 'Add line' })}
            </button>
          </div>
        )}
      </div>
    </fieldset>
  );
}
