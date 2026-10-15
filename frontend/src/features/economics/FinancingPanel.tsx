// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The financing plan: the sources of finance with their drawdown tranches, and
// the coverage check against the investment. A shortfall and a surplus are
// shown apart, so neither hides the other.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { addSource, addTranche, deleteSource, deleteTranche, type Financing, type SourceKind } from './api';
import { AddRow, ConfirmDelete, Field, cleanDecimal, inputClass, isDecimal, useMoney } from './EconomicsBits';
import { useEconomicsAction } from './hooks';
import { SOURCE_KIND } from './labels';

const KINDS = Object.keys(SOURCE_KIND) as SourceKind[];
const DATE = /^\d{4}-\d{2}-\d{2}$/;

function TrancheForm({ projectId, sourceId }: { projectId: string; sourceId: string }) {
  const { t } = useTranslation();
  const [due, setDue] = useState('');
  const [amount, setAmount] = useState('');
  const add = useEconomicsAction(projectId, (body: Record<string, unknown>) => addTranche(projectId, sourceId, body));
  return (
    <AddRow
      submitLabel={t('economics.financing.add_tranche', { defaultValue: 'Add a tranche' })}
      disabled={!DATE.test(due) || !isDecimal(amount || 'x')}
      onSubmit={async () => {
        await add({ due_on: due, amount: cleanDecimal(amount) });
        setDue('');
        setAmount('');
      }}
    >
      <Field label={t('economics.financing.due_on', { defaultValue: 'Due on (YYYY-MM-DD)' })}>
        <input className={`${inputClass} w-36`} value={due} onChange={(e) => setDue(e.target.value)} />
      </Field>
      <Field label={t('economics.case.col_amount', { defaultValue: 'Amount' })}>
        <input className={`${inputClass} w-32 text-right`} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
      </Field>
    </AddRow>
  );
}

