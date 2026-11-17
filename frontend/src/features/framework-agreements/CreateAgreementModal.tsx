// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Create a framework agreement: client, title, term, cap and the price list pasted from a
 * spreadsheet (code, description, unit, rate). The project's pack adds its fields and the
 * term hint; everything else has a default under "Advanced".
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, WideModal } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { fwkApi, fwkKeys, type CreateAgreementBody } from './api';
import { agreementPackInputs } from './status';
import { fmtList } from '@/shared/lib/formatters';

interface Props {
  projectId: string;
  onClose: () => void;
  onCreated: (id: string) => void;
}

type ItemRow = CreateAgreementBody['items'][number];

/** Rows of code TAB description TAB unit TAB rate [TAB est. qty [TAB max qty]]. */
export function parsePriceList(text: string): { items: ItemRow[]; duplicates: string[] } {
  const items: ItemRow[] = [];
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const raw of text.split(/\r?\n/)) {
    const c = raw.split('\t').map((x) => x.trim());
    if (c.length < 4 || !c[0]) continue;
    const num = (v: string | undefined) => (v ? v.replace(/\s/g, '').replace(',', '.') : '');
    const rate = num(c[3]);
    if (!/^\d+(\.\d+)?$/.test(rate)) continue;
    if (seen.has(c[0])) duplicates.add(c[0]);
    seen.add(c[0]);
    const est = num(c[4]);
    const max = num(c[5]);
    items.push({
      code: c[0],
      description: c[1] ?? '',
      unit: c[2] ?? '',
      base_rate: rate,
      estimated_qty: /^\d+(\.\d+)?$/.test(est) ? est : null,
      max_qty: /^\d+(\.\d+)?$/.test(max) ? max : null,
    });
  }
  return { items, duplicates: [...duplicates] };
}

