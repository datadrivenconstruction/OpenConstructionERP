// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Rate catalogue tab of the Equipment page: internal plant rates per month, day and hour,
 * computed from value, life, interest and repair. Nothing national is shipped; the demo
 * machines are marked as invented numbers.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Badge, Button, Card, CardContent, EmptyState, ErrorState, MoneyDisplay, SkeletonTable } from '@/shared/ui';
import { SideDrawer } from '@/shared/ui/SideDrawer';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  fractionToPercent,
  getRateCatalogue,
  listRateCatalogues,
  loadDemoCatalogue,
  percentToFraction,
  previewRate,
  type RateItem,
} from '../ratesApi';
import { RateImportModal } from './RateImportModal';

const FIELDS = ['value', 'residual', 'life_years', 'months_per_year', 'interest', 'repair', 'hours_per_month'] as const;
type Field = (typeof FIELDS)[number];
const PERCENT: ReadonlySet<Field> = new Set<Field>(['interest', 'repair']);

function draftOf(item: RateItem): Record<Field, string> {
  const out = {} as Record<Field, string>;
  for (const f of FIELDS) {
    const raw = item[f];
    out[f] = PERCENT.has(f) ? fractionToPercent(raw) : raw ?? '';
  }
  return out;
}

export function RateCatalogueTab() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toast = useToastStore((s) => s.addToast);
  const [chosen, setChosen] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [open, setOpen] = useState<RateItem | null>(null);

  const list = useQuery({ queryKey: ['rate-catalogues'], queryFn: listRateCatalogues });
  const activeId = chosen ?? list.data?.[0]?.id ?? null;
  const detail = useQuery({
    queryKey: ['rate-catalogue', activeId],
    queryFn: () => getRateCatalogue(activeId as string),
    enabled: !!activeId,
  });
  const demo = useMutation({
    mutationFn: () => loadDemoCatalogue('EUR'),
    onSuccess: (c) => {
      setChosen(c.id);
      void qc.invalidateQueries({ queryKey: ['rate-catalogues'] });
    },
    onError: (e) => toast({ type: 'error', title: getErrorMessage(e) }),
  });

  if (list.isLoading) return <SkeletonTable rows={6} columns={8} />;
  if (list.isError) {
    return (
      <ErrorState
        title={t('equipment.rates.load_failed', { defaultValue: 'The rate catalogue could not be loaded.' })}
        onRetry={() => void list.refetch()}
      />
    );
  }
  const catalogues = list.data ?? [];
  const current = detail.data;

  return (
    <div className="space-y-4" data-testid="rate-catalogue-tab">
      <p className="text-sm text-content-secondary">
        {t('equipment.rates.intro', {
          defaultValue:
            'Internal rates per month, day and hour for your own machines, from value, life, interest and repair.',
        })}
      </p>

      {catalogues.length === 0 ? (
        <EmptyState
          title={t('equipment.rates.empty_title', { defaultValue: 'No rate catalogue yet' })}
          description={t('equipment.rates.empty_hint', {
            defaultValue: 'Import the equipment rate table your company uses.',
          })}
          action={
            <div className="flex gap-2">
              <Button onClick={() => setImporting(true)}>
                {t('equipment.rates.import', { defaultValue: 'Import table' })}
              </Button>
              <Button variant="secondary" loading={demo.isPending} onClick={() => demo.mutate()}>
                {t('equipment.rates.load_demo', { defaultValue: 'Load 5 demo machines' })}
              </Button>
            </div>
          }
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-sm" htmlFor="rate-catalogue-select">
              {t('equipment.rates.catalogue', { defaultValue: 'Catalogue' })}
            </label>
            <select
              id="rate-catalogue-select"
              className="oe-input"
              value={activeId ?? ''}
              onChange={(e) => setChosen(e.target.value)}
            >
              {catalogues.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            {current?.superseded && (
              <Badge variant="warning">{t('equipment.rates.superseded', { defaultValue: 'Superseded' })}</Badge>
            )}
            {current?.is_synthetic && (
              <Badge variant="purple">{t('equipment.rates.demo_values', { defaultValue: 'Demo values' })}</Badge>
            )}
            <span className="text-xs text-content-tertiary">
              {t('equipment.rates.valid_from', { defaultValue: 'Valid from' })}{' '}
              {current && <DateDisplay value={current.valid_from} />}
            </span>
            <div className="ml-auto">
              <Button variant="secondary" onClick={() => setImporting(true)}>
                {t('equipment.rates.import', { defaultValue: 'Import table' })}
              </Button>
            </div>
          </div>

          {current?.is_synthetic && (
            <p className="text-xs text-content-secondary">
              {t('equipment.rates.demo_note', {
                defaultValue:
                  'Sample machines with invented numbers. Replace with your own table before pricing real work.',
              })}
            </p>
          )}

          {detail.isLoading ? (
            <SkeletonTable rows={5} columns={8} />
          ) : (
            current && (
              <Card>
                <CardContent className="overflow-x-auto p-0">
                  <table className="oe-table w-full">
                    <thead>
                      <tr>
                        <th>{t('equipment.rates.col_code', { defaultValue: 'Code' })}</th>
                        <th>{t('equipment.rates.col_machine', { defaultValue: 'Machine' })}</th>
                        <th>{t('equipment.rates.col_category', { defaultValue: 'Category' })}</th>
                        <th className="text-right">{t('equipment.rates.col_value', { defaultValue: 'Value' })}</th>
                        <th className="text-right">{t('equipment.rates.col_life', { defaultValue: 'Life' })}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {current.items.map((item) => (
                        <tr
                          key={item.id}
                          className="cursor-pointer"
                          tabIndex={0}
                          onClick={() => setOpen(item)}
                          onKeyDown={(e) => e.key === 'Enter' && setOpen(item)}
                        >
                          <td>{item.code}</td>
                          <td>{item.name}</td>
                          <td>{item.category}</td>
                          <td className="text-right tabular-nums">
                            <MoneyDisplay amount={item.value} currency={current.currency} />
                          </td>
                          <td className="text-right tabular-nums">{item.life_years}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardContent>
              </Card>
            )
          )}
        </>
      )}

      {open && current && <RateDrawer item={open} currency={current.currency} onClose={() => setOpen(null)} />}
      {importing && (
        <RateImportModal
          onClose={() => setImporting(false)}
          onDone={(id) => {
            setImporting(false);
            setChosen(id);
            void qc.invalidateQueries({ queryKey: ['rate-catalogues'] });
          }}
        />
      )}
    </div>
  );
}

function RateDrawer({ item, currency, onClose }: { item: RateItem; currency: string; onClose: () => void }) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<Record<Field, string>>(() => draftOf(item));
  const body: Record<string, string | null> = {};
  for (const f of FIELDS) {
    body[f] = PERCENT.has(f) ? percentToFraction(draft[f]) : draft[f].trim() === '' ? null : draft[f];
  }
  const preview = useQuery({
    queryKey: ['rate-preview', body],
    queryFn: () => previewRate(body),
    placeholderData: (prev) => prev,
  });
  const rates = preview.data?.valid ? preview.data.rates : null;
  const label: Record<Field, string> = {
    value: t('equipment.rates.value', { defaultValue: 'Value' }),
    residual: t('equipment.rates.residual', { defaultValue: 'Residual value' }),
    life_years: t('equipment.rates.life_years', { defaultValue: 'Life (years)' }),
    months_per_year: t('equipment.rates.months_per_year', { defaultValue: 'Operating months per year' }),
    interest: t('equipment.rates.interest', { defaultValue: 'Interest (% per year)' }),
    repair: t('equipment.rates.repair', { defaultValue: 'Repair over life (% of value)' }),
    hours_per_month: t('equipment.rates.hours_per_month', { defaultValue: 'Hours per month' }),
  };
  const line = (name: string, amount: string | null | undefined) => (
    <div className="flex justify-between text-sm">
      <span>{name}</span>
      <span className="tabular-nums">
        {amount ? <MoneyDisplay amount={amount} currency={currency} /> : '-'}
      </span>
    </div>
  );

  return (
    <SideDrawer open onClose={onClose} title={item.name} subtitle={item.code}>
      <div className="space-y-3 p-4">
        {FIELDS.map((f) => (
          <label key={f} className="block text-sm">
            <span className="text-content-secondary">{label[f]}</span>
            <input
              className="oe-input mt-1 w-full"
              inputMode="decimal"
              value={draft[f]}
              placeholder={t('equipment.rates.input_hint', { defaultValue: 'From your rate table or your accountant.' })}
              onChange={(e) => setDraft((d) => ({ ...d, [f]: e.target.value }))}
            />
          </label>
        ))}
        <div className="space-y-1 border-t border-border-light pt-3" data-testid="rate-result">
          {line(t('equipment.rates.depreciation', { defaultValue: 'Depreciation' }), rates?.depreciation)}
          {line(t('equipment.rates.interest_cost', { defaultValue: 'Interest' }), rates?.interest)}
          {line(t('equipment.rates.repair_cost', { defaultValue: 'Repair' }), rates?.repair)}
          {line(t('equipment.rates.monthly_rate', { defaultValue: 'Monthly rate' }), rates?.monthly)}
          {line(t('equipment.rates.hourly_rate', { defaultValue: 'Hourly rate' }), rates?.hourly)}
          {line(t('equipment.rates.daily_rate', { defaultValue: 'Daily rate' }), rates?.daily)}
        </div>
        {preview.data?.issues.map((i) => (
          <p key={`${i.rule_id}-${i.field}`} className="text-xs text-semantic-error">
            {i.message}
          </p>
        ))}
      </div>
    </SideDrawer>
  );
}
