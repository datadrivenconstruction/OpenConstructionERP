// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Align a bill's resource prices with a region's resource price sheet: dry run
// lists every resource whose price differs (old, new, delta, positions), the
// estimator ticks the rows to take, apply rewrites only those.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';

import { Button, EmptyState, WideModal } from '@/shared/ui';
import { apiGet, apiPost, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

export interface PriceAlignmentRow {
  resource_key: string;
  name: string;
  code: string;
  unit: string;
  currency: string;
  old_prices: string[];
  new_price: string;
  delta: string;
  positions: number;
  rows: number;
  amount_delta: string;
  position_ids: string[];
}

export interface PriceAlignmentPreview {
  boq_id: string;
  region: string;
  sheet_resources: number;
  rows: PriceAlignmentRow[];
  rows_skipped_currency: number;
  amount_delta_total: string;
}

export interface PriceAlignmentApplyResult {
  boq_id: string;
  region: string;
  positions_changed: number;
  rows_changed: number;
  rates_kept: number;
  audit_id: string;
}

export const priceAlignmentApi = {
  preview: (boqId: string, region: string) =>
    apiGet<PriceAlignmentPreview>(
      `/v1/boq/boqs/${boqId}/price-alignment/?region=${encodeURIComponent(region)}`,
    ),
  apply: (boqId: string, region: string, resourceKeys: string[]) =>
    apiPost<PriceAlignmentApplyResult, { region: string; resource_keys: string[] }>(
      `/v1/boq/boqs/${boqId}/price-alignment/apply/`,
      { region, resource_keys: resourceKeys },
    ),
};

interface Props {
  boqId: string;
  onClose: () => void;
  onApplied: () => void;
}

export function PriceAlignmentDialog({ boqId, onClose, onApplied }: Props) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [region, setRegion] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const regionsQuery = useQuery({
    queryKey: ['cost-regions-modal'],
    queryFn: () => apiGet<string[]>('/v1/costs/regions/'),
    staleTime: 5 * 60_000,
  });
  useEffect(() => {
    if (!region && regionsQuery.data?.length) setRegion(regionsQuery.data[0] ?? '');
  }, [region, regionsQuery.data]);

  const previewQuery = useQuery({
    queryKey: ['boq', boqId, 'price-alignment', region],
    queryFn: () => priceAlignmentApi.preview(boqId, region),
    enabled: !!region,
  });
  const rows = previewQuery.data?.rows ?? [];

  const applyMut = useMutation({
    mutationFn: () => priceAlignmentApi.apply(boqId, region, [...selected]),
    onSuccess: (res) => {
      addToast({
        type: 'success',
        title: t('boq.price_alignment.applied_title', { defaultValue: 'Prices aligned' }),
        message: t('boq.price_alignment.applied_msg', {
          defaultValue: 'Positions updated: {{n}}. Rates kept for review: {{kept}}.',
          n: res.positions_changed,
          kept: res.rates_kept,
        }),
      });
      onApplied();
      onClose();
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('boq.price_alignment.apply_failed', { defaultValue: 'Alignment failed' }),
        message: getErrorMessage(e),
      }),
  });

  const toggle = (key: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <WideModal
      open
      onClose={onClose}
      busy={applyMut.isPending}
      size="xl"
      testId="boq-price-alignment"
      title={t('boq.price_alignment.title', { defaultValue: 'Align resource prices' })}
      subtitle={t('boq.price_alignment.subtitle', {
        defaultValue: 'Resources whose price in this bill differs from the price sheet. Tick the ones to update.',
      })}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            disabled={selected.size === 0}
            loading={applyMut.isPending}
            onClick={() => applyMut.mutate()}
          >
            {t('boq.price_alignment.apply', { defaultValue: 'Apply selected' })}
          </Button>
        </div>
      }
    >
      <label className="oe-label">
        {t('boq.price_alignment.region', { defaultValue: 'Price sheet' })}
        <select
          className="oe-select mt-1 w-full"
          value={region}
          onChange={(e) => {
            setRegion(e.target.value);
            setSelected(new Set());
          }}
        >
          {(regionsQuery.data ?? []).map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </label>

      {previewQuery.isError && (
        <p className="mt-3 text-sm text-semantic-error">{getErrorMessage(previewQuery.error)}</p>
      )}

      {previewQuery.data && rows.length === 0 && (
        <EmptyState
          title={t('boq.price_alignment.none', { defaultValue: 'All resource prices match the price sheet.' })}
        />
      )}

      {rows.length > 0 && (
        <div className="mt-3 space-y-2">
          <p className="text-xs text-content-secondary tabular-nums">
            {t('boq.price_alignment.total', {
              defaultValue: 'Effect on the bill if all are aligned: {{amount}}',
              amount: previewQuery.data?.amount_delta_total,
            })}
            {previewQuery.data && previewQuery.data.rows_skipped_currency > 0 &&
              ' · ' +
                t('boq.price_alignment.skipped_currency', {
                  defaultValue: 'Rows in another currency left alone: {{n}}',
                  n: previewQuery.data.rows_skipped_currency,
                })}
          </p>
          <table className="oe-table oe-table-compact w-full">
            <thead>
              <tr>
                <th />
                <th className="text-left">{t('boq.price_alignment.col_resource', { defaultValue: 'Resource' })}</th>
                <th className="text-right">{t('boq.price_alignment.col_old', { defaultValue: 'In bill' })}</th>
                <th className="text-right">{t('boq.price_alignment.col_new', { defaultValue: 'Price sheet' })}</th>
                <th className="text-right">{t('boq.price_alignment.col_delta', { defaultValue: 'Delta' })}</th>
                <th className="text-right">{t('boq.price_alignment.col_positions', { defaultValue: 'Positions' })}</th>
                <th className="text-right">{t('boq.price_alignment.col_effect', { defaultValue: 'Effect' })}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.resource_key}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.has(r.resource_key)}
                      onChange={() => toggle(r.resource_key)}
                      aria-label={r.name}
                    />
                  </td>
                  <td>
                    <div className="text-content-primary">{r.name}</div>
                    {r.code && <div className="text-2xs text-content-quaternary tabular-nums">{r.code}</div>}
                  </td>
                  <td className="text-right tabular-nums">{r.old_prices.join(' / ')}</td>
                  <td className="text-right tabular-nums">
                    {r.new_price} {r.currency}
                  </td>
                  <td className="text-right tabular-nums">{r.delta}</td>
                  <td className="text-right tabular-nums">{r.positions}</td>
                  <td className="text-right tabular-nums">{r.amount_delta}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </WideModal>
  );
}
