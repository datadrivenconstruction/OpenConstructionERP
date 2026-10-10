// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The rates of one country that wait for a local specialist's confirmation,
 * each with a form to record it.
 *
 * A rate marked this way resolves to nothing until it is confirmed, so the
 * resolver panel shows this list in place of a number. Confirming records who
 * confirmed it and against which official source; the server keeps that on the
 * rate and in the audit log. Only an admin may confirm, which the server
 * enforces; a refused request shows its error here.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/shared/ui/Button';
import { Input } from '@/shared/ui/Input';
import { confirmTaxConfig, listTaxConfigs, type TaxConfigRow } from './api';

function isPending(row: TaxConfigRow): boolean {
  const block = row.metadata?.local_confirmation;
  return Boolean(block?.required) && block?.status !== 'confirmed';
}

function ConfirmRow({ row }: { row: TaxConfigRow }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [accountant, setAccountant] = useState('');
  const [source, setSource] = useState('');
  const mutation = useMutation({
    mutationFn: () =>
      confirmTaxConfig(row.id, {
        accountant_name: accountant.trim(),
        source_reference: source.trim(),
      }),
    onSuccess: () => queryClient.invalidateQueries(),
  });
  const ready = accountant.trim() !== '' && source.trim() !== '';

  return (
    <li className="rounded-md border border-border-light p-3" data-testid="tax-pending-row">
      <p className="text-sm font-medium text-content-primary">
        {row.tax_name} · {row.rate_pct}%{row.subdivision_code ? ` · ${row.subdivision_code}` : ''}
        {row.effective_from ? ` · ${row.effective_from}` : ''}
      </p>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <Input
          label={t('tax_rates.confirm_accountant_label', { defaultValue: 'Confirmed by' })}
          value={accountant}
          onChange={(e) => setAccountant(e.target.value)}
        />
        <Input
          label={t('tax_rates.confirm_source_label', {
            defaultValue: 'Official source checked',
          })}
          value={source}
          onChange={(e) => setSource(e.target.value)}
        />
      </div>
      {mutation.isError && (
        <p className="mt-2 text-xs text-semantic-error">
          {t('tax_rates.confirm_failed', {
            defaultValue: 'The confirmation was not saved. Only an administrator can confirm a rate.',
          })}
        </p>
      )}
      <div className="mt-2">
        <Button
          variant="primary"
          disabled={!ready || mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          {t('tax_rates.confirm_action', { defaultValue: 'Record confirmation' })}
        </Button>
      </div>
    </li>
  );
}

export function PendingConfirmations({ country }: { country: string }) {
  const { t } = useTranslation();
  const query = useQuery({
    queryKey: ['tax-configs', 'all', country],
    queryFn: () => listTaxConfigs(country),
  });
  const pending = (query.data?.items ?? []).filter(isPending);
  if (pending.length === 0) return null;

  return (
    <div className="mt-3">
      <p className="text-xs font-semibold text-content-secondary">
        {t('tax_rates.pending_list_title', { defaultValue: 'Rates waiting for confirmation' })}
      </p>
      <ul className="mt-2 space-y-2">
        {pending.map((row) => (
          <ConfirmRow key={row.id} row={row} />
        ))}
      </ul>
    </div>
  );
}
