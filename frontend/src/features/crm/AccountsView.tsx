/**
 * Accounts tab: every account with the contacts linked to it.
 *
 * People live in the Contacts module. An account only links to them, so the
 * picker below offers existing contacts and nothing is typed in twice.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, Star, Unlink, Building2 } from 'lucide-react';
import { Button, Badge, EmptyState } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { fetchContacts, type Contact } from '@/features/contacts/api';
import {
  linkAccountContact,
  listAccountContacts,
  unlinkAccountContact,
  type Account,
} from './api';

function contactName(c: Contact): string {
  return (
    [c.first_name, c.last_name].filter(Boolean).join(' ') ||
    c.company_name ||
    c.primary_email ||
    c.id
  );
}

export function AccountContactsPanel({ accountId }: { accountId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [pick, setPick] = useState('');
  const [role, setRole] = useState('');

  const linksQ = useQuery({
    queryKey: ['crm', 'account-contacts', accountId],
    queryFn: () => listAccountContacts(accountId),
  });
  const contactsQ = useQuery({
    queryKey: ['contacts', 'picker'],
    queryFn: () => fetchContacts({ limit: 500 }),
    staleTime: 60_000,
  });

  const linkedIds = useMemo(
    () => new Set((linksQ.data ?? []).map((l) => l.contact_id)),
    [linksQ.data],
  );
  const options = useMemo(
    () => (contactsQ.data?.items ?? []).filter((c) => !linkedIds.has(c.id)),
    [contactsQ.data, linkedIds],
  );

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['crm', 'account-contacts', accountId] });
    qc.invalidateQueries({ queryKey: ['crm', 'accounts'] });
  };
  const onError = (err: unknown) => addToast({ type: 'error', title: getErrorMessage(err) });

  const linkMut = useMutation({
    mutationFn: () => linkAccountContact(accountId, { contact_id: pick, role: role.trim() }),
    onSuccess: () => {
      setPick('');
      setRole('');
      refresh();
      addToast({ type: 'success', title: t('crm.acct_contact_linked', { defaultValue: 'Contact linked' }) });
    },
    onError,
  });
  const primaryMut = useMutation({
    mutationFn: (contactId: string) => linkAccountContact(accountId, { contact_id: contactId, is_primary: true }),
    onSuccess: refresh,
    onError,
  });
  const unlinkMut = useMutation({
    mutationFn: (contactId: string) => unlinkAccountContact(accountId, contactId),
    onSuccess: refresh,
    onError,
  });

  const links = linksQ.data ?? [];

  return (
    <div className="space-y-3 px-4 py-3">
      {links.length === 0 && !linksQ.isLoading ? (
        <p className="text-sm text-content-tertiary">
          {t('crm.acct_contacts_empty', { defaultValue: 'No contacts linked to this account yet.' })}
        </p>
      ) : (
        <ul className="divide-y divide-border-light">
          {links.map((l) => (
            <li key={l.contact_id} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span className="min-w-0">
                <span className="flex items-center gap-2 font-medium text-content-primary">
                  {l.display_name}
                  {l.is_primary && (
                    <Badge variant="blue">
                      {t('crm.acct_contact_primary', { defaultValue: 'Primary' })}
                    </Badge>
                  )}
                  {l.role && <span className="text-xs font-normal text-content-tertiary">{l.role}</span>}
                </span>
                <span className="block truncate text-xs text-content-tertiary">
                  {[l.email, l.phone].filter(Boolean).join(' · ')}
                </span>
              </span>
              <span className="flex shrink-0 gap-1">
                {!l.is_primary && (
                  <button
                    type="button"
                    className="rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
                    title={t('crm.acct_make_primary', { defaultValue: 'Make primary contact' })}
                    aria-label={t('crm.acct_make_primary', { defaultValue: 'Make primary contact' })}
                    onClick={() => primaryMut.mutate(l.contact_id)}
                  >
                    <Star size={14} />
                  </button>
                )}
                <button
                  type="button"
                  className="rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-semantic-error"
                  title={t('crm.acct_unlink_contact', { defaultValue: 'Unlink contact' })}
                  aria-label={t('crm.acct_unlink_contact', { defaultValue: 'Unlink contact' })}
                  onClick={() => unlinkMut.mutate(l.contact_id)}
                >
                  <Unlink size={14} />
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-[14rem] flex-1 text-xs text-content-secondary">
          {t('crm.acct_pick_contact', { defaultValue: 'Link an existing contact' })}
          <select
            value={pick}
            onChange={(e) => setPick(e.target.value)}
            className="oe-select mt-1 w-full"
            data-testid="account-contact-select"
          >
            <option value="">{t('crm.acct_pick_placeholder', { defaultValue: 'Select a contact' })}</option>
            {options.map((c) => (
              <option key={c.id} value={c.id}>
                {contactName(c)}
              </option>
            ))}
          </select>
        </label>
        <label className="w-40 text-xs text-content-secondary">
          {t('crm.acct_contact_role', { defaultValue: 'Role' })}
          <input
            value={role}
            maxLength={64}
            onChange={(e) => setRole(e.target.value)}
            className="oe-input mt-1 w-full"
          />
        </label>
        <Button
          variant="secondary"
          size="sm"
          disabled={!pick || linkMut.isPending}
          onClick={() => linkMut.mutate()}
        >
          {t('crm.acct_link_contact', { defaultValue: 'Link contact' })}
        </Button>
      </div>
    </div>
  );
}

export function AccountsView({ accounts }: { accounts: Account[] }) {
  const { t } = useTranslation();
  const [openId, setOpenId] = useState<string | null>(null);

  if (accounts.length === 0) {
    return (
      <EmptyState
        icon={<Building2 size={22} />}
        title={t('crm.acct_empty', { defaultValue: 'No accounts yet' })}
        description={t('crm.acct_empty_hint', {
          defaultValue: 'Accounts are created with the first deal. Contacts are then linked here.',
        })}
      />
    );
  }

  return (
    <ul className="divide-y divide-border-light" data-testid="accounts-view">
      {accounts.map((a) => {
        const open = openId === a.id;
        return (
          <li key={a.id}>
            <button
              type="button"
              className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm hover:bg-surface-secondary"
              aria-expanded={open}
              onClick={() => setOpenId(open ? null : a.id)}
            >
              {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              <span className="font-medium text-content-primary">{a.name}</span>
              {a.industry && <span className="text-xs text-content-tertiary">{a.industry}</span>}
              {a.country && <span className="ml-auto text-xs text-content-tertiary">{a.country}</span>}
            </button>
            {open && <AccountContactsPanel accountId={a.id} />}
          </li>
        );
      })}
    </ul>
  );
}