export function FinancingPanel({
  projectId,
  data,
  editable,
}: {
  projectId: string;
  data: Financing;
  editable: boolean;
}) {
  const { t } = useTranslation();
  const { money, plain } = useMoney(data.currency);
  const [kind, setKind] = useState<SourceKind>('bank_loan');
  const [name, setName] = useState('');
  const [amount, setAmount] = useState('');
  const [rate, setRate] = useState('');

  const add = useEconomicsAction(projectId, (body: Record<string, unknown>) => addSource(projectId, body));
  const removeSource = useEconomicsAction(projectId, (id: string) => deleteSource(projectId, id));
  const removeTranche = useEconomicsAction(projectId, (id: string) => deleteTranche(projectId, id));
  const cov = data.coverage;

  return (
    <div className="space-y-4" data-testid="economics-financing">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-lg border border-border p-3">
          <div className="text-xs text-content-secondary">{t('economics.financing.requirement', { defaultValue: 'Requirement' })}</div>
          <div className="text-lg font-semibold tabular-nums">{money(data.requirement)}</div>
        </div>
        <div className="rounded-lg border border-border p-3">
          <div className="text-xs text-content-secondary">{t('economics.financing.sources_total', { defaultValue: 'Sources of finance' })}</div>
          <div className="text-lg font-semibold tabular-nums">{money(cov.sources_total)}</div>
        </div>
        <div className="rounded-lg border border-border p-3" data-testid="economics-shortfall">
          <div className="text-xs text-content-secondary">{t('economics.financing.shortfall', { defaultValue: 'Shortfall' })}</div>
          <div className={cov.covered ? 'text-lg font-semibold tabular-nums' : 'text-lg font-semibold tabular-nums text-semantic-error'}>
            {money(cov.shortfall)}
          </div>
        </div>
        <div className="rounded-lg border border-border p-3">
          <div className="text-xs text-content-secondary">{t('economics.financing.surplus', { defaultValue: 'Surplus' })}</div>
          <div className="text-lg font-semibold tabular-nums">{money(cov.surplus)}</div>
        </div>
      </div>

      <div className="space-y-3">
        {data.sources.map((source) => (
          <div key={source.id} className="rounded-lg border border-border p-3" data-testid="economics-source">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div>
                <span className="font-medium">{source.name}</span>
                <span className="ml-2 text-xs text-content-secondary">
                  {t(SOURCE_KIND[source.kind][0], { defaultValue: SOURCE_KIND[source.kind][1] })}
                  {source.interest_rate_pct !== null && ` - ${plain(source.interest_rate_pct, 2)} %`}
                </span>
              </div>
              <div className="flex items-center gap-3 tabular-nums">
                <span>{money(source.amount)}</span>
                {source.share_pct !== null && <span className="text-xs text-content-secondary">{plain(source.share_pct, 1)} %</span>}
                {editable && (
                  <ConfirmDelete
                    label={t('economics.financing.delete_source', { defaultValue: 'Delete the source' })}
                    title={t('economics.confirm.title', { defaultValue: 'Delete this entry?' })}
                    message={t('economics.confirm.source', {
                      defaultValue: 'The source {{name}} is removed with all its tranches.',
                      name: source.name,
                    })}
                    onConfirm={() => removeSource(source.id)}
                  />
                )}
              </div>
            </div>
            {source.award && (
              <p className="mt-1 text-xs text-content-secondary">
                {t('economics.financing.award', {
                  defaultValue: 'Application {{code}} ({{status}}): {{amount}}',
                  code: source.award.code,
                  status: t(`funding.status.${source.award.status}`, { defaultValue: source.award.status }),
                  amount: money(source.award.amount),
                })}
              </p>
            )}
            <ul className="mt-2 divide-y divide-border text-sm">
              {source.tranches.map((tr) => (
                <li key={tr.id} className="flex items-center justify-between py-1">
                  <span className="tabular-nums">{tr.due_on}</span>
                  <span className="tabular-nums">{money(tr.amount)}</span>
                  <span className="text-xs text-content-secondary">{tr.condition}</span>
                  {editable && tr.status !== 'drawn' ? (
                    <ConfirmDelete
                      label={t('economics.financing.delete_tranche', { defaultValue: 'Delete the tranche' })}
                      title={t('economics.confirm.title', { defaultValue: 'Delete this entry?' })}
                      message={t('economics.confirm.tranche', {
                        defaultValue: 'The tranche due on {{name}} is removed.',
                        name: tr.due_on,
                      })}
                      onConfirm={() => removeTranche(tr.id)}
                    />
                  ) : (
                    <span className="w-4" />
                  )}
                </li>
              ))}
            </ul>
            {editable && (
              <div className="mt-2">
                <TrancheForm projectId={projectId} sourceId={source.id} />
              </div>
            )}
          </div>
        ))}
      </div>

      {editable && (
        <div className="rounded-lg border border-border p-3">
          <AddRow
            submitLabel={t('economics.financing.add_source', { defaultValue: 'Add a source' })}
            disabled={name.trim() === '' || !isDecimal(amount || 'x') || (rate !== '' && !isDecimal(rate))}
            onSubmit={async () => {
              await add({
                kind,
                name: name.trim(),
                amount: cleanDecimal(amount),
                interest_rate_pct: rate === '' ? null : cleanDecimal(rate),
              });
              setName('');
              setAmount('');
              setRate('');
            }}
          >
            <Field label={t('economics.financing.kind', { defaultValue: 'Kind' })}>
              <select className={inputClass} value={kind} onChange={(e) => setKind(e.target.value as SourceKind)}>
                {KINDS.map((x) => (
                  <option key={x} value={x}>
                    {t(SOURCE_KIND[x][0], { defaultValue: SOURCE_KIND[x][1] })}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t('economics.financing.name', { defaultValue: 'Name' })}>
              <input className={`${inputClass} w-56`} value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label={t('economics.case.col_amount', { defaultValue: 'Amount' })}>
              <input className={`${inputClass} w-32 text-right`} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
            </Field>
            <Field label={t('economics.financing.interest', { defaultValue: 'Interest (%)' })}>
              <input className={`${inputClass} w-24 text-right`} inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} />
            </Field>
          </AddRow>
        </div>
      )}
    </div>
  );
}
