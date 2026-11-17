// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Price a change from one sealed position: the sealed resources on the
 * inline-start side, this change beside them, then every method the market
 * shows. The engine never picks; a person records the method.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronRight, Plus } from 'lucide-react';
import { Button, MoneyDisplay, SideDrawer } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import {
  archiveApi,
  type BasisMethod,
  type DeriveRequest,
  type ResourceAddition,
  type ResourceChange,
  type SealedPosition,
} from './api';
import { fmtDecimal, fmtRate, fmtStepPercent } from './format';

const blankAddition = (): ResourceAddition => ({
  kind: 'other',
  code: '',
  description: '',
  unit: '',
  consumption: '1',
  unit_cost: '0',
  price_date: '',
  quote_ref: '',
});

export function PricingDrawer({
  sealId,
  position,
  currency,
  variationRequestId,
  onRecorded,
  onClose,
}: {
  sealId: string;
  position: SealedPosition;
  currency: string;
  /** Write the priced line into this variation's own bill, traced to the seal. */
  variationRequestId?: string;
  onRecorded?: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [quantity, setQuantity] = useState(position.quantity);
  const [reference, setReference] = useState('');
  const [changes, setChanges] = useState<Record<string, ResourceChange>>({});
  const [additions, setAdditions] = useState<ResourceAddition[]>([]);
  const [chosen, setChosen] = useState<BasisMethod | null>(null);

  const request: DeriveRequest = useMemo(
    () => ({
      position_ordinal: position.ordinal,
      quantity: quantity || null,
      changes: Object.values(changes).filter((c) => c.consumption != null || c.unit_cost != null || c.note),
      additions: additions.filter((a) => a.description.trim()),
      removals: [],
      current_unit_costs: {},
    }),
    [position.ordinal, quantity, changes, additions],
  );
  const derived = useQuery({
    queryKey: ['estimate-archive', 'derive', sealId, JSON.stringify(request)],
    queryFn: () => archiveApi.derive(sealId, request),
    placeholderData: (prev) => prev,
  });
  const record = useMutation({
    mutationFn: () =>
      archiveApi.recordDerivation(sealId, {
        ...request,
        reference_label: reference,
        basis_method: chosen,
        variation_request_id: variationRequestId ?? null,
        write_to_variation_bill: !!variationRequestId,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['estimate-archive'] });
      onRecorded?.();
      onClose();
    },
  });

  const r = derived.data?.result;
  const findings = derived.data?.findings ?? [];
  const setChange = (code: string, patch: Partial<ResourceChange>) =>
    setChanges((c) => ({ ...c, [code]: { ...(c[code] ?? { code }), ...patch } }));
  const deviationFor = (code: string) =>
    findings.find((f) => f.code === 'VAR_BASIS_DEVIATION' && f.message.includes(code) && !changes[code]?.note);
  const methodLabel = (m: BasisMethod) =>
    t(`estimate_archive.method.${m}`, {
      defaultValue: {
        original_basis: 'Original basis',
        cost_plus_markup: 'Cost plus markups',
        agreed: 'Agreed rate',
        daywork: 'Daywork',
      }[m],
    });
  const order = derived.data?.methods_order ?? [];
  const methods = [...(r?.methods ?? [])].sort((a, b) => order.indexOf(a.method) - order.indexOf(b.method));

  return (
    <SideDrawer
      open
      onClose={onClose}
      widthClass="max-w-5xl"
      busy={record.isPending}
      title={
        <span className="flex items-baseline gap-2">
          <bdi dir="ltr" className="font-mono">{position.ordinal}</bdi>
          <span>{position.description}</span>
        </span>
      }
      subtitle={position.unit}
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1 text-xs font-medium text-content-secondary">
            {t('estimate_archive.price.reference', { defaultValue: 'Change reference' })}
            <input className="oe-input" value={reference} onChange={(e) => setReference(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-content-secondary">
            {t('estimate_archive.price.quantity', { defaultValue: 'Quantity of the change' })}
            <input dir="ltr" className="oe-input" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          </label>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light text-xs text-content-tertiary">
              <th className="px-2 py-1.5 text-start font-medium">{t('estimate_archive.price.resource', { defaultValue: 'Resource' })}</th>
              <th className="px-2 py-1.5 text-end font-medium">{t('estimate_archive.price.sealed', { defaultValue: 'Sealed (frozen)' })}</th>
              <th className="px-2 py-1.5 text-start font-medium">{t('estimate_archive.price.this_change', { defaultValue: 'This change' })}</th>
              <th className="px-2 py-1.5 text-start font-medium">{t('estimate_archive.price.note', { defaultValue: 'Note (required if changed)' })}</th>
            </tr>
          </thead>
          <tbody aria-live="polite">
            {position.resources.map((res) => {
              const sealed = r?.sealed_lines.find((l) => l.code === res.code);
              const changed = r?.changed_lines.find((l) => l.code === res.code && l.origin !== 'new');
              const hint = deviationFor(res.code);
              return (
                <tr key={res.code} className="border-b border-border-light align-top">
                  <td className="px-2 py-1.5">
                    <div>{res.description}</div>
                    <bdi dir="ltr" className="font-mono text-xs text-content-tertiary">{res.code} · {res.unit}</bdi>
                  </td>
                  <td className="px-2 py-1.5 text-end font-mono text-xs" dir="ltr">
                    {fmtDecimal(res.consumption)} × {fmtRate(res.unit_cost)} = {fmtRate(sealed?.amount)}
                  </td>
                  <td className="px-2 py-1.5">
                    <div className="flex items-center gap-1 font-mono text-xs" dir="ltr">
                      <input
                        className="oe-input w-20"
                        aria-label={t('estimate_archive.price.consumption', { defaultValue: 'Consumption' })}
                        defaultValue={res.consumption}
                        onBlur={(e) =>
                          setChange(res.code, { consumption: e.target.value === res.consumption ? null : e.target.value })
                        }
                      />
                      ×
                      <input
                        className="oe-input w-24"
                        aria-label={t('estimate_archive.price.unit_cost', { defaultValue: 'Unit cost' })}
                        defaultValue={res.unit_cost}
                        onBlur={(e) =>
                          setChange(res.code, { unit_cost: e.target.value === res.unit_cost ? null : e.target.value })
                        }
                      />
                      = {fmtRate(changed?.amount)}
                    </div>
                  </td>
                  <td className="px-2 py-1.5">
                    <input
                      className="oe-input"
                      aria-label={t('estimate_archive.price.note', { defaultValue: 'Note (required if changed)' })}
                      value={changes[res.code]?.note ?? ''}
                      onChange={(e) => setChange(res.code, { note: e.target.value })}
                    />
                    {hint && <p className="mt-1 text-xs text-semantic-warning">{hint.message}</p>}
                  </td>
                </tr>
              );
            })}
            {additions.map((a, i) => (
              <tr key={`add-${i}`} className="border-b border-border-light align-top">
                <td className="px-2 py-1.5" colSpan={2}>
                  <input
                    className="oe-input"
                    placeholder={t('estimate_archive.price.new_resource', { defaultValue: 'New resource' })}
                    value={a.description}
                    onChange={(e) => setAdditions((l) => l.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)))}
                  />
                </td>
                <td className="px-2 py-1.5">
                  <div className="flex items-center gap-1 font-mono text-xs" dir="ltr">
                    <input
                      className="oe-input w-20"
                      aria-label={t('estimate_archive.price.consumption', { defaultValue: 'Consumption' })}
                      value={a.consumption}
                      onChange={(e) => setAdditions((l) => l.map((x, j) => (j === i ? { ...x, consumption: e.target.value } : x)))}
                    />
                    ×
                    <input
                      className="oe-input w-24"
                      aria-label={t('estimate_archive.price.unit_cost', { defaultValue: 'Unit cost' })}
                      value={a.unit_cost}
                      onChange={(e) => setAdditions((l) => l.map((x, j) => (j === i ? { ...x, unit_cost: e.target.value } : x)))}
                    />
                  </div>
                </td>
                <td className="px-2 py-1.5">
                  <input
                    className="oe-input"
                    placeholder={t('estimate_archive.price.quote_ref', { defaultValue: 'Quote or price date' })}
                    value={a.quote_ref}
                    onChange={(e) => setAdditions((l) => l.map((x, j) => (j === i ? { ...x, quote_ref: e.target.value } : x)))}
                  />
                  {findings.some((f) => f.code === 'VAR_NEW_RESOURCE_NO_EVIDENCE') && !a.quote_ref && !a.price_date && (
                    <p className="mt-1 text-xs text-semantic-warning">
                      {findings.find((f) => f.code === 'VAR_NEW_RESOURCE_NO_EVIDENCE')?.message}
                    </p>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <Button variant="ghost" size="sm" icon={<Plus size={14} />} onClick={() => setAdditions((l) => [...l, blankAddition()])}>
          {t('estimate_archive.price.add_resource', { defaultValue: 'Add resource' })}
        </Button>
        {r && (
          <dl className="grid grid-cols-3 gap-2 rounded-lg border border-border-light p-3 text-sm">
            <dt className="text-content-secondary">{t('estimate_archive.price.net', { defaultValue: 'Net' })}</dt>
            <dd className="text-end font-mono" dir="ltr">{fmtRate(r.sealed_net)}</dd>
            <dd className="text-end font-mono" dir="ltr">{fmtRate(r.changed_net)}</dd>
            <dt className="text-content-secondary">
              {t('estimate_archive.price.markups', { defaultValue: 'Markups (sealed stack, read-only)' })}
            </dt>
            <dd className="col-span-2 flex flex-wrap items-center justify-end gap-1 text-xs">
              {r.markup_steps.map((s, i) => (
                <span key={`${s.key}-${i}`} className="inline-flex items-center gap-1">
                  {i > 0 && <ChevronRight size={12} aria-hidden className="text-content-tertiary rtl:rotate-180" />}
                  {s.name} {fmtStepPercent(s.percentage)}
                </span>
              ))}
            </dd>
            <dt className="text-content-secondary">{t('estimate_archive.price.rate', { defaultValue: 'Rate' })}</dt>
            <dd className="text-end font-mono" dir="ltr">{fmtRate(r.sealed_rate)}</dd>
            <dd className="text-end font-mono font-semibold" dir="ltr">{fmtRate(r.original_basis_rate)}</dd>
          </dl>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          {methods.map((m) => (
            <div key={m.method} className="rounded-lg border border-border-light p-3">
              <div className="text-sm font-medium">{methodLabel(m.method)}</div>
              <div className="mt-1 font-mono text-sm" dir="ltr">
                {fmtRate(m.rate)} × {fmtDecimal(r?.quantity)} = <MoneyDisplay amount={m.total} currency={currency} />
              </div>
              <Button
                className="mt-2"
                size="sm"
                variant={chosen === m.method ? 'primary' : 'secondary'}
                aria-pressed={chosen === m.method}
                onClick={() => setChosen(m.method)}
              >
                {t('estimate_archive.use_method', { defaultValue: 'Use {{method}}', method: methodLabel(m.method) })}
              </Button>
            </div>
          ))}
        </div>
        {!!derived.data?.citations.length && (
          <p className="text-xs text-content-tertiary">{derived.data.citations.join(' · ')}</p>
        )}
        {derived.isError && <p className="text-sm text-semantic-error">{getErrorMessage(derived.error)}</p>}
        {record.isError && <p className="text-sm text-semantic-error">{getErrorMessage(record.error)}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" disabled={!reference.trim() || !r} onClick={() => record.mutate()}>
            {t('estimate_archive.price.record', { defaultValue: 'Record priced change' })}
          </Button>
        </div>
      </div>
    </SideDrawer>
  );
}
