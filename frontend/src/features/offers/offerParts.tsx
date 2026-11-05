/** Small, separately testable pieces of the offer page: send action, placeholder chips, customer flow, accept dialog. */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Send } from 'lucide-react';
import { Button } from '@/shared/ui/Button';
import { TEXT_PLACEHOLDERS, createCustomer, type Offer } from './api';

/** The primary action. While an error stands it is disabled and the first error is shown, not only hinted. */
export function SendAction({
  canSend,
  firstError,
  pending,
  onSend,
}: {
  canSend: boolean;
  firstError: string | null;
  pending: boolean;
  onSend: () => void;
}) {
  const { t } = useTranslation();
  return (
    <span className="flex flex-col items-end">
      <Button size="sm" icon={<Send size={14} />} disabled={!canSend || pending} onClick={onSend} title={!canSend ? (firstError ?? '') : undefined}>
        {t('offers.download_mark_sent', { defaultValue: 'Download and mark sent' })}
      </Button>
      {!canSend && firstError && (
        <span role="note" data-testid="send-blocked-reason" className="mt-1 max-w-xs text-right text-xs text-semantic-error">
          {firstError}
        </span>
      )}
    </span>
  );
}

/** Click a chip to insert its `{placeholder}` at the caret. */
export function PlaceholderChips({ onInsert }: { onInsert: (token: string) => void }) {
  const { t } = useTranslation();
  return (
    <div className="mb-1 flex flex-wrap gap-1 text-xs">
      <span className="text-content-tertiary">{t('offers.texts.insert', { defaultValue: 'Insert' })}:</span>
      {TEXT_PLACEHOLDERS.map((name) => (
        <button key={name} type="button" className="rounded border border-border-light px-1.5" onClick={() => onInsert(`{${name}}`)}>
          {`{${name}}`}
        </button>
      ))}
    </div>
  );
}

/** "Who is this offer for?" with one-click customer creation; the new contact is picked at once. */
export function CustomerEmpty({
  projectId,
  country,
  onCreated,
}: {
  projectId: string;
  country: string;
  onCreated: (contactId: string) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [asClient, setAsClient] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const save = async () => {
    setBusy(true);
    setError('');
    try {
      const contact = await createCustomer({ name, email, country, projectId, setAsProjectClient: asClient });
      onCreated(contact.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <div className="rounded-lg border border-dashed border-border-light p-4">
        <p className="mb-2 text-sm font-medium">{t('offers.customer_empty', { defaultValue: 'Who is this offer for?' })}</p>
        <Button size="sm" onClick={() => setOpen(true)}>
          {t('offers.add_customer', { defaultValue: 'Add customer' })}
        </Button>
      </div>
    );
  }
  return (
    <form
      className="space-y-2 rounded-lg border border-border-light p-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim()) void save();
      }}
    >
      <input
        className="h-9 w-full rounded-md border border-border-light bg-surface-primary px-2.5 text-sm"
        value={name}
        onChange={(e) => setName(e.target.value)}
        aria-label={t('offers.customer_name', { defaultValue: 'Customer name' })}
        placeholder={t('offers.customer_name', { defaultValue: 'Customer name' })}
      />
      <input
        className="h-9 w-full rounded-md border border-border-light bg-surface-primary px-2.5 text-sm"
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        aria-label={t('offers.customer_email', { defaultValue: 'E-mail' })}
        placeholder={t('offers.customer_email', { defaultValue: 'E-mail' })}
      />
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={asClient} onChange={(e) => setAsClient(e.target.checked)} />
        {t('offers.set_project_client', { defaultValue: 'Also set as the project client' })}
      </label>
      {error && <p className="text-xs text-semantic-error">{error}</p>}
      <Button size="sm" type="submit" disabled={busy || !name.trim()}>
        {t('offers.add_customer', { defaultValue: 'Add customer' })}
      </Button>
    </form>
  );
}

/** Confirm an acceptance: date, which optional items the customer took, and the contract step. */
export function AcceptDialog({
  offer,
  canCreateContract,
  pending,
  onConfirm,
  onCancel,
}: {
  offer: Offer;
  canCreateContract: boolean;
  pending: boolean;
  onConfirm: (body: { accepted_on: string; optional_ordinals: string[]; create_contract: boolean }) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [ticked, setTicked] = useState<string[]>([]);
  const [contract, setContract] = useState(canCreateContract);
  const toggle = (ordinal: string) => setTicked((cur) => (cur.includes(ordinal) ? cur.filter((o) => o !== ordinal) : [...cur, ordinal]));

  return (
    <div role="dialog" aria-modal="true" aria-label={t('offers.mark_accepted', { defaultValue: 'Mark accepted' })} className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-md space-y-3 rounded-lg bg-surface-primary p-5 shadow-xl">
        <h2 className="text-base font-semibold">{t('offers.mark_accepted', { defaultValue: 'Mark accepted' })}</h2>
        <label className="block text-sm">
          {t('offers.accepted_on', { defaultValue: 'Accepted on' })}
          <input type="date" className="mt-1 h-9 w-full rounded-md border border-border-light bg-surface-primary px-2.5 text-sm" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        {offer.totals.not_included.length > 0 && (
          <fieldset>
            <legend className="text-sm font-medium">{t('offers.accept_options', { defaultValue: 'Optional items the customer took' })}</legend>
            {offer.totals.not_included.map((n) => (
              <label key={n.ordinal} className="flex items-center gap-2 py-0.5 text-sm">
                <input type="checkbox" checked={ticked.includes(n.ordinal)} onChange={() => toggle(n.ordinal)} />
                <span>
                  {n.ordinal} {n.description}
                </span>
                <span className="ml-auto tabular-nums">{n.total}</span>
              </label>
            ))}
          </fieldset>
        )}
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={contract && canCreateContract} disabled={!canCreateContract} onChange={(e) => setContract(e.target.checked)} />
          {t('offers.create_contract', { defaultValue: 'Create client contract' })}
        </label>
        {!canCreateContract && (
          <p role="note" data-testid="contract-blocked-reason" className="text-xs text-content-tertiary">
            {t('offers.contract_needs_permission', { defaultValue: 'You can accept the offer, but creating the contract needs the contracts permission.' })}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button size="sm" disabled={pending} onClick={() => onConfirm({ accepted_on: date, optional_ordinals: ticked, create_contract: contract && canCreateContract })}>
            {t('offers.mark_accepted', { defaultValue: 'Mark accepted' })}
          </Button>
        </div>
      </div>
    </div>
  );
}