export function CreateAgreementModal({ projectId, onClose, onCreated }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [clientKind, setClientKind] = useState<'classic' | 'sector'>('classic');
  const profile = useQuery({
    queryKey: ['framework-agreements', 'pack-profile', projectId, clientKind],
    queryFn: () => fwkApi.packProfile(projectId, clientKind),
    enabled: Boolean(projectId),
  });
  const [form, setForm] = useState({
    title: '',
    client_name: '',
    start_date: '',
    end_date: '',
    cap_value: '',
    min_value: '',
    threshold_pct: '80',
    rounding: 'per_rate' as 'per_rate' | 'per_total',
    override_policy: 'block' as 'block' | 'warn',
  });
  const [packValues, setPackValues] = useState<Record<string, string>>({});
  const [priceList, setPriceList] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const parsed = useMemo(() => parsePriceList(priceList), [priceList]);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const pack = profile.data;
  const termYears = (() => {
    if (!form.start_date || !form.end_date) return null;
    const ms = new Date(form.end_date).getTime() - new Date(form.start_date).getTime();
    return ms > 0 ? ms / (365.25 * 24 * 3600 * 1000) : null;
  })();
  const overTerm = pack?.term_limit && termYears != null && termYears > pack.term_limit.years + 0.01;
  const minRequired = Boolean(pack?.min_value_required);

  const create = useMutation({
    mutationFn: () =>
      fwkApi.create({
        project_id: projectId,
        title: form.title.trim(),
        client_name: form.client_name.trim(),
        start_date: form.start_date,
        end_date: form.end_date,
        cap_value: form.cap_value || null,
        min_value: form.min_value || null,
        threshold_pct: form.threshold_pct || '80',
        rounding: form.rounding,
        override_policy: form.override_policy,
        client_kind: clientKind,
        pack_values: packValues,
        items: parsed.items,
      }),
    onSuccess: (row) => {
      qc.invalidateQueries({ queryKey: fwkKeys.all });
      onCreated(row.id);
      onClose();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const valid =
    form.title.trim() &&
    form.start_date &&
    form.end_date &&
    form.end_date >= form.start_date &&
    parsed.duplicates.length === 0 &&
    (!minRequired || form.min_value);

  return (
    <WideModal
      open
      onClose={onClose}
      size="lg"
      title={t('framework.new_agreement', { defaultValue: 'New agreement' })}
      busy={create.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" disabled={!valid} loading={create.isPending} onClick={() => create.mutate()}>
            {t('framework.create', { defaultValue: 'Create agreement' })}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1 sm:col-span-2">
          <span className="oe-label">{t('framework.field.title', { defaultValue: 'Title' })}</span>
          <input className="oe-input" value={form.title} onChange={set('title')} autoFocus />
        </label>
        <label className="flex flex-col gap-1">
          <span className="oe-label">{t('framework.col.client', { defaultValue: 'Client' })}</span>
          <input className="oe-input" value={form.client_name} onChange={set('client_name')} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="oe-label">
            {t('framework.field.cap', { defaultValue: 'Cap (maximum value)' })}
            {pack?.currency ? ` (${pack.currency})` : ''}
          </span>
          <input className="oe-input" inputMode="decimal" value={form.cap_value} onChange={set('cap_value')} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="oe-label">{t('framework.field.start', { defaultValue: 'Start' })}</span>
          <input type="date" className="oe-input" value={form.start_date} onChange={set('start_date')} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="oe-label">{t('framework.field.end', { defaultValue: 'End' })}</span>
          <input type="date" className="oe-input" value={form.end_date} onChange={set('end_date')} />
          {pack?.term_limit && (
            <span className={`text-xs ${overTerm ? 'text-semantic-warning' : 'text-content-tertiary'}`}>
              {t('framework.term_hint', {
                defaultValue: 'Usual maximum term: {{years}} years ({{source}})',
                years: pack.term_limit.years,
                source: pack.term_limit.source,
              })}
            </span>
          )}
        </label>
        {(minRequired || advanced) && (
          <label className="flex flex-col gap-1">
            <span className="oe-label">{t('framework.field.min_value', { defaultValue: 'Minimum value' })}</span>
            <input className="oe-input" inputMode="decimal" value={form.min_value} onChange={set('min_value')} />
            {minRequired && (
              <span className="text-xs text-content-tertiary">
                {t('framework.min_required', { defaultValue: 'Required: {{source}}', source: pack?.min_value_required })}
              </span>
            )}
          </label>
        )}
        {agreementPackInputs(pack?.pack_fields).map((f) => (
            <label key={f} className="flex flex-col gap-1">
              <span className="oe-label">{t(`framework.pack_field.${f}`, { defaultValue: f.replace(/_/g, ' ') })}</span>
              <input
                className="oe-input"
                value={packValues[f] ?? ''}
                onChange={(e) => setPackValues((v) => ({ ...v, [f]: e.target.value }))}
              />
            </label>
          ))}
      </div>

      <button
        type="button"
        className="mt-4 text-sm font-medium text-oe-blue hover:underline"
        aria-expanded={advanced}
        onClick={() => setAdvanced((a) => !a)}
      >
        {t('framework.advanced', { defaultValue: 'Advanced' })}
      </button>
      {advanced && (
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <label className="flex flex-col gap-1">
            <span className="oe-label">{t('framework.field.threshold', { defaultValue: 'Warning threshold, %' })}</span>
            <input className="oe-input" inputMode="decimal" value={form.threshold_pct} onChange={set('threshold_pct')} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="oe-label">{t('framework.field.rounding', { defaultValue: 'Rounding' })}</span>
            <select className="oe-input" value={form.rounding} onChange={set('rounding')}>
              <option value="per_rate">{t('framework.rounding.per_rate', { defaultValue: 'Per rate' })}</option>
              <option value="per_total">{t('framework.rounding.per_total', { defaultValue: 'Per order total' })}</option>
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="oe-label">{t('framework.field.override_policy', { defaultValue: 'Over the cap' })}</span>
            <select className="oe-input" value={form.override_policy} onChange={set('override_policy')}>
              <option value="block">{t('framework.policy.block', { defaultValue: 'Block, override with a reason' })}</option>
              <option value="warn">{t('framework.policy.warn', { defaultValue: 'Warn and ask for a reason' })}</option>
            </select>
          </label>
          {pack?.term_limit && (
            <label className="flex flex-col gap-1">
              <span className="oe-label">{t('framework.field.client_kind', { defaultValue: 'Client type' })}</span>
              <select
                className="oe-input"
                value={clientKind}
                onChange={(e) => setClientKind(e.target.value as 'classic' | 'sector')}
              >
                <option value="classic">{t('framework.client_kind.classic', { defaultValue: 'Public authority' })}</option>
                <option value="sector">{t('framework.client_kind.sector', { defaultValue: 'Utility (sector client)' })}</option>
              </select>
            </label>
          )}
        </div>
      )}

      <label className="mt-4 flex flex-col gap-1">
        <span className="oe-label">{t('framework.field.price_list', { defaultValue: 'Price list' })}</span>
        <textarea
          className="oe-input min-h-[120px] font-mono text-xs"
          value={priceList}
          onChange={(e) => setPriceList(e.target.value)}
          placeholder={t('framework.price_list_hint', {
            defaultValue: 'Paste from a spreadsheet: code, description, unit, rate, estimated qty, max qty',
          })}
        />
        <span className="text-xs text-content-tertiary">
          {t('framework.items_parsed', { defaultValue: 'Items read: {{total}}', total: parsed.items.length })}
        </span>
        {parsed.duplicates.length > 0 && (
          <span role="alert" className="text-xs text-semantic-error">
            {t('framework.duplicates', {
              defaultValue: 'Codes listed twice: {{codes}}. Fix them before saving.',
              codes: fmtList(parsed.duplicates),
            })}
          </span>
        )}
      </label>
    </WideModal>
  );
}
