// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// ContractPartiesPanel — who the contract is between.
//
// The register had endpoints and no screen. Nothing in the app could add a
// party, which mattered once the signing bridge started deriving its
// signatories from this list and refusing a contract that had nobody in a
// signing role: the refusal named a register the user could not open.
//
// A contract also carries an older counterparty_type / counterparty_id pair,
// shown in the header above. That pair is one side and a category; this is the
// full list with roles. They are deliberately not merged here. Folding the
// legacy pair in as a synthetic row would put a party in the list that cannot
// be edited or removed like the others, and quietly change what the signature
// block is derived from.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Users, Plus, Trash2, PenLine } from 'lucide-react';

import { Button, Badge } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  listContractParties,
  createContractParty,
  deleteContractParty,
  CONTRACT_PARTY_ROLES,
  SIGNING_PARTY_ROLES,
  type ContractParty,
} from './api';

// Last-resort English, worded exactly as en.ts words it. Every role is in all
// 29 locale files, so these should never render; they exist because each t()
// in this tree carries a defaultValue.
const ROLE_LABELS: Record<string, string> = {
  employer: 'Employer',
  contractor: 'Contractor',
  subcontractor: 'Subcontractor',
  consultant: 'Consultant',
  architect: 'Architect',
  engineer: 'Engineer',
  guarantor: 'Guarantor',
  other: 'Other',
};

interface ContractPartiesPanelProps {
  contractId: string;
}

// The register stays editable after the contract leaves draft, because the API
// allows it and a party can genuinely change mid-contract through novation or
// a change of guarantor. Freezing it in the UI only would be this screen
// guessing at a rule the module has not made.
export function ContractPartiesPanel({ contractId }: ContractPartiesPanelProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [adding, setAdding] = useState(false);
  const [role, setRole] = useState<string>('employer');
  const [name, setName] = useState('');

  const partiesQ = useQuery<ContractParty[]>({
    queryKey: ['contracts', 'parties', contractId],
    queryFn: () => listContractParties(contractId),
  });
  const parties = partiesQ.data ?? [];

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['contracts', 'parties', contractId] });
    // The signing panel derives its signatory list from these rows, so a party
    // added here has to reach it without a reload.
    qc.invalidateQueries({
      queryKey: ['contracts', 'signing-sessions', contractId],
    });
  };

  const addMut = useMutation({
    mutationFn: () =>
      createContractParty(contractId, {
        contract_id: contractId,
        party_role: role,
        // No contact was picked, so the name stands on its own rather than
        // claiming a link into a register it did not come from.
        party_type: 'external',
        display_name: name.trim(),
        is_primary: parties.length === 0,
      }),
    onSuccess: () => {
      invalidate();
      setName('');
      setAdding(false);
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const removeMut = useMutation({
    mutationFn: (partyId: string) => deleteContractParty(partyId),
    onSuccess: invalidate,
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const roleLabel = (value: string) =>
    t(`contracts.party_role.${value}`, {
      defaultValue: ROLE_LABELS[value] ?? value,
    });

  const signingCount = parties.filter((p) =>
    SIGNING_PARTY_ROLES.includes(p.party_role as never),
  ).length;

  const canSubmit = name.trim().length > 0 && !addMut.isPending;

  return (
    <div className="rounded-lg border border-border-light">
      <header className="flex items-center justify-between gap-2 border-b border-border-light px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Users size={15} className="text-content-tertiary" />
          <span className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
            {t('contracts.parties.title', { defaultValue: 'Parties' })}
          </span>
        </div>
        {!adding && (
          <Button
            variant="ghost"
            size="sm"
            icon={<Plus size={14} />}
            onClick={() => setAdding(true)}
          >
            {t('contracts.parties.add', { defaultValue: 'Add party' })}
          </Button>
        )}
      </header>

      <div className="px-4 py-3">
        {partiesQ.isLoading && (
          <p className="text-sm text-content-tertiary">
            {t('common.loading', { defaultValue: 'Loading...' })}
          </p>
        )}

        {!partiesQ.isLoading && parties.length === 0 && (
          <p className="text-sm text-content-tertiary">
            {t('contracts.parties.empty', {
              defaultValue:
                'No parties yet. A contract needs the two sides that sign it before it can be put up for signature.',
            })}
          </p>
        )}

        {parties.length > 0 && (
          <ul className="divide-y divide-border-light">
            {parties.map((p) => (
              <li
                key={p.id}
                className="flex items-center justify-between gap-3 py-2 first:pt-0 last:pb-0"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <Badge variant="neutral" size="sm">
                    {roleLabel(p.party_role)}
                  </Badge>
                  <span className="truncate text-sm text-content-primary">
                    {/* The resolved name is the current one where display_name
                        is a copy taken when the row was written. */}
                    {p.resolved_name || p.display_name}
                  </span>
                  {p.is_primary && (
                    <Badge variant="blue" size="sm">
                      {t('contracts.parties.primary', {
                        defaultValue: 'Primary',
                      })}
                    </Badge>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Trash2 size={14} />}
                  aria-label={t('contracts.parties.remove', {
                    defaultValue: 'Remove party',
                  })}
                  onClick={() => removeMut.mutate(p.id)}
                  disabled={removeMut.isPending}
                />
              </li>
            ))}
          </ul>
        )}

        {adding && (
          <div className="mt-3 flex flex-wrap items-end gap-2 rounded-lg bg-surface-secondary p-3">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-content-tertiary">
                {t('contracts.parties.role', { defaultValue: 'Role' })}
              </span>
              <select
                className="rounded-md border border-border-light bg-surface-elevated px-2 py-1.5 text-sm"
                value={role}
                onChange={(e) => setRole(e.target.value)}
              >
                {CONTRACT_PARTY_ROLES.map((r) => (
                  <option key={r} value={r}>
                    {roleLabel(r)}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex min-w-[14rem] flex-1 flex-col gap-1">
              <span className="text-xs text-content-tertiary">
                {t('contracts.parties.name', { defaultValue: 'Name' })}
              </span>
              <input
                className="rounded-md border border-border-light bg-surface-elevated px-2 py-1.5 text-sm"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && canSubmit) addMut.mutate();
                }}
                autoComplete="organization"
              />
            </label>
            <Button
              variant="primary"
              size="sm"
              onClick={() => addMut.mutate()}
              disabled={!canSubmit}
              loading={addMut.isPending}
            >
              {t('common.add', { defaultValue: 'Add' })}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setAdding(false);
                setName('');
              }}
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        )}

        {/* Says which of these rows the signature block will be built from, so
            a register full of consultants does not look ready when it is not. */}
        {parties.length > 0 && (
          <p className="mt-3 flex items-center gap-1.5 text-xs text-content-tertiary">
            <PenLine size={12} />
            {signingCount === 0
              ? t('contracts.parties.none_sign', {
                  defaultValue:
                    'None of these roles sign the contract. Add an employer and a contractor.',
                })
              : t('contracts.parties.who_signs', {
                  defaultValue:
                    'The employer, contractor and subcontractor rows are the ones asked to sign.',
                })}
          </p>
        )}
      </div>
    </div>
  );
}
